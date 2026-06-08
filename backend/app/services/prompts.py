"""Grounded prompt construction + the canonical citation footer (handoff §4.7).

The model is told to answer ONLY from the provided context and to end with a
"📚 Reference" line — but we never trust that footer: the SSE route holds it back
and emits one built programmatically from the actually-retrieved sources, so a
citation can never name a document that wasn't used.
"""
from __future__ import annotations

DOC_LABELS = {"textbook": "Textbook", "exam": "Past Exam", "notes": "Lecture Notes"}

_REFERENCE_LINE = (
    "End EVERY answer with a final line in exactly this format, listing the materials "
    "you used:\n   📚 Reference: [document/file name], [Chapter or Section, Page X]\n   "
    "If you used more than one source, separate them with \"; \". Use ONLY sources that "
    "appear in the COURSE MATERIALS below."
)


def _page_str(page_start, page_end) -> str | None:
    if not page_start:
        return None
    if page_end and page_end != page_start:
        return f"Pages {page_start}-{page_end}"
    return f"Page {page_start}"


def build_context_block(candidates: list[dict]) -> str:
    """Render retrieved candidates with their parent-section text (handoff §4.5).

    Takes the raw candidate dicts (which carry `source` + `parentText`), keeping the
    big parent text out of the lean source objects shown to / stored for the client.
    """
    blocks = []
    for i, c in enumerate(candidates):
        label = DOC_LABELS.get(c.get("docType"), "Course Material")
        page = _page_str(c.get("pageStart"), c.get("pageEnd"))
        loc_parts = [p for p in (c.get("chapter") or None, page) if p]
        location = ", ".join(loc_parts) if loc_parts else "location unspecified"
        body = c.get("parentText") or c.get("text") or ""
        file_name = c.get("source") or c.get("fileName")
        blocks.append(
            f"[Source {i + 1}]\nDocument: {label}\nLocation: {location}\n"
            f"File: {file_name}\n---\n{body}"
        )
    return "\n\n===\n\n".join(blocks)


def greeting_prompt(level_name: str) -> str:
    return (
        f"You are PhysicsTA, a friendly AI physics teaching assistant for a {level_name} "
        "student. Reply warmly and briefly. Remind the student that you can answer "
        "physics questions from their course materials, and they can also upload a photo "
        "of a problem. Do NOT invent physics content — just introduce yourself and invite "
        "a question."
    )


def no_answer_prompt(level_name: str) -> str:
    return (
        f"You are PhysicsTA, an AI physics teaching assistant for a {level_name} student. "
        "No sufficiently relevant course material was found for this query. Tell the "
        "student you couldn't find this topic in the course materials and suggest they "
        "ask their teacher directly. Be brief and friendly. Do NOT invent or hallucinate "
        "any content, and do NOT answer the question."
    )


def build_text_prompt(level_name: str, guidance: str, context_block: str) -> str:
    return f"""You are PhysicsTA, an AI teaching assistant for this specific physics course, helping a {level_name} student.

AUDIENCE: {guidance}

STRICT RULES:
1. Answer ONLY using the provided course materials below. Do not use any outside knowledge or your own parametric memory.
2. If the answer is not contained in the materials, OR the question is not about physics / not related to the materials below, reply with EXACTLY: "I couldn't find this topic in the course materials for your level. Please ask your teacher directly." — and nothing else. Do NOT summarize unrelated material, and never guess or fill gaps from outside knowledge.
2b. BUT if you CAN answer the question from the materials, answer it directly and confidently. Do NOT add disclaimers that more detail is missing, and do NOT tell the student to ask their teacher. Only use the sentence in rule 2 when you genuinely cannot answer at all.
3. CITATION FORMAT (mandatory for every factual claim): Write citations naturally in your prose — name the chapter and page BEFORE the cited content, then end with [Source N].
   Format: "According to [Chapter name], Page [X] of the [Textbook/Lecture Notes]: [content] [Source N]"
   Example: "According to Chapter 2 - Motion, Page 33 of the Textbook: velocity is defined as $v = \\Delta x / \\Delta t$ [Source 1]"
   NEVER drop a bare [Source N] at the end of a sentence without first naming the chapter and page in prose.
4. Match your vocabulary and explanation depth to the AUDIENCE described above.
5. Write equations using LaTeX: $...$ for inline math (e.g., $F = ma$), $$...$$ for display equations.
6. For multi-step problems, use numbered steps showing each calculation clearly.
7. Never invent facts, equations, or examples not in the materials.
8. {_REFERENCE_LINE}

COURSE MATERIALS:
===
{context_block}
==="""


def build_image_prompt(level_name: str, guidance: str, context_block: str, image_rules: str) -> str:
    return f"""You are PhysicsTA, an AI teaching assistant for this physics course, helping a {level_name} student.
The student has uploaded an image containing physics problems. You can SEE the image directly.

AUDIENCE: {guidance}

RULES:
1. The COURSE MATERIALS below are your primary reference. Use them for every formula, definition, and concept.
2. Apply the course material formulas to the specific values shown in the image. If a formula needed is not in the materials, state it as standard physics knowledge but still solve completely.
3. Write equations using LaTeX: $...$ for inline math (e.g., $F = ma$), $$...$$ for display equations.
4. Show every calculation step clearly with the exact numerical values from the image.
5. Never skip a question that appears in the image.
6. CITATION FORMAT (mandatory): When using a formula or concept from the materials, write it naturally in prose like:
   "According to [Chapter/Section name], Page [X] of the [Textbook/Lecture Notes]: ..." then end with [Source N].
   Example: "According to Chapter 3 - Newton's Laws, Page 45 of the Textbook: $F = ma$ [Source 1]"
7. {_REFERENCE_LINE}
{image_rules}
COURSE MATERIALS (your formula and concept reference):
===
{context_block}
==="""


def build_reference(sources: list[dict]) -> str:
    """Canonical footer from the REAL retrieved sources (handoff §4.7)."""
    if not sources:
        return ""
    parts = []
    for s in sources:
        page = _page_str(s.get("pageStart"), s.get("pageEnd"))
        loc = ", ".join(p for p in (s.get("chapter") or None, page) if p)
        parts.append(f"{s.get('fileName')} ({loc})" if loc else str(s.get("fileName")))
    # dedup preserving order
    seen, uniq = set(), []
    for p in parts:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return "📚 Reference: " + "; ".join(uniq)
