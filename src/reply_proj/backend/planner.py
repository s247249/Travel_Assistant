"""Deterministic itinerary builder (Phase 4, D24 — architecture A).

Pure code: no LLM, no embedding calls, no API key needed, no Chroma dependency.
Reads everything from SQL (datastore), including activity targets (authority =
generator, D28). Chroma is used only by the agent's semantic search, not here.

Algorithm (F2b): enumerate top-5 cheapest flight windows x top-3 hotels;
fill each calendar day with the best feasible activity (lexicographic:
category match, target overlap, cheaper price); keep complete plans within
budget; pick the best. Infeasible -> structured diagnosis (F5), never a
partial plan. Revision deltas (exclusions/pins) are honored and validated.
"""

from __future__ import annotations

import calendar
import uuid
from datetime import date, timedelta

from reply_proj.backend import datastore

MAX_WINDOWS = 5
MAX_HOTELS = 3


def _month_dates(month: str) -> list[date]:
    y, m = map(int, month.split("-"))
    return [date(y, m, d) for d in range(1, calendar.monthrange(y, m)[1] + 1)]


def _flight_windows(origin: str, dest_airport: str, month: str, nights: int,
                    travelers: int, start_override: str | None,
                    required_dates: set[str] | None = None) -> list[dict]:
    """Cheapest valid outbound/return pairs (seats >= party both ways), F1.

    required_dates (pin dates, D24/F6): windows MUST cover every pinned date,
    otherwise a pin could be silently sidestepped by a cheaper window.
    Filtering happens BEFORE the top-5 truncation.
    """
    dates = _month_dates(month)
    d0, d1 = dates[0].isoformat(), dates[-1].isoformat()
    outbound = datastore.flights_between(origin, dest_airport, d0, d1)
    inbound = datastore.flights_between(dest_airport, origin, d0, d1)

    def best_by_date(rows: list[dict]) -> dict[str, dict]:
        best: dict[str, dict] = {}
        for r in rows:
            if r["seats_left"] < travelers:
                continue
            cur = best.get(r["date"])
            if cur is None or (r["price"], r["depart_time"]) < (cur["price"], cur["depart_time"]):
                best[r["date"]] = r
        return best

    out_best, in_best = best_by_date(outbound), best_by_date(inbound)
    windows = []
    for d in dates:
        start = d.isoformat()
        end = (d + timedelta(days=nights)).isoformat()
        if start_override and start != start_override:
            continue
        o, i = out_best.get(start), in_best.get(end)
        if not o or not i:
            continue
        if required_dates:
            trip_days = {(d + timedelta(days=j)).isoformat() for j in range(nights + 1)}
            if not required_dates <= trip_days:
                continue
        windows.append({"start": start, "end": end, "out": o, "ret": i,
                        "flight_cost": round((o["price"] + i["price"]) * travelers, 2)})
    # stable two-pass sort: cost asc, earliest outbound, latest return (maximize time on site)
    windows.sort(key=lambda w: w["ret"]["depart_time"], reverse=True)
    windows.sort(key=lambda w: (w["flight_cost"], w["out"]["depart_time"]))
    return windows[:MAX_WINDOWS]


def _fill_days(city_id: str, trip_dates: list[date], travelers: int, prefs: set,
               party_targets: set, targets_map: dict, revisions: dict, remaining: float):
    """Greedy lexicographic fill, one activity per day (F3i). Returns (picks, cost, failure)."""
    rows = datastore.available_activities(city_id, [d.isoformat() for d in trip_dates], travelers)
    by_day: dict[str, list[dict]] = {}
    for r in rows:
        by_day.setdefault(r["date"], []).append(r)
    excluded = set(revisions.get("exclude_activity_ids", []))
    pins = revisions.get("pins", {})
    used: set[str] = set()
    picks, total = [], 0.0
    for d in trip_dates:
        iso = d.isoformat()
        cands = [r for r in by_day.get(iso, [])
                 if r["id"] not in excluded and r["base_price"] * travelers <= remaining + 1e-9]
        pin = pins.get(iso)
        if pin:
            cands = [r for r in cands if r["id"] == pin]
            if not cands:
                return None, 0.0, f"pinned activity {pin} not feasible on {iso} (sold out, excluded, or over budget)"
        fresh = [r for r in cands if r["id"] not in used]
        pool = fresh or cands  # prefer distinct; reuse allowed if trip outlasts catalog (D24)
        if not pool:
            return None, 0.0, f"no feasible activity on {iso} (availability/budget/exclusions)"
        best = max(pool, key=lambda r: (r["category"] in prefs,
                                        len(targets_map.get(r["id"], set()) & party_targets),
                                        -r["base_price"], r["id"]))
        cost = round(best["base_price"] * travelers, 2)
        picks.append({**best, "date": iso, "cost": cost})
        total += cost
        remaining -= cost
        used.add(best["id"])
    return picks, round(total, 2), None


