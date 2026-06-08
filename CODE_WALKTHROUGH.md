# PhysicsTA v2 — Code Walkthrough

A file-by-file tour of the **actual code**. Read it top-to-bottom once to build a
mental model, then dip back in per module. Each section says *what the file is for*,
walks the *key functions*, and zooms in on the *tricky bits* (with the real code).

> Design-level "why" lives in [`ARCHITECTURE.md`](./ARCHITECTURE.md); this doc is the
> "how the code actually works" companion. Paths are under `backend/app/`.

**Mental model:** a request enters at `api/*.py`, which calls `services/rag.py` (the
orchestrator). `rag.py` strings together the small single-purpose modules:
`intent → llm/parsing → retrieval (→ embeddings + reranker + the DB) → prompts → llm`.
`store.py` is the only place that reads/writes the database. Everything is `async`.

Reading order:
`config → levels → db → models → schemas → services(embeddings, reranker, parsing,
chunking, intent, images, llm, prompts, retrieval, store, rag) → api(chat, ingest,
sessions) → main → eval`.

---

## 0. Async & SQLAlchemy primer (skim if you know it)

- **`async def` / `await`**: functions that can pause at `await` points (I/O — DB
  queries, HTTP calls). FastAPI runs them on one event loop, so blocking CPU work
  (model inference) is pushed to threads with `asyncio.to_thread(fn, ...)`.
- **`async for token in stream:`** consumes an **async generator** — a function with
  `yield` inside an `async def`. We use these to stream LLM tokens.
- **SQLAlchemy 2.0 ORM**: tables are Python classes (`models.py`); rows are objects.
  Queries are built with `select(Model).where(...)` and run via `await
  session.execute(stmt)`. `session.scalars(...)` returns model objects; `.all()` /
  `.first()` materialize them. `await session.commit()` persists.

---

## 1. `config.py` — one place for every knob

`Settings` is a `pydantic-settings` model: each attribute is a config value with a
default, automatically overridable by an env var of the same (upper-cased) name and
read from `.env`. Example: `rerank_gate_prob: float = 0.30` is overridden by
`RERANK_GATE_PROB=0.4` in `.env`.

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+asyncpg://…"
    embed_model: str = "BAAI/bge-small-en-v1.5"
    embed_dim: int = 384
    rerank_gate_prob: float = 0.30   # off-topic gate
    ...
settings = get_settings()            # one cached instance imported everywhere
```

The retrieval/rerank constants (`retrieve_k`, `final_context`, `rerank_pool`,
`rerank_gate_prob`, `rerank_keep_prob`, `vector_min_score`) live here on purpose —
they're what you tune against the eval harness. `get_settings()` is `@lru_cache`'d so
there's exactly one `Settings` instance process-wide.

---

## 2. `levels.py` — the 1–5 education system

A plain dict `LEVELS[1..5]`, each entry holding `id, key, name, short, guidance`. The
`guidance` string is injected verbatim into the LLM prompt ("Explain as if to a 7–10
year old…"). Three helpers guard against bad input:

- `normalize_level(value)` → coerces anything (str/int/None) to a valid `1..5`,
  defaulting to `3`. Used everywhere a level arrives from outside.
- `is_valid_level(value)` → bool, for request validation (`PATCH …/level`).
- `get_level(value)` → returns the full dict for a (normalized) level.

This is the single source of truth; the frontend keeps only a label mirror.

---

## 3. `db.py` — engine, Neon URL handling, schema bootstrap

### 3.1 `_normalize_url(raw)` — making any Postgres URL work with asyncpg
The trickiest 30 lines in the file, because hosted Postgres (Neon/Supabase) hands you
a `libpq`-style URL that the **asyncpg** driver doesn't fully understand.

```python
def _normalize_url(raw):
    url = raw.strip()
    if url.startswith("postgres://"):                 # Neon sometimes uses this
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)   # force async driver
    parts = urlsplit(url); q = dict(parse_qsl(parts.query)); connect_args = {}
    sslmode = q.pop("sslmode", None)                  # asyncpg doesn't take 'sslmode='
    q.pop("channel_binding", None)                    # …or this — strip both
    if sslmode and sslmode != "disable":
        connect_args["ssl"] = sslmode                 # translate to asyncpg's ssl arg
    elif "neon.tech" in parts.netloc or "supabase" in parts.netloc:
        connect_args["ssl"] = "require"               # hosted => TLS even if unstated
    if "pooler" in parts.netloc or "pgbouncer" in parts.netloc:
        connect_args["statement_cache_size"] = 0      # PgBouncer txn mode breaks prepared stmts
    clean = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q), parts.fragment))
    return clean, connect_args
