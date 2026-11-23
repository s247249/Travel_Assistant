"""The seven Phase-3 agent tools (D21).

Three families:
- update_requirements: slot filling; LLM extracts, CODE validates (D20).
  Uses InjectedState (read current slots, hidden from the LLM schema) and
  returns a Command that updates state — the LangGraph pattern for
  state-writing tools.
- semantic search (4): thin wrappers over backend.retriever.Retriever (D17).
- SQL facts (2): flight options and hotel availability/pricing via datastore.

Tool docstrings are part of the LLM-facing contract: Gemini reads them to
decide when/how to call each tool, so they state arguments and vocabularies.
"""

from __future__ import annotations

import json
from typing import Annotated

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from reply_proj.agent.state import AgentState, missing_slots
from reply_proj.backend import datastore
from reply_proj.backend.retriever import Retriever

CATEGORIES = {"culture", "sport", "relax", "nightlife", "food", "nature"}
TARGETS = {"family", "young", "sporty", "couples", "solo", "seniors", "relax-seekers", "foodies"}

_retriever: Retriever | None = None


def get_retriever() -> Retriever:
    """Lazy singleton: no Chroma/API connection at import time."""
    global _retriever
    if _retriever is None:
        _retriever = Retriever()
    return _retriever


def _semantic_search(query: str, doc_type: str, **filters) -> str:
    hits = get_retriever().search(query, k=5, type=doc_type, **filters)
    return json.dumps(
        [{"doc_id": h["metadata"]["doc_id"], "city": h["metadata"]["city"],
          "distance": round(h["distance"], 3), "text": h["text"]} for h in hits],
        ensure_ascii=False,
    )


# ---------------- semantic tools (D17) ----------------

@tool
def search_activities(query: str, city: str | None = None, category: str | None = None,
                      target: str | None = None) -> str:
    """Search activity descriptions by meaning (RAG). Use for 'what would suit us' questions.
    Args:
        query: natural-language preference description, e.g. 'relaxing sea day for kids'.
        city: optional display name, e.g. 'Rome', 'Palma de Mallorca'.
        category: optional, one of culture/sport/relax/nightlife/food/nature.
        target: optional ideal audience, one of family/young/sporty/couples/solo/seniors/relax-seekers/foodies.
    Returns JSON list of matches with doc_id (the bookable ID), city, distance, full text."""
    return _semantic_search(query, "activity", city=city, category=category, target=target)


@tool
def search_hotels(query: str, city: str | None = None, tier: str | None = None,
                  target: str | None = None) -> str:
    """Search hotel descriptions by meaning (vibe, amenities, audience). For REAL prices and
    availability use find_hotels instead.
    Args:
        query: natural-language description, e.g. 'quiet family-friendly place near the sea'.
        city: optional display name.
        tier: optional, one of budget/mid/high.
        target: optional, one of family/young/sporty/couples/solo/seniors/relax-seekers/foodies."""
    return _semantic_search(query, "hotel", city=city, tier=tier, target=target)


@tool
def search_destinations(query: str, country: str | None = None) -> str:
    """Search destination profiles to choose or compare cities (e.g. nation-level requests:
    'Italy with sea and relax' -> Naples vs 'Italy with culture' -> Rome).
    Args:
        query: natural-language traveller profile or wish.
        country: optional, one of Italy/Spain/France/Austria."""
    return _semantic_search(query, "destination", country=country)


@tool
def search_guides(query: str, city: str | None = None) -> str:
    """Search practical city guides: transport, food, seasonality, day-planning tips.
    Args:
        query: natural-language practical question.
        city: optional display name."""
    return _semantic_search(query, "guide", city=city)


# ---------------- SQL fact tools ----------------

@tool
def search_flights(origin: str, destination_city: str, date_from: str, date_to: str) -> str:
    """Search REAL flight options: price per seat and seats left, per date.
    Args:
        origin: departure airport IATA code, e.g. TRN, MXP, FCO.
        destination_city: city id or display name, e.g. 'Paris'.
        date_from: ISO date YYYY-MM-DD (window start).
        date_to: ISO date YYYY-MM-DD (window end).
    Returns JSON list of {date, depart_time, from_code, to_code, price, seats_left}."""
    try:
        rows = datastore.search_flights(origin.upper(), destination_city, date_from, date_to)
    except ValueError as e:
        return json.dumps({"error": str(e)})
    return json.dumps(rows, ensure_ascii=False)


