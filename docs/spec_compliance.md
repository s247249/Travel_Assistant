# Spec Compliance Audit

Mapping of every project requirement to its implementation. Verified against the code
(schema tables, routers, services, frontend). Synthetic-data simplifications are noted.

## Database — relational (SQLite, `backend/schema.sql`)

| Requirement | Implementation | Status |
|---|---|---|
| Users | `users` (email, password_hash, name, home_airport) | ✅ |
| Hotels — available dates & cost/night | `hotels` + `hotel_availability(date, rooms_left, price_night)` | ✅ |
| Activities — available dates | `activities` + `activity_availability(date, spots_left)` | ✅ |
| Flights — departure/arrival airports, dates, costs | `airports` + `flights(from_code, to_code, date, depart_time, price, seats_left)` | ✅ |
| Bookings — user, itinerary | `bookings(user_id, status, …)` + `booking_items` (itinerary line items) | ✅ |

## Database — vector (Chroma)

| Requirement | Implementation | Status |
|---|---|---|
| Textual descriptions of activities | `data/corpus/<city>/activity_*.md` → Gemini embeddings | ✅ |
| Ideal targets (families, young, sporty, …) | `targets` — SQL authority, validated corpus copies, Chroma metadata flags for search | ✅ |

## Backend (Python web framework)

| Requirement | Implementation | Status |
|---|---|---|
| Python web framework | FastAPI (`backend/main.py`) | ✅ |
| REST API | `backend/api/` routers: users, sessions, conversations, bookings | ✅ |
| Business logic | services: `datastore`, `planner`, `booking`, `retriever`, `user_db` (separate from endpoints) | ✅ |

## Frontend (`src/reply_proj/frontend/`)

| Requirement | Implementation | Status |
|---|---|---|
| Registration & authentication | register/login/logout; signed-cookie stateless sessions | ✅ |
| Chat interface | chat view (bubbles, loading state, requirements panel) | ✅ |
| Itinerary visualization | structured proposal card (flights, hotel, day-by-day, total/margin) | ✅ |
| Booking via chat | `book_itinerary` tool: preview → explicit consent → commit | ✅ |
| Bookings dashboard | bookings view: list, item detail, cancel | ✅ |

## Main functions

| # | Requirement | Implementation | Status |
|---|---|---|---|
| 1 | Intelligent conversation (NL chat, context comprehension) | LangGraph agent + SQLite checkpointer (per-thread state) | ✅ |
| 2 | Requirements collection (extract & validate budget, destination, activities, period) | `update_requirements` tool, code-side validation | ✅ |
| 3 | Itinerary generation: outbound+return flight, hotel every night, activities every day; respect budget/availability/preferences | `planner` (bounded enumeration, lexicographic preference scoring, constraint guarantees) | ✅ |
| 4 | Booking the whole itinerary via chat; save booking status | `booking` service (atomic re-validating transaction; `confirmed`/`cancelled`) | ✅ |

## Optional functions

| Feature | Status |
|---|---|
| History of user conversations | ✅ done (checkpointer + sidebar resume) |
| Confirm-booking button (developer discretion) | ✅ done (code-only path, same service as chat) |
| Image upload to suggest preferences | ⬜ not implemented (parked) |
| Editing already-booked itineraries | ⬜ not implemented (parked — to be re-discussed) |

## Deliverable

| Requirement | Status |
|---|---|
| Git repository | ✅ local repo with full history (remote push / share link pending) |
| README with execution instructions | ✅ `README.md` |
| Architectural notes | ✅ `docs/architecture.md` (+ `docs/demo_walkthrough.md`) |

## Documented simplifications

- Synthetic inventory (fictional hotels, generated prices/availability); booking simulated locally.
- Nation-level requests resolve to a confirmed city (multiple cities per country).
- Trip length (nights) and party size (travelers) are **asked, never assumed**; origin defaults to
  the user's registered home airport.
- Whole-booking cancellation only (no item-level editing yet); no fees.
- Free-tier model fallback chain; transient API errors retried.