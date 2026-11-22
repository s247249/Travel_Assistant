"""Score the retriever against the validated eval set (P5/D18).

For each query: run Retriever.search (k=5, query's filters), dedupe chunks to
document IDs, find the rank of the first expected hit. Metrics: hit@5 (primary),
hit@1, MRR (mean reciprocal rank). Writes data/eval/results.json.

Refuses to run on unvalidated input: requires data/eval/queries.json
(produced by validate_eval.py).

Usage: python scripts/eval_retrieval.py
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from google.genai import errors as genai_errors

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from reply_proj.backend.retriever import Retriever  # noqa: E402

K = 5


def search_with_retry(r: Retriever, query: str, filters: dict) -> list[dict]:
    for attempt in range(3):
        try:
            return r.search(query, k=K, **filters)
        except genai_errors.APIError as e:
            if getattr(e, "code", None) == 429 and attempt < 2:
                print("  rate limited; sleeping 60s")
                time.sleep(60)
                continue
            raise
    raise RuntimeError("unreachable")


def main() -> None:
    path = ROOT / "data" / "eval" / "queries.json"
    if not path.exists():
        sys.exit("data/eval/queries.json missing — run scripts/validate_eval.py first")
    queries = json.loads(path.read_text(encoding="utf-8"))

    r = Retriever()
    rows = []
    for q in queries:
        hits = search_with_retry(r, q["query"], q.get("filters", {}))
        doc_ids = list(dict.fromkeys(h["metadata"]["doc_id"] for h in hits))  # chunks -> docs, keep order
        expected = set(q["expected_hits"])
        rank = next((i for i, d in enumerate(doc_ids, start=1) if d in expected), None)
        row = {
            "id": q["id"], "query": q["query"], "filters": q.get("filters", {}),
            "expected_hits": q["expected_hits"], "retrieved": doc_ids,
            "first_hit_rank": rank, "hit_at_5": rank is not None, "hit_at_1": rank == 1,
            "reciprocal_rank": 1.0 / rank if rank else 0.0, "tests": q.get("tests", ""),
        }
        rows.append(row)
        status = "PASS" if rank else "FAIL"
        print(f"{q['id']} {status} rank={rank or '-'}  retrieved={doc_ids[:3]}  expected={q['expected_hits']}")

    n = len(rows)
    metrics = {
        "n_queries": n,
        "hit_at_5": sum(r_["hit_at_5"] for r_ in rows) / n,
        "hit_at_1": sum(r_["hit_at_1"] for r_ in rows) / n,
        "mrr": sum(r_["reciprocal_rank"] for r_ in rows) / n,
    }
    print(f"\nhit@5 = {metrics['hit_at_5']:.0%}   hit@1 = {metrics['hit_at_1']:.0%}   MRR = {metrics['mrr']:.3f}   (k={K}, n={n})")
    failures = [r_["id"] for r_ in rows if not r_["hit_at_5"]]
    if failures:
        print(f"failures: {failures}")

    out = ROOT / "data" / "eval" / "results.json"
    out.write_text(json.dumps(
        {"meta": {"k": K, "generated_at": datetime.now(timezone.utc).isoformat(), "metrics": metrics},
         "queries": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"WROTE {out}")


if __name__ == "__main__":
    main()
