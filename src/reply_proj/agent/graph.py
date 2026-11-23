"""Hand-built single agent + tool loop (D19) with sync SQLite checkpointer (D22).

Topology (~15 lines of graph wiring):
    START -> agent -> (tool calls?) -> tools -> agent -> ... -> END

The agent node prepends the system prompt + authoritative slots state each turn,
so the LLM never relies on its memory for requirements. Guards live in the tools
(validation, refusals), not in graph edges — the LLM orchestrates, code enforces.
"""

from __future__ import annotations

import json
import time

from langchain_core.messages import SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from reply_proj.agent.prompts import SYSTEM_PROMPT
from reply_proj.agent.state import AgentState, missing_slots
from reply_proj.agent.tools import TOOLS
from reply_proj.backend import config


def make_model(model_name: str | None = None):
    return ChatGoogleGenerativeAI(
        model=model_name or config.AGENT_MODEL,
        # note: gemini-3.6-flash uses fixed sampling; temperature is not configurable (D23)
        google_api_key=config.google_api_key(),
        max_retries=0,  # retry policy lives ONLY in invoke_with_retry/invoke_with_fallback
        timeout=30,     # never hang forever on a demand spike
    )


TRANSIENT_MARKERS = ("429", "500", "503", "504", "UNAVAILABLE", "RESOURCE_EXHAUSTED",
                     "DEADLINE_EXCEEDED", "INTERNAL", "timed out", "timeout",
                     "connecterror", "remoteprotocolerror")


def is_transient(e: Exception) -> bool:
    """API codes AND client-side transport failures (ReadTimeout etc.) are all retryable."""
    text = f"{type(e).__name__}: {e}".lower()
    return any(m.lower() in text for m in TRANSIENT_MARKERS)


def invoke_with_retry(model, messages, attempts: int = 4):
    """Explicit backoff for transient free-tier errors (429 quota, 503 demand spikes).
    Same philosophy as the ingestion retry: survive the free tier gracefully."""
    for i in range(attempts):
        try:
            return model.invoke(messages)
        except Exception as e:
            if is_transient(e) and i < attempts - 1:
                delay = 10 * (i + 1)
                print(f"  [llm] {type(e).__name__}: {str(e)[:140]}")
                print(f"  [llm] retrying in {delay}s")
                time.sleep(delay)
                continue
            raise


def invoke_with_fallback(models, messages):
    """Try each (name, bound model) in order; persistent transient errors move to the next.

    Free-tier reality (D23): flash demand spikes (503) come and go; the lite tier
    usually serves and handles all 7 tools correctly (verified). Fallbacks are logged.
    """
    last_error = None
    for i, (name, model) in enumerate(models):
        # fast failover: one attempt per model; full retries only on the last one
        attempts = 3 if i == len(models) - 1 else 1
        try:
            response = invoke_with_retry(model, messages, attempts=attempts)
            if i > 0:
                print(f"  [llm] answered by fallback model: {name}")
            return response
        except Exception as e:
            if not is_transient(e):
                raise
            last_error = e
            print(f"  [llm] {name} unavailable ({type(e).__name__}); trying next model")
    raise last_error


def build_graph(checkpointer, model_name: str | None = None):
    names = [model_name] if model_name else [config.AGENT_MODEL, *config.AGENT_MODEL_FALLBACKS]
    models = [(n, make_model(n).bind_tools(TOOLS)) for n in names]

    def agent(state: AgentState) -> dict:
        slots = state.get("slots", {})
        missing = missing_slots(slots)
        system = (
            SYSTEM_PROMPT
            + "\n\n## Current requirements (authoritative state)\n"
            + json.dumps(slots, ensure_ascii=False)
            + "\nMissing required slots: "
            + (", ".join(missing) if missing else "none — requirements complete")
        )
        response = invoke_with_fallback(models, [SystemMessage(content=system)] + state["messages"])
        return {"messages": [response]}

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent)
    graph.add_node("tools", ToolNode(TOOLS))
    graph.set_entry_point("agent")
    # tools_condition: last AI message has tool_calls -> "tools", else END
    graph.add_conditional_edges("agent", tools_condition, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    return graph.compile(checkpointer=checkpointer)
