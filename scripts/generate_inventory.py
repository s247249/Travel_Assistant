"""Generate the synthetic travel inventory (Phase 1, decisions D6-D12).

Deterministic: same seed + months => identical database and JSON.
Stdlib only. Writes:
  - db/travel.db        (business facts: inventory + per-date availability + flights)
  - data/inventory.json (static entities with shared IDs, for prompts & validation)

Usage:
  python scripts/generate_inventory.py [--seed 42] [--months 2026-06 2026-07 2026-08 2026-09]
"""

from __future__ import annotations

import argparse
import calendar
import json
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "src" / "reply_proj" / "backend" / "schema.sql"

# ----------------------------- world definition -----------------------------

AIRPORTS = [  # (code, city, country)
    ("TRN", "Turin", "Italy"),
    ("MXP", "Milan", "Italy"),
    ("FCO", "Rome", "Italy"),
    ("NAP", "Naples", "Italy"),
    ("BCN", "Barcelona", "Spain"),
    ("PMI", "Palma de Mallorca", "Spain"),
    ("CDG", "Paris", "France"),
    ("INN", "Innsbruck", "Austria"),
]
ORIGINS = ["TRN", "MXP", "FCO"]
AIRPORT_COUNTRY = {code: country for code, _, country in AIRPORTS}

CITIES = [  # (id, name, country, airport, cost_index, tags)
    ("rome", "Rome", "Italy", "FCO", 1.0, ["culture", "history", "touristy", "city"]),
    ("naples", "Naples", "Italy", "NAP", 0.8, ["sea", "food", "niche", "lively"]),
    ("barcelona", "Barcelona", "Spain", "BCN", 1.0, ["culture", "nightlife", "architecture", "city-beach"]),
    ("palma", "Palma de Mallorca", "Spain", "PMI", 1.15, ["sea", "relax", "family", "beach"]),
    ("paris", "Paris", "France", "CDG", 1.3, ["culture", "museums", "luxury", "touristy"]),
    ("innsbruck", "Innsbruck", "Austria", "INN", 1.1, ["mountain", "sport", "nature", "niche"]),
]

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAILY = None  # operating pattern: None = every day, else tuple of weekday ints (0=Mon)

