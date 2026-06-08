# PhysicsTA v2 (Python) — Build Progress Tracker

> **What this is:** the Python/FastAPI rewrite of the PhysicsTA backend, built to
> `physics-ta/PHYSICSTA_V2_HANDOFF.md`. The v1 Node backend is the behavioral
> reference; this reuses the **React frontend unchanged** by preserving the v1 API
> contract (handoff §8). This file tracks **what's implemented and what's missing**.
>
> **Read the handoff first** (`../physics-ta/PHYSICSTA_V2_HANDOFF.md`). Section
> references below (§4, §5, …) point into it. The §4 "hard-won lessons" are baked
> into the code; do not regress them.

Last updated: 2026-06-08 · Status: **running live against Neon — FULL RAG verified +
35/35 endpoint smoke tests pass.** A 148-page scanned textbook was OCR'd via **Mistral
OCR** → **358 chunks** (correct page numbers, LaTeX). Verified: grounded cited answers,
greeting path, off-topic→review, levels, reply-to numeric worked examples, teacher
review/reply, persistence. Test scripts in `scripts/` (`smoke_test.py`,
`physics_followup_test.py`).

**Bug found & fixed by testing:** messages weren't persisted when a client
disconnected the instant it saw `[DONE]` (the SSE generator was cancelled before the
DB write). Fixed by persisting **before** yielding `[DONE]` (`api/chat.py`).

---

## TL;DR status

| Area | Status | Notes |
|---|---|---|
| Scaffold (FastAPI, pgvector, Docker) | ✅ Done | boots on :3001 so the v1 frontend works unchanged |
| Single store (Postgres + pgvector) | ✅ Done | vectors + FTS + sessions + messages + docs in one DB |
| Ingestion (parse→chunk→embed→upsert, async) | ✅ Done | background task; Docling optional, PyMuPDF default |
| Retrieval (hybrid + RRF + level filter + rerank gate + parent-dedup) | ✅ Done | cross-encoder replaces v1's LLM-judge |
| Generation (grounded streaming, canonical footer, no-answer→review) | ✅ Done | Groq text primary / Gemini vision |
| Parity features (levels, image, reply-to, stop, teacher review) | ✅ Done (backend) | contract-compatible with v1 frontend |
| Eval harness | ✅ Done | Recall@k / MRR; needs a real golden set + ingested KB |
| Auth / multi-user / rate-limit | ⛔ Deferred | `users` table exists; no auth yet |
| Verified live (Neon pgvector) | ✅ Done | init_db creates extension+HNSW+GIN+tables on Neon; `/api/health`, `/api/sessions`, session round-trip, and greeting SSE/LLM stream all confirmed |
| Full RAG path (PDF ingest → grounded answer) | ⏳ Pending | infra proven; needs a real PDF + first-use model load |

Legend: ✅ done · 🟡 partial · ⏳ pending verification · ⛔ not started/deferred

---

## Architecture decisions (per handoff §5)

- **No agent framework.** Plain async functions calling native libs directly
  (SQLAlchemy/asyncpg, sentence-transformers, Groq/Gemini SDKs). Every
  rewrite/rerank/gate decision is explicit in `services/` — deliberate (§5).
- **One datastore: Postgres + pgvector.** Dense = `vector` + HNSW cosine; sparse =
  generated `tsvector` + GIN + `websearch_to_tsquery`; fused with RRF (k=60) in app
  code. Kills v1's Chroma+BM25 hand-sync.
- **Local, free models.** Embeddings `BAAI/bge-small-en-v1.5` (384-dim);
  reranker `BAAI/bge-reranker-base` (CrossEncoder) — replaces v1's LLM-as-judge.
- **LLMs (free):** Groq `llama-3.3-70b` primary for text; Gemini for vision +
  image extraction. Native SDKs, streamed, with empty-response fallback.
- **PDF parsing:** **Mistral OCR** (cloud, free tier) primary when `MISTRAL_API_KEY`
  set — Markdown + LaTeX equations, fast (one server-side call), correct page
  numbers, best on physics/math (verified: cleaner than local OCR, emits `$$…$$`).
  Falls back to Docling (local, page-by-page to bound memory) then PyMuPDF.
- **Async ingestion:** FastAPI `BackgroundTasks` (handoff allowed this as the
  simpler start; swap to arq/Celery+Redis for progress/scale — see gaps).

---

## File map (where each piece lives)

