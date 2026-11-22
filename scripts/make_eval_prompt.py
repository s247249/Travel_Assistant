"""Render the retrieval-eval generation prompt (P5/D18 delegation).

Embeds the full entity list (from inventory + validated corpus front matter) so the
delegate can only reference real IDs. Output contract: data/eval/queries_raw.json.

Usage: python scripts/make_eval_prompt.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from make_corpus_prompt import TARGETS_VOCAB, budget_level, cost_level  # noqa: E402

TEMPLATE = """# Retrieval evaluation set — generation task

You are building an evaluation set for the RAG retriever of a synthetic travel assistant.
The retriever combines **semantic search** (Gemini embeddings over description documents)
with **metadata filters** (type, city, country, category, tier, cost_level, target flags).
Write **15–25 evaluation queries** that test this combination, as a single JSON array.

## Output format (strict)

**Agent mode (you have file tools, e.g. pi):** use ONLY the write tool to create
`data/eval/queries_raw.json` (relative to project root) containing the JSON array.
No bash, no git, no other files created or modified, no running scripts, no validating
yourself — a separate validator handles that. Final chat message: only the query count.

**Chat UI mode:** wrap the JSON in ONE outer code fence so it can be copied as raw text.

## JSON schema (each element)

{{
  "id": "q01",
  "query": "relaxing days by the sea for a family",
  "expected_hits": ["activity_palma_002", "activity_palma_004"],
  "filters": {{"type": "activity", "country": "Spain", "target": "family"}},
  "tests": "nation-level + family target + sea/relax semantics"
}}

## Rules (strict)

1. `id`: q01, q02, ... sequential.
2. `query`: natural tourist utterance, English, 5–20 words. **Paraphrase** preferences —
   never copy document titles verbatim, never mention entity IDs. These are semantic tests.
3. `expected_hits`: 1–4 document IDs **from the tables below only**. They must be genuinely
   strong matches for the query under the given filters (plausible top-3 results), and
   consistent with every filter (city, country, type, category, tier, cost_level, target).
4. `filters`: optional object; keys only from: type, city, country, category, tier,
   target, cost_level, budget_level. Values:
   - type: activity | hotel | destination | guide
   - city: exact display name from the tables; country: Italy | Spain | France | Austria
   - target: one of {targets_vocab}
   - cost_level (activities): free | low | medium | high; tier (hotels): budget | mid | high
   - budget_level (destinations): low | medium | high
5. `tests`: one short line naming what the query exercises.
6. Coverage requirements (ALL mandatory):
   - each of the 6 cities appears in ≥2 queries (via filters.city or expected hits' city)
   - each document type (activity, hotel, destination, guide) has ≥1 query
   - ≥5 distinct `target` values used across the set
   - ≥2 nation-level queries (filters.country set, no city filter)
   - ≥1 budget query (cost_level low or free)
   - ≥2 semantic-only queries (filters empty or just {{"type": ...}})
   - ≥1 hotel query and ≥1 "which city suits..." destination-choice query
7. Do not invent entities, prices, or facts. Use only the tables below.

## Activities (id | city | name | category | cost_level | targets)

{activity_table}

## Hotels (id | city | name | tier | targets)

{hotel_table}

## Destinations (id | city | tags | budget_level)

{destination_table}

## Guides (id | city | topics)

{guide_table}
"""


def main() -> None:
    inv = json.loads((ROOT / "data" / "inventory.json").read_text(encoding="utf-8"))
    cities = {c["id"]: c for c in inv["cities"]}
    corpus_fm = {}
    for path in sorted((ROOT / "data" / "corpus").rglob("*.md")):
        fm = yaml.safe_load(path.read_text(encoding="utf-8").split("---", 2)[1])
        corpus_fm[fm["id"]] = fm

    act_rows, hot_rows, dest_rows, guide_rows = [], [], [], []
    for a in inv["activities"]:
        fm = corpus_fm[a["id"]]
        act_rows.append(f"| {a['id']} | {cities[a['city_id']]['name']} | {a['name']} | {a['category']} "
                        f"| {cost_level(a['base_price'])} | {', '.join(fm['targets'])} |")
    for h in inv["hotels"]:
        fm = corpus_fm[h["id"]]
        hot_rows.append(f"| {h['id']} | {cities[h['city_id']]['name']} | {h['name']} | {h['tier']} "
                        f"| {', '.join(fm['targets'])} |")
    for cid, c in cities.items():
        fm = corpus_fm[f"destination_{cid}"]
        dest_rows.append(f"| destination_{cid} | {c['name']} | {', '.join(c['tags'])} | {budget_level(c['cost_index'])} |")
        guide_rows.append(f"| guide_{cid} | {c['name']} | transport, food, seasonality, day-planning |")

    prompt = TEMPLATE.format(
        targets_vocab=", ".join(TARGETS_VOCAB),
        activity_table="\n".join(act_rows), hotel_table="\n".join(hot_rows),
        destination_table="\n".join(dest_rows), guide_table="\n".join(guide_rows),
    )
    out = ROOT / "data" / "prompts" / "eval_queries_prompt.md"
    out.write_text(prompt, encoding="utf-8")
    print(f"OK  {out}  ({len(act_rows)} activities, {len(hot_rows)} hotels, {len(dest_rows)} destinations, {len(guide_rows)} guides)")


if __name__ == "__main__":
    main()