# (name, category, duration_min, price_lo, price_hi, operating_days)
ACTIVITIES: dict[str, list[tuple]] = {
    "rome": [
        ("Colosseum & Roman Forum Guided Tour", "culture", 180, 45, 75, DAILY),
        ("Vatican Museums & Sistine Chapel Timed Entry", "culture", 210, 20, 30, DAILY),
        ("Trastevere Evening Food Tour", "food", 180, 55, 85, (1, 3, 5)),
        ("Borghese Gallery Timed Entry", "culture", 120, 15, 25, DAILY),
        ("Evening Vespa Sidecar Tour", "nightlife", 150, 60, 90, (2, 4, 5)),
        ("Appian Way E-Bike Ride", "sport", 240, 35, 60, (0, 2, 5)),
        ("Villa Borghese Gardens & Rowboat Lake", "relax", 120, 0, 12, DAILY),
        ("Pizza & Gelato Making Class", "food", 180, 45, 70, (0, 2, 4)),
        ("Catacombs of San Callisto Visit", "culture", 90, 12, 20, DAILY),
        ("Janiculum Hill Sunset Walk", "nature", 90, 0, 0, DAILY),
        ("Testaccio Market Street Food Crawl", "food", 120, 30, 50, (1, 3, 5)),
    ],
    "naples": [
        ("Pompeii Ruins Half-Day Trip", "culture", 300, 45, 75, DAILY),
        ("Spaccanapoli Old Town Walking Tour", "culture", 150, 20, 35, DAILY),
        ("Pizza Margherita Masterclass", "food", 150, 35, 60, (0, 2, 4)),
        ("Capri & Blue Grotto Boat Day Trip", "nature", 480, 70, 90, DAILY),
        ("Napoli Sotterranea Underground Tour", "culture", 120, 12, 20, DAILY),
        ("Lungomare Seafront Sunset Stroll", "relax", 90, 0, 0, DAILY),
        ("Castel dell'Ovo & Borgo Marinaro Visit", "culture", 90, 0, 8, DAILY),
        ("Mount Vesuvius Crater Hike", "sport", 240, 30, 55, DAILY),
        ("Amalfi Coast & Positano Day Trip", "nature", 480, 60, 90, (1, 3, 5, 6)),
        ("Quartieri Spagnoli Street Art Tour", "culture", 120, 18, 30, (1, 3, 5)),
        ("Chiaia Beach Club Day", "relax", 300, 25, 50, DAILY),
    ],
    "barcelona": [
        ("Sagrada Familia Timed Entry & Towers", "culture", 120, 26, 40, DAILY),
        ("Park Guell Timed Entry", "culture", 120, 10, 18, DAILY),
        ("Gothic Quarter Evening Tapas Tour", "food", 180, 45, 75, (1, 3, 5)),
        ("Barceloneta Paddle Surf Lesson", "sport", 150, 30, 55, DAILY),
        ("El Born Flamenco Show", "nightlife", 90, 25, 45, (2, 4, 5, 6)),
        ("Montjuic Cable Car & Castle Views", "nature", 150, 15, 30, DAILY),
        ("Picasso Museum Entry", "culture", 120, 12, 20, DAILY),
        ("Rooftop Bar Crawl", "nightlife", 180, 35, 60, (4, 5)),
        ("Montserrat Monastery Half-Day Trip", "nature", 300, 45, 70, (0, 2, 4, 6)),
        ("El Born Vermut & Cocktail Tasting", "nightlife", 120, 30, 50, (3, 4, 5)),
        ("Ciutadella Park Picnic & Rowboats", "relax", 120, 0, 12, DAILY),
    ],
    "palma": [
        ("Palma Cathedral (La Seu) Entry", "culture", 90, 10, 15, DAILY),
        ("Catamaran Cove & Snorkel Cruise", "relax", 300, 45, 75, DAILY),
        ("Serra de Tramuntana Guided Hike", "sport", 300, 35, 60, (0, 2, 5)),
        ("Playa de Palma Beach Club Day", "relax", 300, 25, 50, DAILY),
        ("Old Town & Patios Walking Tour", "culture", 150, 20, 35, (1, 3, 5)),
        ("Bellver Castle & Forest Walk", "culture", 120, 5, 10, DAILY),
        ("Sunset Sailing Trip", "relax", 180, 40, 65, DAILY),
        ("Mountain E-Bike Tour", "sport", 240, 40, 65, (0, 2, 4)),
        ("Santa Catalina Wine & Tapas Tasting", "food", 150, 35, 60, (2, 4, 5)),
        ("Es Baluard Modern Art Museum", "culture", 120, 8, 12, DAILY),
        ("Formentor Cape & Beach Day Trip", "nature", 420, 45, 75, (1, 3, 5, 6)),
    ],
    "paris": [
        ("Louvre Timed Entry & Highlights Tour", "culture", 210, 30, 55, DAILY),
        ("Eiffel Tower Summit Access", "culture", 150, 35, 60, DAILY),
        ("Seine Evening Dinner Cruise", "food", 180, 75, 120, DAILY),
        ("Montmartre & Sacre-Coeur Walking Tour", "culture", 150, 20, 35, DAILY),
        ("Versailles Palace Day Trip", "culture", 360, 55, 85, (0, 2, 4, 6)),
        ("Luxembourg Gardens & Latin Quarter Stroll", "relax", 120, 0, 0, DAILY),
        ("Marais Food & Wine Tasting Tour", "food", 180, 60, 90, (1, 3, 5)),
        ("Moulin Rouge Cabaret Show", "nightlife", 150, 90, 140, (2, 4, 5, 6)),
        ("Catacombs of Paris Entry", "culture", 90, 15, 30, DAILY),
        ("Canal Saint-Martin Picnic & Petanque", "relax", 150, 0, 15, DAILY),
        ("Bois de Boulogne Bike Ride", "sport", 180, 20, 35, (0, 2, 5)),
    ],
    "innsbruck": [
        ("Nordkette Cable Car to Hafelekar", "nature", 240, 35, 50, DAILY),
        ("Alpine Half-Day Guided Hike", "sport", 300, 30, 55, (0, 2, 5)),
        ("Old Town & Golden Roof Walking Tour", "culture", 120, 15, 25, DAILY),
        ("Ambras Castle & Gardens Entry", "culture", 150, 12, 18, DAILY),
        ("Mountain Bike Downhill Intro Session", "sport", 240, 45, 70, (1, 3, 5)),
        ("Bergisel Ski Jump & Panorama Walk", "sport", 120, 10, 15, DAILY),
        ("Tyrolean Evening Show with Dinner", "nightlife", 180, 45, 70, (2, 4, 5)),
        ("Alpenzoo Alpine Zoo Visit", "nature", 150, 10, 15, DAILY),
        ("Swarovski Crystal Worlds Day Trip", "culture", 240, 25, 40, DAILY),
        ("Inn River Promenade & Sunset Picnic", "relax", 120, 0, 0, DAILY),
        ("Stubai Glacier Panorama Day Trip", "nature", 420, 55, 85, (0, 2, 4, 6)),
    ],
}

