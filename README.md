# Travel RAG Assistant

A conversational virtual assistant for travel & experiences: it collects requirements
(budget, nation, activity preferences, month) via chat, generates complete itineraries
(flights + hotel for every night + daily activities) under budget/availability constraints,
and supports booking — built as a RAG + tool-calling agent over a synthetic travel world.

See `docs/architecture.md` for the full design and decision log, and
`docs/demo_walkthrough.md` for a guided demo / manual test checklist.

> All inventory is **synthetic demo data** (fictional hotels, generated prices/availability).
> Booking is simulated against the local database. No live travel data.

## Architecture (two knowledge stores)

- **SQLite** (`db/travel.db`, regenerable): hard facts — flights, hotels, activities,
  per-date availability, users, bookings. Exact queries, budget math, transactions.
- **Chroma** (`db/chroma/`, regenerable): semantic knowledge — 114 validated Markdown
  documents (activities, hotels, destination profiles, guides), Gemini embeddings.
- Both stores share entity IDs. The LLM converses and orchestrates; deterministic code
  computes and commits (itinerary building, booking).

## Quickstart

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/). A free
[Google AI Studio](https://aistudio.google.com) API key is needed for embeddings and the agent.

```bash
uv sync                              # install dependencies
echo GOOGLE_API_KEY=your_key > .env  # never committed (gitignored)

python scripts/generate_inventory.py # build the SQLite world (deterministic, seed 42)
python scripts/ingest_corpus.py      # build Chroma from data/corpus (≈2 embedding calls)

uv run uvicorn reply_proj.backend.main:app --port 8000
```

Open http://localhost:8000 — register, chat, plan, book. Interactive API docs at
http://localhost:8000/docs. The frontend needs internet access for the Bootstrap CDN.

The committed sources are `data/inventory.json` (entity contract) and `data/corpus/`
(validated Markdown). The databases are **not** committed — they regenerate from the two
scripts above. On the free API tier the agent uses a model fallback chain; transient
rate-limit/demand errors are retried automatically (logged in the server console).

## Repository layout

```
docs/                     architecture + decision log, demo walkthrough
src/reply_proj/
  agent/                  LangGraph agent (state, tools, graph, prompts)
  backend/                FastAPI app, API routers, services (datastore, planner,
                          booking, retriever, auth), schema.sql
  frontend/               vanilla JS + Bootstrap CDN (no build step)
scripts/                  database generation (inventory + corpus ingestion)
data/inventory.json       entity contract (IDs, names, prices, targets)
data/corpus/<city>/       validated Markdown corpus (114 docs, 6 cities)
```

Development tools (testers, validators, prompt generators, CLI chat) live in `scripts/dev/`
and intermediate artifacts in `data/corpus_raw/`, `data/prompts/`, `data/eval/`; these are
gitignored and not required to run the application.
