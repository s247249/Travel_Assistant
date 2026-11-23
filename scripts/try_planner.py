"""Deterministic planner tests (D24) — ZERO LLM/API calls, quota-free.

Scenarios: happy path + constraint re-verification against the DB, tight budget
diagnosis, exclusion rebuild (determinism: untouched days stay), pin honoring,
incomplete guard.

Usage: python scripts/try_planner.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from reply_proj.backend import datastore, planner  # noqa: E402

BASE = {"budget": 2500.0, "nation": "Spain", "city": "palma", "preferences": ["relax"],
        "targets": ["family"], "month": "2026-07", "nights": 4, "travelers": 4, "origin": "TRN"}


def verify_constraints(p: dict, slots: dict) -> None:
    """Re-check every guarantee directly against the database."""
    assert p["status"] == "proposed"
    assert p["total_price"] <= slots["budget"] + 1e-9, "over budget"
    items = p["items"]
    flights = [i for i in items if i["item_type"] == "flight"]
    hotels = [i for i in items if i["item_type"] == "hotel_night"]
    acts = [i for i in items if i["item_type"] == "activity"]
    assert len(flights) == 2, "need outbound + return"
    assert len(hotels) == slots["nights"], "hotel for every night"
    assert len(acts) == slots["nights"] + 1, "activity for every calendar day"
    assert round(sum(i["subtotal"] for i in items), 2) == p["total_price"], "arithmetic"
    con = datastore.connect()
    try:
        for i in flights:
            seats = con.execute("SELECT seats_left FROM flights WHERE id=?", (int(i["ref_id"]),)).fetchone()[0]
            assert seats >= i["quantity"], f"flight {i['ref_id']} seats"
        for i in hotels:
            rooms = con.execute("SELECT rooms_left FROM hotel_availability WHERE hotel_id=? AND date=?",
                                (i["ref_id"], i["date"])).fetchone()[0]
            assert rooms >= i["quantity"], f"hotel {i['ref_id']} rooms on {i['date']}"
        for i in acts:
            spots = con.execute("SELECT spots_left FROM activity_availability WHERE activity_id=? AND date=?",
                                (i["ref_id"], i["date"])).fetchone()[0]
            assert spots >= i["quantity"], f"activity {i['ref_id']} spots on {i['date']}"
    finally:
        con.close()


def show(p: dict) -> None:
    s = planner.proposal_summary(p)
    print(f"  {s['city']} {s['start']}..{s['end']} | hotel: {s['hotel']['name']} ({s['hotel']['rooms_needed']} room(s))")
    for d in s["days"]:
        print(f"    {d['date']}  {d['name']} [{d['category']}]")
    print(f"  total EUR {s['total_price']} / budget {s['budget']} -> margin {s['margin']}")


def main() -> None:
    print("1) happy path: family of 4, Palma, relax, July, EUR 2500, 4 nights from TRN")
    p1 = planner.build_itinerary(BASE)
    assert p1["status"] == "proposed", p1
    verify_constraints(p1, BASE)
    show(p1)
    print("  PASS (all constraints re-verified against DB)")

    print("\n2) tight budget: EUR 900 -> diagnosis, never a partial plan")
    p2 = planner.build_itinerary({**BASE, "budget": 900.0})
    assert p2["status"] == "infeasible", p2
    print(f"  reasons: {p2['reasons'][:2]}")
    print(f"  cheapest skeleton: {p2['cheapest_skeleton_cost']} | min feasible total: {p2['minimum_feasible_total']}")
    print(f"  suggestions: {p2['suggestions']}")
    assert p2["minimum_feasible_total"] is None or p2["minimum_feasible_total"] > 900
    print("  PASS")

    print("\n3) exclusion rebuild: drop day-2 activity; untouched days must stay (determinism)")
    day2 = p1["day_summary"][1]
    p3 = planner.build_itinerary(BASE, {"exclude_activity_ids": [day2["activity_id"]], "pins": {}})
    assert p3["status"] == "proposed", p3
    verify_constraints(p3, BASE)
    assert p3["day_summary"][1]["activity_id"] != day2["activity_id"], "exclusion ignored"
    assert p3["day_summary"][0] == p1["day_summary"][0], "day 1 changed"
    assert p3["start_date"] == p1["start_date"] and p3["hotel"] == p1["hotel"], "skeleton changed"
    print(f"  day 2: {day2['name']} -> {p3['day_summary'][1]['name']}")
    print("  PASS (day 1, flights, hotel identical)")

    print("\n4) pin: force a specific activity on day 3")
    day3 = p1["day_summary"][2]
    alts = datastore.available_activities("palma", [day3["date"]], BASE["travelers"])
    alt = next(r for r in alts if r["id"] != day3["activity_id"])
    p4 = planner.build_itinerary(BASE, {"exclude_activity_ids": [], "pins": {day3["date"]: alt["id"]}})
    assert p4["status"] == "proposed", p4
    verify_constraints(p4, BASE)
    assert p4["day_summary"][2]["activity_id"] == alt["id"], "pin ignored"
    print(f"  day 3 pinned to: {alt['name']}")
    print("  PASS")

    print("\n5) guard: missing city -> incomplete, no build")
    p5 = planner.build_itinerary({k: v for k, v in BASE.items() if k != "city"})
    assert p5["status"] == "incomplete" and "city" in p5["missing"]
    print(f"  missing: {p5['missing']}  PASS")

    print("\n6) pin outside the cheapest window: window selection MUST honor the pin (regression)")
    con = datastore.connect()
    pin_date = con.execute(
        "SELECT date FROM activity_availability WHERE activity_id='activity_palma_011' "
        "AND date LIKE '2026-07%' AND spots_left >= 4 "
        "AND date NOT BETWEEN '2026-07-14' AND '2026-07-18' ORDER BY date LIMIT 1").fetchone()["date"]
    con.close()
    p6 = planner.build_itinerary(BASE, {"exclude_activity_ids": [], "pins": {pin_date: "activity_palma_011"}})
    assert p6["status"] == "proposed", p6
    verify_constraints(p6, BASE)
    days = {d["date"]: d["activity_id"] for d in p6["day_summary"]}
    assert pin_date in days, "pin date not in trip"
    assert days[pin_date] == "activity_palma_011", "pin not honored"
    print(f"  window {p6['start_date']}..{p6['end_date']} covers pin; {pin_date} = Formentor  PASS")

    print("\n7) infeasible pin (sold out for the party) -> explicit diagnosis, never silent drop")
    con = datastore.connect()
    row = con.execute(
        "SELECT av.activity_id, av.date FROM activity_availability av "
        "JOIN activities a ON a.id = av.activity_id "
        "WHERE a.city_id='palma' AND av.spots_left < 4 AND av.date LIKE '2026-07%' LIMIT 1").fetchone()
    con.close()
    assert row, "test needs a sold-out July date in Palma"
    p7 = planner.build_itinerary(BASE, {"exclude_activity_ids": [], "pins": {row["date"]: row["activity_id"]}})
    assert p7["status"] == "infeasible", p7
    assert any("pin" in r.lower() for r in p7["reasons"]), p7["reasons"]
    print(f"  pinned {row['activity_id']} on {row['date']} (spots<4) -> refused: {p7['reasons'][0][:80]}  PASS")

    print("\nALL PLANNER TESTS PASS (0 API calls)")


if __name__ == "__main__":
    main()
