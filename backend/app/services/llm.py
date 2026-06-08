"""Free LLM providers, native SDKs — no agent framework (handoff §5).

Text reasoning  -> Groq llama-3.3-70b (primary), Gemini flash (fallback).
Vision + image  -> Gemini (only it can see the image), Groq-from-extraction fallback.

Every stream function is an async generator yielding plain token strings, so the
SSE route consumes one shape regardless of provider. Gemini streams raise on an
empty response so `stream_with_fallback` (rag.py) can detect it and switch — the
exact v1 behavior (handoff §8).
"""
from __future__ import annotations

import base64
import logging
from typing import AsyncIterator, Callable

from ..config import settings

log = logging.getLogger("physicsta.llm")

# ─── Lazy clients ────────────────────────────────────────────────────────────
_groq = None
_gemini_ready = False


def _groq_client():
    global _groq
    if _groq is None:
        from groq import AsyncGroq

        _groq = AsyncGroq(api_key=settings.groq_api_key)
    return _groq


def _ensure_gemini():
    global _gemini_ready
    if not _gemini_ready:
        import google.generativeai as genai

        genai.configure(api_key=settings.gemini_api_key)
        _gemini_ready = True


# ─── History adapters ────────────────────────────────────────────────────────
def _trim(history: list[dict]) -> list[dict]:
    clean = [
        {"role": m["role"], "content": m["content"].strip()}
        for m in (history or [])
        if m.get("role") in ("user", "assistant") and (m.get("content") or "").strip()
    ]
    return clean[-settings.history_turns :]


def _to_gemini_history(history: list[dict]) -> list[dict]:
    """Port of toGeminiHistory: strict user<->model alternation, starts with user,
    ends with model (send_message adds the next user turn)."""
    turns: list[dict] = []
    for m in _trim(history):
        role = "model" if m["role"] == "assistant" else "user"
        if turns and turns[-1]["role"] == role:
            turns[-1]["parts"][0]["text"] += "\n" + m["content"]
        else:
            turns.append({"role": role, "parts": [{"text": m["content"]}]})
    while turns and turns[0]["role"] != "user":
        turns.pop(0)
    while turns and turns[-1]["role"] != "model":
        turns.pop()
    return turns


# ─── Streaming generators (yield str tokens) ─────────────────────────────────
async def groq_stream(system_prompt: str, user_message: str, history: list[dict]) -> AsyncIterator[str]:
    client = _groq_client()
    stream = await client.chat.completions.create(
        model=settings.groq_text_model,
        max_tokens=settings.max_answer_tokens,
        stream=True,
        messages=[{"role": "system", "content": system_prompt}, *_trim(history), {"role": "user", "content": user_message}],
    )
    async for chunk in stream:
        token = chunk.choices[0].delta.content if chunk.choices else None
        if token:
            yield token


async def gemini_stream_text(system_prompt: str, user_message: str, history: list[dict]) -> AsyncIterator[str]:
    _ensure_gemini()
    import google.generativeai as genai

    model = genai.GenerativeModel(settings.gemini_model, system_instruction=system_prompt)
    chat = model.start_chat(history=_to_gemini_history(history))
    response = await chat.send_message_async(user_message, stream=True)
    yielded = False
    async for chunk in response:
        text = _safe_text(chunk)
        if text:
            yielded = True
            yield text
    if not yielded:
        raise RuntimeError("Gemini returned empty response — falling back")


async def gemini_stream_image(
    system_prompt: str, image_b64: str, mime_type: str, history: list[dict]
) -> AsyncIterator[str]:
    _ensure_gemini()
    import google.generativeai as genai

    model = genai.GenerativeModel(settings.gemini_model, system_instruction=system_prompt)
    chat = model.start_chat(history=_to_gemini_history(history))
    parts = [
        {"mime_type": mime_type or "image/jpeg", "data": base64.b64decode(image_b64)},
        {"text": "Solve all questions shown in this image using the course materials provided in the system instructions."},
    ]
    response = await chat.send_message_async(parts, stream=True)
    yielded = False
    async for chunk in response:
        text = _safe_text(chunk)
        if text:
            yielded = True
            yield text
    if not yielded:
        raise RuntimeError("Gemini returned empty response — falling back")


