"""ORM models — the Postgres data model from handoff §10.

Timestamps are stored as epoch-milliseconds (BigInteger) because the reused React
frontend computes `Date.now() - updatedAt` for its "x minutes ago" labels, so the
API must return millisecond integers exactly as v1 did.
"""
from __future__ import annotations

import time
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .config import settings


def now_ms() -> int:
    return int(time.time() * 1000)


def new_uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    file_name: Mapped[str] = mapped_column(String, index=True)
    doc_type: Mapped[str] = mapped_column(String, default="notes")
    level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # async ingestion lifecycle: queued -> parsing -> embedding -> ready | error
    status: Mapped[str] = mapped_column(String, default="queued")
    chunks_added: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[int] = mapped_column(BigInteger, default=now_ms)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=now_ms, onupdate=now_ms)


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    document_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("documents.id", ondelete="CASCADE"), nullable=True
    )
    text: Mapped[str] = mapped_column(Text)
    # Parent-document retrieval (handoff §4.5): embed small children, feed the LLM
    # the larger parent section for complete context.
    parent_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    parent_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    chapter: Mapped[str] = mapped_column(String, default="")
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    doc_type: Mapped[str] = mapped_column(String, default="notes")
    source: Mapped[str] = mapped_column(String, index=True)

    embedding: Mapped[list[float]] = mapped_column(Vector(settings.embed_dim))
    # Generated full-text column — Postgres keeps it in sync; no app-side BM25 to
    # hand-maintain (this is the sparse/keyword side of hybrid search, handoff §5).
    tsv: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', text)", persisted=True)
    )

    __table_args__ = (
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
        Index("ix_chunks_level", "level"),
    )


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String, default="New Chat")
    level: Mapped[int] = mapped_column(Integer, default=settings.default_level)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[int] = mapped_column(BigInteger, default=now_ms)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=now_ms, onupdate=now_ms)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    session_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String)  # user | assistant | teacher
    content: Mapped[str] = mapped_column(Text, default="")
    has_image: Mapped[bool] = mapped_column(Boolean, default=False)
    sources: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    rewritten_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    quoted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    quoted_role: Mapped[str | None] = mapped_column(String, nullable=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[int] = mapped_column(BigInteger, default=now_ms)

    session: Mapped["Session"] = relationship(back_populates="messages")


class User(Base):
    """Minimal user table for the production auth milestone (handoff §5/§11.6).

    Multi-user isolation + per-user rate limiting are deferred; the table exists
    so sessions can carry a nullable user_id today without a later migration.
    """

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=new_uuid)
    email: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    role: Mapped[str] = mapped_column(String, default="student")  # student | teacher
    created_at: Mapped[int] = mapped_column(BigInteger, default=now_ms)
