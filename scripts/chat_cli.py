"""Terminal chat with the agent — Phase 3 test harness (D21).

Creates a demo user (real auth arrives in Phase 6), opens a conversation thread
(checkpointed in db/checkpoints.db), and streams the agent loop so you can SEE
the tool calls happen (agentic RAG in action).

Usage:
  python scripts/chat_cli.py                     # new conversation
  python scripts/chat_cli.py --thread <uuid>     # resume (history + slots restored)
  python scripts/chat_cli.py --verbose           # also print tool results
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from langchain_core.messages import HumanMessage  # noqa: E402
from langgraph.checkpoint.sqlite import SqliteSaver  # noqa: E402

from reply_proj.agent.graph import build_graph  # noqa: E402
from reply_proj.agent.state import DEFAULT_SLOTS  # noqa: E402
from reply_proj.backend import config, datastore, user_db  # noqa: E402


def message_text(m) -> str:
    if isinstance(m.content, str):
        return m.content
    return " ".join(b.get("text", "") for b in m.content if isinstance(b, dict))


def main() -> None:
    # Windows consoles default to cp1252; agent replies are UTF-8 (may contain emoji)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--thread", help="thread id to resume")
    parser.add_argument("--email", default="demo@travel.local")
    parser.add_argument("--home-airport", default="TRN")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--model", help="override the agent model (e.g. gemini-3.5-flash-lite when flash is demand-limited)")
    args = parser.parse_args()

    user = user_db.ensure_demo_user(args.email, args.home_airport)
    thread_id = args.thread or str(uuid.uuid4())

    with SqliteSaver.from_conn_string(str(config.CHECKPOINTS_DB)) as checkpointer:
        graph = build_graph(checkpointer, args.model)
        print(f"model: {args.model or config.AGENT_MODEL + ' -> ' + ' -> '.join(config.AGENT_MODEL_FALLBACKS)}")
        cfg = {"configurable": {"thread_id": thread_id}}
        existing = graph.get_state(cfg)

        initial = None
        if not existing.values:  # brand-new thread
            con = datastore.connect()
            con.execute("INSERT OR IGNORE INTO conversations (id, user_id, title) VALUES (?, ?, ?)",
                        (thread_id, user["id"], "CLI conversation"))
            con.commit()
            con.close()
            initial = {
                "messages": [],
                "slots": {**DEFAULT_SLOTS, "origin": user["home_airport"]},
                "proposal": None,
                "revisions": {"exclude_activity_ids": [], "pins": {}},
                "user_id": user["id"],
            }
        else:
            print(f"resuming thread — slots: {json.dumps(existing.values.get('slots', {}), ensure_ascii=False)}")

        print(f"thread_id: {thread_id}   (resume later with --thread {thread_id})")
        print("type 'exit' to quit\n")

        while True:
            try:
                text = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not text:
                continue
            if text.lower() in {"exit", "quit"}:
                break

            payload = {"messages": [HumanMessage(content=text)]}
            if initial is not None:
                payload = {**initial, **payload}
                initial = None

            try:
                for update in graph.stream(payload, cfg, stream_mode="updates"):
                    for node, data in update.items():
                        for m in (data.get("messages", []) if isinstance(data, dict) else []):
                            tool_calls = getattr(m, "tool_calls", None)
                            if tool_calls:
                                for tc in tool_calls:
                                    print(f"  [tool] {tc['name']}({json.dumps(tc['args'], ensure_ascii=False)[:200]})")
                            elif m.type == "ai" and message_text(m):
                                print(f"\nassistant> {message_text(m)}\n")
                            elif m.type == "tool" and args.verbose:
                                print(f"  [result] {m.name}: {str(m.content)[:300]}")
            except KeyboardInterrupt:
                print("\n[interrupted — completed steps are checkpointed; resume with --thread]")
                break

            slots = graph.get_state(cfg).values.get("slots", {})
            print(f"  [slots] {json.dumps(slots, ensure_ascii=False)}")

    print("bye")


if __name__ == "__main__":
    main()
