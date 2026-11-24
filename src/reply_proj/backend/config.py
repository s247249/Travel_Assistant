"""Shared configuration: paths, constants, and dependency-free .env loading."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

DB_PATH = ROOT / "db" / "travel.db"
CHECKPOINTS_DB = ROOT / "db" / "checkpoints.db"
CHROMA_DIR = ROOT / "db" / "chroma"
CORPUS_DIR = ROOT / "data" / "corpus"
INVENTORY_PATH = ROOT / "data" / "inventory.json"

EMBED_MODEL = "gemini-embedding-001"
EMBED_DIMS = 3072
COLLECTION = "travel_corpus"
AGENT_MODEL = "gemini-3.6-flash"  # D23: pinned; availability probed (3.7/3.8 demand-limited, 2.5 closed to new keys)
AGENT_MODEL_FALLBACKS = ["gemini-3.5-flash", "gemini-3.5-flash-lite"]  # D23: auto-fallback on persistent 429/503
SESSION_MAX_AGE = 24 * 3600  # D26: signed-cookie session lifetime (24h)


def load_env() -> None:
    """Load ROOT/.env into os.environ (existing variables win). No dependency."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def google_api_key() -> str:
    load_env()
    key = os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("GOOGLE_API_KEY missing — create .env at project root (see README)")
    return key


def session_secret() -> str:
    """Secret for signing session cookies (D26). Generated once into .env if absent."""
    load_env()
    secret = os.environ.get("SESSION_SECRET")
    if secret:
        return secret
    import secrets
    secret = secrets.token_hex(32)
    with (ROOT / ".env").open("a", encoding="utf-8") as f:
        f.write(f"\nSESSION_SECRET={secret}\n")
    os.environ["SESSION_SECRET"] = secret
    print("generated SESSION_SECRET and appended to .env (gitignored)")
    return secret
