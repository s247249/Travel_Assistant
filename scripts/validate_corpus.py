"""Split + validate raw corpus output against the inventory contract (D6, §7).

Handles two raw formats:
  - proper: '=== FILE: x.md ===' separators + real YAML front matter (--- ... ---)
  - rendered-copy artifacts: leading indentation, missing --- markers, headings
    stripped of '##', hard-wrapped paragraphs -> mechanically repaired, then validated.

Validation is strict on anything that affects ingestion (IDs, exact field values,
controlled vocabularies, headings, anti-drift rules); word counts are soft warnings.
On zero errors, normalized documents are written to data/corpus/<city>/.

Usage: python scripts/validate_corpus.py --city rome [--raw data/corpus_raw/rome.txt]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from make_corpus_prompt import TARGETS_VOCAB, budget_level, cost_level  # noqa: E402

# Unambiguous synonyms -> canonical vocabulary (logged as warnings when applied).
# Anything not in this map is rejected, not guessed.
TARGET_ALIASES = {
    "families": "family", "youth": "young", "young people": "young",
    "sports people": "sporty", "sporty people": "sporty",
    "relax seekers": "relax-seekers", "foodie": "foodies",
}

HOTEL_COST = {"budget": "low", "mid": "medium", "high": "high"}
HEADINGS = {
    "activity": ["Description", "Who it's for", "Practical notes"],
    "hotel": ["Description", "Who it's for", "Practical notes"],
    "destination": ["Overview", "Vibe & who it suits", "When to go", "Getting around"],
    "guide": ["Transport", "Food", "Day-planning tips", "Seasonality"],
}
ALL_HEADINGS = {h for hs in HEADINGS.values() for h in hs}
WORD_RANGES = {"activity": (150, 280), "hotel": (100, 180), "destination": (250, 400), "guide": (300, 450)}
FM_KEYS = {
    "activity": {"id", "type", "city", "country", "category", "interests", "targets",
                 "duration_min", "cost_level", "indoor_outdoor", "booking_recommended"},
    "hotel": {"id", "type", "city", "country", "tier", "max_guests_per_room", "amenities",
              "targets", "cost_level"},
    "destination": {"id", "type", "city", "country", "tags", "budget_level", "best_for"},
    "guide": {"id", "type", "city", "country", "topics"},
}
GUIDE_TOPICS = {"transport", "food", "seasonality", "day-planning"}
TAG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
SEP_RE = re.compile(r"^===\s*FILE:\s*(\S+)\s*===\s*$")
FM_LINE_RE = re.compile(r"^([a-z_]+):(.*)$")

DRIFT_RULES = [
    ("exact price", re.compile(r"[€$£]\s*\d|\d\s*[€$£]|\bEUR\s*\d|\b\d+(?:[.,]\d+)?\s*(?:euros?|eur)\b", re.I)),
    ("clock time / opening hours", re.compile(r"\b\d{1,2}[:.]\d{2}\b|\b\d{1,2}\s*(?:am|pm)\b", re.I)),
    ("URL", re.compile(r"https?://|www\.", re.I)),
    ("availability claim", re.compile(r"\b(?:rooms?|spots?|seats?)\s+(?:left|available|remaining)\b|\bsold[\s-]out\b", re.I)),
]


def norm_apos(s: str) -> str:
    return s.replace("\u2019", "'").strip()


def strip_outer_fence(text: str) -> tuple[str, bool]:
    lines = text.splitlines()
    idx = [i for i, ln in enumerate(lines) if ln.strip()]
    if idx and lines[idx[0]].lstrip().startswith("```") and idx[-1] != idx[0] and lines[idx[-1]].strip().startswith("```"):
        return "\n".join(lines[idx[0] + 1:idx[-1]]), True
    return text, False


def split_docs(text: str) -> tuple[list[tuple[str, str]], list[str]]:
    """Return [(filename, content)] and global warnings."""
    warnings: list[str] = []
    docs: list[tuple[str, str]] = []
    seen: set[str] = set()
    current: str | None = None
    buf: list[str] = []
    preamble: list[str] = []
    for ln in text.splitlines():
        ln = ln.strip()  # contract: no meaningful indentation anywhere
        if ln.startswith("```"):
            warnings.append(f"stray code fence removed: {ln[:30]}")
            continue
        if ln == "CONTINUE":
            warnings.append("CONTINUE marker found (output was truncated?)")
            continue
        m = SEP_RE.match(ln)
        if m:
            if current is not None:
                docs.append((current, "\n".join(buf)))
            current = m.group(1)
            if current in seen:
                warnings.append(f"duplicate separator for {current}")
            seen.add(current)
            buf = []
        elif current is None:
            if ln:
                preamble.append(ln)
        else:
            buf.append(ln)
    if current is not None:
        docs.append((current, "\n".join(buf)))
    if preamble:
        warnings.append(f"preamble before first separator ignored ({len(preamble)} lines)")
    return docs, warnings


def repair_and_parse(content: str, dtype: str) -> tuple[dict, str, bool]:
    """Return (front_matter dict, normalized body, repaired?)."""
    lines = [ln for ln in content.splitlines()]
    while lines and not lines[0]:
        lines.pop(0)
    repaired = False

    if lines and lines[0] == "---":
        end = next((i for i in range(1, len(lines)) if lines[i] == "---"), None)
        if end is None:
            raise ValueError("front matter opened with --- but never closed")
        fm = yaml.safe_load("\n".join(lines[1:end]))
        body_lines = lines[end + 1:]
    else:
        # rendered-copy repair: leading 'key: value' lines are the front matter
        repaired = True
        fm_lines, body_lines = [], []
        in_fm = True
        for ln in lines:
            if in_fm:
                if not ln:
                    continue
                if norm_apos(ln) in ALL_HEADINGS:
                    in_fm = False
                    body_lines.append(ln)
                    continue
                m = FM_LINE_RE.match(ln)
                if m and m.group(1) in FM_KEYS[dtype]:
                    fm_lines.append(ln)
                    continue
                raise ValueError(f"unrecognized line in front-matter region: {ln[:60]!r}")
            else:
                body_lines.append(ln)
        if not fm_lines:
            raise ValueError("no front-matter fields found")
        fm = yaml.safe_load("\n".join(fm_lines))

    if not isinstance(fm, dict):
        raise ValueError("front matter did not parse to a mapping")

    # restore headings + reflow hard-wrapped paragraphs
    out: list[str] = []
    para: list[str] = []

    def flush() -> None:
        if para:
            out.append(" ".join(para))
            out.append("")
            para.clear()

    for ln in body_lines:
        canonical = norm_apos(ln)
        if canonical in ALL_HEADINGS:
            flush()
            if not ln.startswith("## "):
                repaired = True
            out.append(f"## {canonical}")
            out.append("")
        elif not ln:
            flush()
        elif ln.startswith(("- ", "|", "#")):
            flush()
            out.append(ln)
        else:
            para.append(ln)
    flush()
    body = "\n".join(out).strip() + "\n"
    return fm, body, repaired


def validate(fname: str, fm: dict, body: str, dtype: str, city: dict,
             act: dict | None, hot: dict | None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    stem = fname.removesuffix(".md")

    missing = FM_KEYS[dtype] - set(fm)
    extra = set(fm) - FM_KEYS[dtype]
    if missing:
        errors.append(f"missing front-matter fields: {sorted(missing)}")
    if extra:
        errors.append(f"unexpected front-matter fields: {sorted(extra)}")

    def eq(field: str, expected) -> None:
        if field in fm and fm[field] != expected:
            errors.append(f"{field}: {fm[field]!r} != expected {expected!r}")

    eq("id", stem)
    eq("type", dtype)
    eq("city", city["name"])
    eq("country", city["country"])

    def vocab_list(field: str, required: bool = True) -> None:
        v = fm.get(field)
        if not isinstance(v, list) or (required and not v):
            errors.append(f"{field}: must be a non-empty list")
            return
        normalized = []
        for t in v:
            if isinstance(t, str) and t.lower() in TARGET_ALIASES:
                canon = TARGET_ALIASES[t.lower()]
                warnings.append(f"{field}: normalized alias {t!r} -> {canon!r}")
                normalized.append(canon)
            else:
                normalized.append(t)
        fm[field] = normalized  # persisted form uses canonical vocabulary
        bad = [t for t in normalized if t not in TARGETS_VOCAB]
        if bad:
            errors.append(f"{field}: outside controlled vocabulary: {bad}")

    if dtype == "activity":
        assert act is not None
        eq("category", act["category"])
        eq("duration_min", act["duration_min"])
        eq("cost_level", cost_level(act["base_price"]))
        if fm.get("indoor_outdoor") not in {"indoor", "outdoor", "mixed"}:
            errors.append(f"indoor_outdoor: {fm.get('indoor_outdoor')!r} not in indoor/outdoor/mixed")
        if not isinstance(fm.get("booking_recommended"), bool):
            errors.append("booking_recommended: must be true/false (YAML boolean)")
        interests = fm.get("interests")
        if not isinstance(interests, list) or not interests:
            errors.append("interests: must be a non-empty list")
        else:
            bad = [t for t in interests if not isinstance(t, str) or not TAG_RE.match(t)]
            if bad:
                errors.append(f"interests: not lowercase-hyphenated tags: {bad}")
        vocab_list("targets")
    elif dtype == "hotel":
        assert hot is not None
        eq("tier", hot["tier"])
        eq("max_guests_per_room", hot["max_guests_per_room"])
        if set(fm.get("amenities") or []) != set(hot["amenities"]):
            errors.append(f"amenities: {fm.get('amenities')!r} != expected {hot['amenities']!r}")
        eq("cost_level", HOTEL_COST[hot["tier"]])
        vocab_list("targets")
    elif dtype == "destination":
        if set(fm.get("tags") or []) != set(city["tags"]):
            errors.append(f"tags: {fm.get('tags')!r} != expected {city['tags']!r}")
        eq("budget_level", budget_level(city["cost_index"]))
        vocab_list("best_for")
    elif dtype == "guide":
        if set(fm.get("topics") or []) != GUIDE_TOPICS:
            errors.append(f"topics: {fm.get('topics')!r} != expected {sorted(GUIDE_TOPICS)}")

    for h in HEADINGS[dtype]:
        if f"## {h}" not in body.splitlines():
            errors.append(f"missing body heading: '## {h}'")

    words = len(body.split())
    lo, hi = WORD_RANGES[dtype]
    if not lo <= words <= hi:
        warnings.append(f"word count {words} outside {lo}-{hi} (soft rule)")

    for label, rx in DRIFT_RULES:
        m = rx.search(body)
        if m:
            errors.append(f"anti-drift violation ({label}): ...{body[max(0, m.start()-30):m.end()+30]!r}...")

    if city["name"] not in body:
        warnings.append(f"city name '{city['name']}' not mentioned in body (standalone-chunk rule)")
    return errors, warnings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--city", required=True)
    parser.add_argument("--raw", type=Path, default=None)
    parser.add_argument("--inventory", type=Path, default=ROOT / "data" / "inventory.json")
    args = parser.parse_args()

    inv = json.loads(args.inventory.read_text(encoding="utf-8"))
    city = next(c for c in inv["cities"] if c["id"] == args.city)
    acts = {a["id"]: a for a in inv["activities"] if a["city_id"] == args.city}
    hots = {h["id"]: h for h in inv["hotels"] if h["city_id"] == args.city}
    expected: dict[str, str] = {f"{aid}.md": "activity" for aid in acts}
    expected.update({f"{hid}.md": "hotel" for hid in hots})
    expected[f"destination_{args.city}.md"] = "destination"
    expected[f"guide_{args.city}.md"] = "guide"

    raw_path = args.raw or ROOT / "data" / "corpus_raw" / f"{args.city}.txt"
    text, fenced = strip_outer_fence(raw_path.read_text(encoding="utf-8"))
    docs, global_warnings = split_docs(text)
    for w in global_warnings:
        print(f"WARN  [global] {w}")
    if fenced:
        print("INFO  outer code fence stripped")

    got = {f for f, _ in docs}
    missing_files = sorted(set(expected) - got)
    extra_files = sorted(got - set(expected))
    for f in missing_files:
        print(f"ERROR missing document: {f}")
    for f in extra_files:
        print(f"ERROR unexpected document: {f}")

    total_errors = len(missing_files) + len(extra_files)
    total_warnings = len(global_warnings)
    repaired_count = 0
    normalized: dict[str, str] = {}

    for fname, content in docs:
        if fname not in expected:
            continue
        dtype = expected[fname]
        try:
            fm, body, repaired = repair_and_parse(content, dtype)
        except (ValueError, yaml.YAMLError) as e:
            print(f"FAIL  {fname}: {e}")
            total_errors += 1
            continue
        errors, warnings = validate(fname, fm, body, dtype, city,
                                    acts.get(fname.removesuffix(".md")),
                                    hots.get(fname.removesuffix(".md")))
        repaired_count += repaired
        status = "FAIL" if errors else ("WARN" if warnings else "OK  ")
        print(f"{status}  {fname} ({len(body.split())} words{', repaired' if repaired else ''})")
        for e in errors:
            print(f"      ERROR {e}")
        for w in warnings:
            print(f"      warn  {w}")
        total_errors += len(errors)
        total_warnings += len(warnings)
        fm_yaml = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True).strip()
        normalized[fname] = f"---\n{fm_yaml}\n---\n\n{body}"

    print(f"\nSummary: {len(docs)}/{len(expected)} documents, {total_errors} errors, "
          f"{total_warnings} warnings, {repaired_count} repaired")
    if total_errors:
        print("NOT WRITTEN - fix errors first (data/corpus untouched)")
        sys.exit(1)

    out_dir = ROOT / "data" / "corpus" / args.city
    out_dir.mkdir(parents=True, exist_ok=True)
    for fname, content in normalized.items():
        (out_dir / fname).write_text(content, encoding="utf-8")
    print(f"WROTE {len(normalized)} validated documents -> {out_dir}")


if __name__ == "__main__":
    main()
