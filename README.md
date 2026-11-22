# Travel RAG Assistant

A conversational virtual assistant for travel & experiences: collects requirements
(budget, nation, activity preferences, month) via chat, generates complete itineraries
(flights + hotel per night + daily activities) under budget/availability constraints,
and supports booking — built as a RAG + tool-calling agent over a synthetic travel world.

**Status:** Phases 1–2 complete (data layer + retrieval). Phase 3 (LangGraph agent) in progress.
See `docs/architecture.md` for the full design and decision log (D1–D23).

> All inventory is **synthetic demo data** (fictional hotels, generated prices/availability).
> Booking is simulated against the local database. No live travel data.

## Architecture (two knowledge stores)

- **SQLite** (`db/travel.db`, regenerable): hard facts — flights, hotels, activities,
  per-date availability, users, bookings. Exact queries, budget math, transactions.
- **Chroma** (`db/chroma/`, regenerable): semantic knowledge — 114 validated Markdown
  documents (activities, hotels, destination profiles, guides), Gemini embeddings.
- Both stores share entity IDs; the LLM converses and orchestrates, deterministic code
  computes and commits.

## Quickstart

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/). A free
[Google AI Studio](https://aistudio.google.com) API key is needed for embeddings/agent.

```bash
uv sync                              # install dependencies
echo GOOGLE_API_KEY=your_key > .env  # never committed (gitignored)

python scripts/generate_inventory.py # rebuild SQLite world (deterministic, seed 42)
python scripts/ingest_corpus.py      # rebuild Chroma from data/corpus (≈2 embedding calls)
python scripts/try_retrieval.py      # showcase: hybrid semantic + metadata queries
python scripts/eval_retrieval.py     # score retrieval (18 queries; see data/eval/results.json)
```

The validated corpus (`data/corpus/`) and eval set (`data/eval/queries.json`) are committed;
databases are not — they regenerate from the scripts above.

## Repository layout

```
docs/architecture.md      design + decision log (start here)
scripts/                  data generation, corpus prompts/validation, ingestion, eval
src/reply_proj/backend/   config, schema.sql, retriever (FastAPI app grows in Phase 6)
src/reply_proj/agent/     LangGraph agent (Phase 3)
data/inventory.json       generated entity contract (IDs, names, prices)
data/prompts/             delegation prompts (corpus + eval generation)
data/corpus/<city>/       validated Markdown corpus (114 docs, 6 cities)
data/eval/                retrieval eval queries + results
```

## Regenerating the corpus (optional)

`data/prompts/<city>_prompt.md` can be run in any capable LLM chat or agent session;
save output to `data/corpus_raw/<city>.txt`, then `python scripts/validate_corpus.py --city <city>`.