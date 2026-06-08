"""Request/response schemas + serializers that preserve v1's exact JSON contract
(handoff §8). The reused React frontend speaks camelCase, so inputs accept camelCase
aliases and outputs are serialized to camelCase dicts explicitly.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from .models import Document, Message, Session


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")


# ─── Inbound ─────────────────────────────────────────────────────────────────
class HistoryTurn(_CamelModel):
    role: str
    content: str = ""


class ReplyTo(_CamelModel):
    role: str | None = None
    content: str | None = None


class ChatRequest(_CamelModel):
    message: str | None = ""
    image_base64: str | None = None
    mime_type: str | None = None
    history: list[HistoryTurn] = []
    session_id: str | None = None
    level: int | None = None
    reply_to: ReplyTo | None = None


class CreateSessionRequest(_CamelModel):
    title: str = "New Chat"
    level: int | None = None


class SetLevelRequest(_CamelModel):
    level: int


class TeacherReplyRequest(_CamelModel):
    content: str


# ─── Outbound serializers (exact v1 shapes) ──────────────────────────────────
def serialize_session(s: Session) -> dict[str, Any]:
    return {
        "id": s.id,
        "title": s.title,
        "level": s.level,
        "needsReview": s.needs_review,
        "createdAt": s.created_at,
        "updatedAt": s.updated_at,
    }


def serialize_message(m: Message) -> dict[str, Any]:
    return {
        "id": m.id,
        "role": m.role,
        "content": m.content,
        "hasImage": m.has_image,
        "sources": m.sources or [],
        "rewrittenQuery": m.rewritten_query,
        "quotedText": m.quoted_text,
        "quotedRole": m.quoted_role,
        "needsReview": m.needs_review,
        "createdAt": m.created_at,
    }


def serialize_document(d: Document) -> dict[str, Any]:
    return {
        "name": d.file_name,
        "docType": d.doc_type,
        "level": d.level,
        "chunks": d.chunks_added,
        "status": d.status,
    }