```
physics-ta-v2/
├── CLAUDE.md                       ← this tracker
├── README.md                       ← how to run
├── docker-compose.yml              ← db (pgvector) + api
└── backend/
    ├── requirements.txt  Dockerfile  .env.example
    └── app/
        ├── main.py                 FastAPI app, CORS, lifespan, /api/health
        ├── config.py               all tunables (retrieval/rerank/gate consts)
        ├── levels.py               education levels 1–5 (handoff §7)
        ├── db.py                   async engine, init_db, dim-migration guard
        ├── models.py               ORM: documents, chunks, sessions, messages, users (§10)
        ├── schemas.py              camelCase request models + serializers (§8)
        ├── api/
        │   ├── chat.py             POST /api/chat — SSE (§8, §4.7, §4.10)
        │   ├── ingest.py           upload(async)/stats/delete/clear
        │   └── sessions.py         sessions CRUD + review queue + teacher-reply
        ├── services/
        │   ├── embeddings.py       bge, lazy, off-event-loop (§5)
        │   ├── reranker.py         CrossEncoder, sigmoid→prob, fails open (§4.4)
        │   ├── parsing.py          Docling | PyMuPDF (§5)
        │   ├── chunking.py         structure-aware + parent-document (§4.5/§4.6)
        │   ├── intent.py           regex intent classify + rewrite guard (§4.1/§4.2)
        │   ├── images.py           MCQ/multi-question rules (§4.11)
        │   ├── llm.py              Groq+Gemini streams, fallback wrapper (§8)
        │   ├── prompts.py          grounded prompts + canonical reference (§4.7)
        │   ├── retrieval.py        hybrid+RRF+rerank gate+parent-dedup (§6)
        │   ├── store.py            all DB reads/writes
        │   └── rag.py              orchestrator: ingest_document, answer_question
        └── eval/
            ├── evaluate.py         Recall@k / MRR harness (§11.3)
            └── golden.json         golden-set template (edit for real docs)
```

---

## Feature parity checklist (handoff §9)

- [x] Student chat: sessions, history (last ~6 turns), streaming, auto-title.
- [x] Education levels 1–5: `/set_level` + header dropdown (frontend), per-session
      persistence, level-aware retrieval **and** prompt.
- [x] Image questions: structured extraction → retrieval → vision solve; MCQ +
      multi-question enforcement (`services/images.py`, `llm.gemini_*`).
- [x] Reply-to-message: `replyTo` quote added to retrieval query + LLM message;
      `quotedText`/`quotedRole` persisted.
- [x] Stop/abort streaming: server honors `await request.is_disconnected()`
      (frontend AbortController already wired).
