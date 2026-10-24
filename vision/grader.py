"""Grader: score detected events against true events and write vision_report.json.

Offline only. This is the one piece of vision code allowed to read simulator
events, and nothing on the runtime path imports it.

A detected event matches a true event of the same type when their times are
within TIME_TOL_S and their start points within DIST_TOL_M. Matching is
one-to-one and closest first.

Usage:
    python -m vision.grader --detected runs/clip/events.json \
        --truth data/generated/m007/events.json \
        --manifest data/renders/m007.mp4.manifest.json --seed 7 \
        --training-seeds 1 2 3 --out runs/clip/vision_report.json

Render settings and seeds are read from the export manifest when it has them;
--render KEY=VALUE, --seed and --training-seeds add to or override them.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

TIME_TOL_S = 0.5
DIST_TOL_M = 5.0

# Event types the v1 vision pipeline detects; the CLI grades these by default.
DETECTED_TYPES = ["kickoff", "pass", "possession_change", "shot", "goal"]

# Detected types that carry a subtype (detected goals and kickoffs have none);
# matched.subtype_accuracy grades these.
SUBTYPE_TYPES = ["pass", "possession_change", "shot"]

# Types whose `to` names a second player (schemas/README.md); for the rest
# (shot, goal, clearance, offside, cards) only `from` identifies the player.
TYPES_WITH_TO = {"pass", "throw_in", "goal_kick", "corner", "free_kick", "kickoff",
                 "possession_change", "foul", "substitution"}


def _gap(det: dict, true: dict) -> tuple[float, float]:
    """Time (s) and start-point distance (m) between two events."""
    return abs(det["t"] - true["t"]), math.dist(det["start"], true["start"])


def match_events(detected: list[dict], truth: list[dict]) -> list[tuple[dict, dict]]:
    """Pair detected with true events of the same type, one-to-one, closest first.

    Candidate pairs within both tolerances are ranked by their combined gap,
    each normalised by its tolerance, and taken greedily.
    """
    candidates = []
    for i, d in enumerate(detected):
        for j, t in enumerate(truth):
            if d["type"] != t["type"]:
                continue
            dt, dx = _gap(d, t)
            if dt <= TIME_TOL_S and dx <= DIST_TOL_M:
                candidates.append((dt / TIME_TOL_S + dx / DIST_TOL_M, i, j))
    used_d, used_t, pairs = set(), set(), []
    for _, i, j in sorted(candidates):
        if i not in used_d and j not in used_t:
            used_d.add(i)
            used_t.add(j)
            pairs.append((detected[i], truth[j]))
    return sorted(pairs, key=lambda p: p[1]["t"])


def _scores(n_det: int, n_true: int, n_matched: int) -> dict:
    """Counts plus precision, recall and F1 (None where undefined, e.g. no events at all)."""
    precision = n_matched / n_det if n_det else None
    recall = n_matched / n_true if n_true else None
    if precision is None and recall is None:
        f1 = None
    elif precision and recall:
        f1 = 2 * precision * recall / (precision + recall)
    else:
        f1 = 0.0
    return {"detected": n_det, "true": n_true, "matched": n_matched,
            "precision": precision, "recall": recall, "f1": f1}


def _same_players(det: dict, true: dict) -> bool:
    """Whether a matched detection names the right player(s): `from`, plus `to`
    for types where `to` is a player."""
    if det.get("from") != true.get("from"):
        return False
    return true["type"] not in TYPES_WITH_TO or det.get("to") == true.get("to")


def _mean(values: list[float]) -> float | None:
    """Arithmetic mean, or None for an empty list."""
    return sum(values) / len(values) if values else None


def _matched_metrics(pairs: list[tuple[dict, dict]]) -> dict:
    """Accuracy and mean absolute errors over matched (detected, true) pairs.

    A player id is correct when `from` agrees, and `to` too for types that
    have one (see TYPES_WITH_TO). Pass success is
    scored over matched passes; subtype accuracy, per type in SUBTYPE_TYPES,
    over pairs whose true event has a subtype; distance and speed errors over pairs where
    both events carry the number.
    """
    def abs_errors(key):
        return [abs(d[key] - t[key]) for d, t in pairs if key in d and key in t]

    passes = [(d, t) for d, t in pairs if t["type"] == "pass" and "success" in t]
    with_subtype = [(d, t) for d, t in pairs if "subtype" in t and t["type"] in SUBTYPE_TYPES]
    subtype_types = list(dict.fromkeys(t["type"] for _, t in with_subtype))
    return {
        "count": len(pairs),
        "player_id_accuracy": _mean([float(_same_players(d, t)) for d, t in pairs]),
        "pass_success_accuracy": _mean([float(d.get("success") == t["success"]) for d, t in passes]),
        "subtype_accuracy": {ty: _mean([float(d.get("subtype") == t["subtype"])
                                        for d, t in with_subtype if t["type"] == ty])
                             for ty in subtype_types},
        "mean_abs_time_error_s": _mean(abs_errors("t")),
        "mean_abs_distance_error_m": _mean(abs_errors("distance_m")),
        "mean_abs_speed_error_kmh": _mean(abs_errors("speed_kmh")),
    }


def _brief(e: dict) -> dict:
    """The fields of an event that identify it in the report's lists."""
    return {"id": e["id"], "type": e["type"], "t": e["t"], "start": e["start"]}