```

Why each line exists: `sslmode`/`channel_binding` are query params asyncpg rejects, so
we *remove them from the URL* and instead pass `ssl="require"` in `connect_args`; and
Neon's **pooler** endpoint runs PgBouncer in transaction mode, which is incompatible
with asyncpg's prepared-statement cache, so we disable it. The engine is then built
once at import:

```python
_url, _connect_args = _normalize_url(settings.database_url)
engine = create_async_engine(_url, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
```

### 3.2 `get_session()` — the request-scoped DB dependency
```python
async def get_session():
    async with SessionLocal() as session:
        yield session         # FastAPI injects this; closes the session after the request
```

### 3.3 `init_db()` — create extension, tables, indexes; dim-migration guard
Run once at startup (from `main.py`'s lifespan):
```python
async with engine.begin() as conn:
    await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))   # pgvector
    await conn.run_sync(Base.metadata.create_all)                       # all tables + indexes
```
Then it checks the stored vector dimension; if it no longer matches
`settings.embed_dim` (you switched embedding models), it **wipes the KB** so vector
search can't silently break on mismatched dimensions (§4.9). On a fresh DB this branch
never fires.

---

## 4. `models.py` — the tables as Python classes

SQLAlchemy 2.0 "Mapped" style: each `Mapped[...] = mapped_column(...)` is a column.
Two things are non-obvious:

**The dense + sparse columns on `Chunk`:**
```python
embedding: Mapped[list[float]] = mapped_column(Vector(settings.embed_dim))   # pgvector, 384-dim
tsv: Mapped[str] = mapped_column(
    TSVECTOR, Computed("to_tsvector('english', text)", persisted=True)        # generated by Postgres
)
```
`embedding` is the semantic vector. `tsv` is a **generated column** — we never write
to it; Postgres derives it from `text` automatically and keeps it in sync. That's the
keyword/sparse side of hybrid search, with **zero** app-side bookkeeping (the thing v1
got wrong with a hand-rolled BM25).

**The indexes** (in `__table_args__`):
```python
Index("ix_chunks_embedding_hnsw", "embedding", postgresql_using="hnsw",
      postgresql_with={"m":16,"ef_construction":64},
      postgresql_ops={"embedding":"vector_cosine_ops"}),   # fast approximate cosine KNN
Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),     # fast full-text
Index("ix_chunks_level", "level"),                          # level filter
```

`now_ms()` returns `int(time.time()*1000)` — all timestamps are epoch-milliseconds so
the React frontend's `Date.now() - updatedAt` math works. `new_uuid()` gives string
UUIDs for primary keys. `Document.status` drives the async ingestion UI
(`queued→parsing→embedding→ready|error`). `Session.messages` is a relationship with
`cascade="all, delete-orphan"` so deleting a session deletes its messages.

---

## 5. `schemas.py` — camelCase in, camelCase out

The React frontend speaks **camelCase** (`imageBase64`, `sessionId`); Python prefers
snake_case. Pydantic bridges it:
```python
class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
class ChatRequest(_CamelModel):
    image_base64: str | None = None      # accepts "imageBase64" from JSON
    session_id: str | None = None        # accepts "sessionId"
    ...
```
`ChatRequest.model_validate(body)` parses the incoming JSON by alias. For **output**
we don't rely on Pydantic — explicit serializers (`serialize_session`,
`serialize_message`, `serialize_document`) build the exact dict shape v1 returned
(e.g. `needsReview`, `createdAt` as ms), so the contract is unmistakable.

---

## 6. `services/embeddings.py` — local bge vectors

The model is loaded **lazily** (first use) and guarded by an `asyncio.Lock` so two
concurrent requests don't both load it:
```python
async def _get_model():
    global _model
    if _model is not None: return _model
    async with _lock:
        if _model is None:
            from sentence_transformers import SentenceTransformer
            _model = await asyncio.to_thread(SentenceTransformer, settings.embed_model)
    return _model
