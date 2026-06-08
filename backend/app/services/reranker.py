"""Local, free cross-encoder reranker — bge-reranker-base (handoff §5).

Replaces v1's LLM-as-judge: deterministic, fast, no API/quota. One signal, three
jobs (handoff §4.4): the off-topic gate, the context selection, and the displayed
sources. The model emits a relevance LOGIT per (query, passage) pair; we sigmoid it
to a 0..1 probability so the gate threshold is interpretable and tunable.

Fails open: if the model can't load, `rerank()` returns None and the caller falls
back to the cosine/keyword heuristic — never blocking an answer.
"""
from __future__ import annotations

import asyncio
import logging
import math

from ..config import settings

log = logging.getLogger("physicsta.reranker")

_model = None
_lock = asyncio.Lock()
_unavailable = False


async def _get_model():
    global _model, _unavailable
    if _model is not None or _unavailable:
        return _model
    async with _lock:
        if _model is None and not _unavailable:
            try:
                from sentence_transformers import CrossEncoder

                log.info("Loading reranker model: %s …", settings.rerank_model)
                _model = await asyncio.to_thread(CrossEncoder, settings.rerank_model)
                log.info("Reranker ready (local cross-encoder)")
            except Exception as e:  # noqa: BLE001
                _unavailable = True
                log.warning("Reranker unavailable (%s) — falling back to heuristic", e)
    return _model


async def warmup() -> None:
    await _get_model()


def sigmoid(x: float) -> float:
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        return 0.0 if x < 0 else 1.0


async def rerank(query: str, passages: list[str]) -> list[float] | None:
    """Return one relevance probability (0..1) per passage, or None if unavailable."""
    if not passages:
        return []
    model = await _get_model()
    if model is None:
        return None
    pairs = [[query, str(p or "")[:1024]] for p in passages]
    try:
        scores = await asyncio.to_thread(model.predict, pairs)
    except Exception as e:  # noqa: BLE001
        log.warning("Rerank predict failed (%s) — falling back", e)
        return None
    return [sigmoid(float(s)) for s in scores]