# Ideal-audience targets per activity (authority: generator; harvested from the
# validated corpus judgments, D24/F4 amended). Corpus copies are validated against
# these; Chroma metadata is a regenerated projection. JSON list in SQL.
ACTIVITY_TARGETS = {
    'activity_barcelona_001': ['couples', 'family', 'seniors'],
    'activity_barcelona_002': ['family', 'couples', 'young'],
    'activity_barcelona_003': ['foodies', 'couples', 'young'],
    'activity_barcelona_004': ['sporty', 'young'],
    'activity_barcelona_005': ['couples', 'young', 'solo'],
    'activity_barcelona_006': ['family', 'couples', 'seniors'],
    'activity_barcelona_007': ['solo', 'couples', 'seniors'],
    'activity_barcelona_008': ['young', 'couples'],
    'activity_barcelona_009': ['sporty', 'couples', 'seniors'],
    'activity_barcelona_010': ['foodies', 'couples', 'young'],
    'activity_barcelona_011': ['family', 'couples', 'relax-seekers'],
    'activity_innsbruck_001': ['sporty', 'couples', 'young'],
    'activity_innsbruck_002': ['sporty', 'young', 'solo'],
    'activity_innsbruck_003': ['couples', 'seniors', 'solo', 'family'],
    'activity_innsbruck_004': ['couples', 'seniors', 'family'],
    'activity_innsbruck_005': ['sporty', 'young'],
    'activity_innsbruck_006': ['sporty', 'family', 'young'],
    'activity_innsbruck_007': ['couples', 'family', 'seniors', 'foodies'],
    'activity_innsbruck_008': ['family', 'seniors', 'couples'],
    'activity_innsbruck_009': ['couples', 'family', 'young'],
    'activity_innsbruck_010': ['couples', 'family', 'relax-seekers', 'solo'],
    'activity_innsbruck_011': ['sporty', 'young', 'couples'],
    'activity_naples_001': ['family', 'couples', 'seniors'],
    'activity_naples_002': ['young', 'solo', 'couples', 'foodies'],
    'activity_naples_003': ['family', 'young', 'couples', 'foodies'],
    'activity_naples_004': ['couples', 'young', 'relax-seekers'],
    'activity_naples_005': ['young', 'solo', 'family'],
    'activity_naples_006': ['couples', 'seniors', 'relax-seekers', 'family'],
    'activity_naples_007': ['family', 'couples', 'seniors'],
    'activity_naples_008': ['sporty', 'young', 'solo'],
    'activity_naples_009': ['couples', 'young', 'relax-seekers'],
    'activity_naples_010': ['young', 'solo', 'couples'],
    'activity_naples_011': ['relax-seekers', 'couples', 'young', 'family'],
    'activity_palma_001': ['family', 'couples', 'seniors'],
    'activity_palma_002': ['family', 'young', 'couples', 'relax-seekers'],
    'activity_palma_003': ['sporty', 'young', 'solo'],
    'activity_palma_004': ['young', 'couples', 'relax-seekers'],
    'activity_palma_005': ['couples', 'seniors', 'solo'],
    'activity_palma_006': ['family', 'couples', 'sporty'],
    'activity_palma_007': ['couples', 'young', 'relax-seekers'],
    'activity_palma_008': ['sporty', 'young', 'solo'],
    'activity_palma_009': ['foodies', 'couples', 'young'],
    'activity_palma_010': ['solo', 'couples', 'seniors'],
    'activity_palma_011': ['family', 'couples', 'sporty', 'young'],
    'activity_paris_001': ['couples', 'solo', 'seniors'],
    'activity_paris_002': ['couples', 'family', 'young'],
    'activity_paris_003': ['couples', 'foodies', 'seniors'],
    'activity_paris_004': ['couples', 'young', 'solo'],
    'activity_paris_005': ['couples', 'seniors', 'family'],
    'activity_paris_006': ['family', 'seniors', 'relax-seekers', 'couples'],
    'activity_paris_007': ['foodies', 'couples', 'young'],
    'activity_paris_008': ['couples', 'young'],
    'activity_paris_009': ['young', 'solo'],
    'activity_paris_010': ['young', 'family', 'couples', 'relax-seekers'],
    'activity_paris_011': ['sporty', 'family', 'young'],
    'activity_rome_001': ['family', 'couples', 'seniors', 'solo'],
    'activity_rome_002': ['couples', 'seniors', 'solo', 'young'],
    'activity_rome_003': ['foodies', 'couples', 'young', 'solo'],
    'activity_rome_004': ['couples', 'seniors', 'solo'],
    'activity_rome_005': ['couples', 'young', 'solo'],
    'activity_rome_006': ['sporty', 'young', 'couples'],
    'activity_rome_007': ['family', 'couples', 'seniors', 'relax-seekers'],
    'activity_rome_008': ['family', 'young', 'couples', 'foodies'],
    'activity_rome_009': ['seniors', 'solo', 'couples', 'family'],
    'activity_rome_010': ['couples', 'young', 'solo', 'seniors'],
    'activity_rome_011': ['foodies', 'young', 'solo', 'family'],
}