```
- `embed_passages(texts)` — batches (`embed_batch=64`), L2-normalizes, returns
  `list[list[float]]`. Used at ingest.
- `embed_query(text)` — prepends the **bge query instruction**
  (`"Represent this sentence for searching relevant passages: "`) because bge is
  *asymmetric* (queries are prefixed, passages are not). Used at query time.

Both push the actual `.encode()` (CPU-bound) into a thread via `asyncio.to_thread`, so
the event loop isn't blocked.

---

## 7. `services/reranker.py` — the cross-encoder

Same lazy-load pattern, but with a `_unavailable` flag so a failed load is remembered
and we don't retry forever. The core:
```python
async def rerank(query, passages):
    model = await _get_model()
    if model is None: return None                 # fail open -> caller uses heuristic
    pairs = [[query, str(p)[:1024]] for p in passages]
    scores = await asyncio.to_thread(model.predict, pairs)
    return [sigmoid(float(s)) for s in scores]    # logit -> 0..1 probability
```
The cross-encoder outputs a raw **logit** per `(query, passage)` pair; `sigmoid()`
maps it to an interpretable 0–1 probability so the gate threshold
(`rerank_gate_prob`) means something. Returning `None` (not raising) is deliberate —
the pipeline degrades gracefully if the model can't load.

---

## 8. `services/parsing.py` — PDF → text/markdown (3 tiers)

`extract_document(path, name)` tries, in order, and returns `(text, is_markdown)`:
```python
if settings.mistral_api_key:                       # 1. Mistral OCR (best for physics)
    md = await asyncio.to_thread(_mistral_ocr_markdown, path, name)
    if _has_text(md): return md, True
if settings.use_docling:                            # 2. Docling (local OCR)
    md = await asyncio.to_thread(_docling_markdown, path)
    if _has_text(md): return md, True
text = await asyncio.to_thread(_pymupdf_text, path) # 3. PyMuPDF (digital text, no OCR)
```

- `_mistral_ocr_markdown` — uploads the file, calls `client.ocr.process(...)`, joins
  the **per-page** markdowns with `\f`, deletes the upload. The `\f` matters: the
  chunker splits on it to recover page numbers.
- `_docling_markdown` — processes the PDF **one page-batch at a time**
  (`DOCLING_PAGE_BATCH`, default 1) so a big scanned book doesn't exhaust RAM
  (`std::bad_alloc`); a page that fails OCR is skipped, not fatal. Joins pages with `\f`.
- `_pymupdf_text` — fast `page.get_text()` per page, joined with `\f`. Raises if the
  result is basically empty (a scanned PDF with no text layer → forces a real OCR tier).

The boolean `is_markdown` flows into the chunker so it knows whether to parse ATX
headings/pipe tables (markdown) or use plain-text heuristics.

---

## 9. `services/chunking.py` — the meatiest algorithm

Turns pages into **child chunks** that each carry their **parent section** text. Read
this one slowly; it's the core of retrieval quality.

### 9.1 Page → typed blocks
`_page_to_blocks(page_text, markdown)` walks lines and emits typed blocks:
`heading | table | para`. Consecutive markdown table rows (`| … |`) merge into one
**atomic** `table` block; blank lines flush the current paragraph. Headings are
detected by `#` (markdown) or an all-caps/short heuristic (plain text).

### 9.2 Building the section/parent/child hierarchy
`chunk_document(pages, file, doc_type, level, markdown)` does it in four passes:

1. **Flatten** every page's blocks into `items`, tracking the current **chapter** —
   preferring the nearest *top-level* heading and **skipping generic** ones
   (Objectives, Summary…) via `_is_generic_heading`. This is what keeps citations
   clean (§4.6).
2. **Segment into sections** — a new section starts at each heading, so a section
   never spans two chapters.
3. **Split sections into parents** bounded by `PARENT_MAX_CHARS=3000` — the parent is
   the big context block fed to the LLM.
4. **Slide a window over each parent to emit children** — the tricky part:

