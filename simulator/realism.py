"""Realism report: are simulated matches football-like, and is tracking sane?

    python -m simulator.realism --matches 40 [--seed 1000] [--jobs 8] [--no-tracking]

Plays N full matches (match i: seed + i, cycling through every ordered
pairing of the teams in simulator/teams/), then prints mean and standard
deviation per event type against real-football norms and runs the tracking
checks below on every frame. Exits with code 1 if any check fails.

Checks:
    event means      every type with a norm averages inside its range (config.NORMS)
    pass accuracy    mean share of successful passes inside PASS_ACCURACY
    max speed        no player moves faster than MAX_SPEED between frames,
                     except across the half-time cut
    nearest player   at >= NEAREST_MIN of passes and shots, the player nearest
                     the ball is the event's player
    set pieces       every set-piece taker is within SET_PIECE_RADIUS of the ball
    players on pitch 7-11 per team in every frame
    ball on pitch    the ball is always within BALL_MARGIN of the pitch
"""

from __future__ import annotations

import argparse
import math
import os
import statistics
import sys
import time
from collections import Counter
from itertools import permutations
from multiprocessing import Pool

from .config import ALL_TYPES, FPS, NORMS, L, W
from .engine import Match
from .movement import iter_tracking
from .teams import list_teams, load_team

PASS_ACCURACY = (0.75, 0.87)
MAX_SPEED = 11.0            # m/s
NEAREST_MIN = 0.95
SET_PIECE_RADIUS = 1.0      # m
SET_PIECES = ("kickoff", "throw_in", "corner", "goal_kick", "free_kick")
PLAYERS_PER_TEAM = (7, 11)
BALL_MARGIN = 1.0           # m


def pairings() -> list[tuple[str, str]]:
    """Every ordered (home, away) pairing of the available teams, sorted."""
    return list(permutations(list_teams(), 2))


def check_tracking(m: Match) -> dict:
    """Run the tracking checks over every frame of a played match.

    Returns the raw numbers (max speed, nearest-player hits, set-piece
    misses, player-count and ball-position violations) for aggregation."""
    # Events to check, keyed by the frame they happen in.
    at_frame: dict[int, list] = {}
    for e in m.events:
        if e["from"] is not None and (e["type"] in ("pass", "shot") or e["type"] in SET_PIECES):
            at_frame.setdefault(int(round(e["t"] * FPS)), []).append(e)

    out = dict(max_speed=0.0, max_speed_at=None, nearest_ok=0, nearest_n=0,
               set_piece_n=0, set_piece_bad=[], count_bad=[], ball_bad=[])
    prev: dict[int, list] = {}
    prev_period = None
    for f in iter_tracking(m, 0, m.t):
        cur = {p["id"]: p["pos"] for p in f["players"]}
        # Speed: compare with the previous frame, but not across the half-time cut.
        if f["period"] == prev_period:
            for pid, (x, y) in cur.items():
                q = prev.get(pid)
                if q is not None:
                    v = math.hypot(x - q[0], y - q[1]) * FPS
                    if v > out["max_speed"]:
                        out["max_speed"], out["max_speed_at"] = v, (f["t"], pid)
        prev, prev_period = cur, f["period"]

        counts = Counter(p["team"] for p in f["players"])
        lo, hi = PLAYERS_PER_TEAM
        if not all(lo <= counts[t] <= hi for t in ("home", "away")):
            out["count_bad"].append((f["t"], dict(counts)))
        bx, by, _ = f["ball"]
        if not (-BALL_MARGIN <= bx <= L + BALL_MARGIN and -BALL_MARGIN <= by <= W + BALL_MARGIN):
            out["ball_bad"].append((f["t"], bx, by))

        for e in at_frame.get(f["frame"], ()):
            ball = f["ball"][:2]
            if e["type"] in ("pass", "shot"):
                nearest = min(cur, key=lambda pid: math.dist(cur[pid], ball))
                out["nearest_n"] += 1
                out["nearest_ok"] += nearest == e["from"]
            else:
                out["set_piece_n"] += 1
                pos = cur.get(e["from"])
                if pos is None or math.dist(pos, ball) > SET_PIECE_RADIUS:
                    out["set_piece_bad"].append((e["id"], e["type"], e["t"]))
    return out


def play_one(job: tuple) -> dict:
    """Play match i of the report (seed + i, pairing i) and measure it.
    Top-level so it can run in a worker process."""
    i, seed, half_len, tracking = job
    home, away = pairings()[i % len(pairings())]
    m = Match(seed + i, half_len, "full", f"realism_{i:03d}",
              home=load_team(home), away=load_team(away))
    m.play()
    passes = [e for e in m.events if e["type"] == "pass"]
    res = dict(i=i, seed=seed + i, home=home, away=away, score=dict(m.score),
               counts=Counter(e["type"] for e in m.events),
               pass_acc=sum(e["success"] for e in passes) / max(1, len(passes)))
    if tracking:
        res["tracking"] = check_tracking(m)
    return res


def run(matches: int, seed: int, jobs: int, tracking: bool, half_len: float = 2700) -> list[dict]:
    """Play the report's matches (in parallel; results are in match order,
    so the report does not depend on the number of jobs)."""
    work = [(i, seed, half_len, tracking) for i in range(matches)]
    if jobs <= 1:
        return [play_one(w) for w in work]
    with Pool(jobs) as pool:
        return pool.map(play_one, work)


