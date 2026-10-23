"""Seam-2 harness: frame observations built from simulator tracking, no video.

Offline and test-only. It reads simulator tracking, so no other vision code
may import it (tests/test_vision_rules.py enforces this). It stands in for the
video stage so the event rules can be built and graded in seconds:

- each roster player becomes an anonymous track (ids handed out in order of
  first appearance, shuffled with a fixed seed within a frame);
- team and goalkeeper flags come from the tracking and the team sheet, as the
  video stage would get them from kit colors;
- the ball keeps only its ground projection: the video stage cannot recover
  its height.

Usage:
    python -m vision.harness TRACKING.jsonl MATCH_INFO.json --out OBSERVATIONS.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Iterable

from vision.observation import Ball, FrameObservation, PlayerObservation, write_observations


def _period_at(t: float, team_sheet: dict) -> int:
    """The period a time falls in, from the team sheet's periods."""
    for p in team_sheet["periods"]:
        if t <= p["end"]:
            return p["period"]
    return team_sheet["periods"][-1]["period"]


def _goalkeepers(team_sheet: dict) -> set[int]:
    """Roster ids of every goalkeeper on the team sheet."""
    return {p["id"] for side in ("home", "away") for p in team_sheet[side]["players"]
            if p["pos"] == "GK"}


def observations_from_tracking(tracking: Iterable[dict], team_sheet: dict,
                               seed: int = 0) -> list[FrameObservation]:
    """Clean frame observations from simulator tracking frames.

    Every player and the ball are seen in every frame with confidence 1.0.
    Roster ids are replaced by anonymous track ids 0, 1, 2, ...
    """
    rng = random.Random(seed)
    keepers = _goalkeepers(team_sheet)
    track_of: dict[int, int] = {}
    out = []
    for fr in tracking:
        new = [p["id"] for p in fr["players"] if p["id"] not in track_of]
        rng.shuffle(new)
        for pid in new:
            track_of[pid] = len(track_of)
        players = [PlayerObservation(track_id=track_of[p["id"]], team=p["team"],
                                     goalkeeper=p["id"] in keepers,
                                     pos=(float(p["pos"][0]), float(p["pos"][1])), confidence=1.0)
                   for p in fr["players"]]
        bx, by = fr["ball"][:2]
        out.append(FrameObservation(
            frame=fr["frame"], t=fr["t"], period=fr.get("period") or _period_at(fr["t"], team_sheet),
            ball=Ball(pos=(float(bx), float(by)), confidence=1.0), ball_visible=True,
            players=players))
    return out


def main(argv: list[str] | None = None) -> int:
    """Write the observations for one tracking file."""
    ap = argparse.ArgumentParser(prog="python -m vision.harness", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tracking", type=Path, help="simulator tracking.jsonl")
    ap.add_argument("match_info", type=Path, help="the match's match_info.json")
    ap.add_argument("--out", type=Path, required=True, help="where to write the observations")
    ap.add_argument("--seed", type=int, default=0, help="seed for the track-id shuffle")
    args = ap.parse_args(argv)
    lines = args.tracking.read_text(encoding="utf-8").splitlines()
    tracking = [json.loads(line) for line in lines if line.strip()]
    team_sheet = json.loads(args.match_info.read_text(encoding="utf-8"))
    frames = observations_from_tracking(tracking, team_sheet, args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_observations(args.out, frames)
    print(f"Wrote {len(frames)} frames to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
