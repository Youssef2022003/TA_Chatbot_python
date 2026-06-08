"""Education-level definitions (handoff §7). Single source of truth on the backend.

Every chunk is tagged with a `level` (1-5) at ingest, every session carries a
`level`, retrieval is filtered to the student's level (legacy NULL levels stay
visible to all), and the LLM prompt is made level-aware. The frontend keeps a
small label-only mirror in frontend/src/config/levels.js.
"""
from __future__ import annotations

from typing import TypedDict


class Level(TypedDict):
    id: int
    key: str
    name: str
    short: str
    guidance: str


LEVELS: dict[int, Level] = {
    1: {
        "id": 1,
        "key": "primary",
        "name": "Primary / Elementary",
        "short": "Primary",
        "guidance": (
            "Explain as if to a 7-10 year old. Use very simple everyday words and "
            "short sentences. Use familiar analogies (toys, playgrounds, sports, "
            "food). Avoid algebra; use at most simple arithmetic. Keep everything "
            "concrete and avoid jargon."
        ),
    },
    2: {
        "id": 2,
        "key": "middle",
        "name": "Middle School",
        "short": "Middle",
        "guidance": (
            "Explain as if to an 11-14 year old. Use simple language with basic "
            "scientific vocabulary. Introduce simple formulas and basic algebra, "
            "but keep the math light. Relate ideas to everyday experiences."
        ),
    },
    3: {
        "id": 3,
        "key": "high",
        "name": "High School",
        "short": "High School",
        "guidance": (
            "Explain as if to a 15-18 year old. Use standard physics terminology, "
            "algebra, trigonometry, and standard formulas. Show clear, numbered "
            "step-by-step working for problems."
        ),
    },
    4: {
        "id": 4,
        "key": "undergrad",
        "name": "Undergraduate",
        "short": "Undergrad",
        "guidance": (
            "Explain as if to a university physics student. Use precise "
            "terminology, calculus, vector notation, and derivations. Assume "
            "comfort with mathematical rigor and show full derivations where "
            "relevant."
        ),
    },
    5: {
        "id": 5,
        "key": "postgrad",
        "name": "Postgraduate / Advanced",
        "short": "Postgrad",
        "guidance": (
            "Explain as if to a graduate-level student or researcher. Use advanced "
            "formalism, rigorous derivations, and domain-specific terminology. Be "
            "concise and technically deep; do not over-explain basics."
        ),
    },
}

DEFAULT_LEVEL = 3
MIN_LEVEL = 1
MAX_LEVEL = 5


def normalize_level(value) -> int:
    """Coerce arbitrary input (str/int/None) into a valid level id."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return DEFAULT_LEVEL
    if MIN_LEVEL <= n <= MAX_LEVEL:
        return n
    return DEFAULT_LEVEL


def is_valid_level(value) -> bool:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return False
    return MIN_LEVEL <= n <= MAX_LEVEL


def get_level(value) -> Level:
    return LEVELS[normalize_level(value)]