```python
for it in group:
    w = _count_words(it["text"]); would_exceed = w_words + w > CHILD_MAX
    atomic = _is_equation_line(it["text"]) or it["kind"] == "table"
    if (w_words >= CHILD_TARGET and would_exceed and not atomic
            and _ends_with_sentence(win[-1]["text"])):
        emit_child()                          # flush a ~170-word child
        last = win[-1]                        # overlap: carry the last block forward
        win = [last]; w_words = _count_words(last["text"])
    win.append(it); w_words += w
emit_child()                                  # flush the tail
```

Plain-English: accumulate blocks into a window; once it's past `CHILD_TARGET` (170
words), would exceed `CHILD_MAX` (260), the last block ends a sentence, **and** the
current block isn't an equation/table, flush a child. Carry the last block into the
next window (1-block **overlap**) so an answer split across a boundary keeps its
context. **Never** flush mid-equation or mid-table (`atomic`) — that's why `F = ma`
stays with the sentence that introduces it.

Each emitted child is a dict with `text`, the metadata (`source, doc_type, level,
chunk_index, word_count, page_start/end, chapter`) **and** `parent_id` + `parent_text`
— so retrieval can match the small child but hand the LLM the whole parent.

> Implementation note: `emit_child` is a nested function using `nonlocal global_idx,
> win, w_words` to mutate the enclosing loop's state — that's why it can flush and
> reset the window in place.

---

## 10. `services/intent.py` — pure-regex routing (no LLM)

Three regexes do the work:
- `PURE_GREETING_RE` — matches a whole message that's *only* a pleasantry, ending in
  `\W*` so trailing junk (`hi+`, `ok...`) still counts as a greeting.
- `LEADING_GREETING_RE` — matches a greeting *prefix* so it can be stripped off a
  hybrid ("hi, what is inertia?" → "what is inertia?").
- `FOLLOWUP_RE` — phrases that legitimately depend on history ("example", "more"…).

```python
def classify_intent(raw):
    text = raw.strip()
    if len(text) < 60 and PURE_GREETING_RE.match(text):
        return {"kind": "greeting", "query": text}
    stripped = LEADING_GREETING_RE.sub("", text).strip()
    if stripped != text and _has_substance(stripped):
        return {"kind": "question", "query": stripped}     # hybrid -> question remainder
    ...
    return {"kind": "question", "query": text}
```
`_has_substance` = has a `?`, a question word, or ≥2 content words (guards against
"hi :)" leftovers).

The rewrite guards:
- `needs_rewrite(query)` → `True` only for follow-ups or ≤2-content-word messages.
- `guard_rewrite(original, rewritten)` → keeps the rewrite only if it shares a content
  word with the original *or* the original is an explicit follow-up; else returns the
  raw query. This is what stops "barça vs real madrid" from being rewritten into a
  physics question off chat history (§4.2). `_content_words` lowercases, keeps tokens
  >2 chars, drops a stopword set.

---

## 11. `services/images.py` — MCQ / multi-question rules

Tiny but important. `detect_mcq(text)` regex-spots answer choices; `count_questions`
finds the max `Q<n>:`. `build_image_rules(extracted)` returns extra prompt lines: use
the exact diagram values; if >1 question, answer **all** in numbered order; if MCQ,
state `Answer: X)` + why the others are wrong. These lines are appended to the image
system prompt.

---

## 12. `services/llm.py` — providers, streaming, fallback

Native SDKs, lazily initialized. The key abstractions:

### 12.1 Token streams are async generators of `str`
Every stream function `yield`s plain strings, so the SSE route consumes one shape:
```python
async def groq_stream(system_prompt, user_message, history):
    stream = await client.chat.completions.create(model=…, stream=True, messages=[…])
    async for chunk in stream:
        token = chunk.choices[0].delta.content
        if token: yield token
```
The Gemini variants (`gemini_stream_text`, `gemini_stream_image`) do the same but
**raise** at the end if nothing was yielded, so the fallback can detect an empty
response.