def build_itinerary(slots: dict, revisions: dict | None = None, start_date: str | None = None) -> dict:
    """Main entry: proposal dict (status=proposed), or incomplete/infeasible/rejected diagnosis."""
    revisions = revisions or {"exclude_activity_ids": [], "pins": {}}
    missing = [k for k in ("budget", "nation", "preferences", "month") if not slots.get(k)]
    if not slots.get("city"):
        missing.append("city")
    if missing:
        return {"status": "incomplete", "missing": missing}
    city = datastore.resolve_city(slots["city"])
    if city is None:
        return {"status": "incomplete", "missing": ["city"], "reason": f"unknown city {slots['city']!r}"}

    travelers = int(slots.get("travelers", 1))
    nights = int(slots.get("nights", 4))
    budget = float(slots["budget"])
    prefs = set(slots["preferences"])
    party_targets = set(slots.get("targets") or [])
    origin = slots.get("origin")

    if start_date:
        try:
            date.fromisoformat(start_date)
        except ValueError:
            return {"status": "rejected", "reason": "start_date must be ISO YYYY-MM-DD"}
        if start_date[:7] != slots["month"]:
            return {"status": "rejected", "reason": f"start_date must be within {slots['month']}"}

    windows = _flight_windows(origin, city["airport_code"], slots["month"], nights, travelers,
                              start_date, set(revisions.get("pins", {})) or None)
    if not windows:
        reasons = [f"no flight pair {origin}<->{city['airport_code']} with >={travelers} seats "
                   f"for {nights} nights in {slots['month']}"
                   + (f" starting {start_date}" if start_date else "")]
        if revisions.get("pins"):
            reasons.append(f"no feasible window covers pinned date(s): {sorted(revisions['pins'])}")
        return {"status": "infeasible", "reasons": reasons,
                "suggestions": ["try another month", "fewer travelers", "another origin airport",
                                "move or remove the pinned day"]}

    targets_map = datastore.activity_targets(city["id"])
    combos = []
    for w in windows:
        for h in datastore.find_hotels(city["name"], w["start"], w["end"], travelers)[:MAX_HOTELS]:
            combos.append((w, h))
    if not combos:
        return {"status": "infeasible",
                "reasons": [f"no hotel in {city['name']} with rooms for {travelers} travelers on any candidate window"],
                "suggestions": ["fewer travelers", "another month", "another city"]}

    def trip_dates(w: dict) -> list[date]:
        s = date.fromisoformat(w["start"])
        return [s + timedelta(days=i) for i in range(nights + 1)]

    complete, failures = [], []
    for w, h in combos:
        skeleton = round(w["flight_cost"] + h["total_stay_price"], 2)
        remaining = budget - skeleton
        if remaining < 0:
            failures.append(f"flights+hotel EUR {skeleton:.2f} already over budget EUR {budget:.2f} ({w['start']}, {h['name']})")
            continue
        picks, act_total, reason = _fill_days(city["id"], trip_dates(w), travelers, prefs,
                                              party_targets, targets_map, revisions, remaining)
        if reason:
            failures.append(f"{w['start']} / {h['name']}: {reason}")
            continue
        total = round(skeleton + act_total, 2)
        cat = sum(p["category"] in prefs for p in picks)
        tov = sum(len(targets_map.get(p["id"], set()) & party_targets) for p in picks)
        complete.append({"w": w, "h": h, "picks": picks, "total": total, "score": (cat, tov, -total)})

    if not complete:
        # F5 diagnosis: cheapest COMPLETE plan ignoring budget, for a concrete suggestion
        min_total = None
        for w, h in combos:
            picks, act_total, reason = _fill_days(city["id"], trip_dates(w), travelers, prefs,
                                                  party_targets, targets_map, revisions, float("inf"))
            if not reason:
                t = round(w["flight_cost"] + h["total_stay_price"] + act_total, 2)
                min_total = t if min_total is None else min(min_total, t)
        cheapest_skeleton = min(round(w["flight_cost"] + h["total_stay_price"], 2) for w, h in combos)
        suggestions = []
        if min_total is not None:
            suggestions.append(f"raise budget to at least EUR {min_total:.0f} (cheapest complete plan)")
        suggestions += ["fewer nights", "another month (August is peak-priced)", f"another city in {slots['nation']}"]
        return {"status": "infeasible", "reasons": sorted(set(failures))[:6],
                "cheapest_skeleton_cost": cheapest_skeleton, "minimum_feasible_total": min_total,
                "suggestions": suggestions}

    best = max(complete, key=lambda c: (c["score"], c["w"]["start"], c["h"]["hotel_id"]))
    return _proposal(slots, city, best, travelers, nights, budget)


