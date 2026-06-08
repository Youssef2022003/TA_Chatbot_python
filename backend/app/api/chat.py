"""POST /api/chat — SSE streaming answer (handoff §8).

Event sequence:  meta -> token* -> [review] -> [DONE]   (or error -> [DONE])

Disconnect detection uses `await request.is_disconnected()` (handoff §4.10), not a
request-body close. The model's "📚 Reference" footer is held back and replaced with
a canonical one built from the real sources (handoff §4.7), and a length-bounded
no-answer check flags the question for teacher review.
"""
from __future__ import annotations

import json
import logging
import re

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..db import SessionLocal
from ..models import now_ms
from ..schemas import ChatRequest
from ..services import store
from ..services.prompts import build_reference
from ..services.rag import answer_question

router = APIRouter()
log = logging.getLogger("physicsta.chat")

_NO_ANSWER_RE = re.compile(r"couldn't find this topic|not in the course materials|ask your teacher", re.I)


def _is_no_answer(text: str) -> bool:
    """A genuine not-found reply is short AND is the message — a long correct answer
    that merely mentions 'teacher' must not be flagged (handoff §4.7)."""
    t = (text or "").strip()
    return bool(_NO_ANSWER_RE.search(t)) and len(t) < 400


def _sse(obj) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


@router.post("")
async def chat(request: Request):
    body = await request.json()
    req = ChatRequest.model_validate(body or {})
    return StreamingResponse(
        _event_stream(req, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


async def _event_stream(req: ChatRequest, request: Request):
    full_content = ""
    meta = None
    try:
        # Retrieval uses a short-lived session that closes BEFORE the (potentially
        # long) LLM stream, so a connection isn't pinned for the whole response.
        async with SessionLocal() as db:
            result = await answer_question(
                db, req.message, req.image_base64, req.mime_type, req.history, req.level, req.reply_to
            )
        sources = result["sources"]
        rewritten = result["rewrittenQuery"]
        needs_review = result["needsReview"]
        meta = {"sources": sources, "rewrittenQuery": rewritten, "needsReview": needs_review}
        yield _sse({"type": "meta", **meta})

        # Stream the body but HOLD everything from the reference marker onward.
        ref_marker = "📚"
        sent_len = 0
        async for token in result["stream"]:
            if await request.is_disconnected():
                break
            if not token:
                continue
            full_content += token
            idx = full_content.find(ref_marker)
            cut = len(full_content) if idx == -1 else idx
            if cut > sent_len:
                yield _sse({"type": "token", "content": full_content[sent_len:cut]})
                sent_len = cut

        body_text = full_content[:sent_len]
        no_answer_body = _is_no_answer(body_text)
        canonical = "" if no_answer_body else build_reference(sources)
        if canonical:
            sep = "\n\n" if body_text.rstrip() else ""
            yield _sse({"type": "token", "content": sep + canonical})
            full_content = body_text.rstrip() + sep + canonical
        else:
            full_content = body_text

        detected_no_answer = _is_no_answer(full_content)
        final_needs_review = needs_review or detected_no_answer
        if detected_no_answer and not needs_review:
            yield _sse({"type": "review", "needsReview": True, "sources": []})

        # Persist BEFORE signalling [DONE]: a client that disconnects the instant it
        # sees [DONE] would otherwise cancel this generator before the DB write runs.
        await _persist(req, full_content, [] if detected_no_answer else sources, rewritten, final_needs_review)
        yield "data: [DONE]\n\n"
    except Exception as e:  # noqa: BLE001
        log.exception("Chat error")
        yield _sse({"type": "error", "message": str(e) or "Something went wrong. Please try again."})
        saved = full_content or "[The assistant encountered an error while processing this question.]"
        flag = (meta["needsReview"] if meta else True) or _is_no_answer(saved)
        await _persist(req, saved, (meta or {}).get("sources", []), None, flag)
        yield "data: [DONE]\n\n"


async def _persist(req: ChatRequest, content: str, sources: list, rewritten, needs_review: bool) -> None:
    if not req.session_id:
        return
    now = now_ms()
    to_save: list[dict] = []
    if (req.message or "").strip() or req.image_base64:
        to_save.append(
            {
                "role": "user",
                "content": (req.message or "").strip(),
                "has_image": bool(req.image_base64),
                "quoted_text": (req.reply_to.content[:1500] if req.reply_to and req.reply_to.content else None),
                "quoted_role": (req.reply_to.role if req.reply_to else None),
                "needs_review": False,
                "created_at": now - 1,
            }
        )
    to_save.append(
        {
            "role": "assistant",
            "content": content,
            "sources": sources,
            "rewritten_query": rewritten,
            "needs_review": needs_review,
            "created_at": now,
        }
    )
    try:
        async with SessionLocal() as db:
            await store.append_messages(db, req.session_id, to_save)
    except Exception as e:  # noqa: BLE001
        log.warning("Session save failed: %s", e)
