"""FastAPI application entry point.

Phase 6 will add the real REST routes (auth, chat, itineraries, bookings).
Kept minimal until then; business logic lives in dedicated modules, never here
(separation of endpoints and logic per project notes).
"""

from fastapi import FastAPI

app = FastAPI(title="Travel RAG Assistant")


@app.get("/")
async def root():
    return {"message": "Travel RAG Assistant API — see /docs"}
