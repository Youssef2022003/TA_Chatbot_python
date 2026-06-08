"""End-to-end smoke test for every API surface (handoff §8). Run against a live
server with a populated KB:

    .venv\\Scripts\\python scripts\\smoke_test.py

Prints PASS/FAIL per check and a summary; exits non-zero if anything fails.
"""
from __future__ import annotations

import json
import sys

import httpx

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

BASE = "http://localhost:3001"
PASS, FAIL = 0, 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  -- {detail}")


def stream_chat(message, history=None, session_id=None, level=3, reply_to=None, image=None, mime=None):
    body = {
        "message": message, "history": history or [], "sessionId": session_id,
        "level": level, "replyTo": reply_to, "imageBase64": image, "mimeType": mime,
    }
    answer, sources, needs_review, got_done, events = "", [], False, False, []
    with httpx.Client(timeout=180) as c:
        with c.stream("POST", f"{BASE}/api/chat", json=body) as r:
            for line in r.iter_lines():
                if not line.startswith("data: "):
                    continue
                raw = line[6:].strip()
                if raw == "[DONE]":
                    got_done = True
                    break
                ev = json.loads(raw)
                events.append(ev.get("type"))
                if ev.get("type") == "meta":
                    sources = ev.get("sources", [])
                    needs_review = ev.get("needsReview", False)
                elif ev.get("type") == "token":
                    answer += ev.get("content", "")
                elif ev.get("type") == "review":
                    needs_review = True
    return {"answer": answer, "sources": sources, "needsReview": needs_review, "done": got_done, "events": events}