def _safe_text(chunk) -> str:
    try:
        return chunk.text or ""
    except Exception:  # noqa: BLE001 - chunk may carry no text part
        return ""


# ─── Non-streaming helpers ───────────────────────────────────────────────────
async def gemini_extract_image(image_b64: str, mime_type: str = "image/jpeg") -> str:
    """Structured digitization of a problem photo (handoff §4.11 step 1)."""
    _ensure_gemini()
    import google.generativeai as genai

    model = genai.GenerativeModel(settings.gemini_model)
    result = await model.generate_content_async(
        [
            {"mime_type": mime_type, "data": base64.b64decode(image_b64)},
            {"text": _EXTRACTION_PROMPT},
        ]
    )
    return result.text


async def groq_rewrite(query: str, history: list[dict]) -> str:
    client = _groq_client()
    res = await client.chat.completions.create(
        model=settings.groq_text_model,
        max_tokens=200,
        messages=[{"role": "system", "content": _REWRITE_PROMPT}, *_trim(history), {"role": "user", "content": query}],
    )
    return (res.choices[0].message.content or "").strip()


async def gemini_rewrite(query: str, history: list[dict]) -> str:
    _ensure_gemini()
    import google.generativeai as genai

    model = genai.GenerativeModel(settings.gemini_model, system_instruction=_REWRITE_PROMPT)
    chat = model.start_chat(history=_to_gemini_history(history))
    result = await chat.send_message_async(query)
    return (result.text or "").strip()


# ─── Fallback wrapper (handoff §8) ───────────────────────────────────────────
async def stream_with_fallback(
    primary: Callable[[], AsyncIterator[str]], fallback: Callable[[], AsyncIterator[str]]
) -> AsyncIterator[str]:
    """Iterate `primary`; if it raises before yielding OR yields nothing, switch to
    `fallback`. If it raises after a partial yield, surface the error (v1 parity)."""
    yielded = False
    try:
        async for token in primary():
            yielded = True
            yield token
    except Exception as e:  # noqa: BLE001
        if not yielded:
            log.warning("Primary LLM stream failed (%s) — using fallback", e)
            async for token in fallback():
                yield token
            return
        raise
    if not yielded:
        log.warning("Primary LLM returned no content — using fallback")
        async for token in fallback():
            yield token


_REWRITE_PROMPT = (
    "You are a query rewriter for a physics RAG system. Given the conversation "
    "history and the latest student message, rewrite the query into a clear, "
    "complete, standalone physics question optimized for textbook retrieval. If the "
    "query is a follow-up (e.g. \"give me an example\", \"explain more\", \"what about "
    "X\"), incorporate the topic from the conversation history so the question is "
    "self-contained. Return ONLY the rewritten question — no preamble, no explanation."
)

_EXTRACTION_PROMPT = """You are a physics problem digitizer. Analyze this image and extract ALL content with complete detail using the exact structure below.

DIAGRAM DESCRIPTION:
Describe every diagram, figure, or illustration present. For each one include: what type it is (free-body diagram, circuit, inclined plane, optics, wave, graph, etc.), every labeled quantity with its value and unit, all angles with values, all force vectors with direction and label, all dimensions, all arrows and their directions, how components connect (pulleys, springs, resistors, capacitors, etc.). If no diagram exists write: None.

QUESTIONS:
List every question found in the image, numbered Q1, Q2, Q3, etc. Copy the full question text exactly as written. Do not paraphrase.

ANSWER CHOICES:
For each question that provides multiple choice options, list them exactly as shown:
Q1 choices: A) ... B) ... C) ... D) ...
If a question is open-ended (no choices), write: Q1: Open-ended
If there are no questions with choices at all, write: None

GIVEN DATA:
List all numerical values, constants, formulas, or conditions stated in the problem (e.g., m = 2 kg, v0 = 10 m/s, g = 9.8 m/s2).

Output only the four sections above. Do not solve anything. Do not add commentary outside these sections."""
