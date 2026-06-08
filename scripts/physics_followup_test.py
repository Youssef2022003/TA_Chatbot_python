"""Qualitative test: ask a physics question, then REPLY asking the bot to explain
with real numbers / a worked substitution. Exercises the reply-to-message feature and
the grounded numeric-reasoning quality. Run against a live server:

    .venv\\Scripts\\python scripts\\physics_followup_test.py
"""
from __future__ import annotations

import json
import sys

import httpx

# Windows consoles default to cp1252 and choke on LaTeX/emoji in answers.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

BASE = "http://localhost:3001"
LEVEL = 3


def stream_chat(message, history, session_id, reply_to=None):
    """POST /api/chat and consume the SSE stream. Returns (answer, sources)."""
    body = {
        "message": message,
        "history": history,
        "sessionId": session_id,
        "level": LEVEL,
        "replyTo": reply_to,
    }
    answer, sources = "", []
    with httpx.Client(timeout=180) as c:
        with c.stream("POST", f"{BASE}/api/chat", json=body) as r:
            for line in r.iter_lines():
                if not line.startswith("data: "):
                    continue
                raw = line[6:].strip()
                if raw == "[DONE]":
                    break
                try:
                    ev = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if ev.get("type") == "meta":
                    sources = ev.get("sources", [])
                elif ev.get("type") == "token":
                    answer += ev.get("content", "")
                elif ev.get("type") == "error":
                    answer = f"[ERROR] {ev.get('message')}"
                    break
    return answer, sources


def main():
    # New session
    s = httpx.post(f"{BASE}/api/sessions", json={"title": "New Chat", "level": LEVEL}).json()
    sid = s["id"]
    print(f"session: {sid}\n")

    # Turn 1 — a physics question the textbook covers
    q1 = "What is kinetic energy and how is it calculated?"
    print("=" * 70)
    print(f"STUDENT (turn 1): {q1}")
    print("=" * 70)
    a1, src1 = stream_chat(q1, [], sid)
    print(a1)
    print(f"\n[sources: {[s.get('fileName') for s in src1]}]  ({len(src1)} chunks)\n")

    # Turn 2 — REPLY to that answer, asking for a numeric worked example
    history = [{"role": "user", "content": q1}, {"role": "assistant", "content": a1}]
    q2 = "I don't fully get it. Can you substitute real numbers and show me a full worked example step by step?"
    reply_to = {"role": "assistant", "content": a1[:1500]}
    print("=" * 70)
    print(f"STUDENT (turn 2, replying to the answer): {q2}")
    print("=" * 70)
    a2, src2 = stream_chat(q2, history, sid, reply_to=reply_to)
    print(a2)
    print(f"\n[sources: {[s.get('fileName') for s in src2]}]  ({len(src2)} chunks)\n")

    # Cleanup
    httpx.delete(f"{BASE}/api/sessions/{sid}")
    print("(session deleted)")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print(f"TEST FAILED: {e}", file=sys.stderr)
        sys.exit(1)
