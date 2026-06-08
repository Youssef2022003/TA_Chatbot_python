# PhysicsTA v2 — Deployment Options & Pricing Guide

Two separate questions, answered here:
- **Part A — Where can I deploy this for free?** (no implementation, just the options)
- **Part B — How do I price API usage to the client?** (a cost model + pricing strategies)

> Numbers below are **estimates** to reason with — verify current provider pricing and
> free-tier limits before quoting a client, as they change.

---

## Part A — Free deployment

### The three things you're deploying
1. **Frontend** — the React app. Static files. *Trivial and free* to host anywhere.
2. **Database** — Postgres + pgvector. *Already solved:* **Neon free tier**.
3. **Backend** — FastAPI. **This is the hard part**, because it loads two local ML
   models (the bge embedding model + the bge cross-encoder reranker) via PyTorch,
   which needs **~1–2 GB RAM**. Most "free" tiers give only 512 MB → they'd crash
   (OOM) trying to load the models.

So the deployment decision hinges on **one question about the backend:**

> **Do you keep the ML models in the backend (needs a big-RAM host), or offload them
> to APIs (lets the backend run on tiny free tiers)?**

### Strategy 1 — Host the models (keep it all local & free, need RAM)
Pick a free host with enough RAM for PyTorch + the two models.

| Platform | Free tier | Fits the ML backend? | Notes |
|---|---|---|---|
| **Hugging Face Spaces** ⭐ | 2 vCPU, **16 GB RAM**, Docker | ✅ Easily | Best free fit for an ML backend. Deploy via Docker. Sleeps after ~48h idle (wakes on request). Public by default (private = paid). |
| **Oracle Cloud Free Tier** ⭐ | Always-free **ARM VM, up to 4 cores / 24 GB RAM** | ✅ Easily (could host *everything*) | Most powerful free option; but it's a raw Linux VM you manage yourself (more ops/setup). |
| Google Cloud Run | 2M req/mo, scales to zero; memory configurable | ⚠️ Possible | Set memory to 1–2 GB; low traffic can stay ~free. Cold starts are slow with big models; large image. |
| Render (free web service) | 512 MB RAM, spins down after 15 min | ❌ Too small | Would OOM on the models. Only works with Strategy 2. |
| Fly.io (free allowance) | 256 MB shared VMs | ❌ Too small | Same — needs Strategy 2 or paid RAM. |
| Railway / Koyeb | ~512 MB; Railway is trial-credit then paid | ❌ / 💲 | Not a durable free fit for the models. |

### Strategy 2 — Offload the models to APIs (tiny/cheap backend, fits anywhere)
Replace the local bge embedding + reranker with hosted APIs (some have free tiers:
**Jina AI** embeddings, **Cohere** trial rerank, **HF Inference API**). Then the
backend is just web + DB glue (~256–512 MB) and fits **Render / Fly.io / Cloud Run**
free tiers. Trade-off: more API dependencies + their rate limits, and embeddings now
cost network round-trips.

### Frontend hosting (all free, all easy)
**Vercel**, **Netlify**, **Cloudflare Pages**, or **GitHub Pages** — any of them serve
the built React app for free. Point its `/api` calls at your backend URL.

### Database
**Neon free tier** (already in use): ~0.5 GB storage — plenty for a course's chunks +
sessions. Alternative: **Supabase** free tier (also Postgres + pgvector).

### ✅ Recommended free stacks
- **Easiest:** Frontend on **Vercel** + Backend on **Hugging Face Spaces** (Docker,
  16 GB) + DB on **Neon**. All free, minimal ops.
- **Most control / most headroom:** one **Oracle Cloud always-free VM** running the
  backend (and optionally Postgres) + Frontend on Vercel.

### The real ceiling on "free"
Hosting is solvable for free. The actual limit is the **free-tier API rate limits**
(Groq, Gemini, Mistral OCR) — they cap how many students you can serve concurrently
before requests get throttled. That's what pushes you to **paid APIs** at scale — which
is exactly what Part B prices.

---

## Part B — Pricing API usage to the client

### Step 1 — What one message actually costs
A typical **text** question runs one LLM generation over the retrieved context.
Approximate tokens per text message:

| Piece | ~tokens |
|---|---|
| System prompt + rules | 400 |
| Retrieved context (≤5 parent sections) | ~2,500 |
| Chat history (last 6 turns) | ~500 |
| The question | ~50 |
| **Input total** | **~3,450** |
| Answer (output) | **~600** |

Embedding + rerank are **local today (free)**. An **image** question costs ~2 vision
calls (extract + solve) — roughly 2–3× a text message.

### Step 2 — Cost per message, by model
Per **text** message (≈3,450 in / 600 out). Prices are approximate $/1M tokens:

| Generation model | In / Out $/1M | ~Cost / text msg |
|---|---|---|
| **Free tier (Groq/Gemini)** | $0 (rate-limited) | **$0** |
| Groq llama-3.3-70b (paid) | 0.59 / 0.79 | ~$0.0025 |
| GPT-4o-mini | 0.15 / 0.60 | ~$0.0009 |
| GPT-4o | 2.50 / 10.0 | ~$0.015 |
| Claude Sonnet | 3.00 / 15.0 | ~$0.020 |

