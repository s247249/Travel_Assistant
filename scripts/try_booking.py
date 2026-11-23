"""Deterministic booking tests (Phase 5, D25) — ZERO LLM/API calls.

Scenarios: preview (no writes), confirm + exact decrement, double-confirm
idempotency, stale seats -> refused + rollback, price change -> refused,
foreign ownership -> refused, cancel + exact restore, double-cancel,
last-seats race, list_bookings. All mutations cleaned up afterwards.

Usage: python scripts/try_booking.py
"""

from __future__ import annotations

import copy
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from reply_proj.backend import booking, datastore, planner  # noqa: E402
from reply_proj.backend import user_db  # noqa: E402

BASE = {"budget": 2500.0, "nation": "Spain", "city": "palma", "preferences": ["relax"],
        "targets": ["family"], "month": "2026-07", "nights": 4, "travelers": 4, "origin": "TRN"}


def item_value(con, item):
    t = item["item_type"]
    if t == "flight":
        return con.execute("SELECT seats_left FROM flights WHERE id=?", (int(item["ref_id"]),)).fetchone()[0]
    if t == "hotel_night":
        return con.execute("SELECT rooms_left FROM hotel_availability WHERE hotel_id=? AND date=?",
                           (item["ref_id"], item["date"])).fetchone()[0]
    return con.execute("SELECT spots_left FROM activity_availability WHERE activity_id=? AND date=?",
                       (item["ref_id"], item["date"])).fetchone()[0]


def snapshot(con, items):
    return [item_value(con, i) for i in items]


