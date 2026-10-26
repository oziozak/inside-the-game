"""Command line: simulate one match and write its files.

    python -m simulator --home bosphorus --away thames --seed 7 --half-length 45 \\
        --out data/generated/m007 [--no-tracking] [--start 0 --end 600]

Writes match_info.json, events.json and tracking.jsonl (25 fps) into --out.
Teams are the file names in simulator/teams/ (without .json).
The same arguments always give byte-identical files.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .config import PROFILES
from .engine import Match
from .io import write_match
from .teams import list_teams, load_team


def parse_args(argv=None) -> argparse.Namespace:
    """Parse the command-line arguments."""
    ap = argparse.ArgumentParser(prog="python -m simulator", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home", default="bosphorus", help=f"home team ({', '.join(list_teams())})")
    ap.add_argument("--away", default="thames", help="away team")
    ap.add_argument("--seed", type=int, default=1, help="random seed (default 1)")
    ap.add_argument("--half-length", type=float, default=45.0, help="minutes per half (default 45)")
    ap.add_argument("--profile", choices=sorted(PROFILES), default="full",
                    help="event probabilities: full (realistic) or short (rare events boosted)")
    ap.add_argument("--out", type=Path, required=True, help="output folder")
    ap.add_argument("--match-id", help="match id (default: the output folder name)")
    ap.add_argument("--no-tracking", action="store_true", help="skip tracking.jsonl")
    ap.add_argument("--start", type=float, default=0.0, help="tracking start, seconds (default 0)")
    ap.add_argument("--end", type=float, default=None, help="tracking end, seconds (default full time)")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    """Simulate one match from the command line; returns the exit code."""
    args = parse_args(argv)
    if args.home == args.away:
        print("error: --home and --away must be different teams", file=sys.stderr)
        return 2
    if args.half_length <= 0:
        print("error: --half-length must be positive", file=sys.stderr)
        return 2
    if args.start < 0:
        print("error: --start must be 0 or more", file=sys.stderr)
        return 2
    if args.end is not None and args.end <= args.start:
        print("error: --end must be after --start", file=sys.stderr)
        return 2

    t0 = time.perf_counter()
    match_id = args.match_id or args.out.resolve().name
    try:
        # Bad team files and kit clashes (resolved in Match) are user errors.
        home, away = load_team(args.home), load_team(args.away)
        m = Match(args.seed, args.half_length * 60, args.profile, match_id, home=home, away=away)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    m.play()
    if not args.no_tracking and args.start >= m.t:
        print(f"error: --start must be before the end of the match ({m.t:.1f} s)", file=sys.stderr)
        return 2
    files = write_match(args.out, m, tracking=not args.no_tracking, start=args.start, end=args.end)
    took = time.perf_counter() - t0
    print(f"{match_id}: {home['name']} {m.score['home']}-{m.score['away']} {away['name']} "
          f"(seed {args.seed}, {len(m.events)} events) in {took:.1f} s")
    for name, path in files.items():
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
