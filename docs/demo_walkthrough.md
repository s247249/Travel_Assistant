# Demo Walkthrough & Manual Test Checklist (Phase 7/8)

The API is battery-tested (dev tools in `scripts/dev/`, gitignored); this checklist verifies the
frontend in a real browser. It doubles as the reviewer demo script.

## Setup

```bash
uv sync
# .env must contain GOOGLE_API_KEY (free Google AI Studio key)
python scripts/generate_inventory.py   # if db/travel.db missing
python scripts/ingest_corpus.py        # if db/chroma missing
uv run uvicorn reply_proj.backend.main:app --port 8000
```

Open http://localhost:8000. (Server console shows model-fallback logs — normal
on the free tier; the chat keeps working via the fallback chain.)

## Checklist

| # | Action | Expected |
|---|--------|----------|
| 1 | Register (email, password ≥8, name, home airport) | auto-login, chat view, empty conversation |
| 2 | Wrong password login (after logout) | clear error, no session |
| 3 | New conversation → "Family of 4, Spain in July, relax by the sea, budget 2500 euros, 4 nights from Turin" | requirements panel fills (budget/nation/month/nights/travelers/origin/targets); assistant recommends a city; loading indicator while waiting |
| 4 | Confirm the city ("Palma sounds good, build it") | **itinerary card** appears: flights, hotel, day-by-day, total ≤ budget, margin; badge `proposed` |
| 5 | Object to one day ("the kids won't like the last day, something by the sea") | card rebuilds; objected day changes; other days stay (deterministic rebuild) |
| 6 | "Book it" → assistant shows preview → "yes, confirm" | card badge `booked #id`; success flash |
| 7 | Bookings page | booking listed `confirmed`; Details shows all items (2 flights, N hotel nights, N+1 activities); total matches card |
| 8 | Second trip, new conversation, requirements → card → **Confirm booking button** | booked without any chat consent text (code-only path, same guarantees) |
| 9 | Cancel a booking from dashboard (confirm dialog) | status `cancelled`; seats/rooms/spots released (a rebook of the same plan succeeds) |
| 10 | Click an older conversation in the sidebar | messages, requirements panel and proposal card restored (checkpointer history) |
| 11 | Logout → login again | conversations and bookings persist |
| 12 | Budget too low ("budget 300 euros") → build | assistant explains the diagnosis (minimum feasible total, suggestions) — no partial plan, no booking possible |
| 13 | Duplicate registration email | 409 error shown |

## Notes

- The itinerary card is rendered from the structured proposal (authoritative);
  the assistant's prose is commentary. If they ever disagree, the card wins —
  report it as a bug (narrative drift).
- No tool names/args are shown in the UI by design (D27/F3); the full trace is
  in the API response (`tool_trace`), the CLI (`scripts/dev/chat_cli.py`), and logs.
- Graphics are intentionally simple (reviewer: graphical quality not evaluated).
