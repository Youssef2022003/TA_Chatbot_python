"""Session + review-queue endpoints (handoff §8). Literal routes (/review,
/review/count) are declared before the parametrized /{id} routes so they match first.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..levels import is_valid_level
from ..models import now_ms
from ..schemas import (
    CreateSessionRequest,
    SetLevelRequest,
    TeacherReplyRequest,
    serialize_message,
    serialize_session,
)
from ..services import store

router = APIRouter()


@router.get("")
async def list_sessions(db: AsyncSession = Depends(get_session)):
    return [serialize_session(s) for s in await store.list_sessions(db)]


@router.post("")
async def create_session(body: CreateSessionRequest, db: AsyncSession = Depends(get_session)):
    s = await store.create_session(db, body.title, body.level)
    return serialize_session(s)


@router.get("/review")
async def review_queue(db: AsyncSession = Depends(get_session)):
    out = []
    for s, msgs in await store.review_queue(db):
        out.append({**serialize_session(s), "messages": [serialize_message(m) for m in msgs]})
    return out


@router.get("/review/count")
async def review_count(db: AsyncSession = Depends(get_session)):
    return {"count": await store.review_count(db)}


@router.patch("/{session_id}/level")
async def set_level(session_id: str, body: SetLevelRequest, db: AsyncSession = Depends(get_session)):
    if not is_valid_level(body.level):
        raise HTTPException(status_code=400, detail="level must be an integer 1-5")
    s = await store.set_session_level(db, session_id, body.level)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    return serialize_session(s)


@router.get("/{session_id}/messages")
async def get_messages(session_id: str, db: AsyncSession = Depends(get_session)):
    return [serialize_message(m) for m in await store.get_messages(db, session_id)]


@router.delete("/{session_id}")
async def delete_session(session_id: str, db: AsyncSession = Depends(get_session)):
    await store.delete_session(db, session_id)
    return {"success": True}


@router.patch("/{session_id}/review")
async def mark_reviewed(session_id: str, db: AsyncSession = Depends(get_session)):
    await store.mark_reviewed(db, session_id)
    return {"success": True}


@router.post("/{session_id}/teacher-reply")
async def teacher_reply(session_id: str, body: TeacherReplyRequest, db: AsyncSession = Depends(get_session)):
    if not (body.content or "").strip():
        raise HTTPException(status_code=400, detail="Content required")
    msg = {
        "role": "teacher",
        "content": body.content.strip(),
        "needs_review": False,
        "created_at": now_ms(),
    }
    await store.append_messages(db, session_id, [msg])
    await store.mark_reviewed(db, session_id)
    return {"success": True}
