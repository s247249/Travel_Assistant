"""Render a per-city corpus generation prompt from data/inventory.json (D6 workflow).

The prompt is the schema contract in prose form: exact IDs, controlled vocabularies,
anti-drift rules. The user runs it in a separate LLM chat and saves the raw response
to data/corpus_raw/<city>.txt (files separated by '=== FILE: <name> ===' lines).

Usage: python scripts/make_corpus_prompt.py --city rome
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TARGETS_VOCAB = ["family", "young", "sporty", "couples", "solo", "seniors", "relax-seekers", "foodies"]
INTERESTS_EXAMPLES = ("history, archaeology, art, architecture, food, wine, sea, swimming, hiking, "
                      "cycling, nature, photography, music, wellness, shopping, adventure, local-life")


def cost_level(price: float) -> str:
    if price == 0:
        return "free"
    if price < 20:
        return "low"
    if price < 60:
        return "medium"
    return "high"


def budget_level(index: float) -> str:
    return "low" if index <= 0.85 else ("medium" if index <= 1.15 else "high")


TEMPLATE = """# Corpus generation task — {city_name} ({country})

You are a travel copywriter producing documents for a **synthetic demo dataset** used by a
RAG travel assistant. Write exactly **{n_files} Markdown documents**: {n_act} activity documents,
{n_hot} hotel documents, 1 destination profile, 1 practical guide.

## Output format (strict)

Two execution modes — follow the one that applies to you:

**Agent mode (you have file tools, e.g. pi):** use the write tool to create ONE file,
`data/corpus_raw/{city_id}.txt` (relative to the project root), containing all documents
as specified below. You may build the file incrementally, but the final file must contain
all {n_files} documents. Use ONLY the write tool: no bash, no git, no other files created
or modified, no running scripts, no validating anything yourself — a separate validator
handles that. Your final chat message should only state how many documents you wrote.

**Chat UI mode (no file tools):** wrap your ENTIRE response in ONE outer code fence
(```text on the first line, ``` on the last line) so it can be copied as raw text with the
copy button. The user saves it as `data/corpus_raw/{city_id}.txt`. If the response would
be truncated, stop at a document boundary and end with the single word CONTINUE.

In both modes the content is: all documents one after another, each preceded by a
separator line on its own, exactly:

=== FILE: <filename> ===

Then the raw Markdown document: YAML front matter between --- lines, body with ## headings.
No indentation, no code fences inside the content, no commentary between documents.
Filenames are given in the tables below.

## Global rules (strict)

1. Use **exactly** the ids, names, categories, durations, tiers, capacities, amenities and
   cost levels listed below. Do not invent entities, do not rename anything.
2. Front matter: YAML between `---` lines, fields exactly as in the skeletons below.
   Lists in square brackets, lowercase hyphenated tags.
3. `targets` values must come from this controlled vocabulary:
   {targets_vocab}
   `interests` are lowercase hyphenated tags, e.g.: {interests_examples}
4. **Anti-drift rule: no exact prices, no opening hours, no availability numbers, no URLs
   in the prose.** Prices/availability live in a separate database. Use qualitative words
   (free, inexpensive, moderate, premium). Mentioning operating weekdays from the tables is allowed.
5. Activity descriptions reference real places: keep general facts plausible and stable;
   avoid volatile specifics (ticket prices, schedules, rules that change).
6. **Hotels are fictional**: describe them plausibly from tier/amenities/area as if they exist
   in this demo world. Never mention that they are fictional, never claim real-world existence.
7. English, professional guidebook tone, no emoji. Every chunk of text must be understandable
   standalone: always name the city and the entity in the body.
8. Word counts (body, excluding front matter): activities 150–280, hotels 100–180,
   destination 250–400, guide 300–450. Count before finishing; stay inside the ranges.

## Body sections (use these exact headings)

- activity: `## Description`, `## Who it's for`, `## Practical notes`
- hotel: `## Description`, `## Who it's for`, `## Practical notes`
- destination: `## Overview`, `## Vibe & who it suits`, `## When to go`, `## Getting around`
- guide: `## Transport`, `## Food`, `## Day-planning tips`, `## Seasonality`

