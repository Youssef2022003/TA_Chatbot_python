"""Hybrid retrieval pipeline (handoff §6 steps 3-5, §4.3/§4.4/§4.5).

dense (pgvector cosine) + sparse (Postgres tsvector) -> level filter -> RRF fuse
-> cross-encoder rerank (gate + select) -> parent-dedup. No hard cosine cutoff
before fusion (that killed recall in v1); relevance is decided by the reranker
reading the actual text.

Shared by the live answer path and the eval harness so they measure the same thing.
"""
from __future__ import annotations

import logging

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..models import Chunk
from . import reranker
from .embeddings import embed_query

log = logging.getLogger("physicsta.retrieval")

RRF_K = 60


def _to_cand(chunk: Chunk, score: float | None) -> dict:
    return {
        "id": chunk.id,
        "text": chunk.text,
        "parentId": chunk.parent_id,
        "parentText": chunk.parent_text,
        "chapter": chunk.chapter or "",
        "pageStart": chunk.page_start,
        "pageEnd": chunk.page_end,
        "docType": chunk.doc_type,
        "source": chunk.source,
        "chunkIndex": chunk.chunk_index,
        "level": chunk.level,
        "score": score,
    }


def _level_filter(level_id: int):
    # Legacy chunks with no level stay visible at every level (handoff §4.8).
    return or_(Chunk.level.is_(None), Chunk.level == level_id)


async def retrieve_candidates(db: AsyncSession, retrieval_query: str, level_id: int) -> dict:
    """Return {'merged': [...], 'vector_fallback_low_conf': bool}."""
    # Dense (pgvector cosine). score = 1 - distance.
    vector_cands: list[dict] = []
    best_vector_sim = 0.0
    try:
        qvec = await embed_query(retrieval_query)
        dist = Chunk.embedding.cosine_distance(qvec)
        rows = (
            await db.execute(
                select(Chunk, dist.label("dist")).where(_level_filter(level_id)).order_by(dist).limit(settings.retrieve_k)
            )
        ).all()
        for chunk, d in rows:
            sim = 1.0 - float(d)
            best_vector_sim = max(best_vector_sim, sim)
            vector_cands.append(_to_cand(chunk, sim))
    except Exception as e:  # noqa: BLE001
        log.warning("Vector retrieval failed (%s) — using keyword-only", e)

    # Sparse (tsvector / websearch_to_tsquery).
    bm25_cands: list[dict] = []
    try:
        tsq = func.websearch_to_tsquery("english", retrieval_query)
        rank = func.ts_rank_cd(Chunk.tsv, tsq)
        rows = (
            await db.execute(
                select(Chunk, rank.label("rank"))
                .where(Chunk.tsv.op("@@")(tsq))
                .where(_level_filter(level_id))
                .order_by(rank.desc())
                .limit(settings.retrieve_k)
            )
        ).all()
        bm25_cands = [_to_cand(chunk, None) for chunk, _ in rows]
    except Exception as e:  # noqa: BLE001
        log.warning("Keyword retrieval failed (%s)", e)

    # Reciprocal Rank Fusion (k=60). Fuse ALL level-matching hits — no cosine cutoff.
    rrf: dict[str, float] = {}
    data: dict[str, dict] = {}
    for i, c in enumerate(vector_cands):
        rrf[c["id"]] = rrf.get(c["id"], 0.0) + 1.0 / (RRF_K + i + 1)
        data[c["id"]] = c
    for i, c in enumerate(bm25_cands):
        rrf[c["id"]] = rrf.get(c["id"], 0.0) + 1.0 / (RRF_K + i + 1)
        data.setdefault(c["id"], c)

    merged = [data[cid] for cid, _ in sorted(rrf.items(), key=lambda kv: kv[1], reverse=True)]

    vector_fallback_low_conf = best_vector_sim < settings.vector_min_score and len(bm25_cands) < 2
    log.info(
        "[RAG] retrieval(level %s): vector=%d(best=%.2f) bm25=%d fused=%d",
        level_id, len(vector_cands), best_vector_sim, len(bm25_cands), len(merged),
    )
    return {"merged": merged, "vector_fallback_low_conf": vector_fallback_low_conf}


async def rerank_candidates(query: str, candidates: list[dict]) -> dict:
    """Cross-encoder rerank. Returns {ordered, max_score, keep}.

    max_score is None when the reranker is unavailable, so the caller knows not to
    gate on it (handoff §4.4). `keep` drives BOTH the LLM context and the displayed
    sources (precision).
    """
    if len(candidates) <= 1:
        return {"ordered": candidates, "max_score": None, "keep": None}
    pool = candidates[: settings.rerank_pool]
    scores = await reranker.rerank(query, [c.get("text", "") for c in pool])
    if scores is None or len(scores) != len(pool):
        return {"ordered": candidates, "max_score": None, "keep": None}

    ranked = sorted(zip(pool, scores), key=lambda cs: cs[1], reverse=True)
    max_score = ranked[0][1] if ranked else 0.0
    keep = [c for c, s in ranked if s >= settings.rerank_keep_prob]
    ordered = [c for c, _ in ranked] + candidates[settings.rerank_pool :]
    log.info(
        "[RAG] rerank scores=[%s] max=%.3f keep=%d/%d",
        ",".join(f"{s:.2f}" for _, s in ranked), max_score, len(keep), len(pool),
    )
    return {"ordered": ordered, "max_score": max_score, "keep": keep}


def dedup_parents(candidates: list[dict]) -> list[dict]:
    """Collapse child hits to their unique PARENT section, capped at FINAL_CONTEXT."""
    seen: set[str] = set()
    out: list[dict] = []
    for c in candidates:
        key = c.get("parentId") or f"{c.get('source')}||{c.get('chapter') or '_'}"
        if key not in seen:
            seen.add(key)
            out.append(c)
            if len(out) == settings.final_context:
                break
    return out


def to_source(c: dict) -> dict:
    """Candidate -> the §8 source object shape used by meta events and stored msgs.

    Deliberately omits parentText to keep the streamed/stored payload lean — the
    parent section only needs to reach the LLM, via build_context_block.
    """
    return {
        "fileName": c.get("source"),
        "docType": c.get("docType"),
        "chunkIndex": c.get("chunkIndex"),
        "pageStart": c.get("pageStart"),
        "pageEnd": c.get("pageEnd"),
        "chapter": c.get("chapter") or "",
        "text": c.get("text"),
    }


async def retrieve_sources(db: AsyncSession, query: str, level_id: int, use_rerank: bool = False) -> dict:
    """Retrieval-only entry point for the eval harness (handoff §6/§11.3)."""
    res = await retrieve_candidates(db, query, level_id)
    ranked = res["merged"]
    low_confidence = res["vector_fallback_low_conf"]
    if use_rerank:
        rr = await rerank_candidates(query, ranked)
        if rr["max_score"] is not None:
            low_confidence = rr["max_score"] < settings.rerank_gate_prob
            ranked = rr["keep"] if rr["keep"] else rr["ordered"]
        else:
            ranked = rr["ordered"]
    compressed = dedup_parents(ranked)
    return {"lowConfidence": low_confidence, "sources": [to_source(c) for c in compressed]}