# (name, tier, max_guests_per_room, amenities) — hotel names are fictional
HOTELS: dict[str, list[tuple]] = {
    "rome": [
        ("B&B Aurelia", "budget", 2, ["wifi", "breakfast"]),
        ("Casa Navona", "budget", 2, ["wifi", "ac"]),
        ("Hotel Trastevere Verde", "mid", 3, ["wifi", "breakfast", "ac"]),
        ("Residenza Borghese", "mid", 2, ["wifi", "breakfast", "ac", "gym"]),
        ("Hotel Colosseo Vista", "mid", 3, ["wifi", "breakfast", "ac", "family-rooms"]),
        ("Grand Hotel Palatino", "high", 4, ["wifi", "breakfast", "ac", "spa", "gym", "family-rooms"]),
    ],
    "naples": [
        ("B&B Partenope", "budget", 2, ["wifi", "breakfast"]),
        ("Casa Spaccanapoli", "budget", 3, ["wifi", "ac"]),
        ("Hotel Chiaia Blu", "mid", 2, ["wifi", "breakfast", "ac", "sea-view"]),
        ("Residenza del Golfo", "mid", 3, ["wifi", "breakfast", "ac", "sea-view"]),
        ("Hotel Lungomare Napoli", "mid", 4, ["wifi", "breakfast", "ac", "family-rooms", "sea-view"]),
        ("Grand Hotel Miramare", "high", 4, ["wifi", "breakfast", "ac", "spa", "sea-view", "family-rooms"]),
    ],
    "barcelona": [
        ("Hostal Gracia Sol", "budget", 2, ["wifi", "ac"]),
        ("Casa Barceloneta", "budget", 3, ["wifi", "ac", "sea-view"]),
        ("Hotel Born Central", "mid", 2, ["wifi", "breakfast", "ac"]),
        ("Hotel Eixample Garden", "mid", 3, ["wifi", "breakfast", "ac", "pool"]),
        ("Hotel Mirador Montjuic", "mid", 3, ["wifi", "breakfast", "ac", "gym"]),
        ("Grand Hotel Passeig de Gracia", "high", 4, ["wifi", "breakfast", "ac", "pool", "spa", "family-rooms"]),
    ],
    "palma": [
        ("Hostal Casco Antiguo", "budget", 2, ["wifi", "ac"]),
        ("Casa Santa Catalina", "budget", 2, ["wifi", "breakfast", "ac"]),
        ("Hotel Cala Mayor", "mid", 3, ["wifi", "breakfast", "ac", "sea-view", "pool"]),
        ("Residencia Badia de Palma", "mid", 3, ["wifi", "breakfast", "ac", "pool"]),
        ("Hotel Puerto Azul", "mid", 4, ["wifi", "breakfast", "ac", "pool", "family-rooms", "sea-view"]),
        ("Grand Hotel Miramar Palma", "high", 4, ["wifi", "breakfast", "ac", "pool", "spa", "family-rooms", "sea-view"]),
    ],
    "paris": [
        ("Hotel Canal Saint-Martin", "budget", 2, ["wifi"]),
        ("Maison Montmartre", "budget", 2, ["wifi", "breakfast"]),
        ("Hotel Jardin du Luxembourg", "mid", 2, ["wifi", "breakfast", "ac"]),
        ("Residence Marais Bleue", "mid", 3, ["wifi", "breakfast", "ac", "family-rooms"]),
        ("Hotel Tour Eiffel Vue", "mid", 3, ["wifi", "breakfast", "ac", "gym"]),
        ("Grand Palace Opera", "high", 4, ["wifi", "breakfast", "ac", "spa", "gym", "family-rooms"]),
    ],
    "innsbruck": [
        ("Pension Alpenrose", "budget", 2, ["wifi", "breakfast"]),
        ("Haus Innbrucke", "budget", 3, ["wifi", "breakfast", "parking"]),
        ("Hotel Bergblick Innsbruck", "mid", 3, ["wifi", "breakfast", "sauna", "ski-storage"]),
        ("Hotel Nordkettenblick", "mid", 2, ["wifi", "breakfast", "sauna", "parking"]),
        ("Alpenhotel Talstation", "mid", 4, ["wifi", "breakfast", "sauna", "ski-storage", "family-rooms"]),
        ("Grand Hotel Europa Tirol", "high", 4, ["wifi", "breakfast", "spa", "sauna", "ski-storage", "family-rooms"]),
    ],
}