### 12.2 `stream_with_fallback(primary, fallback)` — the resilience core
```python
async def stream_with_fallback(primary, fallback):
    yielded = False
    try:
        async for token in primary():
            yielded = True; yield token
    except Exception:
        if not yielded:                       # primary failed before any token -> fallback
            async for token in fallback(): yield token
            return
        raise                                  # failed mid-answer -> surface it
    if not yielded:                            # primary ended empty -> fallback
        async for token in fallback(): yield token
```
`primary`/`fallback` are **zero-arg lambdas** (e.g. `lambda: groq_stream(...)`) so the
generator isn't created until we're ready to iterate it. Used everywhere: greeting,
text answer, image answer, no-answer.

### 12.3 History adapters
`_trim` keeps the last `history_turns` user/assistant turns. `_to_gemini_history`
enforces Gemini's strict rules: alternating user/model, must start with `user`, must
end with `model` (because `send_message` adds the next user turn) — merging
consecutive same-role turns. This is the port of v1's `toGeminiHistory` and prevents
Gemini 400 errors on multi-turn chats.

Non-streaming helpers: `gemini_extract_image` (the 4-section problem digitizer),
`groq_rewrite` / `gemini_rewrite` (query rewriting).

---

## 13. `services/prompts.py` — prompt construction + the canonical footer

- `build_context_block(candidates)` — renders each retrieved candidate as
  `[Source N] / Document / Location / File / --- / <parent_text>`. It reads
  `parentText` (the big section) for the LLM, while the lean source objects shown to
  the client omit it.
- `build_text_prompt` / `build_image_prompt` — the level-aware system prompts with the
  strict grounding rules, citation format, LaTeX rules, and (for images) the MCQ
  rules. Both end with the `📚 Reference` instruction.
- `greeting_prompt` / `no_answer_prompt` — the short prompts for the non-RAG paths.
- `build_reference(sources)` — builds the **trustworthy** footer from the real
  sources: `📚 Reference: file (chapter, Page X); …`, de-duplicated. The route uses
  this to *replace* whatever footer the model produced.

---

## 14. `services/retrieval.py` — hybrid search, fusion, gate, dedup

### 14.1 `retrieve_candidates(db, query, level_id)`
Runs the two searches and fuses them.

Dense (pgvector cosine; `score = 1 - distance`):
```python
dist = Chunk.embedding.cosine_distance(qvec)
rows = await db.execute(
    select(Chunk, dist.label("dist")).where(_level_filter(level_id)).order_by(dist).limit(K))
```
Sparse (Postgres full-text):
```python
tsq = func.websearch_to_tsquery("english", query)
rows = await db.execute(
    select(Chunk, func.ts_rank_cd(Chunk.tsv, tsq).label("rank"))
        .where(Chunk.tsv.op("@@")(tsq)).where(_level_filter(level_id))
        .order_by(text("rank DESC")).limit(K))
```
`_level_filter` = `level IS NULL OR level == student_level` (legacy chunks visible to
all). Then **Reciprocal Rank Fusion**:
```python
for i, c in enumerate(vector_cands): rrf[c["id"]] += 1/(60 + i + 1)
for i, c in enumerate(bm25_cands):   rrf[c["id"]] += 1/(60 + i + 1)
merged = [data[id] for id,_ in sorted(rrf.items(), key=lambda kv: kv[1], reverse=True)]
```
No cosine pre-cut — we fuse everything and let the reranker judge (§4.3). Both searches
are wrapped in `try/except` so one failing (e.g. embeddings down) degrades to the other.

### 14.2 `rerank_candidates(query, candidates)`
Cross-encoder scores the top `rerank_pool`; returns `{ordered, max_score, keep}` where
`keep` = chunks ≥ `rerank_keep_prob`. `max_score is None` signals "reranker
unavailable" so the caller knows to fall back instead of gating on a missing score.

### 14.3 `dedup_parents` / `to_source` / `retrieve_sources`
`dedup_parents` collapses children to unique `parent_id` (cap `final_context=5`).
`to_source` shapes the §8 source object (no `parentText` — keeps the payload lean).
`retrieve_sources` is the **eval** entry point: same pipeline, returns sources +
`lowConfidence`, optionally with rerank.

---

## 15. `services/store.py` — the only DB I/O

