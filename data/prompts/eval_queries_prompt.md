# Retrieval evaluation set — generation task

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

{
  "id": "q01",
  "query": "relaxing days by the sea for a family",
  "expected_hits": ["activity_palma_002", "activity_palma_004"],
  "filters": {"type": "activity", "country": "Spain", "target": "family"},
  "tests": "nation-level + family target + sea/relax semantics"
}

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
   - target: one of family, young, sporty, couples, solo, seniors, relax-seekers, foodies
   - cost_level (activities): free | low | medium | high; tier (hotels): budget | mid | high
   - budget_level (destinations): low | medium | high
5. `tests`: one short line naming what the query exercises.
6. Coverage requirements (ALL mandatory):
   - each of the 6 cities appears in ≥2 queries (via filters.city or expected hits' city)
   - each document type (activity, hotel, destination, guide) has ≥1 query
   - ≥5 distinct `target` values used across the set
   - ≥2 nation-level queries (filters.country set, no city filter)
   - ≥1 budget query (cost_level low or free)
   - ≥2 semantic-only queries (filters empty or just {"type": ...})
   - ≥1 hotel query and ≥1 "which city suits..." destination-choice query
7. Do not invent entities, prices, or facts. Use only the tables below.

## Activities (id | city | name | category | cost_level | targets)

| activity_rome_001 | Rome | Colosseum & Roman Forum Guided Tour | culture | high | family, couples, seniors, solo |
| activity_rome_002 | Rome | Vatican Museums & Sistine Chapel Timed Entry | culture | medium | couples, seniors, solo, young |
| activity_rome_003 | Rome | Trastevere Evening Food Tour | food | high | foodies, couples, young, solo |
| activity_rome_004 | Rome | Borghese Gallery Timed Entry | culture | low | couples, seniors, solo |
| activity_rome_005 | Rome | Evening Vespa Sidecar Tour | nightlife | high | couples, young, solo |
| activity_rome_006 | Rome | Appian Way E-Bike Ride | sport | medium | sporty, young, couples |
| activity_rome_007 | Rome | Villa Borghese Gardens & Rowboat Lake | relax | low | family, couples, seniors, relax-seekers |
| activity_rome_008 | Rome | Pizza & Gelato Making Class | food | medium | family, young, couples, foodies |
| activity_rome_009 | Rome | Catacombs of San Callisto Visit | culture | low | seniors, solo, couples, family |
| activity_rome_010 | Rome | Janiculum Hill Sunset Walk | nature | free | couples, young, solo, seniors |
| activity_rome_011 | Rome | Testaccio Market Street Food Crawl | food | medium | foodies, young, solo, family |
| activity_naples_001 | Naples | Pompeii Ruins Half-Day Trip | culture | medium | family, couples, seniors |
| activity_naples_002 | Naples | Spaccanapoli Old Town Walking Tour | culture | low | young, solo, couples, foodies |
| activity_naples_003 | Naples | Pizza Margherita Masterclass | food | medium | family, young, couples, foodies |
| activity_naples_004 | Naples | Capri & Blue Grotto Boat Day Trip | nature | high | couples, young, relax-seekers |
| activity_naples_005 | Naples | Napoli Sotterranea Underground Tour | culture | low | young, solo, family |
| activity_naples_006 | Naples | Lungomare Seafront Sunset Stroll | relax | free | couples, seniors, relax-seekers, family |
| activity_naples_007 | Naples | Castel dell'Ovo & Borgo Marinaro Visit | culture | low | family, couples, seniors |
| activity_naples_008 | Naples | Mount Vesuvius Crater Hike | sport | medium | sporty, young, solo |
| activity_naples_009 | Naples | Amalfi Coast & Positano Day Trip | nature | high | couples, young, relax-seekers |
| activity_naples_010 | Naples | Quartieri Spagnoli Street Art Tour | culture | medium | young, solo, couples |
| activity_naples_011 | Naples | Chiaia Beach Club Day | relax | medium | relax-seekers, couples, young, family |
| activity_barcelona_001 | Barcelona | Sagrada Familia Timed Entry & Towers | culture | medium | couples, family, seniors |
| activity_barcelona_002 | Barcelona | Park Guell Timed Entry | culture | low | family, couples, young |
| activity_barcelona_003 | Barcelona | Gothic Quarter Evening Tapas Tour | food | medium | foodies, couples, young |
| activity_barcelona_004 | Barcelona | Barceloneta Paddle Surf Lesson | sport | medium | sporty, young |
| activity_barcelona_005 | Barcelona | El Born Flamenco Show | nightlife | medium | couples, young, solo |
| activity_barcelona_006 | Barcelona | Montjuic Cable Car & Castle Views | nature | low | family, couples, seniors |
| activity_barcelona_007 | Barcelona | Picasso Museum Entry | culture | low | solo, couples, seniors |
| activity_barcelona_008 | Barcelona | Rooftop Bar Crawl | nightlife | medium | young, couples |
| activity_barcelona_009 | Barcelona | Montserrat Monastery Half-Day Trip | nature | high | sporty, couples, seniors |
| activity_barcelona_010 | Barcelona | El Born Vermut & Cocktail Tasting | nightlife | medium | foodies, couples, young |
| activity_barcelona_011 | Barcelona | Ciutadella Park Picnic & Rowboats | relax | low | family, couples, relax-seekers |
| activity_palma_001 | Palma de Mallorca | Palma Cathedral (La Seu) Entry | culture | low | family, couples, seniors |
| activity_palma_002 | Palma de Mallorca | Catamaran Cove & Snorkel Cruise | relax | high | family, young, couples, relax-seekers |
| activity_palma_003 | Palma de Mallorca | Serra de Tramuntana Guided Hike | sport | medium | sporty, young, solo |
| activity_palma_004 | Palma de Mallorca | Playa de Palma Beach Club Day | relax | medium | young, couples, relax-seekers |
| activity_palma_005 | Palma de Mallorca | Old Town & Patios Walking Tour | culture | medium | couples, seniors, solo |
| activity_palma_006 | Palma de Mallorca | Bellver Castle & Forest Walk | culture | low | family, couples, sporty |
| activity_palma_007 | Palma de Mallorca | Sunset Sailing Trip | relax | high | couples, young, relax-seekers |
| activity_palma_008 | Palma de Mallorca | Mountain E-Bike Tour | sport | medium | sporty, young, solo |
| activity_palma_009 | Palma de Mallorca | Santa Catalina Wine & Tapas Tasting | food | medium | foodies, couples, young |
| activity_palma_010 | Palma de Mallorca | Es Baluard Modern Art Museum | culture | low | solo, couples, seniors |
| activity_palma_011 | Palma de Mallorca | Formentor Cape & Beach Day Trip | nature | medium | family, couples, sporty, young |
| activity_paris_001 | Paris | Louvre Timed Entry & Highlights Tour | culture | medium | couples, solo, seniors |
| activity_paris_002 | Paris | Eiffel Tower Summit Access | culture | medium | couples, family, young |
| activity_paris_003 | Paris | Seine Evening Dinner Cruise | food | high | couples, foodies, seniors |
| activity_paris_004 | Paris | Montmartre & Sacre-Coeur Walking Tour | culture | medium | couples, young, solo |
| activity_paris_005 | Paris | Versailles Palace Day Trip | culture | high | couples, seniors, family |
| activity_paris_006 | Paris | Luxembourg Gardens & Latin Quarter Stroll | relax | free | family, seniors, relax-seekers, couples |
| activity_paris_007 | Paris | Marais Food & Wine Tasting Tour | food | high | foodies, couples, young |
| activity_paris_008 | Paris | Moulin Rouge Cabaret Show | nightlife | high | couples, young |
| activity_paris_009 | Paris | Catacombs of Paris Entry | culture | medium | young, solo |
| activity_paris_010 | Paris | Canal Saint-Martin Picnic & Petanque | relax | low | young, family, couples, relax-seekers |
| activity_paris_011 | Paris | Bois de Boulogne Bike Ride | sport | medium | sporty, family, young |
| activity_innsbruck_001 | Innsbruck | Nordkette Cable Car to Hafelekar | nature | medium | sporty, couples, young |
| activity_innsbruck_002 | Innsbruck | Alpine Half-Day Guided Hike | sport | medium | sporty, young, solo |
| activity_innsbruck_003 | Innsbruck | Old Town & Golden Roof Walking Tour | culture | low | couples, seniors, solo, family |
| activity_innsbruck_004 | Innsbruck | Ambras Castle & Gardens Entry | culture | low | couples, seniors, family |
| activity_innsbruck_005 | Innsbruck | Mountain Bike Downhill Intro Session | sport | high | sporty, young |
| activity_innsbruck_006 | Innsbruck | Bergisel Ski Jump & Panorama Walk | sport | low | sporty, family, young |
| activity_innsbruck_007 | Innsbruck | Tyrolean Evening Show with Dinner | nightlife | medium | couples, family, seniors, foodies |
| activity_innsbruck_008 | Innsbruck | Alpenzoo Alpine Zoo Visit | nature | low | family, seniors, couples |
| activity_innsbruck_009 | Innsbruck | Swarovski Crystal Worlds Day Trip | culture | medium | couples, family, young |
| activity_innsbruck_010 | Innsbruck | Inn River Promenade & Sunset Picnic | relax | free | couples, family, relax-seekers, solo |
| activity_innsbruck_011 | Innsbruck | Stubai Glacier Panorama Day Trip | nature | high | sporty, young, couples |

## Hotels (id | city | name | tier | targets)

| hotel_rome_001 | Rome | B&B Aurelia | budget | couples, solo, young |
| hotel_rome_002 | Rome | Casa Navona | budget | young, couples, solo |
| hotel_rome_003 | Rome | Hotel Trastevere Verde | mid | family, couples, foodies |
| hotel_rome_004 | Rome | Residenza Borghese | mid | couples, sporty, solo |
| hotel_rome_005 | Rome | Hotel Colosseo Vista | mid | family, seniors, couples |
| hotel_rome_006 | Rome | Grand Hotel Palatino | high | family, couples, relax-seekers, seniors |
| hotel_naples_001 | Naples | B&B Partenope | budget | couples, solo, young |
| hotel_naples_002 | Naples | Casa Spaccanapoli | budget | young, solo, family |
| hotel_naples_003 | Naples | Hotel Chiaia Blu | mid | couples, relax-seekers |
| hotel_naples_004 | Naples | Residenza del Golfo | mid | couples, family, seniors |
| hotel_naples_005 | Naples | Hotel Lungomare Napoli | mid | family, couples, seniors |
| hotel_naples_006 | Naples | Grand Hotel Miramare | high | couples, family, relax-seekers |
| hotel_barcelona_001 | Barcelona | Hostal Gracia Sol | budget | young, solo, couples |
| hotel_barcelona_002 | Barcelona | Casa Barceloneta | budget | young, family, sporty |
| hotel_barcelona_003 | Barcelona | Hotel Born Central | mid | couples, solo, foodies |
| hotel_barcelona_004 | Barcelona | Hotel Eixample Garden | mid | family, couples, relax-seekers |
| hotel_barcelona_005 | Barcelona | Hotel Mirador Montjuic | mid | sporty, couples, family |
| hotel_barcelona_006 | Barcelona | Grand Hotel Passeig de Gracia | high | family, couples, relax-seekers |
| hotel_palma_001 | Palma de Mallorca | Hostal Casco Antiguo | budget | solo, young, couples |
| hotel_palma_002 | Palma de Mallorca | Casa Santa Catalina | budget | foodies, couples, solo |
| hotel_palma_003 | Palma de Mallorca | Hotel Cala Mayor | mid | couples, relax-seekers, family |
| hotel_palma_004 | Palma de Mallorca | Residencia Badia de Palma | mid | family, seniors, relax-seekers |
| hotel_palma_005 | Palma de Mallorca | Hotel Puerto Azul | mid | family, relax-seekers, young |
| hotel_palma_006 | Palma de Mallorca | Grand Hotel Miramar Palma | high | couples, family, relax-seekers |
| hotel_paris_001 | Paris | Hotel Canal Saint-Martin | budget | young, solo, couples |
| hotel_paris_002 | Paris | Maison Montmartre | budget | young, couples, solo |
| hotel_paris_003 | Paris | Hotel Jardin du Luxembourg | mid | couples, seniors, relax-seekers |
| hotel_paris_004 | Paris | Residence Marais Bleue | mid | family, couples |
| hotel_paris_005 | Paris | Hotel Tour Eiffel Vue | mid | family, sporty, couples |
| hotel_paris_006 | Paris | Grand Palace Opera | high | family, couples, relax-seekers, seniors |
| hotel_innsbruck_001 | Innsbruck | Pension Alpenrose | budget | couples, solo, young |
| hotel_innsbruck_002 | Innsbruck | Haus Innbrucke | budget | family, young, sporty |
| hotel_innsbruck_003 | Innsbruck | Hotel Bergblick Innsbruck | mid | sporty, couples, young |
| hotel_innsbruck_004 | Innsbruck | Hotel Nordkettenblick | mid | couples, relax-seekers, seniors |
| hotel_innsbruck_005 | Innsbruck | Alpenhotel Talstation | mid | family, sporty, young |
| hotel_innsbruck_006 | Innsbruck | Grand Hotel Europa Tirol | high | family, couples, relax-seekers, foodies |

## Destinations (id | city | tags | budget_level)

| destination_rome | Rome | culture, history, touristy, city | medium |
| destination_naples | Naples | sea, food, niche, lively | low |
| destination_barcelona | Barcelona | culture, nightlife, architecture, city-beach | medium |
| destination_palma | Palma de Mallorca | sea, relax, family, beach | medium |
| destination_paris | Paris | culture, museums, luxury, touristy | high |
| destination_innsbruck | Innsbruck | mountain, sport, nature, niche | medium |

## Guides (id | city | topics)

| guide_rome | Rome | transport, food, seasonality, day-planning |
| guide_naples | Naples | transport, food, seasonality, day-planning |
| guide_barcelona | Barcelona | transport, food, seasonality, day-planning |
| guide_palma | Palma de Mallorca | transport, food, seasonality, day-planning |
| guide_paris | Paris | transport, food, seasonality, day-planning |
| guide_innsbruck | Innsbruck | transport, food, seasonality, day-planning |
