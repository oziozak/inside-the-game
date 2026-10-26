"""Measure NAME_MIN_CONFIDENCE (agents/director.py) on the dev footage clips.

Usage:
    python scripts/name_threshold.py                     # dev1 dev2 dev3
    python scripts/name_threshold.py dev1 dev2 --runs ~/itg/runs/footage --footage ~/itg/data/renders/footage

Detects each clip's events from its saved frame observations (runs/footage/<clip>/observations.jsonl,
written by `python -m vision.grade_footage --role dev`) with the current event rules and the clip's team
sheet, reads its true events (data/renders/footage/<clip>/truth/events.json), pairs them with the vision
grader and pools the clips. Every detection gets an outcome: its player ids are right or wrong, it has
no player, or it is unmatched (no true event near it). Prints, per threshold, the share of detected
events below it (team-named) and the player-id accuracy of the matched events at or above it (named),
then the detections below the agents' current NAME_MIN_CONFIDENCE. Offline only: it reads simulator truth.

Event confidence measures detection, not identity, so the threshold is a safety floor chosen where the
clearly bad detections end (agents/README.md, "Naming players"), not a precision dial.
Only dev clips are accepted: test1 is the held-out grade and is never used to choose.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.director import NAME_MIN_CONFIDENCE  # noqa: E402
from vision.footage import OUT as FOOTAGE, load_record  # noqa: E402
from vision.grader import DETECTED_TYPES, _same_players, match_events  # noqa: E402
from vision.observation import read_observations  # noqa: E402
from vision.rules import detect_events  # noqa: E402

RUNS = ROOT / "runs" / "footage"
TABLE_STEPS = [round(0.05 * i, 2) for i in range(21)]


def outcomes(detected: list[dict], truth: list[dict]) -> list[tuple[float, str]]:
    """(confidence, outcome) for every detected event of the types the vision AI detects, in order:
    "right" or "wrong" player ids (as the vision grader scores them), "no player", or "unmatched"."""
    detected = [e for e in detected if e["type"] in DETECTED_TYPES]
    truth = [e for e in truth if e["type"] in DETECTED_TYPES]
    paired = {id(d): t for d, t in match_events(detected, truth)}

    def outcome(d: dict) -> str:
        if id(d) not in paired:
            return "unmatched"
        if d.get("from") is None:
            return "no player"
        return "right" if _same_players(d, paired[id(d)]) else "wrong"

    return [(d["confidence"], outcome(d)) for d in detected]


def measure(graded: list[tuple[float, str]], threshold: float) -> dict:
    """What a threshold does: the share of detected events below it (team-named) and their outcomes,
    and the player-id accuracy of the matched events with a player at or above it (named)."""
    below = Counter(o for c, o in graded if c < threshold)
    named = [o == "right" for c, o in graded if c >= threshold and o in ("right", "wrong")]
    return {"threshold": threshold, "detected": len(graded),
            "share_below": sum(below.values()) / len(graded) if graded else None, "below": dict(below),
            "named": len(named), "player_id_accuracy_named": sum(named) / len(named) if named else None}


def main(argv: list[str] | None = None) -> int:
    """Command line; returns the exit code."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clips", nargs="*", default=["dev1", "dev2", "dev3"], help="dev clip names")
    ap.add_argument("--runs", type=Path, default=RUNS, help=f"saved observations root (default {RUNS})")
    ap.add_argument("--footage", type=Path, default=FOOTAGE,
                    help=f"footage root with match_info.json and truth/ (default {FOOTAGE})")
    args = ap.parse_args(argv)

    roles = {c["name"]: c["role"] for c in load_record()["clips"]}
    not_dev = [n for n in args.clips if roles.get(n) != "dev"]
    if not_dev:
        print(f"error: only dev clips may choose the threshold (not: {', '.join(not_dev)})", file=sys.stderr)
        return 2
    graded = []
    for name in args.clips:
        clip = args.footage.expanduser() / name
        team_sheet = json.loads((clip / "match_info.json").read_text("utf-8"))
        detected = detect_events(read_observations(args.runs.expanduser() / name / "observations.jsonl"), team_sheet)
        truth = json.loads((clip / "truth" / "events.json").read_text("utf-8"))
        g = outcomes(detected, truth)
        graded += g
        print(f"{name}: {len(g)} detected, {dict(Counter(o for _, o in g))}")
    print("\nthreshold  share below  named  player-id accuracy (named)")
    for t in TABLE_STEPS:
        m = measure(graded, t)
        acc = "-" if m["player_id_accuracy_named"] is None else f"{m['player_id_accuracy_named']:.3f}"
        print(f"{t:9.2f}  {m['share_below']:11.3f}  {m['named']:5d}  {acc}")
    print(f"\nlowest detections: {sorted(graded)[:10]}")
    print(f"NAME_MIN_CONFIDENCE = {NAME_MIN_CONFIDENCE}: {json.dumps(measure(graded, NAME_MIN_CONFIDENCE))}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
