"""Eval harness (handoff §6/§11.3/§12).

Runs the REAL retrieval pipeline against a golden set and reports Recall@final and
MRR — so retrieval is tuned against numbers, never by feel (handoff §4.3). A golden
item is a "hit" when a returned source's file name matches `expectedSource` OR its
text contains any `expectedKeywords`.

    python -m app.eval.evaluate            # fusion-only retrieval
    python -m app.eval.evaluate --rerank   # with the cross-encoder gate
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os

from ..db import SessionLocal
from ..levels import normalize_level
from ..services.retrieval import retrieve_sources

GOLDEN_PATH = os.path.join(os.path.dirname(__file__), "golden.json")


def _is_hit(item: dict, source: dict) -> bool:
    fname = (source.get("fileName") or "").lower()
    text = (source.get("text") or "").lower()
    exp_src = (item.get("expectedSource") or "").lower()
    if exp_src and exp_src in fname:
        return True
    for kw in item.get("expectedKeywords", []):
        if kw.lower() in text:
            return True
    return False


async def run(use_rerank: bool) -> None:
    with open(GOLDEN_PATH, encoding="utf-8") as f:
        golden = json.load(f)
    if not golden:
        print("golden.json is empty — add {query, level, expectedSource, expectedKeywords} items.")
        return

    hits = 0
    reciprocal = 0.0
    low_conf = 0
    async with SessionLocal() as db:
        for item in golden:
            res = await retrieve_sources(db, item["query"], normalize_level(item.get("level")), use_rerank=use_rerank)
            sources = res["sources"]
            if res["lowConfidence"]:
                low_conf += 1
            rank = next((i for i, s in enumerate(sources) if _is_hit(item, s)), None)
            if rank is not None:
                hits += 1
                reciprocal += 1.0 / (rank + 1)
            status = f"hit@{rank + 1}" if rank is not None else "MISS"
            print(f"  [{status:>7}] {item['query'][:60]}")

    n = len(golden)
    print("\n── Retrieval eval ──────────────────────────────")
    print(f"  mode         : {'hybrid + rerank gate' if use_rerank else 'hybrid (fusion only)'}")
    print(f"  Recall@final : {hits}/{n} = {hits / n:.3f}")
    print(f"  MRR          : {reciprocal / n:.3f}")
    print(f"  low-confidence: {low_conf}/{n}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rerank", action="store_true", help="enable the cross-encoder rerank gate")
    args = ap.parse_args()
    asyncio.run(run(args.rerank))


if __name__ == "__main__":
    main()