`## Who it's for` must explicitly discuss the ideal targets (families, young travellers,
sporty people, ...). `## Seasonality` / `## When to go` cover June–September {season_year}
(heat, crowds, prices peak in August — qualitative only).

## Front matter skeletons

activity:
---
id: <exact id from table>
type: activity
city: {city_name}
country: {country}
category: <exact category from table>
interests: [2-5 tags]
targets: [1-4 from vocabulary]
duration_min: <exact int from table>
cost_level: <exact value from table>
indoor_outdoor: <indoor|outdoor|mixed>
booking_recommended: <true|false>
---

hotel:
---
id: <exact id from table>
type: hotel
city: {city_name}
country: {country}
tier: <exact tier from table>
max_guests_per_room: <exact int from table>
amenities: <exact list from table>
targets: [1-4 from vocabulary]
cost_level: <exact value from table>
---

destination:
---
id: destination_{city_id}
type: destination
city: {city_name}
country: {country}
tags: {tags}
budget_level: {budget_level}
best_for: [2-4 from vocabulary]
---

guide:
---
id: guide_{city_id}
type: guide
city: {city_name}
country: {country}
topics: [transport, food, seasonality, day-planning]
---

## Activities ({n_act} documents)

| filename | id | name | category | duration_min | cost_level | operating days |
|---|---|---|---|---|---|---|
{activity_table}

## Hotels ({n_hot} documents)

| filename | id | name | tier | max_guests_per_room | amenities | cost_level |
|---|---|---|---|---|---|---|
{hotel_table}

## Destination profile (1 document)

Filename: `destination_{city_id}.md`, id `destination_{city_id}`.
City character to convey: {tags_readable}. Budget level: {budget_level}.
This document helps the assistant choose between cities of the same country
(e.g. culture vs sea/relax), so make the vibe and ideal traveller explicit.

## Practical guide (1 document)

Filename: `guide_{city_id}.md`, id `guide_{city_id}`.
Practical planning knowledge for {city_name}: getting around (airport to centre, metro/bus,
walking), food scene and typical dishes, how to structure days (grouping nearby sights,
booking popular entries ahead, pacing for families vs young travellers), June–September
seasonality. Qualitative only — no fares, prices, hours or timetables.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city", required=True)
    parser.add_argument("--inventory", type=Path, default=ROOT / "data" / "inventory.json")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    inv = json.loads(args.inventory.read_text(encoding="utf-8"))
    city = next(c for c in inv["cities"] if c["id"] == args.city)
    acts = [a for a in inv["activities"] if a["city_id"] == args.city]
    hots = [h for h in inv["hotels"] if h["city_id"] == args.city]

    act_table = "\n".join(
        f"| {a['id']}.md | {a['id']} | {a['name']} | {a['category']} | {a['duration_min']} "
        f"| {cost_level(a['base_price'])} | {a['operating_days'] if isinstance(a['operating_days'], str) else ', '.join(a['operating_days'])} |"
        for a in acts
    )
    hot_table = "\n".join(
        f"| {h['id']}.md | {h['id']} | {h['name']} | {h['tier']} | {h['max_guests_per_room']} "
        f"| {', '.join(h['amenities'])} | { {'budget': 'low', 'mid': 'medium', 'high': 'high'}[h['tier']] } |"
        for h in hots
    )

    prompt = TEMPLATE.format(
        city_name=city["name"], country=city["country"], city_id=city["id"],
        n_files=len(acts) + len(hots) + 2, n_act=len(acts), n_hot=len(hots),
        targets_vocab=", ".join(TARGETS_VOCAB), interests_examples=INTERESTS_EXAMPLES,
        season_year=inv["meta"]["season_start"][:4],
        tags=json.dumps(city["tags"]), tags_readable=", ".join(city["tags"]),
        budget_level=budget_level(city["cost_index"]),
        activity_table=act_table, hotel_table=hot_table,
    )
    out = args.out or ROOT / "data" / "prompts" / f"{args.city}_prompt.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(prompt, encoding="utf-8")
    print(f"OK  {out}  ({len(acts)} activities, {len(hots)} hotels, +2 city docs)")


if __name__ == "__main__":
    main()
