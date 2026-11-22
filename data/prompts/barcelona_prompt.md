# Corpus generation task — Barcelona (Spain)

You are a travel copywriter producing documents for a **synthetic demo dataset** used by a
RAG travel assistant. Write exactly **19 Markdown documents**: 11 activity documents,
6 hotel documents, 1 destination profile, 1 practical guide.

## Output format (strict)

Two execution modes — follow the one that applies to you:

**Agent mode (you have file tools, e.g. pi):** use the write tool to create ONE file,
`data/corpus_raw/barcelona.txt` (relative to the project root), containing all documents
as specified below. You may build the file incrementally, but the final file must contain
all 19 documents. Use ONLY the write tool: no bash, no git, no other files created
or modified, no running scripts, no validating anything yourself — a separate validator
handles that. Your final chat message should only state how many documents you wrote.

**Chat UI mode (no file tools):** wrap your ENTIRE response in ONE outer code fence
(```text on the first line, ``` on the last line) so it can be copied as raw text with the
copy button. The user saves it as `data/corpus_raw/barcelona.txt`. If the response would
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
   family, young, sporty, couples, solo, seniors, relax-seekers, foodies
   `interests` are lowercase hyphenated tags, e.g.: history, archaeology, art, architecture, food, wine, sea, swimming, hiking, cycling, nature, photography, music, wellness, shopping, adventure, local-life
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
sporty people, ...). `## Seasonality` / `## When to go` cover June–September 2026
(heat, crowds, prices peak in August — qualitative only).

## Front matter skeletons

activity:
---
id: <exact id from table>
type: activity
city: Barcelona
country: Spain
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
city: Barcelona
country: Spain
tier: <exact tier from table>
max_guests_per_room: <exact int from table>
amenities: <exact list from table>
targets: [1-4 from vocabulary]
cost_level: <exact value from table>
---

destination:
---
id: destination_barcelona
type: destination
city: Barcelona
country: Spain
tags: ["culture", "nightlife", "architecture", "city-beach"]
budget_level: medium
best_for: [2-4 from vocabulary]
---

guide:
---
id: guide_barcelona
type: guide
city: Barcelona
country: Spain
topics: [transport, food, seasonality, day-planning]
---

## Activities (11 documents)

| filename | id | name | category | duration_min | cost_level | operating days |
|---|---|---|---|---|---|---|
| activity_barcelona_001.md | activity_barcelona_001 | Sagrada Familia Timed Entry & Towers | culture | 120 | medium | daily |
| activity_barcelona_002.md | activity_barcelona_002 | Park Guell Timed Entry | culture | 120 | low | daily |
| activity_barcelona_003.md | activity_barcelona_003 | Gothic Quarter Evening Tapas Tour | food | 180 | medium | tue, thu, sat |
| activity_barcelona_004.md | activity_barcelona_004 | Barceloneta Paddle Surf Lesson | sport | 150 | medium | daily |
| activity_barcelona_005.md | activity_barcelona_005 | El Born Flamenco Show | nightlife | 90 | medium | wed, fri, sat, sun |
| activity_barcelona_006.md | activity_barcelona_006 | Montjuic Cable Car & Castle Views | nature | 150 | low | daily |
| activity_barcelona_007.md | activity_barcelona_007 | Picasso Museum Entry | culture | 120 | low | daily |
| activity_barcelona_008.md | activity_barcelona_008 | Rooftop Bar Crawl | nightlife | 180 | medium | fri, sat |
| activity_barcelona_009.md | activity_barcelona_009 | Montserrat Monastery Half-Day Trip | nature | 300 | high | mon, wed, fri, sun |
| activity_barcelona_010.md | activity_barcelona_010 | El Born Vermut & Cocktail Tasting | nightlife | 120 | medium | thu, fri, sat |
| activity_barcelona_011.md | activity_barcelona_011 | Ciutadella Park Picnic & Rowboats | relax | 120 | low | daily |

## Hotels (6 documents)

| filename | id | name | tier | max_guests_per_room | amenities | cost_level |
|---|---|---|---|---|---|---|
| hotel_barcelona_001.md | hotel_barcelona_001 | Hostal Gracia Sol | budget | 2 | wifi, ac | low |
| hotel_barcelona_002.md | hotel_barcelona_002 | Casa Barceloneta | budget | 3 | wifi, ac, sea-view | low |
| hotel_barcelona_003.md | hotel_barcelona_003 | Hotel Born Central | mid | 2 | wifi, breakfast, ac | medium |
| hotel_barcelona_004.md | hotel_barcelona_004 | Hotel Eixample Garden | mid | 3 | wifi, breakfast, ac, pool | medium |
| hotel_barcelona_005.md | hotel_barcelona_005 | Hotel Mirador Montjuic | mid | 3 | wifi, breakfast, ac, gym | medium |
| hotel_barcelona_006.md | hotel_barcelona_006 | Grand Hotel Passeig de Gracia | high | 4 | wifi, breakfast, ac, pool, spa, family-rooms | high |

## Destination profile (1 document)

Filename: `destination_barcelona.md`, id `destination_barcelona`.
City character to convey: culture, nightlife, architecture, city-beach. Budget level: medium.
This document helps the assistant choose between cities of the same country
(e.g. culture vs sea/relax), so make the vibe and ideal traveller explicit.

## Practical guide (1 document)

Filename: `guide_barcelona.md`, id `guide_barcelona`.
Practical planning knowledge for Barcelona: getting around (airport to centre, metro/bus,
walking), food scene and typical dishes, how to structure days (grouping nearby sights,
booking popular entries ahead, pacing for families vs young travellers), June–September
seasonality. Qualitative only — no fares, prices, hours or timetables.
