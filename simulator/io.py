"""Writing simulator outputs: match_info.json, events.json, tracking.jsonl."""

from __future__ import annotations

import json
from pathlib import Path


def write_json(path: Path, obj):
    """Write obj as indented UTF-8 JSON, creating parent folders."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows):
    """Write rows as JSON Lines (one compact object per line)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
