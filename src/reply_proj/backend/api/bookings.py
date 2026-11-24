"""Bookings resource: dashboard data + cancellation (ownership enforced in service)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from reply_proj.backend import booking
from reply_proj.backend.api.deps import get_current_user

router = APIRouter(tags=["bookings"])


@router.get("/bookings")
def list_bookings(user: dict = Depends(get_current_user)):
    return booking.list_bookings(user["id"])


@router.get("/bookings/{bid}")
def get_booking(bid: int, user: dict = Depends(get_current_user)):
    b = booking.get_booking(bid, user["id"])
    if b is None:
        raise HTTPException(404, "booking not found")
    return b


@router.post("/bookings/{bid}/cancel")
def cancel(bid: int, user: dict = Depends(get_current_user)):
    result = booking.cancel_booking(bid, user["id"])
    if result["status"] != "cancelled":
        raise HTTPException(409, detail=result)
    return result
