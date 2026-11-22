"""Ingest the validated corpus into Chroma (D14 fit-or-split, D15 embeddings, D16 layout).

Reads data/corpus/<city>/*.md (validated documents only), chunks with the
fit-or-split policy, embeds with gemini-embedding-001 (RETRIEVAL_DOCUMENT),
and rebuilds the single `travel_corpus` collection (cosine space).

Idempotent: the collection is deleted and recreated on every run.
Usage: python scripts/ingest_corpus.py
"""

from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

import chromadb
import yaml
from google import genai
from google.genai import types
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from reply_proj.backend import config  # noqa: E402

WHOLE_DOC_MAX_WORDS = 375  # ~500 tokens at ~1.33 tokens/word (D14)
# size fallback: chars ~= 4 tokens -> 2400 chars ~ 600 tokens, 320 ~ 80 overlap
MD_SPLITTER = MarkdownHeaderTextSplitter(headers_to_split_on=[("##", "section")])
SIZE_SPLITTER = RecursiveCharacterTextSplitter(chunk_size=2400, chunk_overlap=320)
BATCH_SIZE = 100

KIND_LABEL = {"activity": "Activity", "hotel": "Hotel",
              "destination": "Destination profile", "guide": "Practical guide"}


def parse_doc(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---"), f"{path}: missing front matter"
    _, fm, body = text.split("---", 2)
    return yaml.safe_load(fm), body.strip()


def fit_or_split(body: str) -> list[tuple[str | None, str]]:
    """Return [(section_or_None, text)]. Whole doc when it fits (D14)."""
    if len(body.split()) <= WHOLE_DOC_MAX_WORDS:
        return [(None, body)]
    chunks: list[tuple[str | None, str]] = []
    for sec in MD_SPLITTER.split_text(body):
        section = sec.metadata.get("section")
        if len(sec.page_content.split()) <= WHOLE_DOC_MAX_WORDS:
            chunks.append((section, sec.page_content))
        else:
            chunks.extend((section, piece) for piece in SIZE_SPLITTER.split_text(sec.page_content))
    return chunks


def context_prefix(fm: dict, title: str, section: str | None) -> str:
    kind = KIND_LABEL[fm["type"]]
    head = f"{kind} in {fm['city']}, {fm['country']}: {title}"
    if section:
        head += f" — {section}"
    return head + ".\n\n"


def build_metadata(fm: dict, city_id: str, chunk_index: int, source: str) -> dict:
    meta = {
        "doc_id": fm["id"], "type": fm["type"], "city": fm["city"], "city_id": city_id,
        "country": fm["country"], "chunk_index": chunk_index, "source_file": source,
    }
    for field in ("category", "cost_level", "tier", "budget_level", "indoor_outdoor", "duration_min"):
        if field in fm:
            meta[field] = fm[field]
    for target in fm.get("targets") or fm.get("best_for") or []:
        meta[f"target_{target}"] = True  # boolean flags: exact filtering (D16)
    for field in ("interests", "amenities", "tags", "topics"):
        if field in fm:
            meta[field] = ",".join(fm[field])  # Chroma metadata must be scalar
    return meta


def _retry_delay(e: Exception) -> float:
    """Honor the server's RetryInfo (free tier: 100 embedded TEXTS/min, not HTTP calls)."""
    for d in getattr(e, "details", None) or []:
        if isinstance(d, dict) and "retryDelay" in d:
            try:
                return float(str(d["retryDelay"]).rstrip("s")) + 2.0
            except ValueError:
                pass
    m = re.search(r"retryDelay['\"]?:\s*['\"]?(\d+)", str(e))
    return float(m.group(1)) + 2.0 if m else 60.0


def embed_batches(client: genai.Client, texts: list[str]) -> list[list[float]]:
    vectors: list[list[float]] = []
    for start in range(0, len(texts), BATCH_SIZE):
        batch = texts[start:start + BATCH_SIZE]
        for attempt in range(5):
            try:
                resp = client.models.embed_content(
                    model=config.EMBED_MODEL,
                    contents=batch,
                    config=types.EmbedContentConfig(
                        task_type="RETRIEVAL_DOCUMENT", output_dimensionality=config.EMBED_DIMS,
                    ),
                )
                vectors.extend(e.values for e in resp.embeddings)
                break
            except genai.errors.APIError as e:
                if getattr(e, "code", None) == 429 and attempt < 4:
                    delay = _retry_delay(e)
                    print(f"  rate limited on batch at {start}; sleeping {delay:.0f}s (attempt {attempt + 1})")
                    time.sleep(delay)
                    continue
                raise
    return vectors


def main() -> None:
    inventory = json.loads(config.INVENTORY_PATH.read_text(encoding="utf-8"))
    names = {e["id"]: e["name"] for e in inventory["activities"] + inventory["hotels"]}

    ids, texts, metadatas = [], [], []
    per_type: Counter = Counter()
    split_docs = 0
    files = sorted(config.CORPUS_DIR.rglob("*.md"))
    assert files, "no validated corpus found — run validate_corpus.py first"

    for path in files:
        fm, body = parse_doc(path)
        city_id = path.parent.name
        title = names.get(fm["id"], f"{fm['city']} {KIND_LABEL[fm['type']].lower()}")
        chunks = fit_or_split(body)
        if len(chunks) > 1 or chunks[0][0] is not None:
            split_docs += 1
        for i, (section, text) in enumerate(chunks):
            ids.append(f"{fm['id']}#c{i}")
            texts.append(context_prefix(fm, title, section) + text)
            metadatas.append(build_metadata(fm, city_id, i, str(path.relative_to(ROOT))))
        per_type[fm["type"]] += 1

    print(f"documents: {len(files)}  chunks: {len(ids)}  docs needing split path: {split_docs}")
    print(f"per type: {dict(per_type)}")

    client = genai.Client(api_key=config.google_api_key())
    vectors = embed_batches(client, texts)
    assert len(vectors) == len(texts) and all(len(v) == config.EMBED_DIMS for v in vectors)
    print(f"embedded {len(vectors)} chunks ({(len(texts) + BATCH_SIZE - 1) // BATCH_SIZE} API calls, {config.EMBED_DIMS} dims)")

    chroma = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
    try:
        chroma.delete_collection(config.COLLECTION)  # idempotent rebuild
    except Exception:
        pass
    col = chroma.create_collection(config.COLLECTION, metadata={"hnsw:space": "cosine"})
    col.add(ids=ids, embeddings=vectors, documents=texts, metadatas=metadatas)
    assert col.count() == len(ids)
    print(f"OK  collection '{config.COLLECTION}' rebuilt at {config.CHROMA_DIR} ({col.count()} chunks)")


if __name__ == "__main__":
    main()