Plain async functions over `AsyncSession`, grouped: sessions
(`list/create/get/set_level/delete`), messages (`get_messages`, `append_messages`),
review (`mark_reviewed`, `review_queue`, `review_count`), documents/chunks
(`upsert_document`, `set_document_status`, `delete_chunks_by_source`, `add_chunks`,
`delete_document`, `clear_kb`), and `stats`.

`append_messages` is where the **session side-effects** live:
```python
for m in messages: db.add(Message(session_id=session_id, **m))
s.updated_at = now_ms()
if any(m.get("needs_review") for m in messages): s.needs_review = True   # feeds review queue
if s.title == "New Chat":                                                # auto-title
    first_user = next((m for m in messages if m["role"]=="user" and m["content"].strip()), None)
    s.title = (first_user["content"][:60]+"…") if first_user else "Image question"
await db.commit()
```

`add_chunks` zips chunk dicts with their embeddings and inserts `Chunk` rows (skipping
any with an empty embedding); `tsv` is filled by Postgres automatically.

---

## 16. `services/rag.py` — the orchestrator

Two public functions.

### 16.1 `ingest_document(document_id, path, name, doc_type, level)` — the async job
Opens its **own** session (it runs in a background task, after the request's session is
gone), and walks the pipeline updating `status`:
```python
await set_document_status(db, id, "parsing")
text, markdown = await extract_document(path, name)
chunks = chunk_document(text.split("\f"), name, doc_type, lvl, markdown=markdown)
await set_document_status(db, id, "embedding")
embeddings = await embed_passages([c["text"] for c in chunks])
await delete_chunks_by_source(db, name)            # re-upload REPLACES (§4.9)
added = await add_chunks(db, id, chunks, embeddings)
await set_document_status(db, id, "ready", chunks_added=added)
# finally: os.unlink(path)  -> clean up the temp file
```

### 16.2 `answer_question(db, message, image, mime, history, level, reply_to)`
The query pipeline, in order:

1. **Intent** (text only). Greeting → return a greeting stream immediately, no
   retrieval. Otherwise `msg = intent["query"]`.
2. **Image understanding** (if image) → `gemini_extract_image` → `final_query`.
3. **Conditional rewrite** (text, has history, `needs_rewrite`) → `gemini_rewrite`
   (fallback `groq_rewrite`) → `guard_rewrite`.
4. **Retrieve** → `retrieve_candidates`. Empty → `_no_answer()`.
5. **Rerank + gate**:
   ```python
   rr = await rerank_candidates(retrieval_query, merged)
   if rr["max_score"] is None:                         # reranker down
       if res["vector_fallback_low_conf"]: return await _no_answer()
       selected = rr["ordered"]
   elif rr["max_score"] < settings.rerank_gate_prob:   # off-topic
       return await _no_answer()                        # -> teacher review
   else:
       selected = rr["keep"] or rr["ordered"]           # only relevant chunks
   ```
6. **Dedup parents** → `compressed`; build `sources` (lean) and `context_block`
   (from `compressed`, with parent text).
7. **Prompt** (text or image) → **stream** with the right primary/fallback:
   - text: `groq_stream` primary, `gemini_stream_text` fallback;
   - image: `gemini_stream_image` primary (it can see the image), `groq_stream`
     fallback (on the extracted text).
8. Return `{stream, sources, rewrittenQuery, needsReview, emptyKB}`.

`_no_answer()` returns a stream that politely says it couldn't find the topic and sets
`needsReview=True`.

---

## 17. `api/chat.py` — SSE, the footer hold-back, persistence

`POST /api/chat` parses the body into `ChatRequest` and returns a
`StreamingResponse(_event_stream(...), media_type="text/event-stream")`.

`_event_stream` is the heart. Three subtleties:

**(a) Short-lived DB session before streaming.** Retrieval uses a session that closes
*before* the LLM stream, so a DB connection isn't pinned for the whole (possibly long)
response:
```python
async with SessionLocal() as db:
    result = await answer_question(db, …)     # retrieval done; session closes here
# … then stream result["stream"] with no DB held …
```

