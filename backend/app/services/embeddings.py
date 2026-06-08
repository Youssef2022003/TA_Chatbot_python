"""Local, free embeddings via sentence-transformers — bge-small-en-v1.5 (384-dim).

In-process, no API, no rate limits (the v1 win, handoff §5). bge is asymmetric:
queries get an instruction prefix, passages do not. The model is loaded lazily and
all encode calls are pushed off the event loop with asyncio.to_thread.
"""
from __future__ import annotations

import asyncio
import logging

from ..config import settings

log = logging.getLogger("physicsta.embeddings")

_model = None
_lock = asyncio.Lock()


async def _get_model():
    global _model
    if _model is not None:
        return _model
    async with _lock:
        if _model is None:
            from sentence_transformers import SentenceTransformer

            log.info("Loading embedding model: %s …", settings.embed_model)
            _model = await asyncio.to_thread(SentenceTransformer, settings.embed_model)
            log.info("Embedding model ready (%d-dim, local)", settings.embed_dim)
    return _model


async def warmup() -> None:
    try:
        await _get_model()
    except Exception as e:  # noqa: BLE001 - boot must not fail on model load
        log.warning("Embedding warmup failed: %s", e)


async def embed_passages(texts: list[str]) -> list[list[float]]:
    clean = [("" if t is None else str(t)) for t in (texts or [])]
    if not clean:
        return []
    model = await _get_model()

    def _encode():
        out: list[list[float]] = []
        for i in range(0, len(clean), settings.embed_batch):
            batch = clean[i : i + settings.embed_batch]
            vecs = model.encode(batch, normalize_embeddings=True, convert_to_numpy=True)
            out.extend(v.tolist() for v in vecs)
        return out

    return await asyncio.to_thread(_encode)


async def embed_query(text: str) -> list[float]:
    model = await _get_model()
    prefixed = settings.embed_query_prefix + str(text or "")
    vec = await asyncio.to_thread(
        lambda: model.encode([prefixed], normalize_embeddings=True, convert_to_numpy=True)[0]
    )
    return vec.tolist()
