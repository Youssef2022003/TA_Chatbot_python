"""Structure-aware, parent-document chunking (handoff §4.5/§4.6/§6).

Faithful port of v1's chunkingService.js:
  - Small CHILD chunks (~170 words) are embedded for precise retrieval; each
    carries its larger PARENT section text (<=3000 chars) for complete LLM context.
  - Tables and equation lines are atomic (never a flush boundary).
  - A section never spans two chapters; the citation "chapter" prefers the nearest
    TOP-LEVEL heading and skips generic/boilerplate headings (Objectives, Exercises…).
"""
from __future__ import annotations

import re
import uuid

# Lines that look like math — never used as a flush boundary, so an equation is
# never separated from the sentence that introduces it.
_PHYSICS_EQUATION_PATTERNS = [
    re.compile(r"[=²³√∫Σ∂∇]"),
    re.compile(r"\b(F|v|a|m|E|P|W|Q|T|λ|ω|α|τ|μ|ρ|σ|θ|φ)\s*="),
    re.compile(r"\d+\s*[×x*]\s*10"),
    re.compile(r"m/s|km/h|N·m|kg·m"),
    re.compile(r"\$\$?.+\$\$?"),
]

_CHAPTER_PATTERNS = [
    re.compile(r"^chapter\s+\d+", re.I),
    re.compile(r"^ch\.\s*\d+", re.I),
    re.compile(r"^unit\s+\d+", re.I),
    re.compile(r"^\d+\s+[A-Z][a-zA-Z\s]{3,50}$"),
    re.compile(r"^section\s+\d+", re.I),
]

_GENERIC_HEADING_RE = re.compile(
    r"^(unit|chapter|section)?\s*(objectives?|contents?|table of contents|exercises?|"
    r"problems?|summary|introduction|overview|review( questions)?|questions?|"
    r"key ?terms?|glossary|index|references?|answers?|appendix)\s*$",
    re.I,
)

CHILD_TARGET = 170
CHILD_MAX = 260
PARENT_MAX_CHARS = 3000


def _count_words(text: str) -> int:
    return len([w for w in text.split() if w])


def _is_equation_line(text: str) -> bool:
    return any(p.search(text) for p in _PHYSICS_EQUATION_PATTERNS)


def _ends_with_sentence(text: str) -> bool:
    return bool(re.search(r"[.!?:]$", text.strip()))


def _is_md_heading(line: str) -> bool:
    return bool(re.match(r"^#{1,6}\s+\S", line))


def _is_table_row(line: str) -> bool:
    t = line.strip()
    return t.startswith("|") and t.endswith("|") and len(t) > 2


def _strip_md(line: str) -> str:
    return re.sub(r"[*_`]+", "", re.sub(r"^#{1,6}\s+", "", line)).strip()


def _is_generic_heading(text: str) -> bool:
    return bool(_GENERIC_HEADING_RE.match(text.strip()))


def _is_heuristic_heading(text: str) -> bool:
    t = text.strip()
    if len(t) > 100:
        return False
    if any(p.search(t) for p in _CHAPTER_PATTERNS):
        return True
    upper = t.upper()
    return (
        t == upper
        and len(t) < 70
        and _count_words(t) <= 8
        and bool(re.search(r"[A-Z]", t))
        and not t.endswith(".")
    )


