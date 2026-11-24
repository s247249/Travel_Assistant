"""Users resource: POST /api/users = registration (course-style, D26/A2)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from reply_proj.backend import datastore, user_db

router = APIRouter(tags=["users"])


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    name: str | None = None
    home_airport: str = "TRN"


@router.post("/users", status_code=201)
def register(body: RegisterIn, request: Request):
    if body.home_airport not in datastore.valid_airports():
        raise HTTPException(422, f"home_airport must be one of {datastore.valid_airports()}")
    try:
        user = user_db.register_user(str(body.email), body.password, body.name, body.home_airport)
    except user_db.DuplicateEmailError:
        raise HTTPException(409, "email already registered")
    request.session["user_id"] = user["id"]  # auto-login after registration
    return user
