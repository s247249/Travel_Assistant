"""Deterministic API tests (Phase 6, D26) — FastAPI TestClient, ZERO LLM calls.

Covers: register/login/logout lifecycle, validation (422), duplicate email (409),
wrong password (401), ownership 404s across users, conversations CRUD + history,
the code-only book-button path with a deterministically seeded proposal (no LLM),
bookings list/detail/cancel via HTTP. Idempotent: pre-clean + finally-clean.

Usage: python scripts/try_api.py [--live]   (--live adds one real chat smoke call)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from fastapi.testclient import TestClient  # noqa: E402

from reply_proj.backend import booking, datastore, planner  # noqa: E402
from reply_proj.backend.main import app  # noqa: E402

BASE = {"budget": 2500.0, "nation": "Spain", "city": "palma", "preferences": ["relax"],
        "targets": ["family"], "month": "2026-07", "nights": 4, "travelers": 4, "origin": "TRN"}
ALICE = {"email": "alice@example.com", "password": "password123", "name": "Alice", "home_airport": "TRN"}
BOB = {"email": "bob@example.com", "password": "password456", "name": "Bob", "home_airport": "MXP"}


def cleanup_test_users() -> None:
    """Remove test users and their artifacts; restore inventory from leftover bookings."""
    con = datastore.connect()
    try:
        for email in (ALICE["email"], BOB["email"]):
            row = con.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if row is None:
                continue
            uid = row["id"]
            for b in con.execute("SELECT id, status FROM bookings WHERE user_id=?", (uid,)).fetchall():
                if b["status"] == "confirmed":
                    booking.cancel_booking(b["id"], uid)  # exact inventory restore
            con.execute("DELETE FROM booking_items WHERE booking_id IN (SELECT id FROM bookings WHERE user_id=?)", (uid,))
            con.execute("DELETE FROM bookings WHERE user_id=?", (uid,))
            con.execute("DELETE FROM conversations WHERE user_id=?", (uid,))
            con.execute("DELETE FROM users WHERE id=?", (uid,))
        con.commit()
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="one real LLM chat smoke call")
    args = parser.parse_args()

    cleanup_test_users()  # idempotent: survive leftovers from crashed runs
    try:
        with TestClient(app) as client:
            print("1) register alice: 201 + auto-login")
            r = client.post("/api/users", json=ALICE)
            assert r.status_code == 201, r.text
            alice_id = r.json()["id"]
            assert client.get("/api/sessions/current").json()["email"] == ALICE["email"]
            print("  PASS")

            print("2) validation: weak password 422, bad airport 422, duplicate email 409")
            assert client.post("/api/users", json={**ALICE, "password": "short"}).status_code == 422
            assert client.post("/api/users", json={**ALICE, "email": "x@example.com", "home_airport": "XXX"}).status_code == 422
            assert client.post("/api/users", json=ALICE).status_code == 409
            print("  PASS")

            print("3) logout -> 401; wrong password -> 401; login -> 201")
            assert client.delete("/api/sessions/current").status_code == 204
            assert client.get("/api/sessions/current").status_code == 401
            assert client.post("/api/sessions", json={**ALICE, "password": "wrong"}).status_code == 401
            r = client.post("/api/sessions", json={"email": ALICE["email"], "password": ALICE["password"]})
            assert r.status_code == 201
            print("  PASS")

            print("4) conversations: create, list, empty history")
            r = client.post("/api/conversations")
            assert r.status_code == 201
            tid = r.json()["id"]
            assert any(c["id"] == tid for c in client.get("/api/conversations").json())
            h = client.get(f"/api/conversations/{tid}/messages").json()
            assert h["messages"] == [] and h["proposal"] is None
            print("  PASS")

            print("5) book-button path: seed proposal deterministically (no LLM), book via HTTP")
            graph = client.app.state.graph
            cfg = {"configurable": {"thread_id": tid}}
            p = planner.build_itinerary(BASE)
            assert p["status"] == "proposed"
            graph.update_state(cfg, {"messages": [], "slots": BASE, "proposal": p,
                                     "revisions": {"exclude_activity_ids": [], "pins": {}},
                                     "user_id": alice_id}, as_node="tools")
            r = client.post(f"/api/conversations/{tid}/book")
            assert r.status_code == 201 and r.json()["status"] == "booked", r.text
            bid = r.json()["booking_id"]
            assert client.post(f"/api/conversations/{tid}/book").status_code == 409  # proposal consumed
            print(f"  booking #{bid} via button path  PASS")

            print("6) bookings via HTTP: list, detail with items")
            lst = client.get("/api/bookings").json()
            assert any(b["id"] == bid for b in lst)
            detail = client.get(f"/api/bookings/{bid}").json()
            assert len(detail["items"]) == len(p["items"])
            print("  PASS")

            print("7) ownership: bob cannot see alice's thread or booking")
            client.delete("/api/sessions/current")
            r = client.post("/api/users", json=BOB)
            assert r.status_code == 201
            assert client.get(f"/api/conversations/{tid}/messages").status_code == 404
            assert client.post(f"/api/conversations/{tid}/chat", json={"message": "hi"}).status_code == 404
            assert client.get(f"/api/bookings/{bid}").status_code == 404
            assert client.post(f"/api/bookings/{bid}/cancel").status_code == 409
            assert client.get("/api/bookings").json() == []
            print("  PASS")

            print("8) cancel via HTTP as owner: inventory restored")
            client.delete("/api/sessions/current")
            client.post("/api/sessions", json={"email": ALICE["email"], "password": ALICE["password"]})
            con = datastore.connect()
            fl = next(i for i in p["items"] if i["item_type"] == "flight")
            seats_before = con.execute("SELECT seats_left FROM flights WHERE id=?", (int(fl["ref_id"]),)).fetchone()[0]
            con.close()
            r = client.post(f"/api/bookings/{bid}/cancel")
            assert r.status_code == 200 and r.json()["status"] == "cancelled"
            con = datastore.connect()
            seats_after = con.execute("SELECT seats_left FROM flights WHERE id=?", (int(fl["ref_id"]),)).fetchone()[0]
            con.close()
            assert seats_after == seats_before + fl["quantity"]
            assert client.post(f"/api/bookings/{bid}/cancel").status_code == 409  # double cancel
            print("  PASS")

            if args.live:
                print("9) LIVE chat smoke (1 LLM turn)")
                r = client.post(f"/api/conversations/{tid}/chat", json={"message": "Hello! What can you do?"})
                assert r.status_code == 200 and r.json()["reply"], r.text
                print(f"  reply: {r.json()['reply'][:100]}...  PASS")

            print("\nALL API TESTS PASS (0 LLM calls)" if not args.live else "\nALL API TESTS PASS (1 live call)")
    finally:
        cleanup_test_users()
        print("cleanup: test users/conversations/bookings removed, inventory restored")


if __name__ == "__main__":
    main()
