"""DB repository — all reads/writes against the single Postgres store.

Replaces v1's JSON session file + Chroma + BM25 with transactional Postgres
operations (handoff §5/§10). Sessions, messages, documents, and chunks all live
here so there is no cross-store sync to get wrong.
"""
from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..levels import DEFAULT_LEVEL, normalize_level
from ..models import Chunk, Document, Message, Session, now_ms

# ─── Sessions ────────────────────────────────────────────────────────────────
async def list_sessions(db: AsyncSession) -> list[Session]:
    rows = (await db.execute(select(Session).order_by(Session.updated_at.desc()))).scalars().all()
    return list(rows)


async def create_session(db: AsyncSession, title: str = "New Chat", level=None) -> Session:
    s = Session(title=title or "New Chat", level=normalize_level(level if level is not None else DEFAULT_LEVEL))
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def get_session(db: AsyncSession, session_id: str) -> Session | None:
    return await db.get(Session, session_id)


async def set_session_level(db: AsyncSession, session_id: str, level) -> Session | None:
    s = await db.get(Session, session_id)
    if not s:
        return None
    s.level = normalize_level(level)
    s.updated_at = now_ms()
    await db.commit()
    await db.refresh(s)
    return s


async def delete_session(db: AsyncSession, session_id: str) -> None:
    await db.execute(delete(Session).where(Session.id == session_id))
    await db.commit()


async def get_messages(db: AsyncSession, session_id: str) -> list[Message]:
    rows = (
        await db.execute(
            select(Message).where(Message.session_id == session_id).order_by(Message.created_at)
        )
    ).scalars().all()
    return list(rows)


async def append_messages(db: AsyncSession, session_id: str, messages: list[dict]) -> None:
    """Append messages, auto-title from the first user message, propagate needs_review."""
    s = await db.get(Session, session_id)
    if not s:
        return
    for m in messages:
        db.add(Message(session_id=session_id, **m))
    s.updated_at = now_ms()
    if any(m.get("needs_review") for m in messages):
        s.needs_review = True
    if s.title == "New Chat":
        first_user = next((m for m in messages if m.get("role") == "user" and (m.get("content") or "").strip()), None)
        if first_user:
            t = first_user["content"].strip()
            s.title = (t[:60] + "…") if len(t) > 60 else t
        elif any(m.get("has_image") for m in messages):
            s.title = "Image question"
    await db.commit()


async def mark_reviewed(db: AsyncSession, session_id: str) -> None:
    s = await db.get(Session, session_id)
    if not s:
        return
    s.needs_review = False
    for m in await get_messages(db, session_id):
        m.needs_review = False
    await db.commit()


async def review_queue(db: AsyncSession) -> list[dict]:
    sessions = (
        await db.execute(select(Session).where(Session.needs_review.is_(True)).order_by(Session.updated_at.desc()))
    ).scalars().all()
    out = []
    for s in sessions:
        msgs = await get_messages(db, s.id)
        out.append((s, msgs))
    return out


async def review_count(db: AsyncSession) -> int:
    return int(
        (await db.execute(select(func.count()).select_from(Session).where(Session.needs_review.is_(True)))).scalar() or 0
    )


# ─── Documents + chunks ──────────────────────────────────────────────────────
async def upsert_document(db: AsyncSession, file_name: str, doc_type: str, level: int, status: str) -> Document:
    existing = (
        await db.execute(select(Document).where(Document.file_name == file_name))
    ).scalars().first()
    if existing:
        existing.doc_type = doc_type
        existing.level = level
        existing.status = status
        existing.error = None
        existing.updated_at = now_ms()
        await db.commit()
        await db.refresh(existing)
        return existing
    d = Document(file_name=file_name, doc_type=doc_type, level=level, status=status)
    db.add(d)
    await db.commit()
    await db.refresh(d)
    return d


async def set_document_status(db: AsyncSession, doc_id: str, status: str, chunks_added: int | None = None, error: str | None = None) -> None:
    d = await db.get(Document, doc_id)
    if not d:
        return
    d.status = status
    if chunks_added is not None:
        d.chunks_added = chunks_added
    d.error = error
    d.updated_at = now_ms()
    await db.commit()


async def delete_chunks_by_source(db: AsyncSession, file_name: str) -> None:
    await db.execute(delete(Chunk).where(Chunk.source == file_name))
    await db.commit()


async def add_chunks(db: AsyncSession, document_id: str, chunks: list[dict], embeddings: list[list[float]]) -> int:
    added = 0
    for c, emb in zip(chunks, embeddings):
        if not emb:
            continue
        db.add(
            Chunk(
                id=c["id"],
                document_id=document_id,
                text=c["text"],
                parent_id=c.get("parent_id"),
                parent_text=c.get("parent_text"),
                chapter=c.get("chapter") or "",
                page_start=c.get("page_start"),
                page_end=c.get("page_end"),
                chunk_index=c.get("chunk_index", 0),
                word_count=c.get("word_count", 0),
                level=c.get("level"),
                doc_type=c.get("doc_type", "notes"),
                source=c["source"],
                embedding=emb,
            )
        )
        added += 1
    await db.commit()
    return added


async def delete_document(db: AsyncSession, file_name: str) -> None:
    await db.execute(delete(Chunk).where(Chunk.source == file_name))
    await db.execute(delete(Document).where(Document.file_name == file_name))
    await db.commit()


async def clear_kb(db: AsyncSession) -> None:
    await db.execute(delete(Chunk))
    await db.execute(delete(Document))
    await db.commit()


async def stats(db: AsyncSession) -> dict:
    total = int((await db.execute(select(func.count()).select_from(Chunk))).scalar() or 0)
    docs = (await db.execute(select(Document).order_by(Document.created_at))).scalars().all()
    documents = [
        {"name": d.file_name, "docType": d.doc_type, "level": d.level, "chunks": d.chunks_added, "status": d.status}
        for d in docs
    ]
    return {"totalChunks": total, "documents": documents}