def _proposal(slots: dict, city: dict, best: dict, travelers: int, nights: int, budget: float) -> dict:
    """Emit the proposal; items mirror booking_items exactly (S1/D13)."""
    w, h, picks = best["w"], best["h"], best["picks"]
    items = []
    for leg in (w["out"], w["ret"]):
        items.append({"item_type": "flight", "ref_id": str(leg["id"]), "date": leg["date"],
                      "quantity": travelers, "unit_price": leg["price"],
                      "subtotal": round(leg["price"] * travelers, 2),
                      "details": {"from": leg["from_code"], "to": leg["to_code"], "depart_time": leg["depart_time"]}})
    rooms = h["rooms_needed"]
    for night in datastore.hotel_nights(h["hotel_id"], w["start"], w["end"]):
        assert night["rooms_left"] >= rooms, "hotel availability changed mid-build"
        items.append({"item_type": "hotel_night", "ref_id": h["hotel_id"], "date": night["date"],
                      "quantity": rooms, "unit_price": night["price_night"],
                      "subtotal": round(night["price_night"] * rooms, 2)})
    for p in picks:
        items.append({"item_type": "activity", "ref_id": p["id"], "date": p["date"],
                      "quantity": travelers, "unit_price": p["base_price"], "subtotal": p["cost"],
                      "details": {"name": p["name"], "category": p["category"]}})
    total = round(sum(i["subtotal"] for i in items), 2)
    assert total <= budget + 1e-9, "budget guarantee violated"  # by construction, never by hope
    return {"status": "proposed", "proposal_id": str(uuid.uuid4()),
            "city_id": city["id"], "city_name": city["name"], "origin": slots["origin"],
            "start_date": w["start"], "end_date": w["end"], "n_travelers": travelers, "nights": nights,
            "hotel": {"hotel_id": h["hotel_id"], "name": h["name"], "tier": h["tier"], "rooms_needed": rooms},
            "items": items, "total_price": total, "budget": budget, "margin": round(budget - total, 2),
            "day_summary": [{"date": p["date"], "activity_id": p["id"], "name": p["name"], "category": p["category"]}
                            for p in picks]}


def proposal_summary(p: dict) -> dict:
    """Compact view for the LLM context and tool results (IDs included for revision deltas)."""
    return {"proposal_id": p["proposal_id"], "status": p.get("status", "proposed"),
            "booking_id": p.get("booking_id"), "city": p["city_name"],
            "start": p["start_date"], "end": p["end_date"], "travelers": p["n_travelers"],
            "hotel": p["hotel"],
            "flights": [{"date": i["date"], **i["details"]} for i in p["items"] if i["item_type"] == "flight"],
            "days": p["day_summary"], "total_price": p["total_price"],
            "budget": p["budget"], "margin": p["margin"]}
