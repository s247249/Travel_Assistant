"""Validate the delegated retrieval-eval set (P5/D18) against the corpus contract.

Checks: JSON schema, sequential ids, real entity IDs, filter/value validity,
expected-hits consistency with every filter, and the coverage rules from the prompt.
On zero errors, writes the normalized set to data/eval/queries.json (the scorer
refuses to run on anything else).

Usage: python scripts/validate_eval.py [--raw data/eval/queries_raw.json]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from make_corpus_prompt import TARGETS_VOCAB  # noqa: E402

ALLOWED_FILTERS = {"type", "city", "country", "category", "tier", "target", "cost_level", "budget_level"}
TYPES = {"activity", "hotel", "destination", "guide"}
CATEGORIES = {"culture", "sport", "relax", "nightlife", "food", "nature"}
TIERS = {"budget", "mid", "high"}
COSTS = {"free", "low", "medium", "high"}
BUDGETS = {"low", "medium", "high"}
COUNTRIES = {"Italy", "Spain", "France", "Austria"}
ENTITY_ID_RE = re.compile(r"(activity|hotel|destination|guide)_")
VALUE_SETS = {"type": TYPES, "country": COUNTRIES, "category": CATEGORIES,
              "tier": TIERS, "cost_level": COSTS, "budget_level": BUDGETS,
              "target": set(TARGETS_VOCAB)}


def load_corpus_fm() -> dict[str, dict]:
    fm = {}
    for path in sorted((ROOT / "data" / "corpus").rglob("*.md")):
        d = yaml.safe_load(path.read_text(encoding="utf-8").split("---", 2)[1])
        fm[d["id"]] = d
    return fm


def consistency_problems(doc_fm: dict, filters: dict) -> list[str]:
    problems = []
    for key, val in filters.items():
        if key == "target":
            if val not in (doc_fm.get("targets") or doc_fm.get("best_for") or []):
                problems.append(f"target {val!r} not in doc targets")
        elif doc_fm.get(key) != val:
            problems.append(f"{key}: doc has {doc_fm.get(key)!r}, filter requires {val!r}")
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=ROOT / "data" / "eval" / "queries_raw.json")
    args = parser.parse_args()

    corpus = load_corpus_fm()
    cities = {fm["city"] for fm in corpus.values()}
    queries = json.loads(args.raw.read_text(encoding="utf-8"))
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(queries, list) or not 15 <= len(queries) <= 25:
        errors.append(f"expected a JSON array of 15-25 queries, got {type(queries).__name__} of len {len(queries) if isinstance(queries, list) else '?'}")
        queries = queries if isinstance(queries, list) else []

    for i, q in enumerate(queries):
        qid = q.get("id", f"index{i}")
        if q.get("id") != f"q{i + 1:02d}":
            errors.append(f"{qid}: id not sequential (expected q{i + 1:02d})")
        for field in ("query", "expected_hits", "tests"):
            if field not in q:
                errors.append(f"{qid}: missing field {field}")
        query = q.get("query", "")
        if not isinstance(query, str) or not query.strip():
            errors.append(f"{qid}: query must be a non-empty string")
        else:
            if ENTITY_ID_RE.search(query):
                errors.append(f"{qid}: query contains an entity ID (must be natural language)")
            wc = len(query.split())
            if not 5 <= wc <= 20:
                warnings.append(f"{qid}: query word count {wc} outside 5-20 (soft rule)")

        hits = q.get("expected_hits", [])
        if not isinstance(hits, list) or not 1 <= len(hits) <= 4:
            errors.append(f"{qid}: expected_hits must be a list of 1-4 IDs")
            hits = []
        filters = q.get("filters", {})
        if not isinstance(filters, dict):
            errors.append(f"{qid}: filters must be an object")
            filters = {}
        for key, val in filters.items():
            if key not in ALLOWED_FILTERS:
                errors.append(f"{qid}: unknown filter key {key!r}")
            elif key == "city":
                if val not in cities:
                    errors.append(f"{qid}: unknown city {val!r}")
            elif val not in VALUE_SETS[key]:
                errors.append(f"{qid}: invalid {key} value {val!r}")

        for doc_id in hits:
            if doc_id not in corpus:
                errors.append(f"{qid}: expected hit {doc_id!r} does not exist in corpus")
                continue
            for p in consistency_problems(corpus[doc_id], filters):
                errors.append(f"{qid}: {doc_id} inconsistent with filters — {p}")
        q["filters"] = filters  # normalize

    # ---- coverage rules (from the delegation prompt) ----
    def touches_city(q, city):
        return q.get("filters", {}).get("city") == city or any(
            corpus.get(d, {}).get("city") == city for d in q.get("expected_hits", []))

    coverage = {
        "each city >=2 queries": all(sum(touches_city(q, c) for q in queries) >= 2 for c in cities),
        "each type >=1 query": all(any(q.get("filters", {}).get("type") == t or any(
            corpus.get(d, {}).get("type") == t for d in q.get("expected_hits", [])) for q in queries) for t in TYPES),
        ">=5 distinct targets": len({q.get("filters", {}).get("target") for q in queries} - {None}) >= 5,
        ">=2 nation-level": sum("country" in q.get("filters", {}) and "city" not in q.get("filters", {}) for q in queries) >= 2,
        ">=1 budget query": any(q.get("filters", {}).get("cost_level") in {"low", "free"} for q in queries),
        ">=2 semantic-only": sum(set(q.get("filters", {})) <= {"type"} for q in queries) >= 2,
        ">=1 hotel query": any(q.get("filters", {}).get("type") == "hotel" for q in queries),
        ">=1 destination-choice": any(q.get("filters", {}).get("type") == "destination" for q in queries),
    }
    for rule, ok in coverage.items():
        print(f"coverage {'OK  ' if ok else 'FAIL'} {rule}")
        if not ok:
            errors.append(f"coverage rule failed: {rule}")

    for e in errors:
        print(f"ERROR {e}")
    for w in warnings:
        print(f"warn  {w}")
    print(f"\nSummary: {len(queries)} queries, {len(errors)} errors, {len(warnings)} warnings")
    if errors:
        print("NOT WRITTEN — fix errors first")
        sys.exit(1)

    out = ROOT / "data" / "eval" / "queries.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(queries, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"WROTE validated eval set -> {out}")


if __name__ == "__main__":
    main()
