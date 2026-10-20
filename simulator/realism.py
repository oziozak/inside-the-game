"""Realism checks: compare simulated matches with real-football norms."""

from __future__ import annotations

from collections import Counter

from .config import ALL_TYPES, NORMS
from .engine import Match


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
