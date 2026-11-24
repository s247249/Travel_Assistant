"""Conversations: threads, history, chat (plain JSON, A3), code-only booking path.

Ownership: every route verifies conversations.user_id == session user (404 otherwise).
user_id is injected into graph state from the session — never from the client.
Chat endpoint is sync def -> FastAPI threadpool (sync SqliteSaver + graph).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from reply_proj.agent.state import DEFAULT_SLOTS
from reply_proj.backend import booking, datastore, planner
from reply_proj.backend.api.deps import get_current_user

router = APIRouter(tags=["conversations"])


def _thread_or_404(tid: str, user: dict) -> dict:
    con = datastore.connect()
    try:
        row = con.execute("SELECT * FROM conversations WHERE id=? AND user_id=?",
                          (tid, user["id"])).fetchone()
    finally:
        con.close()
    if row is None:
        raise HTTPException(404, "conversation not found")
    return dict(row)


def _cfg(tid: str) -> dict:
    return {"configurable": {"thread_id": tid}}


def _message_text(m) -> str:
    if isinstance(m.content, str):
        return m.content
    return " ".join(b.get("text", "") for b in m.content if isinstance(b, dict))


@router.get("/conversations")
def list_conversations(user: dict = Depends(get_current_user)):
    con = datastore.connect()
    try:
        rows = con.execute(
            "SELECT id, title, created_at, updated_at FROM conversations "
            "WHERE user_id=? ORDER BY updated_at DESC, rowid DESC", (user["id"],)).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


@router.post("/conversations", status_code=201)
def create_conversation(user: dict = Depends(get_current_user)):
    tid = str(uuid.uuid4())
    con = datastore.connect()
    try:
        con.execute("INSERT INTO conversations (id, user_id, title) VALUES (?, ?, ?)",
                    (tid, user["id"], "New conversation"))
        con.commit()
    finally:
        con.close()
    return {"id": tid, "title": "New conversation", "user_id": user["id"]}


@router.get("/conversations/{tid}/messages")
def get_messages(tid: str, request: Request, user: dict = Depends(get_current_user)):
    _thread_or_404(tid, user)
    st = request.app.state.graph.get_state(_cfg(tid)).values
    messages = []
    for m in st.get("messages", []):
        entry = {"role": m.type, "content": _message_text(m)}
        if getattr(m, "tool_calls", None):
            entry["tool_calls"] = [{"name": tc["name"], "args": tc["args"]} for tc in m.tool_calls]
        if m.type == "tool":
            entry["name"] = m.name
        messages.append(entry)
    proposal = st.get("proposal")
    return {"messages": messages, "slots": st.get("slots", {}),
            "proposal": planner.proposal_summary(proposal) if proposal else None}


class ChatIn(BaseModel):
    message: str = Field(min_length=1)


@router.post("/conversations/{tid}/chat")
def chat(tid: str, body: ChatIn, request: Request, user: dict = Depends(get_current_user)):
    _thread_or_404(tid, user)
    graph = request.app.state.graph
    cfg = _cfg(tid)
    st = graph.get_state(cfg).values
    payload = {"messages": [HumanMessage(content=body.message)]}
    if not st:  # first turn: seed state (user_id from SESSION, never from client)
        payload = {
            "messages": [], "slots": {**DEFAULT_SLOTS, "origin": user["home_airport"]},
            "proposal": None, "revisions": {"exclude_activity_ids": [], "pins": {}},
            "user_id": user["id"],
            **payload,
        }
    n_before = len(st.get("messages", []))
    try:
        result = graph.invoke(payload, cfg)
    except Exception as e:
        raise HTTPException(503, f"assistant unavailable: {type(e).__name__}: {str(e)[:120]}")

    trace, reply = [], ""
    for m in result["messages"][n_before:]:
        if getattr(m, "tool_calls", None):
            for tc in m.tool_calls:
                trace.append({"tool": tc["name"], "args": tc["args"]})
        elif m.type == "tool":
            trace.append({"tool": m.name, "result": str(m.content)[:500]})
        elif m.type == "ai" and _message_text(m):
            reply = _message_text(m)

    con = datastore.connect()
    try:
        con.execute("UPDATE conversations SET updated_at=datetime('now') WHERE id=?", (tid,))
        con.commit()
    finally:
        con.close()

    proposal = result.get("proposal")
    return {"reply": reply, "tool_trace": trace, "slots": result.get("slots", {}),
            "proposal": planner.proposal_summary(proposal) if proposal else None}


@router.post("/conversations/{tid}/book", status_code=201)
def book(tid: str, request: Request, user: dict = Depends(get_current_user)):
    """Code-only booking path (D25/B1): the confirm button. No LLM in the loop;
    same booking service, same guarantees as chat booking."""
    _thread_or_404(tid, user)
    graph = request.app.state.graph
    cfg = _cfg(tid)
    proposal = graph.get_state(cfg).values.get("proposal")
    if not proposal or proposal.get("status") != "proposed":
        raise HTTPException(409, "no active proposal to book")
    result = booking.confirm_booking(proposal, user["id"])
    if result["status"] in ("booked", "already_booked"):
        graph.update_state(cfg, {"proposal": {**proposal, "status": "booked",
                                              "booking_id": result.get("booking_id")}},
                           as_node="tools")
        return result
    raise HTTPException(409, detail=result)