# ----------------------------- price model (D10) -----------------------------

TIER_BANDS = {"budget": (45.0, 80.0), "mid": (80.0, 170.0), "high": (170.0, 350.0)}
MONTH_FACTOR = {6: 1.0, 7: 1.1, 8: 1.35, 9: 0.95}  # other months default to 1.0
FLIGHT_BAND_DOMESTIC = (25.0, 90.0)
FLIGHT_BAND_INTERNATIONAL = (50.0, 180.0)
FLIGHT_CLAMP = (29.0, 260.0)
DEPART_TIMES = ["07:10", "09:45", "13:20", "17:30", "20:15"]
INN_FLIGHT_WEEKDAYS = {1, 3, 5}  # Tue/Thu/Sat: sparse route (D8)


def season_dates(months: list[str]) -> list[date]:
    first_y, first_m = map(int, months[0].split("-"))
    last_y, last_m = map(int, months[-1].split("-"))
    start = date(first_y, first_m, 1)
    end = date(last_y, last_m, calendar.monthrange(last_y, last_m)[1])
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def month_factor(d: date) -> float:
    return MONTH_FACTOR.get(d.month, 1.0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--months", nargs="+", default=["2026-06", "2026-07", "2026-08", "2026-09"])
    parser.add_argument("--db", type=Path, default=ROOT / "db" / "travel.db")
    parser.add_argument("--json", type=Path, default=ROOT / "data" / "inventory.json")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    dates = season_dates(args.months)
    city_by_id = {c[0]: c for c in CITIES}

    # ---- recreate database ----
    args.db.parent.mkdir(parents=True, exist_ok=True)
    if args.db.exists():
        args.db.unlink()  # regeneration semantics: derived artifact, rebuild from scratch
    con = sqlite3.connect(args.db)
    con.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    con.executemany("INSERT INTO airports VALUES (?,?,?)", AIRPORTS)
    con.executemany(
        "INSERT INTO cities VALUES (?,?,?,?,?,?)",
        [(cid, name, country, ap, idx, json.dumps(tags)) for cid, name, country, ap, idx, tags in CITIES],
    )

    # ---- hotels + per-night availability (S3) ----
    hotel_rows, hotel_avail, hotel_json = [], [], []
    for cid, name, country, ap, index, tags in CITIES:
        for i, (hname, tier, capacity, amenities) in enumerate(HOTELS[cid], start=1):
            hid = f"hotel_{cid}_{i:03d}"
            lo, hi = TIER_BANDS[tier]
            base = round(rng.uniform(lo, hi) * index, 2)
            total_rooms = rng.randint(4, 12)
            hotel_rows.append((hid, cid, hname, tier, capacity, json.dumps(amenities)))
            hotel_json.append({
                "id": hid, "city_id": cid, "name": hname, "tier": tier,
                "max_guests_per_room": capacity, "amenities": amenities,
                "base_price_night": base,
            })
            for d in dates:
                r = rng.random()
                rooms = 0 if r < 0.06 else rng.randint(1, total_rooms)
                mf = month_factor(d)
                price = round(base * mf * rng.uniform(0.92, 1.12), 2)
                assert lo * index * mf * 0.92 - 0.01 <= price <= hi * index * mf * 1.12 + 0.01
                hotel_avail.append((hid, d.isoformat(), rooms, price))
    con.executemany("INSERT INTO hotels VALUES (?,?,?,?,?,?)", hotel_rows)
    con.executemany("INSERT INTO hotel_availability VALUES (?,?,?,?)", hotel_avail)

    # ---- activities + per-date availability ----
    act_rows, act_avail, act_json = [], [], []
    for cid, name, country, ap, index, tags in CITIES:
        for i, (aname, category, duration, lo, hi, pattern) in enumerate(ACTIVITIES[cid], start=1):
            aid = f"activity_{cid}_{i:03d}"
            base = 0.0 if hi == 0 else round(rng.uniform(lo, hi) * index, 2)
            if hi > 0:
                assert lo * index - 0.01 <= base <= hi * index + 0.01
            targets = ACTIVITY_TARGETS[aid]
            act_rows.append((aid, cid, aname, category, duration, base, json.dumps(targets)))
            act_json.append({
                "id": aid, "city_id": cid, "name": aname, "category": category,
                "duration_min": duration, "base_price": base, "targets": targets,
                "operating_days": "daily" if pattern is None else [WEEKDAYS[w] for w in pattern],
            })
            for d in dates:
                if pattern is not None and d.weekday() not in pattern:
                    continue
                r = rng.random()
                if r < 0.05:
                    spots = 0
                elif r < 0.12:
                    spots = rng.randint(1, 3)  # near-sold-out: constraints must bite
                else:
                    spots = rng.randint(4, 30)
                act_avail.append((aid, d.isoformat(), spots))
    con.executemany("INSERT INTO activities VALUES (?,?,?,?,?,?,?)", act_rows)
    con.executemany("INSERT INTO activity_availability VALUES (?,?,?)", act_avail)

    # ---- flights: directed edges, both directions, sparse INN (D8) ----
    dest_airports = [c[3] for c in CITIES]
    routes: list[tuple[str, str]] = []
    for o in ORIGINS:
        for da in dest_airports:
            if o != da:
                routes.extend([(o, da), (da, o)])
    routes = list(dict.fromkeys(routes))  # dedupe, keep order

    flight_rows, route_json = [], []
    for frm, to in routes:
        sparse = INN_FLIGHT_WEEKDAYS if "INN" in (frm, to) else None
        band = FLIGHT_BAND_DOMESTIC if AIRPORT_COUNTRY[frm] == AIRPORT_COUNTRY[to] else FLIGHT_BAND_INTERNATIONAL
        route_json.append({
            "from": frm, "to": to,
            "frequency": "daily" if sparse is None else "/".join(WEEKDAYS[w] for w in sorted(sparse)),
        })
        for d in dates:
            if sparse is not None and d.weekday() not in sparse:
                continue
            price = round(rng.uniform(*band) * month_factor(d) * rng.uniform(0.85, 1.20), 2)
            price = max(FLIGHT_CLAMP[0], min(FLIGHT_CLAMP[1], price))
            r = rng.random()
            if r < 0.06:
                seats = 0
            elif r < 0.14:
                seats = rng.randint(1, 5)
            else:
                seats = rng.randint(8, 180)
            flight_rows.append((frm, to, d.isoformat(), rng.choice(DEPART_TIMES), price, seats))
    con.executemany(
        "INSERT INTO flights (from_code, to_code, date, depart_time, price, seats_left) VALUES (?,?,?,?,?,?)",
        flight_rows,
    )
    con.commit()

    # ---- sanity assertions ----
    assert not con.execute("PRAGMA foreign_key_check").fetchall(), "orphan foreign keys"
    counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in
              ["airports", "cities", "hotels", "hotel_availability", "activities", "activity_availability", "flights"]}
    assert counts["cities"] == 6 and counts["hotels"] == 36 and counts["activities"] == 66
    assert counts["flights"] > 3000
    fmin, fmax = con.execute("SELECT MIN(price), MAX(price) FROM flights").fetchone()
    assert FLIGHT_CLAMP[0] <= fmin and fmax <= FLIGHT_CLAMP[1]
    sold_out = {
        "hotel_nights": con.execute("SELECT COUNT(*) FROM hotel_availability WHERE rooms_left=0").fetchone()[0],
        "activity_dates": con.execute("SELECT COUNT(*) FROM activity_availability WHERE spots_left=0").fetchone()[0],
        "flights": con.execute("SELECT COUNT(*) FROM flights WHERE seats_left=0").fetchone()[0],
    }
    assert all(v > 50 for v in sold_out.values()), "constraints would never bite"
    per_city_acts = dict(con.execute("SELECT city_id, COUNT(*) FROM activities GROUP BY city_id"))
    assert all(v == 11 for v in per_city_acts.values())
    con.close()

    # ---- inventory.json (static entities only; availability lives in the DB) ----
    inventory = {
        "meta": {
            "seed": args.seed, "months": args.months,
            "season_start": dates[0].isoformat(), "season_end": dates[-1].isoformat(),
            "note": "Synthetic demo data. Hotel names fictional. Regenerate with scripts/generate_inventory.py",
        },
        "airports": [{"code": c, "city": city, "country": co} for c, city, co in AIRPORTS],
        "cities": [{"id": cid, "name": n, "country": co, "airport_code": ap, "cost_index": idx, "tags": t}
                   for cid, n, co, ap, idx, t in CITIES],
        "hotels": hotel_json,
        "activities": act_json,
        "routes": route_json,
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(inventory, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"OK  seed={args.seed}  season={dates[0]}..{dates[-1]} ({len(dates)} days)")
    for t, n in counts.items():
        print(f"  {t:22s} {n:6d} rows")
    print(f"  flight price range      EUR {fmin:.2f} .. {fmax:.2f}")
    print(f"  sold-out (constraint demos): {sold_out}")
    print(f"  DB   -> {args.db}")
    print(f"  JSON -> {args.json}")


if __name__ == "__main__":
    main()
