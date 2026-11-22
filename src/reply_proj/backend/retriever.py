"""Semantic retrieval over Chroma (Phase 2, decisions D15-D17).

Golden rule: this module answers "what is suitable / similar / described as...".
Hard facts (prices, availability, budget math) come from SQL via other modules.

Filter kwargs map to Chroma metadata (D16): scalar fields directly,
`target=<vocab term>` -> boolean flag `target_<term> == True`.
"""

from __future__ import annotations

import chromadb
from google import genai
from google.genai import types

from reply_proj.backend import config

FILTER_FIELDS = {
    "type", "city", "city_id", "country", "category", "tier",
    "cost_level", "budget_level", "indoor_outdoor",
}


def _build_where(filters: dict) -> dict | None:
    clauses = []
    for key, value in filters.items():
        if value is None:
            continue
        if key == "target":
            clauses.append({f"target_{value}": True})
        elif key in FILTER_FIELDS:
            clauses.append({key: value})
        else:
            raise ValueError(f"unknown retrieval filter: {key!r}")
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


class Retriever:
    def __init__(self) -> None:
        self._genai = genai.Client(api_key=config.google_api_key())
        self._chroma = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
        self._col = self._chroma.get_collection(config.COLLECTION)

    def embed_query(self, text: str) -> list[float]:
        resp = self._genai.models.embed_content(
            model=config.EMBED_MODEL,
            contents=text,
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_QUERY",  # asymmetric vs RETRIEVAL_DOCUMENT (D15)
                output_dimensionality=config.EMBED_DIMS,
            ),
        )
        return resp.embeddings[0].values

    def search(self, query: str, k: int = 5, **filters) -> list[dict]:
        """Semantic top-k with metadata filters. Distance = cosine distance (lower is better)."""
        result = self._col.query(
            query_embeddings=[self.embed_query(query)],
            n_results=k,
            where=_build_where(filters),
            include=["documents", "metadatas", "distances"],
        )
        hits = []
        for i in range(len(result["ids"][0])):
            hits.append({
                "chunk_id": result["ids"][0][i],
                "distance": result["distances"][0][i],
                "text": result["documents"][0][i],
                "metadata": result["metadatas"][0][i],
            })
        return hits
