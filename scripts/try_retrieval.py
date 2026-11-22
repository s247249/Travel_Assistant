"""Quick retrieval showcase: hybrid semantic + metadata queries against Chroma.

Usage: python scripts/try_retrieval.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from reply_proj.backend.retriever import Retriever  # noqa: E402

QUERIES = [
    ("relaxing days by the sea for a family", {"type": "activity", "country": "Spain", "target": "family"}),
    ("adrenaline and hiking in the mountains", {"type": "activity", "target": "sporty"}),
    ("evening entertainment for young travellers", {"type": "activity", "category": "nightlife", "target": "young"}),
    ("inexpensive cultural experiences", {"type": "activity", "country": "Italy", "cost_level": "low"}),
    ("luxury stay for a couple's trip", {"type": "hotel", "city": "Paris", "target": "couples"}),
    ("which Italian city suits food lovers on a budget", {"type": "destination", "country": "Italy"}),
]


def main() -> None:
    r = Retriever()
    for query, filters in QUERIES:
        print(f"\nQ: {query!r}  filters={filters}")
        for hit in r.search(query, k=3, **filters):
            m = hit["metadata"]
            snippet = " ".join(hit["text"].split())[:100]
            print(f"  {hit['distance']:.3f}  {m['doc_id']:24s} [{m['city']}] {snippet}...")


if __name__ == "__main__":
    main()
