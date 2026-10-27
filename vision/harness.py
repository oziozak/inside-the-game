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

`add_noise` then makes clean observations look like a real video stage's
(see NOISE): position noise, dropped detections, identity swaps between
nearby players, merged boxes, ball occlusion and varying confidence.

Usage:
    python -m vision.harness TRACKING.jsonl MATCH_INFO.json --out OBSERVATIONS.jsonl
    python -m vision.harness ... --noise swaps=0.3 --noise occlusion=0.1
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from dataclasses import replace
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


# ---- noise: what a real video stage gets wrong -----------------------------
CLOSE_M = 1.0               # players this close can be swapped or merged into one box, and hide the ball
DRIFT_KEEP = 0.998          # position noise: share of a track's offset kept from one frame to the next
JITTER_SHARE = 1 / 12       # ... plus per-frame jitter of this share of the level
DROP_MAX_FRAMES = 5         # a dropped detection stays missing 1 to this many frames
OCCLUDE_MAX_FRAMES = 12     # the ball stays hidden behind a player 1 to this many frames
FIRST_NEW_TRACK = 10_000    # track ids handed out to tracks that come back after a merge


def _close_pairs(players: list[PlayerObservation]) -> set[tuple[int, int]]:
    """Track id pairs (lower first) of players within CLOSE_M of each other."""
    by_x = sorted(players, key=lambda p: p.pos[0])
    out = set()
    for i, a in enumerate(by_x):
        for b in by_x[i + 1:]:
            if b.pos[0] - a.pos[0] > CLOSE_M:
                break
            if math.dist(a.pos, b.pos) <= CLOSE_M:
                out.add((min(a.track_id, b.track_id), max(a.track_id, b.track_id)))
    return out


def _position_noise(frames: list[FrameObservation], sigma_m: float, rng: random.Random):
    """Each track carries an offset of about `sigma_m` per axis that drifts
    slowly, plus small per-frame jitter, as a detector's foot point does; the
    ball's is half that."""
    offset: dict = {}
    drift = math.sqrt(1 - DRIFT_KEEP ** 2)

    def moved(key, pos, sigma):
        ox, oy = offset.get(key) or (rng.gauss(0, sigma), rng.gauss(0, sigma))
        ox, oy = DRIFT_KEEP * ox + rng.gauss(0, sigma * drift), DRIFT_KEEP * oy + rng.gauss(0, sigma * drift)
        offset[key] = ox, oy
        jitter = sigma * JITTER_SHARE
        return pos[0] + ox + rng.gauss(0, jitter), pos[1] + oy + rng.gauss(0, jitter)

    out = []
    for f in frames:
        players = [replace(p, pos=moved(p.track_id, p.pos, sigma_m)) for p in f.players]
        ball = f.ball and replace(f.ball, pos=moved("ball", f.ball.pos, sigma_m / 2))
        out.append(replace(f, players=players, ball=ball))
    return out


def _dropped(frames: list[FrameObservation], rate: float, rng: random.Random):
    """Players go missing for 1-DROP_MAX_FRAMES frames at a time, about
    `rate` of all detections, and come back under the same track id."""
    start = rate / ((1 + DROP_MAX_FRAMES) / 2)      # so about `rate` of detections are dropped
    gone: dict[int, int] = {}                       # track -> frames left missing
    out = []
    for f in frames:
        players = []
        for p in f.players:
            if gone.get(p.track_id, 0) == 0 and rng.random() < start:
                gone[p.track_id] = rng.randint(1, DROP_MAX_FRAMES)
            if gone.get(p.track_id, 0) > 0:
                gone[p.track_id] -= 1
            else:
                players.append(p)
        out.append(replace(f, players=players))
    return out


def _swaps(frames: list[FrameObservation], chance: float, rng: random.Random):
    """When two players come within CLOSE_M, with probability `chance` their
    tracks swap players. Team and keeper flags stay with the players: the
    video stage reads them from kit colors."""
    shown: dict[int, int] = {}                      # player (clean track) -> track id shown
    close: set = set()
    out = []
    for f in frames:
        now = _close_pairs(f.players)
        for a, b in sorted(now - close):
            if rng.random() < chance:
                shown[a], shown[b] = shown.get(b, b), shown.get(a, a)
        close = now
        out.append(replace(f, players=[replace(p, track_id=shown.get(p.track_id, p.track_id))
                                       for p in f.players]))
    return out


