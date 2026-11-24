"""Booking service (Phase 5, D25; guarantees from D13/D9/S1).

Pure code, no LLM, quota-free testable.
- preview_booking: exact echo of what will be booked (B1 a+ default path).
- confirm_booking: ONE transaction — re-validate live inventory/prices (D13),
  guarded decrements (D9, race-safe), write bookings + booking_items (S1),
  idempotent via proposal_id UNIQUE. Any failure -> full rollback + structured diff.
- cancel_booking: whole-booking only (B3), ownership-checked, exact restore,
  idempotent (no double restore).
- list_bookings: per-user index for chat + dashboard.

user_id always comes from the authenticated state, never from LLM arguments.
"""

from __future__ import annotations

import sqlite3

from reply_proj.backend import datastore, planner

PRICE_TOL = 1e-6


def preview_booking(proposal: dict) -> dict:
    summary = planner.proposal_summary(proposal)
    return {**summary, "status": "preview",
            "instruction": "Show this exact preview to the user and ask for explicit confirmation. "
                           "Only then call book_itinerary(confirmed_by_user=true)."}


def _item_checks(con, item: dict) -> list[dict]:
    """Live re-validation of one proposal item (D13). Returns diffs."""
    t, ref, date, qty, price = (item["item_type"], item["ref_id"], item["date"],
                                item["quantity"], item["unit_price"])
    diffs = []
    if t == "flight":
        r = con.execute("SELECT seats_left, price FROM flights WHERE id=?", (int(ref),)).fetchone()
        if r is None:
            return [{"item": f"flight {ref}", "problem": "no longer exists"}]
        if r["seats_left"] < qty:
            diffs.append({"item": f"flight {ref} on {date}", "problem": "seats",
                          "needed": qty, "available": r["seats_left"]})
        if abs(r["price"] - price) > PRICE_TOL:
            diffs.append({"item": f"flight {ref} on {date}", "problem": "price",
                          "proposed": price, "current": r["price"]})
    elif t == "hotel_night":
        r = con.execute("SELECT rooms_left, price_night FROM hotel_availability "
                        "WHERE hotel_id=? AND date=?", (ref, date)).fetchone()
        if r is None:
            return [{"item": f"hotel {ref} on {date}", "problem": "no longer exists"}]
        if r["rooms_left"] < qty:
            diffs.append({"item": f"hotel {ref} on {date}", "problem": "rooms",
                          "needed": qty, "available": r["rooms_left"]})
        if abs(r["price_night"] - price) > PRICE_TOL:
            diffs.append({"item": f"hotel {ref} on {date}", "problem": "price",
                          "proposed": price, "current": r["price_night"]})
    elif t == "activity":
        r = con.execute("SELECT spots_left FROM activity_availability "
                        "WHERE activity_id=? AND date=?", (ref, date)).fetchone()
        a = con.execute("SELECT base_price FROM activities WHERE id=?", (ref,)).fetchone()
        if r is None or a is None:
            return [{"item": f"activity {ref} on {date}", "problem": "no longer exists"}]
        if r["spots_left"] < qty:
            diffs.append({"item": f"activity {ref} on {date}", "problem": "spots",
                          "needed": qty, "available": r["spots_left"]})
        if abs(a["base_price"] - price) > PRICE_TOL:
            diffs.append({"item": f"activity {ref} on {date}", "problem": "price",
                          "proposed": price, "current": a["base_price"]})
    return diffs


def _decrement(con, item: dict) -> bool:
    """Guarded decrement (D9): rowcount 1 = success; 0 = lost a race -> rollback."""
    t, ref, date, qty = item["item_type"], item["ref_id"], item["date"], item["quantity"]
    if t == "flight":
        cur = con.execute("UPDATE flights SET seats_left=seats_left-? WHERE id=? AND seats_left>=?",
                          (qty, int(ref), qty))
    elif t == "hotel_night":
        cur = con.execute("UPDATE hotel_availability SET rooms_left=rooms_left-? "
                          "WHERE hotel_id=? AND date=? AND rooms_left>=?", (qty, ref, date, qty))
    else:
        cur = con.execute("UPDATE activity_availability SET spots_left=spots_left-? "
                          "WHERE activity_id=? AND date=? AND spots_left>=?", (qty, ref, date, qty))
    return cur.rowcount == 1


