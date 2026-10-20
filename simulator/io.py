"""Writing simulator outputs: match_info.json, events.json, tracking.jsonl."""

from __future__ import annotations

import json
from pathlib import Path


def write_json(path: Path, obj):
    """Write obj as indented UTF-8 JSON, creating parent folders."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows) -> int:
    """Write rows (any iterable, e.g. a generator) as JSON Lines, one compact
    object per line. Returns the number of rows written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
            n += 1
    return n


def write_match(out_dir: Path, m, tracking: bool = True, start: float = 0.0,
                end: float | None = None) -> dict:
    """Write a played match to out_dir: match_info.json, events.json and
    (unless tracking=False) tracking.jsonl for start <= t < end (seconds;
    end defaults to full time). Returns {file name: path}."""
    from .movement import iter_tracking         # local import: movement imports engine

    out_dir = Path(out_dir)
    written = {"match_info.json": out_dir / "match_info.json", "events.json": out_dir / "events.json"}
    write_json(written["match_info.json"], m.match_info())
    write_json(written["events.json"], m.events)
    if tracking:
        stop = m.t if end is None else min(end, m.t)
        written["tracking.jsonl"] = out_dir / "tracking.jsonl"
        write_jsonl(written["tracking.jsonl"], iter_tracking(m, start, stop))
    return written
