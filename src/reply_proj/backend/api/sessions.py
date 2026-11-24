"""Sessions as a resource (course pattern, D26/A2):
POST /api/sessions = login (create session), GET /api/sessions/current = me,
DELETE /api/sessions/current = logout (destroy session).

The session itself is a SIGNED COOKIE (stateless validation, A1 option 2):
no server session table; logout clears the cookie; expiry limits lifetime.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from reply_proj.backend import user_db
from reply_proj.backend.api.deps import get_current_user

router = APIRouter(tags=["sessions"])


class LoginIn(BaseModel):
    email: str
    password: str


@router.post("/sessions", status_code=201)
def login(body: LoginIn, request: Request):
    user = user_db.authenticate(body.email, body.password)
    if user is None:
        raise HTTPException(401, "Incorrect email or password")
    request.session["user_id"] = user["id"]
    return user


@router.get("/sessions/current")
def current(user: dict = Depends(get_current_user)):
    return user


@router.delete("/sessions/current", status_code=204)
def logout(request: Request):
    request.session.clear()
    return Response(status_code=204)