def confirm_booking(proposal: dict, user_id: int) -> dict:
    if not proposal or proposal.get("status") != "proposed":
        return {"status": "refused", "reasons": ["no active proposal to book"]}
    con = datastore.connect()
    con.isolation_level = None  # manual transaction control
    try:
        con.execute("BEGIN IMMEDIATE")  # take the write lock upfront: race-safe
        existing = con.execute("SELECT id FROM bookings WHERE proposal_id=?",
                               (proposal["proposal_id"],)).fetchone()
        if existing:
            con.execute("ROLLBACK")
            return {"status": "already_booked", "booking_id": existing["id"],
                    "note": "this proposal was already booked — no second booking created"}

        diffs = []
        for item in proposal["items"]:
            diffs.extend(_item_checks(con, item))
        total = round(sum(i["subtotal"] for i in proposal["items"]), 2)
        if abs(total - proposal["total_price"]) > 0.01:
            diffs.append({"item": "total", "problem": "arithmetic mismatch",
                          "proposed": proposal["total_price"], "current": total})
        if diffs:
            con.execute("ROLLBACK")
            return {"status": "refused",
                    "reasons": ["proposal no longer valid against live inventory/prices (D13)"],
                    "diffs": diffs,
                    "next_step": "explain the differences, rebuild the itinerary, obtain FRESH confirmation"}

        for item in proposal["items"]:
            if not _decrement(con, item):
                con.execute("ROLLBACK")
                return {"status": "refused",
                        "reasons": [f"concurrent booking took {item['item_type']} "
                                    f"{item['ref_id']} on {item['date']} — nothing was booked"],
                        "next_step": "rebuild the itinerary and obtain fresh confirmation"}

        cur = con.execute(
            "INSERT INTO bookings (user_id, proposal_id, status, city_id, origin_airport, "
            "start_date, end_date, n_travelers, total_price) VALUES (?,?,?,?,?,?,?,?,?)",
            (user_id, proposal["proposal_id"], "confirmed", proposal["city_id"],
             proposal["origin"], proposal["start_date"], proposal["end_date"],
             proposal["n_travelers"], total))
        booking_id = cur.lastrowid
        con.executemany(
            "INSERT INTO booking_items (booking_id, item_type, ref_id, date, quantity, unit_price, subtotal) "
            "VALUES (?,?,?,?,?,?,?)",
            [(booking_id, i["item_type"], i["ref_id"], i["date"], i["quantity"],
              i["unit_price"], i["subtotal"]) for i in proposal["items"]])
        con.execute("COMMIT")
        return {"status": "booked", "booking_id": booking_id, "total_price": total,
                "proposal_id": proposal["proposal_id"]}
    except sqlite3.IntegrityError as e:
        con.execute("ROLLBACK")
        if "proposal_id" in str(e):  # UNIQUE race: another process booked it first
            row = con.execute("SELECT id FROM bookings WHERE proposal_id=?",
                              (proposal["proposal_id"],)).fetchone()
            return {"status": "already_booked", "booking_id": row["id"] if row else None}
        return {"status": "refused", "reasons": [str(e)]}
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def cancel_booking(booking_id: int, user_id: int) -> dict:
    """Whole-booking cancellation (B3): ownership check, exact restore, idempotent."""
    con = datastore.connect()
    con.isolation_level = None
    try:
        con.execute("BEGIN IMMEDIATE")
        b = con.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()
        if b is None:
            con.execute("ROLLBACK")
            return {"status": "refused", "reasons": ["booking not found"]}
        if b["user_id"] != user_id:
            con.execute("ROLLBACK")
            return {"status": "refused", "reasons": ["this booking belongs to another user"]}
        if b["status"] != "confirmed":
            con.execute("ROLLBACK")
            return {"status": "refused", "reasons": [f"booking is already {b['status']}"]}
        items = con.execute("SELECT * FROM booking_items WHERE booking_id=?", (booking_id,)).fetchall()
        for i in items:
            t, ref, date, qty = i["item_type"], i["ref_id"], i["date"], i["quantity"]
            if t == "flight":
                cur = con.execute("UPDATE flights SET seats_left=seats_left+? WHERE id=?", (qty, int(ref)))
            elif t == "hotel_night":
                cur = con.execute("UPDATE hotel_availability SET rooms_left=rooms_left+? "
                                  "WHERE hotel_id=? AND date=?", (qty, ref, date))
            else:
                cur = con.execute("UPDATE activity_availability SET spots_left=spots_left+? "
                                  "WHERE activity_id=? AND date=?", (qty, ref, date))
            if cur.rowcount != 1:
                con.execute("ROLLBACK")
                return {"status": "refused", "reasons": [f"cannot restore {t} {ref} (inventory row missing)"]}
        con.execute("UPDATE bookings SET status='cancelled' WHERE id=? AND status='confirmed'", (booking_id,))
        con.execute("COMMIT")
        return {"status": "cancelled", "booking_id": booking_id, "restored_items": len(items)}
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def list_bookings(user_id: int) -> list[dict]:
    con = datastore.connect()
    try:
        rows = con.execute(
            "SELECT b.id, b.status, b.city_id, c.name AS city_name, b.origin_airport, "
            "b.start_date, b.end_date, b.n_travelers, b.total_price, b.created_at "
            "FROM bookings b JOIN cities c ON c.id = b.city_id "
            "WHERE b.user_id=? ORDER BY b.id DESC", (user_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def get_booking(booking_id: int, user_id: int) -> dict | None:
    """Booking + items, ownership-scoped (None if missing or not yours)."""
    con = datastore.connect()
    try:
        b = con.execute(
            "SELECT b.*, c.name AS city_name FROM bookings b JOIN cities c ON c.id = b.city_id "
            "WHERE b.id=? AND b.user_id=?", (booking_id, user_id)).fetchone()
        if b is None:
            return None
        items = con.execute("SELECT * FROM booking_items WHERE booking_id=? ORDER BY id",
                            (booking_id,)).fetchall()
        return {**dict(b), "items": [dict(i) for i in items]}
    finally:
        con.close()
