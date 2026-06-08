"""Image-problem helpers (handoff §4.11). MCQ + multi-question detection feed
mandatory rules into the system prompt so every question is answered and MCQs get
an explicit "Answer: X)" with reasoning about the other options.
"""
from __future__ import annotations

import re

_MCQ_RE = re.compile(r"Q\d+\s+choices:|answer choices:|^\s*[A-D]\)", re.I | re.M)
_QNUM_RE = re.compile(r"\bQ(\d+)\s*:", re.I)


def detect_mcq(extracted: str) -> bool:
    return bool(_MCQ_RE.search(extracted or ""))


def count_questions(extracted: str) -> int:
    nums = [int(n) for n in _QNUM_RE.findall(extracted or "")]
    return max(nums) if nums else 1


def build_image_rules(extracted: str) -> str:
    rules = [
        "The DIAGRAM DESCRIPTION and GIVEN DATA sections above describe the physical "
        "setup from the image. Use those exact values (masses, angles, forces, "
        "distances) in every calculation — do not substitute generic values."
    ]
    q_count = count_questions(extracted)
    if q_count > 1:
        rules.append(
            f"The image contains {q_count} questions (Q1-Q{q_count}). You MUST answer "
            "EVERY question in numbered order. Label each answer clearly as \"Q1:\", "
            "\"Q2:\", etc. Do not skip any."
        )
    if detect_mcq(extracted):
        rules.append(
            "Multiple choice options are present. For each MCQ question you MUST: "
            "(1) state your final answer as \"Answer: X)\" where X is the letter, "
            "(2) show the calculation or reasoning that leads to that choice, "
            "(3) briefly explain why the other options are incorrect."
        )
    if not rules:
        return ""
    body = "\n".join(f"{i + 1}. {r}" for i, r in enumerate(rules))
    return "\nIMAGE PROBLEM RULES (MANDATORY — follow these exactly):\n" + body
