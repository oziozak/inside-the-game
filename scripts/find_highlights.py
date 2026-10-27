"""List candidate highlight windows: a kickoff, then one key moment, by the footage rules.

Usage:
    python scripts/find_highlights.py --home bosphorus --away thames
    python scripts/find_highlights.py --home caldera --away saltmarsh --types goal yellow_card
    python scripts/find_highlights.py --first 3001 --last 3200 --types red_card

Simulator only: each seed's full match is played (events, no tracking, no rendering, no
vision) with vision.footage.simulate, the same call `render` uses, so a window found here is
the window that gets rendered. A candidate window:

- starts about 1 s before a kickoff (0', the second-half kickoff or the kickoff after a goal),
  since the vision AI names players only after it has seen one;
- holds a key event (--types) at least 20 s before its end;
- is at most 3 minutes long, in half-minute steps, and ends by minute 58 (before substitutions);
- comes from a seed in --first..--last that no clip in vision/footage_seeds.json uses.

Highlights are picked for their content, so they are never held-out test clips.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vision.footage import SUBS_FROM, load_record, score_at, simulate  # noqa: E402

KEY_TYPES = ("goal", "red_card", "yellow_card")
MAX_MINUTES = 3
TAIL_S = 20            # the key moment is at least this long before the window ends
LEAD_S = 1             # the window starts this long before the kickoff


def windows(seed: int, home: str, away: str, types=KEY_TYPES) -> list[dict]:
    """Candidate windows in one seed's match: one per key event that fits, from the last
    kickoff before it (the shortest window)."""
    m = simulate({"name": f"seed{seed}", "seed": seed, "home": home, "away": away})
    info = m.match_info()
    names = {p["id"]: p["name"] for side in ("home", "away") for p in info[side]["players"]}
    kickoffs = [e["t"] for e in m.events if e["type"] == "kickoff"]
    found = []
    for key in (e for e in m.events if e["type"] in types):
        kick = max(t for t in kickoffs if t <= key["t"])
        start_minute = math.floor(max(0.0, kick - LEAD_S) / 60 * 100) / 100
        start = start_minute * 60
        minutes = math.ceil((key["t"] + TAIL_S - start) / 30) / 2
        if minutes > MAX_MINUTES or start + minutes * 60 > SUBS_FROM * 60:
            continue
        found.append({
            "seed": seed, "home": home, "away": away, "start_minute": start_minute,
            "minutes": minutes, "kickoff_t": kick, "key": key,
            "player": names.get(key.get("from"), "?"),
            "score_start": score_at(m.events, start),
            "score_after": score_at(m.events, key["t"] + 0.01),
            "score_final": score_at(m.events, math.inf),
        })
    return found


def describe(w: dict) -> str:
    """One line: seed, window, kickoff, key moment, score at start, after the moment and final."""
    k = w["key"]
    what = k["type"] + (f" ({k['subtype']})" if k.get("subtype") else "")
    team = w["home"] if k["team"] == "home" else w["away"]
    h, a = w["score_start"].values()
    ha, aa = w["score_after"].values()
    after = f", after {ha}-{aa}" if k["type"] == "goal" else ""
    fh, fa = w["score_final"].values()
    return (f"seed {w['seed']}  {w['home']} v {w['away']}  start {w['start_minute']:g}' "
            f"+{w['minutes']:g} min  kickoff {w['kickoff_t']:.1f} s  "
            f"{what} {k['t'] / 60:.0f}' ({k['t']:.1f} s) {team} {w['player']}  "
            f"score at start {h}-{a}{after}, final {fh}-{fa}")


def main(argv=None) -> int:
    """Command line; returns the exit code."""
    ap = argparse.ArgumentParser(prog="python scripts/find_highlights.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--home", default="bosphorus")
    ap.add_argument("--away", default="thames")
    ap.add_argument("--first", type=int, default=3001, help="first seed to search")
    ap.add_argument("--last", type=int, default=3999, help="last seed to search")
    ap.add_argument("--types", nargs="+", choices=KEY_TYPES, default=list(KEY_TYPES),
                    help="key event types")
    args = ap.parse_args(argv)

    used = {c["seed"] for c in load_record()["clips"]}
    count = 0
    for seed in range(args.first, args.last + 1):
        if seed in used:
            continue
        for w in windows(seed, args.home, args.away, tuple(args.types)):
            print(describe(w))
            count += 1
    print(f"{count} candidate window(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