def grade(detected: list[dict], truth: list[dict], types: list[str] | None = None) -> dict:
    """Grade detected events against true events; returns the report body.

    Only events whose type is in `types` are graded; None grades every type
    that appears in either list.
    """
    if types is None:
        types = sorted({e["type"] for e in detected} | {e["type"] for e in truth})
    detected = [e for e in detected if e["type"] in types]
    truth = [e for e in truth if e["type"] in types]
    pairs = match_events(detected, truth)
    matched_d = {id(d) for d, _ in pairs}
    matched_t = {id(t) for _, t in pairs}
    per_type = {
        ty: _scores(sum(e["type"] == ty for e in detected), sum(e["type"] == ty for e in truth),
                    sum(t["type"] == ty for _, t in pairs))
        for ty in types
    }
    return {
        "types": list(types),
        "tolerance": {"time_s": TIME_TOL_S, "distance_m": DIST_TOL_M},
        "per_type": per_type,
        "matched": _matched_metrics(pairs),
        "unmatched_detections": [_brief(e) for e in detected if id(e) not in matched_d],
        "missed": [_brief(e) for e in truth if id(e) not in matched_t],
    }


def _value(text: str):
    """A --render value: JSON when it parses (2, true, "x"), else the raw string."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def clip_info(manifest: dict | None, render: dict, seed: int | None,
              training_seeds: list[int] | None) -> dict:
    """The clip's render settings, window and seeds, for reproducing the grade.

    Starts from the export manifest (its `render` block plus frame size and
    rich mode) and lets explicitly passed values win.
    """
    manifest = manifest or {}
    settings = dict(manifest.get("render", {}))
    settings.update({k: manifest[k] for k in ("width", "height", "rich") if k in manifest})
    settings.update(render)
    return {
        "match_id": manifest.get("match_id"),
        "start": manifest.get("start"),
        "end": manifest.get("end"),
        "render": settings,
        "seed": seed if seed is not None else manifest.get("seed"),
        "training_seeds": training_seeds if training_seeds is not None else manifest.get("training_seeds"),
    }


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse the command-line arguments."""
    ap = argparse.ArgumentParser(prog="python -m vision.grader", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--detected", type=Path, required=True, help="detected events (source: cv)")
    ap.add_argument("--truth", type=Path, required=True, help="true events from the simulator")
    ap.add_argument("--out", type=Path, required=True, help="where to write vision_report.json")
    ap.add_argument("--manifest", type=Path, help="the clip's renderer export manifest")
    ap.add_argument("--render", action="append", default=[], metavar="KEY=VALUE",
                    help="a render setting, e.g. ballScale=2 (repeatable)")
    ap.add_argument("--seed", type=int, help="simulator seed of the graded clip")
    ap.add_argument("--training-seeds", type=int, nargs="*", help="seeds used to train the detector")
    ap.add_argument("--types", default=",".join(DETECTED_TYPES),
                    help="comma-separated event types to grade, or 'all' (default: the v1 detected types)")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Grade from the command line and write the report; returns the exit code."""
    args = parse_args(argv)
    render = {}
    for item in args.render:
        key, sep, value = item.partition("=")
        if not sep or not key:
            print(f"error: --render expects KEY=VALUE, got {item!r}", file=sys.stderr)
            return 2
        render[key] = _value(value)
    detected = json.loads(args.detected.read_text(encoding="utf-8"))
    truth = json.loads(args.truth.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8")) if args.manifest else None
    types = None if args.types == "all" else [t.strip() for t in args.types.split(",") if t.strip()]

    clip = clip_info(manifest, render, args.seed, args.training_seeds)
    if clip["seed"] is None:
        print("warning: no clip seed (pass --seed); the report records null", file=sys.stderr)
    report = {
        "match_id": truth[0]["match_id"] if truth else None,
        "detected_file": str(args.detected),
        "truth_file": str(args.truth),
        "clip": clip,
        **grade(detected, truth, types),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    def fmt(x):
        """A score for the console summary."""
        return "  -  " if x is None else f"{x:.3f}"

    for ty, s in report["per_type"].items():
        print(f"{ty:<18} P {fmt(s['precision'])}  R {fmt(s['recall'])}  F1 {fmt(s['f1'])}"
              f"  ({s['matched']}/{s['true']} true, {s['detected']} detected)")
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
