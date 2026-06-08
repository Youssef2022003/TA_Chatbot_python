"""FastAPI entrypoint for PhysicsTA v2 (handoff §5/§11).

Runs on port 3001 by default so the existing React frontend (Vite proxy ->
http://localhost:3001) works unchanged. Boots even if the DB/models aren't ready,
degrading gracefully like v1 did.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("physicsta")


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    from .db import init_db
    from .services import embeddings, reranker

    try:
        await init_db()
        log.info("Postgres + pgvector ready")
    except Exception as e:  # noqa: BLE001 - serve health/sessions even if DB is down
        log.warning("DB init failed (%s) — check DATABASE_URL", e)

    # Warm local models in the background (fire-and-forget, v1 parity) so the server
    # is ready immediately; the first question/ingest waits on the model load.
    async def _warm():
        await embeddings.warmup()
        await reranker.warmup()

    asyncio.create_task(_warm())
    yield


app = FastAPI(title="PhysicsTA v2", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from .api import chat, ingest, sessions  # noqa: E402

app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(ingest.router, prefix="/api/ingest", tags=["ingest"])
app.include_router(sessions.router, prefix="/api/sessions", tags=["sessions"])


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "physics-ta-v2", "embedDim": settings.embed_dim}
