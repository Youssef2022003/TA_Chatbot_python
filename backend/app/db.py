"""Async SQLAlchemy engine + schema bootstrap for the single Postgres+pgvector store.

One DB holds everything: vectors, metadata, full-text, sessions, messages, users
(handoff §5/§10). This kills v1's fragile two-store (Chroma + BM25) hand-sync.
"""
from __future__ import annotations

import logging
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .config import settings

log = logging.getLogger("physicsta.db")


def _normalize_url(raw: str) -> tuple[str, dict]:
    """Make any Postgres URL work with the asyncpg driver.

    Handles hosted providers like Neon/Supabase: forces the +asyncpg driver, and
    strips libpq-only query params (sslmode, channel_binding) that asyncpg doesn't
    understand — translating them into asyncpg connect_args instead. Also disables
    the prepared-statement cache on pooled endpoints (PgBouncer transaction mode).
    """
    url = raw.strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    parts = urlsplit(url)
    q = dict(parse_qsl(parts.query))
    connect_args: dict = {}

    sslmode = q.pop("sslmode", None)
    q.pop("channel_binding", None)  # asyncpg negotiates this itself
    if sslmode and sslmode != "disable":
        connect_args["ssl"] = sslmode  # asyncpg accepts 'require'/'verify-full'/…
    elif "neon.tech" in parts.netloc or "supabase" in parts.netloc:
        connect_args["ssl"] = "require"  # hosted providers require TLS

    # Pooled endpoints (e.g. Neon's "-pooler" host) run PgBouncer in transaction
    # mode, which breaks asyncpg's prepared statements — disable the cache there.
    if "pooler" in parts.netloc or "pgbouncer" in parts.netloc:
        connect_args["statement_cache_size"] = 0

    clean = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q), parts.fragment))
    return clean, connect_args


_url, _connect_args = _normalize_url(settings.database_url)
engine = create_async_engine(_url, pool_pre_ping=True, future=True, connect_args=_connect_args)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncSession:
    """FastAPI dependency: yields a request-scoped async session."""
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    """Enable pgvector, create tables/indexes, and migrate on dimension change.

    Mirrors v1's boot logic (handoff §4.9): if the stored vector dimension no
    longer matches the embedding model, wipe the KB so it can be re-ingested
    cleanly instead of silently breaking vector search.
    """
    from .models import Base, Chunk  # local import avoids a cycle

    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)

    # Dimension-migration guard.
    async with SessionLocal() as session:
        stored = await _stored_embedding_dim(session)
        if stored is not None and stored != settings.embed_dim:
            log.warning(
                "Embedding dimension changed (%s -> %s). Wiping KB — re-ingest "
                "your documents.",
                stored,
                settings.embed_dim,
            )
            await session.execute(text("DELETE FROM chunks"))
            await session.execute(text("DELETE FROM documents"))
            await session.commit()
            # The embedding column type is fixed at create_all time; if the dim
            # truly changed you must also DROP/recreate the column. We log loudly
            # so an operator running an alembic migration knows. For a fresh DB
            # this branch never fires.


async def _stored_embedding_dim(session: AsyncSession) -> int | None:
    try:
        row = (
            await session.execute(
                text("SELECT vector_dims(embedding) FROM chunks LIMIT 1")
            )
        ).first()
        return int(row[0]) if row and row[0] is not None else None
    except Exception:
        return None
