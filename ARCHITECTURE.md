# PhysicsTA v2 — Architecture, Features & Design Rationale

A complete reference for the Python/FastAPI backend: **what each feature does** (with
worked examples), **how the system flows** end-to-end, **why we chose this
architecture over the alternatives**, and **what it would take to reach production**
(including where paid APIs make sense).

> Companion docs: [`README.md`](./README.md) (how to run) · [`CLAUDE.md`](./CLAUDE.md)
> (live build status / what's done vs missing) · `PHYSICSTA_V2_HANDOFF.md` in
> `../physics-ta/` (the original spec; section refs like §4.4 point there).

---

## Table of contents

1. [What it is](#1-what-it-is)
2. [Stack at a glance](#2-stack-at-a-glance)
3. [The data model](#3-the-data-model)
4. [Feature-by-feature, with examples](#4-feature-by-feature-with-examples)
5. [End-to-end flows](#5-end-to-end-flows)
6. [Why this architecture (and not the alternatives)](#6-why-this-architecture-and-not-the-alternatives)
7. [The hard-won lessons baked in](#7-the-hard-won-lessons-baked-in)
8. [Path to production (incl. paid-API upgrades)](#8-path-to-production-incl-paid-api-upgrades)

---

## 1. What it is

PhysicsTA is a **grounded, cited AI teaching assistant** for a physics course.

- **Teachers** upload PDF course materials (textbook, past exams, lecture notes),
  tagged with a *document type* and an *education level (1–5)*.
- **Students** chat — they ask physics questions (as text **or a photo of a
  problem**) and get an answer **written for their level, grounded only in the
  uploaded materials, with citations**. Anything off-topic or not covered is routed
  to a **teacher review queue**; the teacher replies and the student sees it in-chat.

**The non-negotiable constraint:** every external API is **free-tier**. The whole
system is designed around free/open-source models and infrastructure.

---

## 2. Stack at a glance

| Layer | Choice | Why (short) |
|---|---|---|
| API | **FastAPI + uvicorn** | async, native SSE streaming, typed |
| Datastore | **Postgres + pgvector** (one DB) | vectors + full-text + sessions + users in one place, transactional |
| Embeddings | **bge-small-en-v1.5** (local, 384-dim) | free, no rate limits, strong retrieval |
| Reranker | **bge-reranker-base** cross-encoder (local) | deterministic relevance, replaces an LLM judge |
| PDF parsing | **Mistral OCR** → Docling → PyMuPDF | best free physics OCR (LaTeX), graceful fallbacks |
| LLM (text) | **Groq llama-3.3-70b** | strong multi-step physics reasoning, free, fast |
| LLM (vision) | **Gemini flash** | sees images, extracts + solves, free |
| Orchestration | **none — plain async Python** | full control over the logic that caused every v1 bug |

Everything runs from `backend/app/`. The pipeline reads top-to-bottom:
`parse → chunk → embed → retrieve → rerank → gate → generate`.

---

## 3. The data model

One Postgres database holds everything (`app/models.py`):

- **`documents`** — one row per uploaded file: `file_name, doc_type, level, status,
  chunks_added, error`. `status` tracks async ingestion (`queued → parsing →
  embedding → ready | error`).
- **`chunks`** — the knowledge base. Each row: `text` (a small "child" chunk),
  `parent_id` + `parent_text` (the larger section it belongs to), `chapter,
  page_start, page_end, level, doc_type, source`, plus two search columns:
  - `embedding vector(384)` — the dense semantic vector (HNSW cosine index).
  - `tsv tsvector` — a **generated** full-text column Postgres maintains itself
    (GIN index) — the keyword/sparse side.
- **`sessions`** — a chat: `title, level, needs_review, created_at, updated_at`.
- **`messages`** — `role` (`user|assistant|teacher`), `content, has_image,
  sources (jsonb), rewritten_query, quoted_text, quoted_role, needs_review`.
- **`users`** — minimal table for the future auth milestone (nullable today).

Timestamps are epoch-**milliseconds** because the reused React frontend computes
`Date.now() - updatedAt` for its "x minutes ago" labels.

---

## 4. Feature-by-feature, with examples

### 4.1 Intent classification (greeting vs question)
**File:** `services/intent.py` · pure regex, no LLM call.

A message can be a greeting, a question, or a **hybrid**. We strip a leading
greeting and decide on what's *left*.

| Input | Classified as | Query sent to RAG |
|---|---|---|
| `hi` | greeting | — (friendly canned-style reply) |
| `hi+` / `ok...` / `hey :)` | greeting | — (tolerates trailing junk) |
| `hi, what is inertia?` | question | `what is inertia?` (greeting stripped) |
| `good morning, can you explain Newton's 2nd law` | question | `explain Newton's 2nd law` |
| `what is motion?` | question | `what is motion?` |

*Why it matters:* in v1, "hi, what is inertia?" got mishandled and "hi+" was treated
as a question that the rewriter then hallucinated a physics topic from (§4.1).

### 4.2 Conditional query rewriting (with a drift guard)
**File:** `services/intent.py` (`needs_rewrite`, `guard_rewrite`) + `services/llm.py`.

Follow-ups like "give me an example" are meaningless without context, so we rewrite
them using chat history. But rewriting a *self-contained* question can inject an
unrelated topic from history — the cause of v1's intermittent hallucination.

- We **only** rewrite when the message depends on prior turns (a follow-up phrase, or
  ≤2 content words) **and** history exists.
- We **guard** the result: if the rewrite shares no content word with the original
  and isn't an explicit follow-up, we discard it and use the raw query.

| Conversation | New message | Rewrite behavior |
|---|---|---|
| …about Newton's laws | `give me an example` | → `give an example of Newton's second law F=ma` ✅ |
| …about Newton's laws | `what's the score of Barça vs Real Madrid?` | rewrite drifts → **discarded**, raw query used → off-topic → review ✅ |
| (no history) | `what is motion?` | not rewritten (self-contained) ✅ |

### 4.3 Hybrid retrieval (dense + sparse + RRF)
**File:** `services/retrieval.py`.

For each query we run **two** searches over `chunks`, filtered to the student's
level (legacy `NULL`-level chunks stay visible to everyone):

1. **Dense** — `embedding <=> query_vector` (pgvector cosine), top 10.
2. **Sparse** — `tsv @@ websearch_to_tsquery(query)` ranked by `ts_rank_cd`, top 10.

The two ranked lists are fused with **Reciprocal Rank Fusion (k=60)**:
`score(doc) += 1 / (60 + rank)`. Crucially we **do not** hard-cut on a cosine
threshold before fusing — that killed recall in v1 (it dropped the real "motion"
chunk). Relevance is decided downstream by the reranker reading the actual text.

*Example:* "what is velocity?" pulls velocity definitions (dense) **and** chunks
literally containing "velocity"/"v =" (sparse); RRF surfaces the ones both agree on.

### 4.4 Cross-encoder rerank + off-topic gate
**File:** `services/reranker.py` + `retrieval.rerank_candidates`.

The fused top-10 go through a **cross-encoder** (`bge-reranker-base`) that scores each
`(query, passage)` pair and we sigmoid it to a 0–1 relevance probability. **One signal
does three jobs** (§4.4):

- **Gate:** if the *best* chunk scores below `RERANK_GATE_PROB` (default 0.30) → the
  question is off-topic/not covered → return the not-found message and **flag for
  teacher review**.
- **Context:** only chunks ≥ `RERANK_KEEP_PROB` feed the LLM.
- **Sources:** the same kept chunks are what we display (no irrelevant "sources").

It **fails open**: if the model can't load, we fall back to a cosine/keyword
heuristic rather than blocking an answer.

| Query | Best rerank score | Outcome |
|---|---|---|
| `what is velocity?` (in book) | high | grounded answer, sources shown |
| `barça vs real madrid` | low (< gate) | "couldn't find this… ask your teacher" + **review** |

### 4.5 Parent-document retrieval
**File:** `services/chunking.py` + `retrieval.dedup_parents`.

We embed **small child chunks** (~170 words) for *precise* matching, but feed the LLM
the **larger parent section** (≤3000 chars) for *complete* context. After reranking we
dedup children down to their unique parent (cap 5). Tables and equations are kept
**atomic** (never split mid-equation); a section never spans two chapters.

*Example:* a query matches one sentence of a worked example (child), but the LLM
receives the **whole** derivation (parent) so it can reason through every step.

### 4.6 Clean citations from noisy OCR headings
**File:** `services/chunking.py`.

OCR produces junk headings ("UNIT OBJECTIVES", "Exercises"). For the citation
"chapter" we prefer the nearest **top-level** heading (`# UNIT ONE`) and **skip
generic boilerplate** (Objectives, Summary, References…). Verified: a sample with
`# UNIT ONE` + `## Objectives` cites *"UNIT ONE"*, never *"Objectives"*.

### 4.7 Grounded generation + the canonical reference footer
**Files:** `services/prompts.py` + `api/chat.py`.

The system prompt forbids outside knowledge, demands inline `[Source N]` citations,
LaTeX math (`$…$`, `$$…$$`), and a closing `📚 Reference:` line. Two safeguards:

- **We never trust the model's footer.** The SSE route *holds back* everything from
  the `📚` marker and replaces it with a footer built **programmatically from the
  real retrieved sources** — so a citation can never name a document that wasn't used.
- **No false "ask your teacher."** A reply is only treated as "no answer" when it's
  *short and is the not-found sentence* (length-bounded), so a long correct answer
  that merely mentions "teacher" isn't wrongly flagged.

*Example output:* `According to … Page 33 of the Textbook: velocity is $v = \Delta x/\Delta t$ [Source 1]` … then a guaranteed-correct `📚 Reference: PHYSICS_1sec_E.pdf (…)`.

### 4.8 Education levels (1–5)
**File:** `levels.py`.

Primary → Postgraduate, each with prompt *guidance* (vocabulary/depth). Every chunk
is tagged with a level at ingest; retrieval filters to the student's level; the prompt
is made level-aware. A student sets it via the header dropdown or `/set_level N`
(persisted per session). The same question answered at L1 vs L4:

- **L1:** "Velocity is how fast something moves and which way it goes."
- **L4:** "Velocity is the time-derivative of the position vector, $\vec v = d\vec r/dt$…"

### 4.9 Image questions (photo of a problem)
**Files:** `services/images.py` + `llm.gemini_*` + `rag.answer_question`.

Three steps (§4.11): (1) a **vision model extracts** the problem into 4 structured
sections — DIAGRAM DESCRIPTION, QUESTIONS (verbatim, numbered), ANSWER CHOICES, GIVEN
DATA; (2) we retrieve on that text; (3) a vision model **sees the image directly** and
solves, using the retrieved formulas, with mandatory citations. We **detect MCQ and
multi-question** images and enforce: answer *every* question; for MCQ state
`Answer: X)` + why the others are wrong. Query-rewriting is skipped for images
(extraction already has every question verbatim).

### 4.10 Reply-to-message
A student can quote any earlier message and ask a follow-up. The quoted text is added
to *both* the retrieval query and the LLM's user message, and persisted
(`quoted_text`/`quoted_role`) so it survives a reload.

### 4.11 Streaming + stop/abort
Answers stream token-by-token over **Server-Sent Events** (`meta → token* → [DONE]`).
The server detects client disconnect via `await request.is_disconnected()` (not a
request-body close — that fires immediately for POST and would blank the answer). The
frontend's Stop button aborts the fetch; partial text is kept.

### 4.12 Teacher review queue + reply
When the gate fires (or the not-found sentence is detected), the message and its
session are flagged `needs_review`. The teacher panel polls `/api/sessions/review`,
shows the flagged thread, and the teacher replies → a `role:"teacher"` message is
saved and the session is marked reviewed. The student's chat polls and shows the green
"Teacher" message.

### 4.13 Document ingestion (async)
**Files:** `api/ingest.py` + `rag.ingest_document`.

Upload returns **immediately** with a job id; the heavy work runs in a background
task so a big textbook never times out the request. Pipeline:
`parse (OCR) → structure-aware + parent-doc chunk → batch-embed → replace chunks`.
**Re-uploading replaces** (old chunks for that filename are deleted first), so stale
chunks never linger.

### 4.14 PDF parsing (3-tier)
**File:** `services/parsing.py`. Tries in order:
1. **Mistral OCR** (cloud, free tier) when `MISTRAL_API_KEY` set — Markdown + **LaTeX
   equations**, fast, correct per-page boundaries. Best for scanned physics.
2. **Docling** (local) — structured markdown, OCRs scans page-by-page (memory-safe).
3. **PyMuPDF** — fast digital-text extraction (no OCR).

### 4.15 Data hygiene
Re-upload replaces; on an embedding-dimension change `init_db` wipes the KB so vector
search can't silently break on mismatched dimensions (§4.9).

---

## 5. End-to-end flows

### A) Text question
```
Student: "hi, what is velocity?"  (level 3, sessionId=…)
   │
POST /api/chat  ──────────────────────────────────────────────► api/chat.py
   │  (SSE opens)
   ├─ intent.classify_intent → question, query="what is velocity?"   (greeting stripped)
   ├─ needs_rewrite? no (self-contained) → query unchanged
   ├─ retrieve_candidates:  dense (pgvector) + sparse (tsvector), level-filtered, RRF
   ├─ rerank_candidates:    cross-encoder scores; best ≥ gate → proceed; keep relevant
   ├─ dedup_parents:        children → unique parent sections (≤5)
   ├─ build prompt:         level-aware + [Source N] context + LaTeX rules
   ├─ stream:               Groq llama-3.3-70b  (Gemini fallback)
   │     → data:{type:"meta", sources, rewrittenQuery, needsReview}
   │     → data:{type:"token", content:"According"} … (hold back the 📚 footer)
   │     → data:{type:"token", content:"\n\n📚 Reference: …"}  (canonical, from real sources)
   │     → data:[DONE]
   └─ persist user + assistant messages (auto-title the session)
```

### B) Image question
```
Photo + optional note
   ├─ gemini_extract_image → DIAGRAM / QUESTIONS / CHOICES / GIVEN DATA (structured)
   ├─ retrieve on the extracted text (no rewrite)
   ├─ rerank + gate + parent-dedup
   ├─ build image prompt + MCQ/multi-question rules
   └─ stream: Gemini (sees the image) solves with citations  (Groq text fallback)
```

### C) Ingestion (background)
```
POST /api/ingest (multipart: document, docType, level)
   ├─ save temp file, upsert document(status="queued"), RETURN {documentId, status} immediately
   └─ background task:
        parsing  → Mistral OCR markdown (per-page \f)
        chunking → child chunks (+ parent_text), level-tagged, chapters cleaned
        embedding→ bge batch-encode
        replace  → delete old chunks for filename, insert new (vector + tsv)
        status   → "ready" (chunks_added=N)  |  "error" (message stored)
```

---

## 6. Why this architecture (and not the alternatives)

### 6.1 No orchestration framework (vs LangChain / LlamaIndex / Haystack)
**Decision:** plain async Python functions calling native libraries directly.
**Why:** *every* hard bug in v1 lived in the retrieval/rewrite/rerank/gating logic —
exactly the layer frameworks abstract away. We need full, explicit, debuggable
control over each step. The pipeline reads top-to-bottom; there's no hidden chain to
fight. Frameworks would add indirection, version churn, and "magic" with zero benefit
here. (This is the handoff's explicit, non-negotiable §5 choice.)

### 6.2 Postgres + pgvector — one store (vs Chroma+BM25, Qdrant, Pinecone)
| Option | Verdict |
|---|---|
| **v1: ChromaDB + hand-rolled BM25 (two stores)** | Rejected — kept desyncing; every "it's still broken" bug traced to stale/unsynced chunks. |
| **Pinecone / Weaviate Cloud (managed)** | Rejected — not free; another service; data leaves your control. |
| **Qdrant** | Viable — native dense+sparse hybrid. But it's a *second* system alongside Postgres (you still need a DB for sessions/users). |
| **✅ Postgres + pgvector** | Chosen — **one** store for vectors, full-text (tsvector), sessions, messages, users. Transactions, no cross-store sync, free/OSS, runs anywhere (incl. free Neon). |

Hybrid search is done in one place: dense via pgvector, sparse via Postgres
`tsvector`, fused with RRF in app code.

### 6.3 Local bge embeddings (vs OpenAI / Cohere / Voyage embeddings)
**Why local:** free, **no rate limits** (v1's Mistral-embed was a 1-req/1.2s
bottleneck), fully offline, and `bge-small-en-v1.5` is strong on retrieval
benchmarks. The trade-off — a one-time model download and CPU inference — is
acceptable and batched. (Paid embeddings can edge it out on quality; see §8.)

### 6.4 Cross-encoder reranker (vs LLM-as-judge, vs no rerank)
**Why a cross-encoder:** v1 used an LLM to score relevance — slow, costs quota,
non-deterministic, and could hallucinate scores. `bge-reranker-base` is **fast,
deterministic, free, and purpose-built**. Reranking is the single most important
retrieval-quality lever, so it's not optional — but it must be cheap and reliable.

### 6.5 Mistral OCR primary (vs local OCR only, vs paid Mathpix)
**Why:** scanned physics PDFs need OCR that understands equations. Local OCR
(RapidOCR/Tesseract) is slow on CPU, OOMs on big books, and garbles math. Mistral OCR
is **free-tier, fast (cloud), and emits Markdown + LaTeX** — a large quality jump
verified on a real book. Docling/PyMuPDF remain automatic fallbacks for offline use.
(Mathpix is better still but paid — see §8.)

### 6.6 Groq llama-3.3-70b (text) + Gemini (vision)
**Why:** both free; Groq is extremely fast and strong at multi-step physics; Gemini
handles vision (Groq can't see images). The fallback wrapper tries the primary and
silently switches if it errors or yields nothing. (Paid GPT-4o/Claude would raise the
answer ceiling — see §8.)

### 6.7 FastAPI + SSE + async background ingestion
**Why:** SSE is the simplest correct way to stream tokens to a browser (the React
frontend already speaks it). FastAPI's async model makes `is_disconnected()` and
background tasks first-class. Ingestion runs in the background so uploads return
instantly.

---

## 7. The hard-won lessons baked in

Each was a real v1 bug; each is enforced in a specific place. (Full table in
[`CLAUDE.md`](./CLAUDE.md).)

- Greeting/question **hybrids** → strip leading greeting (`intent.py`).
- Rewriter **history-bleed** → conditional + drift guard (`intent.py`).
- **No hard cosine cutoff** before fusion → broad retrieve, rerank judges (`retrieval.py`).
- **One rerank signal** → gate + context + sources (`retrieval.py`).
- **Parent-document** context (`chunking.py` + `dedup_parents`).
- **Clean chapters** from OCR noise (`chunking.py`).
- **Canonical citation footer** from real sources (`chat.py`).
- **Level filter**, legacy NULL visible to all (`retrieval.py`).
- **Re-upload replaces**; dim-migration wipe (`rag.py` / `db.py`).
- **SSE disconnect** via `is_disconnected`; **async ingest** (`chat.py` / `ingest.py`).

---

## 8. Path to production (incl. paid-API upgrades)

The system is feature-complete and runs end-to-end on a 100%-free stack. To make it
**production-grade**, here's what to add — split into "must-have hardening" (mostly
free) and "quality upgrades" (where paid APIs pay off).

### 8.1 Must-have hardening (stay free/OSS)
1. **Auth + multi-tenancy.** Real users/sessions (the `users` table exists but is
   unused). Per-student isolation; teacher vs student roles; login (e.g. OAuth/JWT).
2. **Per-user rate limiting.** Protect the free-tier LLM/OCR quotas (e.g. `slowapi`
   or a Redis token bucket) so one user can't exhaust them.
3. **Durable background jobs.** Replace FastAPI `BackgroundTasks` with **arq or
   Celery + Redis** — survives restarts, reports ingest **progress %**, retries.
4. **Alembic migrations.** Today schema is `create_all`; a real embedding-model swap
   needs a managed migration to `ALTER` the `vector(N)` column.
5. **Observability.** Per-stage latency (retrieve/rerank/generate), retrieval
   hit-rate, fallback counts, LLM token usage. Structured logs + a dashboard
   (OpenTelemetry → Grafana/Honeycomb).
6. **Eval in CI.** Grow `app/eval/golden.json`, gate deploys on **Recall@k / MRR**,
   add **ragas** for answer-faithfulness. Tune `RERANK_GATE_PROB`/`RERANK_KEEP_PROB`
   against numbers, not feel.
7. **Security & limits.** Upload size/type validation, virus scan, max pages,
   request timeouts, secrets in a vault (not `.env`), CORS lockdown, HTTPS.
8. **Caching.** Cache embeddings of repeated queries and identical-document hashes;
   cache the OCR result per file hash to avoid re-OCR on re-upload.
9. **Deployment.** Docker Compose → managed (Render/Railway/Fly), managed Postgres
   with pgvector (Neon/Supabase/RDS), model weights baked into the image or a cached
   volume, health/readiness probes, autoscaling the API.

### 8.2 Quality upgrades — where **paid APIs** are worth it
| Component | Free (now) | Paid upgrade | What you gain |
|---|---|---|---|
| **Text generation** | Groq llama-3.3-70b | **GPT-4o / Claude Sonnet/Opus** | Better multi-step physics reasoning, fewer mistakes, stronger instruction-following for citations. |
| **OCR** | Mistral OCR (free tier) | **Mathpix** | Best-in-class equation→LaTeX fidelity for STEM scans (closest to "100%"). |
| **Embeddings** | bge-small (384) | **OpenAI text-embedding-3-large / Voyage / Cohere** | Higher retrieval recall, esp. on nuanced physics phrasing. (Or just go local **bge-base/large** — free, bigger.) |
| **Reranker** | bge-reranker-base | **Cohere Rerank 3** | Higher precision gating; better off-topic detection. |
| **Vision (images)** | Gemini flash | **GPT-4o / Claude vision** | More reliable solving of multi-part / diagram-heavy problems. |
| **OCR accuracy pass** | — | **LLM correction pass** (Gemini/Groq, free) | Per page: image+OCR→LLM fixes spacing/superscripts, forces LaTeX. ~90%→~98% (already scoped; see CLAUDE.md). |

**Rule of thumb:** spend paid budget first on **generation quality** (it's what the
student sees) and **OCR fidelity** (Mathpix) if your sources are equation-heavy scans.
Embeddings/rerank upgrades are smaller, measurable wins — verify them against the eval
harness before paying.

### 8.3 Correctness upgrades (free or paid)
- **Numeric verification via tool-use / code execution.** Have the model *run* the
  arithmetic (sandboxed Python) instead of doing mental math — a known accuracy win
  for physics calculations.
- **HyDE / multi-query retrieval.** Generate a hypothetical answer or query variants
  to boost recall on hard questions.
- **Born-digital sources.** The single biggest "accuracy" lever: if a publisher PDF
  with a real text layer exists, skip OCR entirely (~100% text fidelity).
- **Human-in-the-loop editing.** A teacher "edit extracted text before indexing" step
  — the only path to *guaranteed* correctness on critical pages.

---

*This document describes the system as built. For the live "done vs missing" status
and per-file map, see [`CLAUDE.md`](./CLAUDE.md).*
