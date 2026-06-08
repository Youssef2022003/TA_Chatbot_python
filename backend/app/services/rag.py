"""RAG orchestrator — the pipeline read top-to-bottom (handoff §5/§6).

parse -> chunk -> embed -> upsert   (ingestion, async)
classify -> rewrite -> retrieve -> rerank/gate -> dedup -> generate   (query)

No framework: plain async functions calling native libraries directly, so every
gating/rewrite/rerank decision (the source of every v1 bug) is explicit here.
"""
from __future__ import annotations

import logging
import os
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from ..db import SessionLocal
from ..levels import get_level, normalize_level
from . import store
from .chunking import chunk_document
from .embeddings import embed_passages
from .images import build_image_rules
from .intent import classify_intent, guard_rewrite, needs_rewrite
from .llm import (
    gemini_extract_image,
    gemini_rewrite,
    gemini_stream_image,
    gemini_stream_text,
    groq_rewrite,
    groq_stream,
    stream_with_fallback,
)
from .parsing import extract_document
from .prompts import (
    build_context_block,
    build_image_prompt,
    build_text_prompt,
    greeting_prompt,
    no_answer_prompt,
)
from .retrieval import dedup_parents, rerank_candidates, retrieve_candidates, to_source

log = logging.getLogger("physicsta.rag")


# ─── Ingestion (async/background) ────────────────────────────────────────────
async def ingest_document(document_id: str, file_path: str, file_name: str, doc_type: str, level) -> None:
    """Background job: parse -> chunk -> embed -> replace chunks. Updates Document
    status so the upload endpoint can return immediately (handoff §4.10/§6)."""
    lvl = normalize_level(level)
    async with SessionLocal() as db:
        try:
            await store.set_document_status(db, document_id, "parsing")
            text, markdown = await extract_document(file_path, file_name)
            pages = text.split("\f")
            chunks = chunk_document(pages, file_name, doc_type, lvl, markdown=markdown)
            log.info("Chunks produced: %d (level %s, markdown=%s)", len(chunks), lvl, markdown)
            if not chunks:
                raise ValueError("No content could be extracted from this PDF.")

            await store.set_document_status(db, document_id, "embedding")
            embeddings = await embed_passages([c["text"] for c in chunks])

            # Re-uploading a file REPLACES it (handoff §4.9): drop old chunks first.
            await store.delete_chunks_by_source(db, file_name)
            added = await store.add_chunks(db, document_id, chunks, embeddings)
            if added == 0:
                raise ValueError("All embeddings failed — no chunks could be indexed.")

            await store.set_document_status(db, document_id, "ready", chunks_added=added)
            log.info("Ingested %s: %d chunks", file_name, added)
        except Exception as e:  # noqa: BLE001
            log.exception("Ingestion failed for %s", file_name)
            await store.set_document_status(db, document_id, "error", error=str(e))
        finally:
            try:
                os.unlink(file_path)
            except OSError:
                pass


# ─── Query ───────────────────────────────────────────────────────────────────
def _sanitize_history(history) -> list[dict]:
    if not isinstance(history, list):
        return []
    out = []
    for m in history:
        role = getattr(m, "role", None) or (m.get("role") if isinstance(m, dict) else None)
        content = getattr(m, "content", None) or (m.get("content") if isinstance(m, dict) else None)
        if role in ("user", "assistant") and isinstance(content, str) and content.strip():
            out.append({"role": role, "content": content.strip()})
    return out[-8:]


