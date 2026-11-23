"""User persistence.

Phase 6 adds real registration/authentication (password hashing, sessions).
For now only a dev helper so the CLI chat can run with a real users row
(bookings in Phase 5 will reference it via foreign key).
"""

from __future__ import annotations

from reply_proj.backend import datastore


def ensure_demo_user(email: str = "demo@travel.local", home_airport: str = "TRN") -> dict:
    """Idempotently create/fetch a demo user. NOT real auth — replaced in Phase 6."""
    con = datastore.connect()
    try:
        row = con.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if row is None:
            con.execute(
                "INSERT INTO users (email, password_hash, name, home_airport) VALUES (?, ?, ?, ?)",
                (email, "demo-placeholder-not-a-real-hash", "Demo User", home_airport),
            )
            con.commit()
            row = con.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return dict(row)
    finally:
        con.close()
