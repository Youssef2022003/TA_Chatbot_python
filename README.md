# PhysicsTA v2 — Python / FastAPI backend

A production-grade Python rewrite of the PhysicsTA backend (a grounded, cited AI
physics teaching assistant). Built to `../physics-ta/PHYSICSTA_V2_HANDOFF.md`. It
**reuses the v1 React frontend unchanged** by preserving the v1 HTTP/SSE API
contract (handoff §8).

> **[SETUP.md](./SETUP.md)** — friend-proof, step-by-step "clone and run it" guide.
> **[ARCHITECTURE.md](./ARCHITECTURE.md)** — every feature with examples, end-to-end
> flows, why-this-vs-alternatives, and the path to production (incl. paid APIs).
> **[CODE_WALKTHROUGH.md](./CODE_WALKTHROUGH.md)** — file-by-file tour of the actual
> code: key functions, data structures, and the tricky algorithms line-by-line.
> **[CLAUDE.md](./CLAUDE.md)** — live "done vs missing" status + per-file map.

## Stack (all free / OSS)

- **API:** FastAPI + uvicorn (async, native SSE)
- **Store:** Postgres + **pgvector** — one DB for vectors, full-text, sessions,
  messages, documents (no dual-store sync)
- **Embeddings:** `BAAI/bge-small-en-v1.5` (384-dim, local, sentence-transformers)
- **Reranker:** `BAAI/bge-reranker-base` CrossEncoder (local — replaces LLM-as-judge)
- **PDF:** Docling (optional, best quality) → PyMuPDF fallback
- **LLM:** Groq `llama-3.3-70b` (text), Gemini flash (vision + image extraction)

## Prerequisites

- Python 3.11+
- Docker (for Postgres + pgvector) — or any Postgres 16 with the `vector` extension
- Free API keys: [Groq](https://console.groq.com) and [Google Gemini](https://aistudio.google.com)

## Run (local dev)

You need a Postgres with **pgvector**. Easiest is a free hosted one
([Neon](https://neon.tech)): create a project and copy its connection string into
`backend/.env` as `DATABASE_URL` — `db.py` auto-adds the `+asyncpg` driver and
handles `?sslmode=require`. (Or run `docker compose up -d db` for a local one.)

This project was set up with **[uv](https://docs.astral.sh/uv/)** (no system `pip`
needed):

```powershell
cd backend
uv venv --python 3.11
uv pip install -r requirements.txt
copy .env.example .env             # then fill in DATABASE_URL + GROQ/GEMINI keys

# Launch (use the venv's Python directly — `uv run` won't pick up a bare .venv
# without a pyproject.toml):
.venv\Scripts\python -m uvicorn app.main:app --port 3001 --reload
```

(bash: `source .venv/bin/activate && uvicorn app.main:app --port 3001 --reload`)

First boot connects to the DB and auto-creates all tables/indexes (pgvector
extension, HNSW, GIN, tsvector). The bge embedding + reranker models (~hundreds of
MB) download in the background on first use, so the server is ready immediately;
the first question/ingest waits on that one-time load. Verify with
`http://localhost:3001/api/health`.

```bash
# 3) Frontend (bundled in this repo — Vite already proxies /api → :3001)
cd ../frontend
npm install
npm run dev          # http://localhost:5173
```

## Run (Docker Compose — db + api)

```bash
# set GROQ_API_KEY and GEMINI_API_KEY in your shell or a root .env
docker compose up --build
```

The `api` service listens on `:3001`. Run the frontend separately as above.

## Eval (tune retrieval by numbers — handoff §4.3)

```bash
cd backend
# edit app/eval/golden.json to match your ingested documents, then:
python -m app.eval.evaluate            # hybrid fusion only
python -m app.eval.evaluate --rerank   # with the cross-encoder gate
# -> Recall@final, MRR, low-confidence count
```

## Configuration

All settings live in `backend/app/config.py` and are overridable via `.env`
(`backend/.env.example` documents them). The retrieval/rerank/gate constants
(`RERANK_GATE_PROB`, `RERANK_KEEP_PROB`, `RETRIEVE_K`, `FINAL_CONTEXT`) are the ones
to tune against the eval harness.

## Project layout

See [CLAUDE.md](./CLAUDE.md) for the annotated file map and the full
implemented / missing breakdown.