async def answer_question(
    db: AsyncSession, user_message: str, image_b64: str | None, mime_type: str | None,
    raw_history, level, reply_to=None,
) -> dict:
    raw_msg = (user_message or "").strip()
    if not raw_msg and not image_b64:
        raise ValueError("Message cannot be empty")

    level_obj = get_level(level)
    history = _sanitize_history(raw_history)
    quoted = None
    if reply_to is not None:
        rc = getattr(reply_to, "content", None) or (reply_to.get("content") if isinstance(reply_to, dict) else None)
        if isinstance(rc, str) and rc.strip():
            quoted = rc.strip()[:1500]

    # Step 0 — intent classification (text only). Images always go through RAG.
    msg = raw_msg
    if not image_b64:
        intent = classify_intent(raw_msg)
        log.info("[RAG] intent=%s level=%s msg=%r", intent["kind"], level_obj["id"], raw_msg[:80])
        if intent["kind"] == "greeting":
            prompt = greeting_prompt(level_obj["name"])
            stream = stream_with_fallback(
                lambda: gemini_stream_text(prompt, raw_msg, history),
                lambda: groq_stream(prompt, raw_msg, history),
            )
            return {"stream": stream, "sources": [], "rewrittenQuery": None, "needsReview": False, "emptyKB": False}
        msg = intent["query"]

    # Step 1 — image understanding
    final_query = msg
    image_extracted = None
    if image_b64:
        image_extracted = await gemini_extract_image(image_b64, mime_type or "image/jpeg")
        final_query = image_extracted + (f"\n\nStudent note: {msg}" if msg else "")

    # Step 2 — conditional query rewrite (skipped for images)
    rewritten = final_query
    if not image_b64 and history and needs_rewrite(final_query):
        rw = final_query
        try:
            rw = await gemini_rewrite(final_query, history)
        except Exception:  # noqa: BLE001
            try:
                rw = await groq_rewrite(final_query, history)
            except Exception:  # noqa: BLE001
                rw = final_query
        rewritten = guard_rewrite(final_query, rw)
        log.info("[RAG] rewrite: %r -> %r", final_query[:50], rewritten[:60])

    retrieval_query = f"{rewritten}\n{quoted[:500]}" if quoted else rewritten

    # Steps 3-4 — hybrid retrieve + level filter + RRF
    res = await retrieve_candidates(db, retrieval_query, level_obj["id"])
    merged = res["merged"]

    async def _no_answer() -> dict:
        prompt = no_answer_prompt(level_obj["name"])
        if image_b64:
            stream = stream_with_fallback(
                lambda: gemini_stream_image(prompt, image_b64, mime_type or "image/jpeg", history),
                lambda: groq_stream(prompt, rewritten, history),
            )
        else:
            stream = stream_with_fallback(
                lambda: gemini_stream_text(prompt, rewritten, history),
                lambda: groq_stream(prompt, rewritten, history),
            )
        return {"stream": stream, "sources": [], "rewrittenQuery": None, "needsReview": True, "emptyKB": False}

    if not merged:
        return await _no_answer()

    # Step 4b — cross-encoder rerank: gate + select (handoff §4.4)
    rr = await rerank_candidates(retrieval_query, merged)
    from ..config import settings

    if rr["max_score"] is None:
        if res["vector_fallback_low_conf"]:
            return await _no_answer()
        selected = rr["ordered"]
    else:
        if rr["max_score"] < settings.rerank_gate_prob:
            log.info("[RAG] off-topic (rerank max=%.3f < %.3f) -> review", rr["max_score"], settings.rerank_gate_prob)
            return await _no_answer()
        selected = rr["keep"] if rr["keep"] else rr["ordered"]

    # Step 5 — parent-document dedup
    compressed = dedup_parents(selected)
    log.info("[RAG] context parents: %s", ", ".join(c.get("source", "") for c in compressed))
    sources = [to_source(c) for c in compressed]

    # Step 6 — grounded system prompt (context uses parent text from candidates)
    context_block = build_context_block(compressed)
    if image_b64:
        system_prompt = build_image_prompt(
            level_obj["name"], level_obj["guidance"], context_block, build_image_rules(image_extracted or "")
        )
    else:
        system_prompt = build_text_prompt(level_obj["name"], level_obj["guidance"], context_block)

    # Step 7 — stream, best-fit model per modality
    if quoted:
        text_user_message = (
            f'I\'m referring to this earlier message:\n"""{quoted}"""\n\n'
            f"My question: {msg or '(see the quoted message above)'}"
        )
    else:
        text_user_message = rewritten

    if image_b64:
        stream = stream_with_fallback(
            lambda: gemini_stream_image(system_prompt, image_b64, mime_type or "image/jpeg", history),
            lambda: groq_stream(system_prompt, image_extracted or final_query, history),
        )
    else:
        stream = stream_with_fallback(
            lambda: groq_stream(system_prompt, text_user_message, history),
            lambda: gemini_stream_text(system_prompt, text_user_message, history),
        )

    return {
        "stream": stream,
        "sources": sources,
        # For image queries `rewritten` == the long extraction — don't surface it.
        "rewrittenQuery": None if image_extracted else rewritten,
        "needsReview": False,
        "emptyKB": False,
    }
