"""User persistence & authentication (Phase 6, D26).

Passwords: Argon2 via pwdlib. Auth CONTEXT lives in the signed cookie
(SessionMiddleware) — stateless validation, no server session table.
This module handles only the users resource.

ensure_demo_user remains a CLI dev helper (placeholder hash, cannot log in via API).
"""

from __future__ import annotations

import sqlite3

from pwdlib import PasswordHash

from reply_proj.backend import datastore

_hasher = PasswordHash.recommended()  # argon2id


class DuplicateEmailError(Exception):
    pass


def _sanitize(row) -> dict:
    return {k: row[k] for k in ("id", "email", "name", "home_airport", "created_at")}


def register_user(email: str, password: str, name: str | None = None, home_airport: str = "TRN") -> dict:
    email = email.lower().strip()
    con = datastore.connect()
    try:
        con.execute(
            "INSERT INTO users (email, password_hash, name, home_airport) VALUES (?, ?, ?, ?)",
            (email, _hasher.hash(password), name, home_airport),
        )
        con.commit()
        row = con.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return _sanitize(row)
    except sqlite3.IntegrityError:
        raise DuplicateEmailError(email)
    finally:
        con.close()


def authenticate(email: str, password: str) -> dict | None:
    con = datastore.connect()
    try:
        row = con.execute("SELECT * FROM users WHERE email = ?", (email.lower().strip(),)).fetchone()
    finally:
        con.close()
    if row is None:
        return None
    try:
        ok = _hasher.verify(password, row["password_hash"])
    except Exception:
        return None  # malformed/placeholder hash (e.g. CLI demo user)
    return _sanitize(row) if ok else None


def get_user(user_id: int) -> dict | None:
    con = datastore.connect()
    try:
        row = con.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _sanitize(row) if row else None
    finally:
        con.close()


def ensure_demo_user(email: str = "demo@travel.local", home_airport: str = "TRN") -> dict:
    """DEV ONLY (CLI chat): placeholder hash, cannot authenticate via the API.
    Real registration goes through register_user."""
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