Optional add-ons if you go paid: hosted **rerank** ≈ $0.001/msg (Cohere), hosted
**embeddings** ≈ negligible, **Mistral OCR** ≈ $0.15 per 148-page book (one-time per
upload), **image** messages ≈ $0.02–0.04 each.

### Step 2b — The per-student unit (tokens → cost → messages)
The cleanest way to reason about price is **one average active student per month**.

- **Tokens per message:** ~3,450 in + ~600 out ≈ **~4,000 tokens/message**.
- **Messages per student/month:** assume **~200** (≈ 8–10 messages on ~22 study days).
  *(Adjust this one number to your reality — everything scales linearly from it.)*
- **Tokens per student/month:** 200 × 4,000 ≈ **~0.8 M tokens/student/month**.

So **1 average student ≈ 200 messages ≈ 0.8 M tokens/month**, costing:

| Generation model | $/message | **$/student/month** (200 msg) | Messages per $1 |
|---|---|---|---|
| **Free tier (Groq/Gemini)** | $0 | **$0** (rate-limited, not unlimited) | ∞* |
| GPT-4o-mini | ~$0.0009 | **~$0.18** | ~1,140 |
| Groq llama-3.3-70b (paid) | ~$0.0025 | **~$0.50** | ~400 |
| GPT-4o | ~$0.0146 | **~$2.93** | ~68 |
| Claude Sonnet | ~$0.0194 | **~$3.87** | ~52 |

\* Free = $0 in dollars, but capped by API rate limits (≈ a small class's worth).
Image questions cost ~2–3× a text message; OCR/embeddings/rerank are one-time or
local and negligible per student.

**Reading it back in plain words:** *one student* runs about **200 messages /
0.8 M tokens a month**, which costs you about **$0.18 (GPT-4o-mini)** to **$0.50
(Groq paid)** on budget models, or **~$3–4** on premium models — and **$1 buys
roughly 400–1,140 messages** on budget models. Since a student costs **well under
$1/month** on budget models, charging **$3–5/student/month** is a comfortable
margin.

### Step 3 — Daily/monthly cost by class size
Assume mostly text messages. "Premium" = GPT-4o-class; "Budget" = GPT-4o-mini / Groq paid.

| Scenario | Messages/day | Free APIs | Budget paid | Premium paid |
|---|---|---|---|---|
| Small — 30 students × 8 msg | 240 | **$0** (within limits) | ~$0.50/day · **~$15/mo** | ~$3.8/day · **~$115/mo** |
| Medium — 100 × 12 | 1,200 | $0 but **near/over free limits** | ~$2.4/day · **~$72/mo** | ~$19/day · **~$575/mo** |
| Large — 500 × 12 | 6,000 | **exceeds free tiers** | ~$12/day · **~$360/mo** | ~$96/day · **~$2,880/mo** |

Add hosting: **$0** (free stack) up to ~$20–50/mo for a reliable paid host.

> Takeaway: on **free APIs** the marginal cost is **$0** — you're paying with *rate
> limits*, not dollars. Free comfortably covers a small class; a medium/large class
> needs paid APIs, and **Budget models (GPT-4o-mini / Groq paid) are ~8× cheaper than
> Premium** for usually-comparable quality on this grounded task.

### Step 4 — How to charge the client (pick a model)
You charge **cost + margin**. Four common structures:

1. **Per-student / month (recommended for schools).** Compute cost-per-student, add
   margin. *Example (medium class, budget model):* $72/mo ÷ 100 students = **$0.72
   cost/student** → charge **$3–5/student/month** (covers hosting, overage buffer,
   your time, healthy margin).
2. **Flat per-class / per-school license.** e.g. **$99–299/month per class** for "up
   to N students, M messages." Simple to sell; you absorb usage within the cap.
3. **Tiered (Free vs Premium).** *Free tier* runs on the free APIs (rate-limited,
   "best-effort"); *Premium tier* uses paid APIs (faster, higher quality, priority
   support). Charge only for Premium.
4. **Credit / message packs.** Sell e.g. **1,000-message packs**. Cost is ~$1–15/1,000
   depending on model; price at **$20–50/1,000** for margin. Good for variable usage.

### Step 5 — If you "enhance performance with paid APIs"
Where the paid budget actually buys quality (see also `ARCHITECTURE.md` §8):
- **Generation → GPT-4o / Claude:** the biggest student-visible upgrade (reasoning,
  fewer mistakes). Dominates the per-message cost — choose deliberately.
- **OCR → Mathpix:** best equation fidelity for scanned books (one-time per upload, cheap).
- **Embeddings/rerank → OpenAI / Cohere:** smaller, *measurable* recall/precision wins
  — validate against the eval harness before paying.

**Rule of thumb for a quote:** price as if you're on **Budget paid APIs** (predictable,
cheap, reliable) and bill the client **per-student/month with margin**; reserve
**Premium models** for a higher-priced tier. Always quote with paid-API assumptions for
anything beyond a single small class, because free-tier rate limits won't hold up.

---

### Quick-reference: recommended starting point
- **Deploy free:** Vercel (frontend) + Hugging Face Spaces (backend) + Neon (DB).
- **Run on:** free APIs for pilots/small classes; **Budget paid** (GPT-4o-mini or Groq
  paid) for production.
- **Charge:** **$3–5/student/month** (or a $99–299/class license), Premium tier extra.
