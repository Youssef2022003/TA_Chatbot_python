"""Central configuration for PhysicsTA v2.

Single source of truth for every tunable. The retrieval/rerank/gate constants are
the ones that mattered for v1's bugs (handoff §4.3/§4.4) — keep them here so they
can be tuned against the eval harness (handoff §6), never by feel.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ─── Server ──────────────────────────────────────────────────────────────
    # Default port 3001 matches the existing React frontend's Vite proxy target,
    # so the v1 frontend works against this backend unchanged (handoff §2/§8).
    port: int = 3001
    cors_origin_regex: str = r"^http://localhost(:\d+)?$"

    # ─── Postgres + pgvector (the one store) ─────────────────────────────────
    database_url: str = (
        "postgresql+asyncpg://physicsta:physicsta@localhost:5432/physicsta"
    )

    # ─── Embeddings (local, free — bge) ──────────────────────────────────────
    # bge-small-en-v1.5 = 384-dim (v1 parity). bge-base-en-v1.5 = 768-dim (better).
    # NOTE: changing this changes EMBED_DIM → the KB must be re-ingested.
    embed_model: str = "BAAI/bge-small-en-v1.5"
    embed_dim: int = 384
    embed_batch: int = 64
    # bge is asymmetric: queries get this instruction prefix, passages do not.
    embed_query_prefix: str = (
        "Represent this sentence for searching relevant passages: "
    )

    # ─── Reranker (local, free — replaces v1's LLM-as-judge, handoff §5) ──────
    rerank_model: str = "BAAI/bge-reranker-base"

    # ─── LLM providers (free) ────────────────────────────────────────────────
    groq_api_key: str = ""
    gemini_api_key: str = ""
    groq_text_model: str = "llama-3.3-70b-versatile"   # text primary
    gemini_model: str = "gemini-3.1-flash-lite"        # vision + extraction
    max_answer_tokens: int = 3000

    # ─── PDF parsing ─────────────────────────────────────────────────────────
    # Parser preference (handoff §5): Mistral OCR (cloud, free tier — best for
    # physics: Markdown + LaTeX, fast, correct page numbers) when a key is set,
    # else Docling (local, heavy) if enabled, else PyMuPDF (fast digital text).
    mistral_api_key: str = ""
    mistral_ocr_model: str = "mistral-ocr-latest"
    # Docling = strong local scientific-PDF parser but heavy + slow on CPU for
    # scanned books. Off by default; flip to true once `pip install docling` done.
    use_docling: bool = False
    # Docling processes the PDF in page batches so peak memory stays bounded (a big
    # scanned book OCR'd in one pass exhausts RAM -> std::bad_alloc). batch=1 also
    # yields exact per-page \f boundaries (correct citation page numbers). Raise for
    # speed at the cost of page-number granularity.
    docling_page_batch: int = 1

    # ─── Retrieval / rerank / gating (handoff §6 — tune against eval) ─────────
    retrieve_k: int = 10          # candidates pulled from each retriever
    final_context: int = 5        # unique parent sections fed to the LLM
    rerank_pool: int = 10         # top fused candidates sent to the reranker
    # bge-reranker emits a logit; we sigmoid it to a 0..1 relevance probability.
    # keep chunks scoring >= this; if the BEST chunk is below the gate, the
    # question is off-topic/not-covered -> route to teacher review (handoff §4.4).
    rerank_keep_prob: float = 0.30   # keep chunks at/above this for LLM context
    rerank_gate_prob: float = 0.50   # if the BEST chunk is below this -> off-topic -> review
    # Fallback ONLY (used when the reranker can't load): a crude cosine floor.
    vector_min_score: float = 0.40

    # ─── History ─────────────────────────────────────────────────────────────
    history_turns: int = 6        # last N turns passed to the LLM

    @property
    def default_level(self) -> int:
        from .levels import DEFAULT_LEVEL

        return DEFAULT_LEVEL


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
