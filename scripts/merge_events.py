"""Merge detected events with the simulator's invisible event types into one events.json.

Usage:
    python scripts/merge_events.py DETECTED TRUTH --out OUT
    python scripts/merge_events.py runs/m007/events.json data/generated/m007/events.json \
        --out data/generated/m007_cv/events.json

DETECTED is the vision AI's events.json (source: cv). TRUTH is the simulator's events.json;
only the types video cannot see are taken from it (source: sim). The merge lives here, outside
vision/, so the vision code never opens simulator files.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

INVISIBLE_TYPES = ("foul", "yellow_card", "red_card", "offside", "substitution")


def merge(detected: list[dict], truth: list[dict]) -> list[dict]:
    """Detected events plus the invisible-type true events, sorted by t, ids renumbered e0001...

    Detected events must all be source cv and none of the invisible types; both files must be
    from the same match. Added true events are labelled source sim with confidence 1.0. On equal
    t the sim event comes first (a foul comes before what follows it). Every other field is kept
    as it is. The inputs are not modified. Raises ValueError if the inputs break these rules.
    """
    not_cv = [e["id"] for e in detected if e.get("source") != "cv"]
    if not_cv:
        raise ValueError(f"detected events must have source 'cv' (not: {', '.join(not_cv[:5])}); "
                         "are the detected and true files swapped?")
    invisible = [f"{e['id']} ({e['type']})" for e in detected if e["type"] in INVISIBLE_TYPES]
    if invisible:
        raise ValueError(f"detected events must not include {', '.join(INVISIBLE_TYPES)}; "
                         f"they come from the true events (found: {', '.join(invisible[:5])})")
    match_ids = sorted({e["match_id"] for e in [*detected, *truth]})
    if len(match_ids) > 1:
        raise ValueError(f"the files are from different matches (match_id: {', '.join(match_ids)})")
    added = [{**e, "source": "sim", "confidence": 1.0} for e in truth if e["type"] in INVISIBLE_TYPES]
    events = [*detected, *added]
    events.sort(key=lambda e: (e["t"], e["source"] == "cv"))
    return [{**e, "id": f"e{i:04d}"} for i, e in enumerate(events, start=1)]


def main(argv: list[str] | None = None) -> int:
    """Read DETECTED and TRUTH, write the merged events to --out. Returns the exit code."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("detected", type=Path, help="detected events (source: cv)")
    ap.add_argument("truth", type=Path, help="simulator's true events (source: sim)")
    ap.add_argument("--out", type=Path, required=True, help="merged events.json to write")
    args = ap.parse_args(argv)

    detected = json.loads(args.detected.read_text(encoding="utf-8"))
    truth = json.loads(args.truth.read_text(encoding="utf-8"))
    try:
        events = merge(detected, truth)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(events, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(detected)} detected + {len(events) - len(detected)} from truth -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
