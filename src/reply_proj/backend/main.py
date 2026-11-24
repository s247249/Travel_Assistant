"""FastAPI application assembly (Phase 6, D26).

Naming: main.py is the FastAPI convention and the uvicorn target
(reply_proj.backend.main:app). Endpoint/logic separation lives in the
structure: api/ routers (HTTP) vs backend services (business logic).

Lifespan: one checkpointer connection + one compiled graph for the app's
lifetime. SessionMiddleware: signed-cookie sessions (stateless validation).
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.sqlite import SqliteSaver
from starlette.middleware.sessions import SessionMiddleware

from reply_proj.agent.graph import build_graph
from reply_proj.backend import config
from reply_proj.backend.api import bookings, conversations, sessions, users


@asynccontextmanager
async def lifespan(app: FastAPI):
    with SqliteSaver.from_conn_string(str(config.CHECKPOINTS_DB)) as checkpointer:
        app.state.graph = build_graph(checkpointer)
        yield


def create_app() -> FastAPI:
    app = FastAPI(title="Travel RAG Assistant", lifespan=lifespan)
    app.add_middleware(
        SessionMiddleware,
        secret_key=config.session_secret(),
        max_age=config.SESSION_MAX_AGE,
        same_site="lax",
        https_only=False,  # demo over http; set True behind TLS in production
    )
    app.include_router(users.router, prefix="/api")
    app.include_router(sessions.router, prefix="/api")
    app.include_router(conversations.router, prefix="/api")
    app.include_router(bookings.router, prefix="/api")

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    # Frontend (D27): same-origin static serving -> session cookies work, no CORS.
    # Mounted LAST so /api/* routes take precedence.
    app.mount("/", StaticFiles(directory=str(config.STATIC_DIR), html=True), name="static")

    return app


app = create_app()
