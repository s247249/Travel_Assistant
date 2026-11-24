"""Agent state schema (D20).

- messages: conversation history; the add_messages reducer APPENDS new messages
  (and dedupes/updates by id) instead of overwriting the list.
- slots: collected travel requirements; updated only by the update_requirements
  tool (validated in code), never directly by the LLM.
- proposal: itinerary proposal dict (filled by build_itinerary in Phase 4).
- user_id: injected from the authenticated session at thread creation;
  never extracted from chat content (security).
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

REQUIRED_SLOTS = ("budget", "nation", "preferences", "month", "nights", "travelers")
DEFAULT_SLOTS = {}
EMPTY_REVISIONS = {"exclude_activity_ids": [], "pins": {}}


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    slots: dict
    proposal: dict | None
    revisions: dict  # D24: accumulated exclude_activity_ids + pins (date -> activity_id)
    user_id: int


def missing_slots(slots: dict) -> list[str]:
    """Required slots that are absent or empty (0/[]/None count as missing)."""
    return [key for key in REQUIRED_SLOTS if not slots.get(key)]