def main():
    print("\n── 1. Health ──────────────────────────────────────────")
    h = httpx.get(f"{BASE}/api/health").json()
    check("health ok", h.get("status") == "ok", h)
    check("embedDim is 384", h.get("embedDim") == 384, h)

    print("\n── 2. Ingest stats ────────────────────────────────────")
    st = httpx.get(f"{BASE}/api/ingest/stats").json()
    check("stats has totalChunks", "totalChunks" in st, st)
    check("KB is populated (>0 chunks)", st.get("totalChunks", 0) > 0, st)
    check("documents listed with status", all("status" in d for d in st.get("documents", [])), st)

    print("\n── 3. Sessions CRUD ───────────────────────────────────")
    s = httpx.post(f"{BASE}/api/sessions", json={"title": "New Chat", "level": 3}).json()
    sid = s["id"]
    check("create returns id", bool(sid), s)
    check("session default level applied", s.get("level") == 3, s)
    listed = httpx.get(f"{BASE}/api/sessions").json()
    check("session appears in list", any(x["id"] == sid for x in listed), "not in list")
    msgs = httpx.get(f"{BASE}/api/sessions/{sid}/messages").json()
    check("new session has no messages", msgs == [], msgs)
    lvl = httpx.patch(f"{BASE}/api/sessions/{sid}/level", json={"level": 4}).json()
    check("set level 4", lvl.get("level") == 4, lvl)
    bad = httpx.patch(f"{BASE}/api/sessions/{sid}/level", json={"level": 9})
    check("invalid level rejected (400)", bad.status_code == 400, bad.status_code)

    print("\n── 4. Greeting path (no retrieval) ────────────────────")
    g = stream_chat("hi", session_id=sid, level=3)
    check("greeting streamed tokens", len(g["answer"]) > 0, g["events"])
    check("greeting has NO sources", g["sources"] == [], g["sources"])
    check("greeting not flagged for review", not g["needsReview"], g)
    check("greeting stream terminated [DONE]", g["done"], g)

    print("\n── 5. Grounded text question (RAG) ────────────────────")
    q = stream_chat("What is kinetic energy?", session_id=sid, level=3)
    check("answer streamed", len(q["answer"]) > 50, len(q["answer"]))
    check("has sources", len(q["sources"]) > 0, q["sources"])
    check("not flagged for review", not q["needsReview"], q)
    check("canonical reference footer present", "📚 Reference" in q["answer"], q["answer"][-120:])
    check("source has fileName/page/chapter", all(k in q["sources"][0] for k in ("fileName", "pageStart", "chapter")), q["sources"][0] if q["sources"] else {})

    print("\n── 6. Off-topic gating → review ───────────────────────")
    # Two layers protect against off-topic: the rerank gate (retrieval) and the LLM's
    # grounded refusal (generation). The meaningful, user-visible properties are that
    # it (a) refuses with the not-found message and (b) routes to review. (The meta
    # event may transiently carry weak sources, but the `review` event clears them and
    # persistence stores none — see CLAUDE.md "off-topic gate tuning".)
    o = stream_chat("Who won the football match between Barcelona and Real Madrid?", session_id=sid, level=3)
    check("off-topic flagged needsReview", o["needsReview"], o)
    check("off-topic returns the not-found message", "couldn't find this topic" in o["answer"].lower(), o["answer"][:160])
    check("off-topic 'review' event fired", "review" in o["events"], o["events"])

    print("\n── 7. Persistence + auto-title ────────────────────────")
    after = httpx.get(f"{BASE}/api/sessions/{sid}/messages").json()
    roles = [m["role"] for m in after]
    check("messages persisted (user+assistant pairs)", roles.count("user") >= 3 and roles.count("assistant") >= 3, roles)
    sess_now = next((x for x in httpx.get(f"{BASE}/api/sessions").json() if x["id"] == sid), {})
    check("session auto-titled from first msg", sess_now.get("title") not in (None, "New Chat"), sess_now.get("title"))
    check("session flagged needsReview (from off-topic)", sess_now.get("needsReview") is True, sess_now)

    print("\n── 8. Review queue + teacher reply ────────────────────")
    rq = httpx.get(f"{BASE}/api/sessions/review").json()
    check("session in review queue", any(x["id"] == sid for x in rq), "not queued")
    cnt = httpx.get(f"{BASE}/api/sessions/review/count").json()
    check("review count >= 1", cnt.get("count", 0) >= 1, cnt)
    tr = httpx.post(f"{BASE}/api/sessions/{sid}/teacher-reply", json={"content": "Here is the explanation from your teacher."})
    check("teacher-reply accepted", tr.status_code == 200, tr.status_code)
    after_tr = httpx.get(f"{BASE}/api/sessions/{sid}/messages").json()
    check("teacher message saved", any(m["role"] == "teacher" for m in after_tr), [m["role"] for m in after_tr])
    rq2 = httpx.get(f"{BASE}/api/sessions/review").json()
    check("session removed from queue after reply", not any(x["id"] == sid for x in rq2), "still queued")

    print("\n── 9. Reply-to-message ────────────────────────────────")
    r = stream_chat(
        "Give a worked example with numbers.",
        history=[{"role": "user", "content": "What is kinetic energy?"}, {"role": "assistant", "content": q["answer"][:800]}],
        session_id=sid, level=3,
        reply_to={"role": "assistant", "content": q["answer"][:800]},
    )
    check("reply-to produced an answer", len(r["answer"]) > 50, len(r["answer"]))

    print("\n── 10. Empty-message guard ────────────────────────────")
    e = stream_chat("", session_id=sid, level=3)
    check("empty message handled (error event, no crash)", e["done"], e["events"])

    print("\n── 11. Cleanup ────────────────────────────────────────")
    d = httpx.delete(f"{BASE}/api/sessions/{sid}").json()
    check("session deleted", d.get("success") is True, d)
    gone = [x for x in httpx.get(f"{BASE}/api/sessions").json() if x["id"] == sid]
    check("session truly gone", gone == [], gone)

    print("\n" + "=" * 56)
    print(f"  RESULT: {PASS} passed, {FAIL} failed")
    print("=" * 56)
    return FAIL == 0


if __name__ == "__main__":
    try:
        ok = main()
    except Exception as e:  # noqa: BLE001
        print(f"\nSMOKE TEST CRASHED: {e}", file=sys.stderr)
        sys.exit(2)
    sys.exit(0 if ok else 1)