def _merged(frames: list[FrameObservation], chance: float, rng: random.Random):
    """When two players come within CLOSE_M, with probability `chance` the
    detector boxes them as one for as long as they stay that close: one track
    (one player's id and kit) at their midpoint, the other gone. When they
    part, the hidden player comes back under a new track id."""
    hidden: dict[int, int] = {}                     # hidden player -> the player whose box covers it
    shown: dict[int, int] = {}                      # player -> track id shown, after coming back
    next_id = FIRST_NEW_TRACK
    close: set = set()
    out = []
    for f in frames:
        at = {p.track_id: p for p in f.players}
        now = _close_pairs(f.players)
        for b, a in list(hidden.items()):           # parted (or gone): the hidden one is back
            if (min(a, b), max(a, b)) not in now:
                del hidden[b]
                shown[b], next_id = next_id, next_id + 1
        busy = set(hidden) | set(hidden.values())
        for pair in sorted(now - close):
            if not busy & set(pair) and rng.random() < chance:
                a, b = pair if rng.random() < 0.5 else pair[::-1]
                hidden[b] = a
                busy |= set(pair)
        close = now
        players = []
        for p in f.players:
            if p.track_id in hidden:
                continue
            cover = [at[b].pos for b, a in hidden.items() if a == p.track_id and b in at]
            pos = ((p.pos[0] + cover[0][0]) / 2, (p.pos[1] + cover[0][1]) / 2) if cover else p.pos
            players.append(replace(p, track_id=shown.get(p.track_id, p.track_id), pos=pos))
        out.append(replace(f, players=players))
    return out


def _occlusion(frames: list[FrameObservation], chance: float, rng: random.Random):
    """While the ball is within CLOSE_M of a player, each frame it goes behind
    them with probability `chance`, hidden for 1-OCCLUDE_MAX_FRAMES frames
    (`ball_visible` false, no position)."""
    left = 0
    out = []
    for f in frames:
        if left == 0 and f.ball is not None and rng.random() < chance and any(
                math.dist(p.pos, f.ball.pos) <= CLOSE_M for p in f.players):
            left = rng.randint(1, OCCLUDE_MAX_FRAMES)
        if left > 0:
            left -= 1
            f = replace(f, ball=None, ball_visible=False)
        out.append(f)
    return out


def _confidence(frames: list[FrameObservation], low: float, rng: random.Random):
    """Every detection's confidence drawn uniformly from [low, 1]."""
    return [replace(f, ball=f.ball and replace(f.ball, confidence=rng.uniform(low, 1.0)),
                    players=[replace(p, confidence=rng.uniform(low, 1.0)) for p in f.players])
            for f in frames]


# Variant -> (function, what its level is).
NOISE = {"position": (_position_noise, "offset per axis, meters"),
         "dropped": (_dropped, "share of player detections missing"),
         "swaps": (_swaps, "chance two players coming within CLOSE_M swap tracks"),
         "merged": (_merged, "chance two players coming within CLOSE_M merge into one box"),
         "occlusion": (_occlusion, "chance per frame near a player that the ball hides"),
         "confidence": (_confidence, "lowest detection confidence")}


def add_noise(frames: list[FrameObservation], variant: str, level: float,
              seed: int = 0) -> list[FrameObservation]:
    """Clean observations with one NOISE variant applied at `level` (seeded).
    Swaps and merges assume one track per player, as observations_from_tracking
    builds them."""
    return NOISE[variant][0](list(frames), level, random.Random(seed))


def main(argv: list[str] | None = None) -> int:
    """Write the observations for one tracking file."""
    ap = argparse.ArgumentParser(prog="python -m vision.harness", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tracking", type=Path, help="simulator tracking.jsonl")
    ap.add_argument("match_info", type=Path, help="the match's match_info.json")
    ap.add_argument("--out", type=Path, required=True, help="where to write the observations")
    ap.add_argument("--seed", type=int, default=0, help="seed for the track-id shuffle and the noise")
    ap.add_argument("--noise", action="append", default=[], metavar="VARIANT=LEVEL",
                    help=f"add noise, in order (repeatable); variants: {', '.join(NOISE)}")
    args = ap.parse_args(argv)
    lines = args.tracking.read_text(encoding="utf-8").splitlines()
    tracking = [json.loads(line) for line in lines if line.strip()]
    team_sheet = json.loads(args.match_info.read_text(encoding="utf-8"))
    frames = observations_from_tracking(tracking, team_sheet, args.seed)
    for spec in args.noise:
        variant, _, level = spec.partition("=")
        if variant not in NOISE or not level:
            ap.error(f"--noise {spec}: expected VARIANT=LEVEL, VARIANT one of {', '.join(NOISE)}")
        frames = add_noise(frames, variant, float(level), args.seed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_observations(args.out, frames)
    print(f"Wrote {len(frames)} frames to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
