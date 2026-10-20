"""Build the committed sample data in data/fake/ (called by scripts/generate_fake_data.py).

    data/fake/sample_a/  short match (2 x 5 min), every event type at least once
        match_info.json, events.json, tracking.jsonl (first 60 s), overlays.json
    data/fake/sample_b/  full match (2 x 45 min) with realistic event counts
        match_info.json, events.json

With --full-tracking, complete 25 fps tracking for both samples is also
written to data/generated/ (too big for git).

Everything is seeded: the same seed always gives the same files.

Usage:
    python scripts/generate_fake_data.py                 # writes data/fake/
    python scripts/generate_fake_data.py --full-tracking # + data/generated/
    python scripts/generate_fake_data.py --seed 7 --report
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .engine import generate
from .fake_overlays import build_overlays
from .io import write_json, write_jsonl
from .movement import build_tracking, iter_tracking
from .realism import report

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None):
    """Command line of scripts/generate_fake_data.py."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--full-tracking", action="store_true", help="also write full 25 fps tracking to data/generated/")
    ap.add_argument("--report", action="store_true", help="print event counts against football norms")
    args = ap.parse_args(argv)

    # Sample A: short, every event type.
    ma, sa = generate(args.seed, 300, "short", "fake_a", require_all=True, min_events=100)
    info_a = ma.match_info()
    out_a = ROOT / "data" / "fake" / "sample_a"
    write_json(out_a / "match_info.json", info_a)
    write_json(out_a / "events.json", ma.events)
    write_jsonl(out_a / "tracking.jsonl", build_tracking(ma, 0, 60))
    write_json(out_a / "overlays.json", build_overlays(ma.events, info_a))
    print(f"sample_a: seed {sa}, {len(ma.events)} events, score {ma.score['home']}-{ma.score['away']}")

    # Sample B: full match.
    mb, sb = generate(args.seed, 2700, "full", "fake_b", require_typical=True)
    info_b = mb.match_info()
    out_b = ROOT / "data" / "fake" / "sample_b"
    write_json(out_b / "match_info.json", info_b)
    write_json(out_b / "events.json", mb.events)
    print(f"sample_b: seed {sb}, {len(mb.events)} events, score {mb.score['home']}-{mb.score['away']}")

    if args.full_tracking:
        gen = ROOT / "data" / "generated"
        write_jsonl(gen / "sample_a" / "tracking.jsonl", iter_tracking(ma, 0, ma.t))
        write_jsonl(gen / "sample_b" / "tracking.jsonl", iter_tracking(mb, 0, mb.t))
        print("full tracking written to data/generated/")

    if args.report:
        report(ma.events, ma, "sample_a (short, boosted rare events)", 300)
        report(mb.events, mb, "sample_b (full match)", 2700)