@tool
def find_hotels(city: str, date_from: str, date_to: str, travelers: int = 1,
                tier: str | None = None) -> str:
    """Find hotels with rooms available for EVERY night of the stay, with REAL total prices
    computed in code (rooms needed x nightly prices).
    Args:
        city: city id or display name.
        date_from: check-in ISO date YYYY-MM-DD.
        date_to: check-out ISO date YYYY-MM-DD (exclusive; nights = date_to - date_from).
        travelers: party size 1-8 (rooms are sized accordingly).
        tier: optional, one of budget/mid/high.
    Returns JSON list sorted by total_stay_price."""
    try:
        rows = datastore.find_hotels(city, date_from, date_to, travelers, tier)
    except ValueError as e:
        return json.dumps({"error": str(e)})
    return json.dumps(rows, ensure_ascii=False)


# ---------------- slot filling (D20) ----------------

@tool
def update_requirements(
    state: Annotated[AgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    budget: float | None = None,
    nation: str | None = None,
    preferences: list[str] | None = None,
    month: str | None = None,
    nights: int | None = None,
    travelers: int | None = None,
    origin: str | None = None,
) -> Command:
    """Record travel requirements learned from the user. Call AS SOON AS any value is revealed;
    partial updates are fine. Values are validated in code; rejected values come back with
    reasons so you can ask the user again. Never guess values the user did not state.
    Args:
        budget: total trip budget in EUR for the whole party, positive number.
        nation: one of Italy/Spain/France/Austria.
        preferences: non-empty list from culture/sport/relax/nightlife/food/nature.
        month: travel month, format YYYY-MM, must be within the available season.
        nights: trip length in nights, integer 1-14.
        travelers: party size, integer 1-8.
        origin: departure airport IATA code, e.g. TRN/MXP/FCO."""
    accepted: dict = {}
    rejected: dict = {}

    if budget is not None:
        if isinstance(budget, (int, float)) and budget > 0:
            accepted["budget"] = float(budget)
        else:
            rejected["budget"] = "must be a positive number (total EUR for the party)"
    if nation is not None:
        nations = datastore.valid_nations()
        match = next((n for n in nations if n.lower() == str(nation).lower()), None)
        if match:
            accepted["nation"] = match
        else:
            rejected["nation"] = f"not in our world; choose from {nations}"
    if preferences is not None:
        if isinstance(preferences, list) and preferences and all(p in CATEGORIES for p in preferences):
            accepted["preferences"] = list(preferences)
        else:
            rejected["preferences"] = f"non-empty list from {sorted(CATEGORIES)}"
    if month is not None:
        months = datastore.valid_months()
        if month in months:
            accepted["month"] = month
        else:
            rejected["month"] = f"outside the available season; choose from {months} (format YYYY-MM)"
    if nights is not None:
        if isinstance(nights, int) and 1 <= nights <= 14:
            accepted["nights"] = nights
        else:
            rejected["nights"] = "integer 1-14"
    if travelers is not None:
        if isinstance(travelers, int) and 1 <= travelers <= 8:
            accepted["travelers"] = travelers
        else:
            rejected["travelers"] = "integer 1-8"
    if origin is not None:
        codes = datastore.valid_airports()
        if str(origin).upper() in codes:
            accepted["origin"] = str(origin).upper()
        else:
            rejected["origin"] = f"unknown airport; choose from {codes}"

    slots = {**state.get("slots", {}), **accepted}
    missing = missing_slots(slots)
    result = {"accepted": accepted, "rejected": rejected, "missing": missing,
              "complete": not missing, "slots": slots}
    return Command(update={
        "slots": slots,
        "messages": [ToolMessage(content=json.dumps(result, ensure_ascii=False), tool_call_id=tool_call_id)],
    })


TOOLS = [update_requirements, search_activities, search_hotels, search_destinations,
         search_guides, search_flights, find_hotels]
