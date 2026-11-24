"""Shared API dependencies: authentication via the signed session cookie (D26).

The cookie carries user_id, signed by SessionMiddleware — validation is a
signature check (stateless), then the users RESOURCE is loaded from the DB.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from reply_proj.backend import user_db


def get_current_user(request: Request) -> dict:
    uid = request.session.get("user_id")
    if not uid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = user_db.get_user(uid)
    if user is None:
        raise HTTPException(status_code=401, detail="User no longer exists")
    return user