def _page_to_blocks(page_text: str, markdown: bool) -> list[dict]:
    """One page -> typed blocks: heading | table | para. Table rows merge atomically."""
    blocks: list[dict] = []
    para: list[str] = []
    tbl: list[str] = []

    def flush_para():
        nonlocal para
        if para:
            text = re.sub(r"\s+", " ", " ".join(para)).strip()
            if _count_words(text) >= 2:
                blocks.append({"text": text, "kind": "para"})
            para = []

    def flush_tbl():
        nonlocal tbl
        if tbl:
            blocks.append({"text": "\n".join(tbl), "kind": "table"})
            tbl = []

    for raw in page_text.split("\n"):
        t = raw.strip()
        if t == "":
            flush_para()
            flush_tbl()
            continue
        if markdown and _is_table_row(t):
            flush_para()
            tbl.append(t)
            continue
        if tbl:
            flush_tbl()
        if (markdown and _is_md_heading(t)) or (not markdown and _is_heuristic_heading(t)):
            flush_para()
            level = (len(re.match(r"^#+", t).group(0)) if markdown and re.match(r"^#+", t) else 1)
            blocks.append({"text": _strip_md(t) if markdown else t, "kind": "heading", "level": level})
            continue
        para.append(t)

    flush_para()
    flush_tbl()
    return blocks


def chunk_document(
    pages_text: list[str], file_name: str, doc_type: str, level: int, markdown: bool = False
) -> list[dict]:
    """Return CHILD chunk dicts; each carries parent_id + parent_text for retrieval."""
    # 1. Flatten pages -> items, tracking the nearest non-generic chapter heading.
    items: list[dict] = []
    current_top = ""
    current_any = ""
    for p, page in enumerate(pages_text):
        page_num = p + 1
        for b in _page_to_blocks(page, markdown):
            if b["kind"] == "heading" and not _is_generic_heading(b["text"]):
                current_any = b["text"][:120]
                if b.get("level", 1) <= 1:
                    current_top = b["text"][:120]
            chapter = current_top or current_any
            items.append({"text": b["text"], "page": page_num, "chapter": chapter, "kind": b["kind"]})

    # 2. Segment into sections (a new section starts at each heading).
    sections: list[list[dict]] = []
    cur: list[dict] = []
    for it in items:
        if it["kind"] == "heading" and cur:
            sections.append(cur)
            cur = []
        cur.append(it)
    if cur:
        sections.append(cur)

    # 3. Within each section: build parents (char-capped) and children within them.
    chunks: list[dict] = []
    global_idx = 0

    for section in sections:
        parents: list[list[dict]] = []
        p_items: list[dict] = []
        p_chars = 0
        for it in section:
            if p_chars + len(it["text"]) > PARENT_MAX_CHARS and p_items:
                parents.append(p_items)
                p_items = []
                p_chars = 0
            p_items.append(it)
            p_chars += len(it["text"]) + 1
        if p_items:
            parents.append(p_items)

        for group in parents:
            parent_id = str(uuid.uuid4())
            parent_text = "\n".join(i["text"] for i in group).strip()[:PARENT_MAX_CHARS]
            chapter = group[0]["chapter"] or ""

            win: list[dict] = []
            w_words = 0

            def emit_child():
                nonlocal global_idx, win, w_words
                if not win:
                    return
                text = re.sub(r"\s+", " ", " ".join(i["text"] for i in win)).strip()
                if _count_words(text) < 4:
                    return
                chunks.append(
                    {
                        "id": str(uuid.uuid4()),
                        "text": text,
                        "source": file_name,
                        "doc_type": doc_type,
                        "level": level,
                        "chunk_index": global_idx,
                        "word_count": w_words,
                        "page_start": win[0]["page"],
                        "page_end": win[-1]["page"],
                        "chapter": chapter,
                        "parent_id": parent_id,
                        "parent_text": parent_text,
                    }
                )
                global_idx += 1

            for it in group:
                w = _count_words(it["text"])
                would_exceed = w_words + w > CHILD_MAX
                atomic = _is_equation_line(it["text"]) or it["kind"] == "table"
                if (
                    w_words >= CHILD_TARGET
                    and would_exceed
                    and not atomic
                    and _ends_with_sentence(win[-1]["text"] if win else "")
                ):
                    emit_child()
                    last = win[-1] if win else None  # overlap: carry last block forward
                    win = [last] if last else []
                    w_words = _count_words(last["text"]) if last else 0
                win.append(it)
                w_words += w
            emit_child()

    return chunks
