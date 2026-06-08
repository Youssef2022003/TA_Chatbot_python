"""Pure-regex intent classification + query-rewriter guard (handoff §4.1/§4.2).

No LLM calls here — these were the two subtlest v1 bugs:
  - Greeting+question hybrids ("hi, what is inertia?") must strip the leading
    greeting and route the REMAINDER to RAG (tolerating trailing junk like "hi+").
  - The rewriter only runs for history-dependent follow-ups, and a rewrite that
    drifts off the original (the "barça" hallucination) is discarded.
"""
from __future__ import annotations

import re

PURE_GREETING_RE = re.compile(
    r"^(hi+|hello+|hey+|yo+|hiya|heya|greetings|good\s+(morning|afternoon|evening|day)|"
    r"thanks?(\s+a\s+lot)?|thank\s+you(\s+so\s+much)?|thx|ty|ok(ay)?|k|great|nice|awesome|"
    r"cool|got\s+it|bye+|goodbye|see\s+you|how\s+are\s+you|who\s+are\s+you|what\s+are\s+you|"
    r"what\s+can\s+you\s+do|what\s+do\s+you\s+do)\W*$",
    re.I,
)

LEADING_GREETING_RE = re.compile(
    r"^(?:(?:hi+|hello+|hey+|yo+|hiya|heya|greetings|good\s+(?:morning|afternoon|evening|day)|"
    r"thanks?(?:\s+a\s+lot)?|thank\s+you|thx|ty)"
    r"(?:\s+(?:there|teacher|ta|bot|sir|maam|ma'am))?)"
    r"(?:\s*[,!.:;+~*&/-]+\s*|\s+)"
    r"(?:(?:also|and|so|please|could\s+you|can\s+you|i\s+(?:have|had)\s+a\s+question[,:]?|"
    r"quick\s+question[,:]?|um+|uh+|well)\s+)*",
    re.I,
)

_QUESTION_WORD_RE = re.compile(
    r"\b(what|why|how|when|where|which|who|explain|define|calculate|solve|find|prove|"
    r"derive|describe|state|give|show|list|compare)\b",
    re.I,
)

FOLLOWUP_RE = re.compile(
    r"\b(example|more|elaborate|continue|again|why|how come|explain|simpler|harder|"
    r"detail|expand|that|previous|last|it)\b",
    re.I,
)

_STOP = {
    "a", "an", "the", "is", "are", "of", "to", "and", "for", "on", "in", "what", "how",
    "why", "when", "which", "give", "me", "example", "explain", "can", "you", "please",
    "do", "does", "about", "this", "that", "it", "more",
}


def _has_substance(text: str) -> bool:
    if "?" in text:
        return True
    if _QUESTION_WORD_RE.search(text):
        return True
    words = [w for w in text.split() if re.search(r"[a-z0-9]", w, re.I)]
    return len(words) >= 2


def classify_intent(raw_msg: str) -> dict:
    """Returns {'kind': 'greeting'|'question', 'query': stripped_text}."""
    text = (raw_msg or "").strip()
    if not text:
        return {"kind": "greeting", "query": ""}

    if len(text) < 60 and PURE_GREETING_RE.match(text):
        return {"kind": "greeting", "query": text}

    stripped = LEADING_GREETING_RE.sub("", text).strip()

    if stripped and stripped != text and _has_substance(stripped):
        return {"kind": "question", "query": stripped}
    if stripped and stripped != text and not _has_substance(stripped):
        return {"kind": "greeting", "query": text}
    return {"kind": "question", "query": text}


def _content_words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(w) > 2 and w not in _STOP]


def needs_rewrite(query: str) -> bool:
    """Only rewrite when the message likely depends on earlier turns."""
    if FOLLOWUP_RE.search(query):
        return True
    return len(_content_words(query)) <= 2


def guard_rewrite(original: str, rewritten: str) -> str:
    """Trust the rewrite only if it stays anchored to the original (handoff §4.2)."""
    orig = (original or "").strip()
    rew = (rewritten or "").strip()
    if not rew:
        return orig
    orig_words = _content_words(orig)
    if not orig_words:
        return rew if FOLLOWUP_RE.search(orig) else orig
    rew_words = set(_content_words(rew))
    if any(w in rew_words for w in orig_words):
        return rew
    return rew if FOLLOWUP_RE.search(orig) else orig