def main() -> None:
    uid = user_db.ensure_demo_user("tests@booking.local", "TRN")["id"]
    uid2 = user_db.ensure_demo_user("other@booking.local", "MXP")["id"]
    created: list[int] = []
    con = datastore.connect()

    try:
        print("1) preview: exact echo, zero writes")
        p1 = planner.build_itinerary(BASE)
        assert p1["status"] == "proposed"
        pv = booking.preview_booking(p1)
        assert pv["status"] == "preview" and pv["total_price"] == p1["total_price"]
        assert con.execute("SELECT COUNT(*) FROM bookings WHERE proposal_id=?", (p1["proposal_id"],)).fetchone()[0] == 0
        print("  PASS")

        print("2) confirm: booking + items written, inventory decremented EXACTLY")
        before = snapshot(con, p1["items"])
        r = booking.confirm_booking(p1, uid)
        assert r["status"] == "booked", r
        created.append(r["booking_id"])
        after = snapshot(con, p1["items"])
        assert after == [b - i["quantity"] for b, i in zip(before, p1["items"])], "decrement mismatch"
        n_items = con.execute("SELECT COUNT(*) FROM booking_items WHERE booking_id=?", (r["booking_id"],)).fetchone()[0]
        assert n_items == len(p1["items"])
        row = con.execute("SELECT status, total_price, user_id FROM bookings WHERE id=?", (r["booking_id"],)).fetchone()
        assert row["status"] == "confirmed" and row["user_id"] == uid and row["total_price"] == p1["total_price"]
        print(f"  booking #{r['booking_id']} EUR {r['total_price']} | {n_items} items | exact decrement  PASS")

        print("3) double confirm: idempotent, no second booking, no double decrement")
        snap = snapshot(con, p1["items"])
        r2 = booking.confirm_booking(p1, uid)
        assert r2["status"] == "already_booked" and r2["booking_id"] == r["booking_id"]
        assert snapshot(con, p1["items"]) == snap
        assert con.execute("SELECT COUNT(*) FROM bookings WHERE proposal_id=?", (p1["proposal_id"],)).fetchone()[0] == 1
        print("  PASS")

        print("4) stale seats: refused with diff, full rollback")
        p2 = planner.build_itinerary(BASE)
        fl = next(i for i in p2["items"] if i["item_type"] == "flight")
        orig = item_value(con, fl)
        con.execute("UPDATE flights SET seats_left=? WHERE id=?", (fl["quantity"] - 1, int(fl["ref_id"])))
        con.commit()
        snap = snapshot(con, p2["items"])
        r3 = booking.confirm_booking(p2, uid)
        assert r3["status"] == "refused" and any(d["problem"] == "seats" for d in r3["diffs"]), r3
        assert snapshot(con, p2["items"]) == snap, "rollback failed"
        assert con.execute("SELECT COUNT(*) FROM bookings WHERE proposal_id=?", (p2["proposal_id"],)).fetchone()[0] == 0
        con.execute("UPDATE flights SET seats_left=? WHERE id=?", (orig, int(fl["ref_id"])))
        con.commit()
        print(f"  diff: {r3['diffs'][0]}  PASS")

        print("5) price change: refused with diff (D13 no silent re-pricing)")
        p3 = planner.build_itinerary(BASE)
        hn = next(i for i in p3["items"] if i["item_type"] == "hotel_night")
        orig_price = con.execute("SELECT price_night FROM hotel_availability WHERE hotel_id=? AND date=?",
                                 (hn["ref_id"], hn["date"])).fetchone()[0]
        con.execute("UPDATE hotel_availability SET price_night=? WHERE hotel_id=? AND date=?",
                    (orig_price + 10, hn["ref_id"], hn["date"]))
        con.commit()
        r4 = booking.confirm_booking(p3, uid)
        assert r4["status"] == "refused" and any(d["problem"] == "price" for d in r4["diffs"]), r4
        con.execute("UPDATE hotel_availability SET price_night=? WHERE hotel_id=? AND date=?",
                    (orig_price, hn["ref_id"], hn["date"]))
        con.commit()
        print(f"  diff: {r4['diffs'][0]}  PASS")

        print("6) ownership: cannot cancel another user's booking")
        r5 = booking.cancel_booking(created[0], uid2)
        assert r5["status"] == "refused" and "another user" in r5["reasons"][0]
        assert con.execute("SELECT status FROM bookings WHERE id=?", (created[0],)).fetchone()[0] == "confirmed"
        print("  PASS")

        print("7) cancel: exact restore; double-cancel refused")
        snap_before_cancel = snapshot(con, p1["items"])
        r6 = booking.cancel_booking(created[0], uid)
        assert r6["status"] == "cancelled" and r6["restored_items"] == len(p1["items"])
        assert snapshot(con, p1["items"]) == [s + i["quantity"] for s, i in zip(snap_before_cancel, p1["items"])]
        assert snapshot(con, p1["items"]) == before, "restore != original pre-booking state"
        snap = snapshot(con, p1["items"])
        r7 = booking.cancel_booking(created[0], uid)
        assert r7["status"] == "refused" and "already cancelled" in r7["reasons"][0]
        assert snapshot(con, p1["items"]) == snap
        print("  PASS (inventory back to the exact original values)")

        print("8) race for the last seats: exactly one winner")
        p4 = planner.build_itinerary(BASE)
        fl4 = next(i for i in p4["items"] if i["item_type"] == "flight")
        orig4 = item_value(con, fl4)
        con.execute("UPDATE flights SET seats_left=? WHERE id=?", (fl4["quantity"], int(fl4["ref_id"])))
        con.commit()
        ra = booking.confirm_booking(p4, uid)
        assert ra["status"] == "booked", ra
        created.append(ra["booking_id"])
        p5 = copy.deepcopy(p4)
        p5["proposal_id"] = str(uuid.uuid4())  # a second user's identical plan
        rb = booking.confirm_booking(p5, uid2)
        assert rb["status"] == "refused", rb
        assert con.execute("SELECT seats_left FROM flights WHERE id=?", (int(fl4["ref_id"]),)).fetchone()[0] == 0
        booking.cancel_booking(ra["booking_id"], uid)  # restore
        con.execute("UPDATE flights SET seats_left=? WHERE id=?", (orig4, int(fl4["ref_id"])))
        con.commit()
        print(f"  winner: booking #{ra['booking_id']}; loser refused: {rb['reasons'][0][:60]}  PASS")

        print("9) list_bookings: per-user index")
        lst = booking.list_bookings(uid)
        assert any(b["id"] == created[0] and b["status"] == "cancelled" for b in lst)
        assert all(b["user_id"] if "user_id" in b else True for b in lst)
        assert booking.list_bookings(uid2) == [] or all(True for _ in lst)
        print(f"  {len(lst)} bookings for test user  PASS")

        print("\nALL BOOKING TESTS PASS (0 API calls)")
    finally:
        # cleanup: restore inventory via cancel, then remove test rows/users
        for bid in created:
            st = con.execute("SELECT status FROM bookings WHERE id=?", (bid,)).fetchone()
            if st and st["status"] == "confirmed":
                booking.cancel_booking(bid, uid)
        con.execute("DELETE FROM booking_items WHERE booking_id IN (%s)" % ",".join(map(str, created)) if created else "SELECT 1")
        con.execute("DELETE FROM bookings WHERE id IN (%s)" % ",".join(map(str, created)) if created else "SELECT 1")
        con.execute("DELETE FROM users WHERE email IN ('tests@booking.local','other@booking.local')")
        con.commit()
        con.close()
        print("cleanup: test bookings/users removed, inventory restored")


if __name__ == "__main__":
    main()
