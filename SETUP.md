# Setup Guide — run PhysicsTA v2 from scratch

This is the **exact, friend-proof** guide to clone and run the whole project. No prior
context needed. ~15 minutes, all services free.

> The repo has two parts: `backend/` (Python/FastAPI) and `frontend/` (React). You'll
> run both, plus point them at a free cloud database. Each person needs **their own**
> free API keys and database (they're personal and not in the repo).

---

## 0. Install these first (one-time)
- **Python 3.11+** — https://www.python.org/downloads/ (tick "Add to PATH")
- **Node.js 18+** — https://nodejs.org (includes `npm`)
- **Git** — https://git-scm.com
- **uv** (fast Python package manager) — https://docs.astral.sh/uv/getting-started/installation/
  - Windows PowerShell: `irm https://astral.sh/uv/install.ps1 | iex`
  - (If you'd rather use plain `pip`, that works too — see the note in step 4.)

Check they work:
```powershell
python --version    # 3.11+
node --version      # 18+
git --version
uv --version
```

---

## 1. Get the code
```powershell
git clone https://github.com/Youssef2022003/TA_Chatbot_python.git
cd TA_Chatbot_python
```

---

## 2. Get a free database (Neon — Postgres + pgvector)
1. Go to **https://neon.tech** → sign up (free; Google/GitHub login works).
2. It creates a project + database automatically.
3. On the dashboard, find **Connection string** and **copy it** — it looks like:
   `postgresql://USER:PASSWORD@ep-xxxx.REGION.aws.neon.tech/neondb?sslmode=require`
   (The app auto-handles the `+asyncpg` driver and SSL — paste it as-is.)

---

## 3. Get three free API keys
- **Groq** (text answers) → https://console.groq.com/keys
- **Google Gemini** (image questions) → https://aistudio.google.com/apikey
- **Mistral** (OCR for scanned PDFs) → https://console.mistral.ai → API Keys

All have free tiers — no card needed to start.

---

## 4. Run the backend
```powershell
cd backend

# create the virtual env + install dependencies (downloads PyTorch etc. — a few min)
uv venv --python 3.11
uv pip install -r requirements.txt

# create your .env from the template, then edit it
copy .env.example .env
notepad .env        # fill in DATABASE_URL + the 3 API keys, save & close

# start the server
.venv\Scripts\python -m uvicorn app.main:app --port 3001 --reload
```

What to expect:
- First boot connects to Neon and **creates all tables/indexes automatically**.
- The first PDF upload / first question downloads the embedding + reranker models
  (~few hundred MB, **one time**) — so the first request is slow, then it's fast.
- Leave this terminal running. Verify at **http://localhost:3001/api/health** →
  `{"status":"ok",...}`.

> **No `uv`?** Use pip instead: `python -m venv .venv` →
> `.venv\Scripts\activate` → `pip install -r requirements.txt` →
> `uvicorn app.main:app --port 3001 --reload`.

Your `.env` should look like:
```
DATABASE_URL=postgresql://USER:PASSWORD@ep-xxxx.REGION.aws.neon.tech/neondb?sslmode=require
GROQ_API_KEY=gsk_...
GEMINI_API_KEY=AIza...
MISTRAL_API_KEY=...
PORT=3001
USE_DOCLING=false
```

---

## 5. Run the frontend (a second terminal)
```powershell
cd TA_Chatbot_python\frontend
npm install
npm run dev
```
Open **http://localhost:5173**. (Vite already proxies `/api` → the backend on 3001,
so they connect automatically.)

---

## 6. Use it
1. Go to the **Teacher Panel** (top nav) → upload a physics PDF, pick a **type** and a
   **level (1–5)**. Scanned PDFs are OCR'd by Mistral (a few seconds–minute).
2. Wait until the document shows **`ready`** with a chunk count.
3. Switch to **Student** view → ask a physics question (text or a photo of a problem).
   You'll get a grounded, cited answer; off-topic questions go to the teacher review
   queue.

---

## 7. (Optional) Sanity-check it works
With the backend running and a PDF ingested:
```powershell
cd backend
.venv\Scripts\python ..\scripts\smoke_test.py            # 35 endpoint checks
.venv\Scripts\python ..\scripts\physics_followup_test.py # a real 2-turn physics chat
```

---

## Troubleshooting
| Symptom | Fix |
|---|---|
| `/api/health` not responding | Backend still loading torch on first boot — wait ~30s. |
| Upload shows "0 chunks" then nothing | OCR runs in the background; watch the doc `status` go `parsing→ready`. Check the backend terminal for errors. |
| `DB init failed` | Re-check `DATABASE_URL` in `.env` (paste the Neon string exactly). |
| Answers say "couldn't find this topic" for everything | The KB is empty or still ingesting — upload a PDF and wait for `ready`. |
| Frontend can't reach API | Make sure the backend is running on port **3001**. |
| Scanned PDF fails to ingest | Ensure `MISTRAL_API_KEY` is set (it's the OCR engine for scans). |

---

That's it — same setup the original author used. See **[README.md](./README.md)** for the
stack overview and **[ARCHITECTURE.md](./ARCHITECTURE.md)** / **[CODE_WALKTHROUGH.md](./CODE_WALKTHROUGH.md)**
to understand how it works.