- [x] Grounded answers + inline `[Source N]` + **canonical** `📚 Reference` footer
      built from real sources (held back the model's footer). KaTeX is frontend.
- [x] Off-topic / not-found gating → teacher Review Queue (rerank gate + length-
      bounded no-answer detection).
- [x] Teacher panel endpoints: upload (type + **level**), stats with level +
      per-doc chunks/status, per-doc delete, clear-all.
- [x] Teacher reply flow: `POST /sessions/:id/teacher-reply` → student polling sees
      the green "Teacher" message.
- [x] Data hygiene: re-upload replaces (delete-by-source first); embedding-dim
      migration guard; **async** ingestion.

---

## API contract status (handoff §8) — all preserved

| Endpoint | Status |
|---|---|
| `POST /api/chat` (SSE: meta/token/review/error/[DONE]) | ✅ |
| `POST /api/ingest` (multipart) → returns job id (async) | ✅ ¹ |
| `GET /api/ingest/stats` | ✅ (adds per-doc `status`) |
| `DELETE /api/ingest/document/:fileName` · `DELETE /api/ingest/clear` | ✅ |
| `GET/POST /api/sessions`, `GET /api/sessions/:id/messages`, `DELETE /api/sessions/:id` | ✅ |
| `PATCH /api/sessions/:id/level` · `PATCH /api/sessions/:id/review` · `POST /api/sessions/:id/teacher-reply` | ✅ |
| `GET /api/sessions/review` · `GET /api/sessions/review/count` | ✅ |

¹ **Async upload note:** the response returns `chunksAdded: 0` + `status:"queued"`
immediately (ingestion runs in the background). The v1 `UploadDropzone` toast will
briefly read "0 chunks indexed"; the document list (from `/stats`) then shows the
real chunk count + live `status` (queued→parsing→embedding→ready). A 1-line
frontend tweak to show "processing…" is the only optional parity polish (see gaps).

---

## Hard-won v1 lessons — where each is enforced (handoff §4)

| § | Lesson | Implemented in |
|---|---|---|
| 4.1 | Greeting+question hybrids (regex, strip leading greeting) | `intent.classify_intent` |
| 4.2 | Rewriter history-bleed guard (only follow-ups; drop drift) | `intent.needs_rewrite` / `guard_rewrite` |
| 4.3 | No hard cosine cutoff before fusion | `retrieval.retrieve_candidates` (fuse all) |
| 4.4 | One reranker signal → gate + context + sources | `retrieval.rerank_candidates` (gate/keep) |
| 4.5 | Parent-document retrieval | `chunking` (parent_id/parent_text) + `dedup_parents` |
| 4.6 | Clean chapter from noisy OCR headings | `chunking._is_generic_heading` / top-level pref |
| 4.7 | Grounding + **canonical** reference footer | `prompts.build_reference` + `chat.py` hold-back |
| 4.8 | Education-level filter + legacy NULL visible to all | `retrieval._level_filter` |
| 4.9 | Re-upload replaces; dim-migration wipe | `rag.ingest_document` / `db.init_db` |
| 4.10 | SSE disconnect via `is_disconnected`; async ingest | `chat.py` / `ingest.py` BackgroundTasks |
| 4.11 | Image pipeline shape (extract → retrieve → vision solve) | `rag.answer_question` + `images.py` |

---

## Acceptance criteria (handoff §12) — how to verify once running

1. "what is motion?" (in book) → grounded answer, correct chapter, **not** flagged.
2. "difference between Newton 1st and 2nd law" → grounded, no false "ask teacher".
3. Off-topic ("barça vs real madrid") → not-found + **review**, regardless of history.
4. Re-upload a PDF at a level → doc shows that level; old chunks gone; coverage updates.
5. Eval harness reports Recall@k + MRR on a golden set.
6. Big textbook ingests asynchronously without timing out the upload.

> These are **not yet executed** here (no live Postgres/model download in this
> environment). Code compiles (`python -m py_compile` over all modules passes).
> Run them per README before sign-off.

---

## What's MISSING / DEFERRED (do these next)

1. **Off-topic gate tuning.** `RERANK_GATE_PROB` is now `0.50`. The scanned book has
   garbage OCR pages (Spanish/Arabic) the cross-encoder still scores > 0.5 on unrelated
   queries, so the gate alone doesn't catch every off-topic question — but the **LLM
   grounded-refusal fallback does** (it returns the not-found message → review, and the
   `review` event clears the sources). Outcome is correct; to make the gate itself
   cleaner, tune against the eval harness and/or filter non-English OCR noise at ingest.
2. **Gemini SDK surface.** Uses `google-generativeai` async streaming
   (`send_message_async(..., stream=True)`). If the installed SDK version differs,
   adjust `services/llm.py` (or switch to the newer `google-genai`). Model id
   `gemini-3.1-flash-lite` carried from v1 — confirm it resolves on your key.
3. **Dimension change isn't a full migration.** `init_db` wipes rows on a dim
   mismatch but cannot `ALTER` the fixed `vector(N)` column. For a real model swap,
   add an **Alembic** migration to drop/recreate `chunks.embedding`. Fresh DBs are fine.
4. **Background ingestion has no progress/durability.** FastAPI `BackgroundTasks`
   dies with the process and reports no progress %. Swap to **arq/Celery + Redis**
   for a job queue with progress + retries (handoff §5).
5. **Auth / multi-user / per-user rate-limit.** `users` table + nullable
   `sessions.user_id` exist; no login, isolation, or quota guard yet (handoff §5/§11.6).
6. **Optional frontend polish:** upload toast "processing…" for async ingest;
   optional doc `status` badge in TeacherPanel. Pure cosmetics — contract unchanged.
7. **ragas answer-faithfulness eval** (handoff §6) — only Recall@k/MRR implemented.
8. **Numeric verification via tool-use/code-execution** for physics calcs — noted
   as a correctness upgrade in the handoff; not implemented.
9. **Docling enablement.** ✅ Installed + `USE_DOCLING=true` + OCR verified on real
   + synthetic scanned PDFs. **OOM fixed:** large scanned books were exhausting RAM
   (`std::bad_alloc` ~page 139) because Docling OCR'd all pages in one pass — now
   processed **page-by-page** (`DOCLING_PAGE_BATCH=1`), which bounds memory AND
   restores real per-page `\f` boundaries (correct citation page numbers). Trade-off:
   page-by-page is slow on a big book (~few seconds/page on CPU); raise
   `DOCLING_PAGE_BATCH` for speed at the cost of page granularity. Caveat: OCR isn't
   perfect on equations/words (e.g. "acce leration") — fine for retrieval, imperfect
   for verbatim citations. Note: the first ingest (before this fix) stored 35 chunks
   with `pageStart:1` and dropped pages 139+; **re-upload to get the full, page-
   accurate book.**
10. **Tests.** No unit tests yet — start with `intent.py` and `chunking.py` (pure,
    deterministic) and a retrieval integration test against a seeded DB.

---

## How to run (summary — full steps in README.md)

```bash
docker compose up -d db                      # Postgres + pgvector
cd backend && python -m venv .venv && . .venv/Scripts/activate   # (PowerShell: .venv\Scripts\Activate.ps1)
pip install -r requirements.txt
cp .env.example .env                         # add GROQ_API_KEY + GEMINI_API_KEY
uvicorn app.main:app --port 3001 --reload    # first boot downloads the bge + reranker models

# Frontend (reused unchanged): in ../physics-ta/frontend → npm install && npm run dev
# Vite already proxies /api → http://localhost:3001
```

Tables + indexes (incl. pgvector extension, HNSW, GIN, tsvector) are created
automatically on first boot by `db.init_db()`.