def summarize(results: list[dict], half_len: float = 2700) -> list[tuple[str, bool, str]]:
    """Print the event table and return the checks as (name, passed, detail)."""
    scale = 5400 / (2 * half_len)
    checks = []
    print(f"{'type':20}{'mean':>8}{'sd':>8}   {'norm':10} status")
    for t in ALL_TYPES:
        vals = [r["counts"][t] * scale for r in results]
        mean = statistics.fmean(vals)
        sd = statistics.stdev(vals) if len(vals) > 1 else 0.0
        status, norm = "", ""
        if t in NORMS:
            lo, hi = NORMS[t]
            norm = f"{lo}-{hi}"
            ok = lo <= mean <= hi
            status = "ok" if ok else "OUT OF RANGE"
            checks.append((f"mean {t} per 90 in {norm}", ok, f"{mean:.1f}"))
        print(f"{t:20}{mean:8.1f}{sd:8.1f}   {norm:10} {status}")
    acc = statistics.fmean(r["pass_acc"] for r in results)
    lo, hi = PASS_ACCURACY
    checks.append((f"pass accuracy in {lo:.0%}-{hi:.0%}", lo <= acc <= hi, f"{acc:.1%}"))

    tr = [r["tracking"] for r in results if "tracking" in r]
    if tr:
        worst = max(tr, key=lambda x: x["max_speed"])
        checks.append((f"max player speed < {MAX_SPEED} m/s (excl. half-time cut)",
                       worst["max_speed"] < MAX_SPEED,
                       f"{worst['max_speed']:.2f} m/s at t={worst['max_speed_at'][0]}, "
                       f"player {worst['max_speed_at'][1]}"))
        n = sum(x["nearest_n"] for x in tr)
        ok = sum(x["nearest_ok"] for x in tr)
        share = ok / max(1, n)
        checks.append((f"nearest player is the event's player >= {NEAREST_MIN:.0%} (passes, shots)",
                       share >= NEAREST_MIN, f"{share:.1%} of {n}"))
        n_sp = sum(x["set_piece_n"] for x in tr)
        bad_sp = [b for x in tr for b in x["set_piece_bad"]]
        checks.append((f"set-piece takers within {SET_PIECE_RADIUS} m of the ball", not bad_sp,
                       f"{n_sp - len(bad_sp)}/{n_sp}" + (f", e.g. {bad_sp[:3]}" if bad_sp else "")))
        bad_c = [b for x in tr for b in x["count_bad"]]
        checks.append(("7-11 players per team in every frame", not bad_c,
                       f"{len(bad_c)} bad frames" + (f", e.g. {bad_c[:2]}" if bad_c else "")))
        bad_b = [b for x in tr for b in x["ball_bad"]]
        checks.append((f"ball within {BALL_MARGIN} m of the pitch", not bad_b,
                       f"{len(bad_b)} bad frames" + (f", e.g. {bad_b[:2]}" if bad_b else "")))
    return checks


def report(events, m: Match, label: str, half_len: float):
    """Print one match's event counts (scaled to 90 minutes) against the norms."""
    c = Counter(e["type"] for e in events)
    scale = 5400 / (2 * half_len)
    passes = [e for e in events if e["type"] == "pass"]
    acc = sum(e["success"] for e in passes) / max(1, len(passes))
    # Possession share by time.
    share = Counter()
    for (t, team), nxt in zip(m.poss, m.poss[1:] + [(m.t, None)]):
        share[team] += nxt[0] - t
    tot = sum(share.values()) or 1
    print(f"\n== {label}: final score {m.score['home']}-{m.score['away']} "
          f"| pass accuracy {acc:.0%} | possession home {share['home'] / tot:.0%}")
    print(f"{'type':20}{'count':>7}{'per 90':>8}   norm")
    for t in ALL_TYPES:
        lo_hi = NORMS.get(t)
        per90 = c[t] * scale
        flag = ""
        if lo_hi and scale == 1.0:
            flag = "ok" if lo_hi[0] <= per90 <= lo_hi[1] else "OUT OF RANGE"
        norm = f"{lo_hi[0]}-{lo_hi[1]}" if lo_hi else ""
        print(f"{t:20}{c[t]:7}{per90:8.0f}   {norm:10} {flag}")
    print(f"{'total':20}{len(events):7}")


def main(argv=None) -> int:
    """Command line; returns 0 if every check passes, 1 otherwise."""
    ap = argparse.ArgumentParser(prog="python -m simulator.realism", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--matches", type=int, default=40)
    ap.add_argument("--seed", type=int, default=1000, help="seed of match 0 (match i uses seed + i)")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 1, help="worker processes")
    ap.add_argument("--no-tracking", action="store_true", help="event checks only (fast)")
    args = ap.parse_args(argv)
    if args.matches < 2:
        ap.error("--matches must be at least 2 (standard deviation)")

    t0 = time.perf_counter()
    results = run(args.matches, args.seed, args.jobs, not args.no_tracking)
    pairs = Counter((r["home"], r["away"]) for r in results)
    goals = statistics.fmean(sum(r["score"].values()) for r in results)
    print(f"{args.matches} matches (seeds {args.seed}-{args.seed + args.matches - 1}), "
          f"{len(pairs)} pairings of {', '.join(list_teams())}; {goals:.2f} goals per match\n")
    checks = summarize(results)
    print()
    for name, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")
    failed = [c for c in checks if not c[1]]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed "
          f"in {time.perf_counter() - t0:.0f} s")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
