"""SQL fact queries (golden rule: hard facts and arithmetic live here, not in the LLM).

Phase 3 surface: flight search, hotel availability+pricing, and the small
lookup helpers used to validate requirements. Booking transactions arrive in
Phase 5; user auth in Phase 6.
"""

from __future__ import annotations

import math
import sqlite3
from datetime import date

from reply_proj.backend import config


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


# ---------------- lookups (requirement validation, D20) ----------------

def valid_nations() -> list[str]:
    with connect() as con:
        return [r["country"] for r in con.execute("SELECT DISTINCT country FROM cities ORDER BY country")]


def valid_months() -> list[str]:
    """Data-driven season: whatever months the inventory actually covers (D7 extensibility)."""
    with connect() as con:
        return [r["m"] for r in con.execute("SELECT DISTINCT substr(date,1,7) AS m FROM flights ORDER BY m")]


def valid_airports() -> list[str]:
    with connect() as con:
        return [r["code"] for r in con.execute("SELECT code FROM airports ORDER BY code")]


def resolve_city(name: str) -> dict | None:
    """Accept a city id ('rome') or display name ('Rome'), case-insensitive."""
    with connect() as con:
        row = con.execute(
            "SELECT id, name, country, airport_code FROM cities WHERE lower(id)=lower(?) OR lower(name)=lower(?)",
            (name, name),
        ).fetchone()
    return dict(row) if row else None


# ---------------- fact queries (agent tools) ----------------

def search_flights(origin: str, destination_city: str, date_from: str, date_to: str, limit: int = 30) -> list[dict]:
    city = resolve_city(destination_city)
    if city is None:
        raise ValueError(f"unknown destination city {destination_city!r}")
    if origin not in valid_airports():
        raise ValueError(f"unknown origin airport {origin!r}")
    date.fromisoformat(date_from)
    date.fromisoformat(date_to)
    return flights_between(origin, city["airport_code"], date_from, date_to, limit)


def flights_between(from_code: str, to_code: str, date_from: str, date_to: str, limit: int = 500) -> list[dict]:
    """Raw route query (both directions usable; planner pairs outbound/return)."""
    with connect() as con:
        rows = con.execute(
            """SELECT id, date, depart_time, from_code, to_code, price, seats_left
               FROM flights WHERE from_code = ? AND to_code = ? AND date BETWEEN ? AND ?
               ORDER BY date, price LIMIT ?""",
            (from_code, to_code, date_from, date_to, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def hotel_nights(hotel_id: str, date_from: str, date_to: str) -> list[dict]:
    """Per-night rows (checkout exclusive) for proposal items."""
    with connect() as con:
        rows = con.execute(
            "SELECT date, rooms_left, price_night FROM hotel_availability "
            "WHERE hotel_id = ? AND date >= ? AND date < ? ORDER BY date",
            (hotel_id, date_from, date_to),
        ).fetchall()
    return [dict(r) for r in rows]


def list_cities() -> list[dict]:
    with connect() as con:
        return [dict(r) for r in con.execute("SELECT id, name, country FROM cities ORDER BY name")]


def activities_for_city(city_id: str) -> list[dict]:
    with connect() as con:
        rows = con.execute(
            "SELECT id, name, category, duration_min, base_price FROM activities WHERE city_id = ? ORDER BY id",
            (city_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def activity_exists(activity_id: str) -> bool:
    with connect() as con:
        return con.execute("SELECT 1 FROM activities WHERE id = ?", (activity_id,)).fetchone() is not None


def available_activities(city_id: str, dates: list[str], travelers: int) -> list[dict]:
    """Activities with spots >= travelers on the given dates (feasibility pre-filter)."""
    placeholders = ",".join("?" * len(dates))
    with connect() as con:
        rows = con.execute(
            f"""SELECT a.id, a.name, a.category, a.base_price, av.date, av.spots_left
                FROM activities a JOIN activity_availability av ON av.activity_id = a.id
                WHERE a.city_id = ? AND av.date IN ({placeholders}) AND av.spots_left >= ?
                ORDER BY av.date, a.id""",
            (city_id, *dates, travelers),
        ).fetchall()
    return [dict(r) for r in rows]


def find_hotels(city_name: str, date_from: str, date_to: str, travelers: int = 1,
                tier: str | None = None, limit: int = 10) -> list[dict]:
    """Hotels with rooms free for EVERY night of [date_from, date_to) (checkout exclusive).

    Rooms needed = ceil(travelers / max_guests_per_room); total stay price is
    computed here in code, never by the LLM.
    """
    city = resolve_city(city_name)
    if city is None:
        raise ValueError(f"unknown city {city_name!r}")
    d_from, d_to = date.fromisoformat(date_from), date.fromisoformat(date_to)
    nights = (d_to - d_from).days
    if nights <= 0:
        raise ValueError("date_to must be after date_from (checkout day)")
    if not 1 <= travelers <= 8:
        raise ValueError("travelers must be 1-8")
    with connect() as con:
        rows = con.execute(
            """SELECT h.id, h.name, h.tier, h.max_guests_per_room,
                      COUNT(a.date) AS n_nights, SUM(a.price_night) AS sum_night,
                      MIN(a.rooms_left) AS min_rooms
               FROM hotels h JOIN hotel_availability a ON a.hotel_id = h.id
               WHERE h.city_id = ? AND a.date >= ? AND a.date < ?
                     AND (? IS NULL OR h.tier = ?)
               GROUP BY h.id
               HAVING COUNT(a.date) = ?""",
            (city["id"], date_from, date_to, tier, tier, nights),
        ).fetchall()
    options = []
    for r in rows:
        rooms_needed = math.ceil(travelers / r["max_guests_per_room"])
        if r["min_rooms"] < rooms_needed:
            continue  # sold out on at least one night for this party size
        options.append({
            "hotel_id": r["id"], "name": r["name"], "tier": r["tier"],
            "max_guests_per_room": r["max_guests_per_room"],
            "rooms_needed": rooms_needed, "nights": nights,
            "total_stay_price": round(r["sum_night"] * rooms_needed, 2),
            "avg_price_per_room_night": round(r["sum_night"] / nights, 2),
        })
    options.sort(key=lambda o: o["total_stay_price"])
    return options[:limit]