**(b) Holding back the model's `📚` footer.** We stream tokens but *never* emit
anything from the `📚` marker onward; after the stream ends we append our **canonical**
footer built from the real sources:
```python
async for token in result["stream"]:
    if await request.is_disconnected(): break    # stop/abort detection
    full_content += token
    idx = full_content.find("📚")
    cut = len(full_content) if idx == -1 else idx
    if cut > sent_len:
        yield _sse({"type":"token","content": full_content[sent_len:cut]})
        sent_len = cut
body_text = full_content[:sent_len]
canonical = "" if _is_no_answer(body_text) else build_reference(sources)
if canonical: yield _sse({"type":"token","content":"\n\n"+canonical})
```
So a citation can never name a document that wasn't actually retrieved (§4.7).

**(c) No-answer detection + persistence.** `_is_no_answer(text)` = matches the
not-found phrase **and** `len(text) < 400` (so a long correct answer mentioning
"teacher" isn't flagged). If detected, emit a `review` event. Finally `_persist(...)`
opens a fresh session and saves the user + assistant messages (assistant sources
empty if it was a no-answer), which also auto-titles the session and propagates
`needs_review`.

Event order on the wire: `meta → token* → [review] → [DONE]` (or `error → [DONE]`).

---

## 18. `api/ingest.py` — async upload, stats, delete

`POST /api/ingest` saves the upload to a temp file, `upsert_document(status="queued")`,
schedules the background job, and **returns immediately**:
```python
background.add_task(ingest_document, doc.id, temp_path, file_name, docType, lvl)
return {"success": True, "fileName": …, "documentId": doc.id, "status": "queued", "chunksAdded": 0}
```
(The `0` is why the upload toast briefly shows "0 chunks"; the real count appears once
the job finishes and `/stats` is polled.) `GET /stats` returns total chunks + per-doc
`{name, docType, level, chunks, status}`. `DELETE /document/{name}` and `/clear` remove
chunks (and the document row) — re-upload safety + KB wipe.

---

## 19. `api/sessions.py` — sessions + review queue

Thin handlers over `store.py`, serialized via `schemas.py`. **Route order matters**:
the literal routes `/review` and `/review/count` are declared *before* `/{session_id}/…`
so Starlette matches them first. `teacher-reply` appends a `role:"teacher"` message and
marks the session reviewed (which is how the student eventually sees the green Teacher
bubble via polling).

---

## 20. `main.py` — app wiring + lifespan

Builds the `FastAPI` app, adds CORS (regex-restricted to localhost), and includes the
three routers under `/api/chat`, `/api/ingest`, `/api/sessions`, plus `/api/health`.
The **lifespan** runs `init_db()` then warms the models **in the background**
(fire-and-forget) so the server is ready immediately and the first request — not
startup — pays the one-time model load:
```python
async def _warm():
    await embeddings.warmup(); await reranker.warmup()
asyncio.create_task(_warm())
```

---

## 21. `eval/evaluate.py` — measuring retrieval

Loads `golden.json` (`{query, level, expectedSource, expectedKeywords}`), runs the
**real** `retrieve_sources` per item, and reports **Recall@final** and **MRR**. A
golden item is a "hit" if a returned source's filename matches `expectedSource` or its
text contains an expected keyword. Run with `python -m app.eval.evaluate [--rerank]`.
This is how you tune `RERANK_GATE_PROB`/`RERANK_KEEP_PROB` against numbers, not feel.

---

## Cross-cutting patterns to remember

- **Lazy + threaded models.** Every heavy model loads on first use and runs in a
  thread (`asyncio.to_thread`) so the event loop stays responsive.
- **Fail open.** Reranker down → heuristic; primary LLM down → fallback; one retriever
  down → the other. The system answers rather than erroring.
- **One store, explicit SQL.** All DB access is in `store.py` / `retrieval.py`; hybrid
  search is two `select()`s + RRF in Python — no hidden magic.
- **camelCase boundary.** snake_case inside Python, camelCase at the HTTP edge
  (`schemas.py`), so the v1 React frontend works unchanged.
- **Tunables in `config.py`.** If retrieval feels off, that's where you turn the dials
  — and `eval/` is how you know which way.

---

*Pair this with [`ARCHITECTURE.md`](./ARCHITECTURE.md) (the "why") and
[`CLAUDE.md`](./CLAUDE.md) (the "what's done / what's left").*
