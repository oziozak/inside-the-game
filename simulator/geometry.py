"""Small geometry helpers shared by the event and movement layers."""

from __future__ import annotations

import math


def other(team: str) -> str:
    """The opposing side: "home" <-> "away"."""
    return "away" if team == "home" else "home"


def clamp(v: float, lo: float, hi: float) -> float:
    """Limit v to the range [lo, hi]."""
    return max(lo, min(hi, v))


def dist(a, b) -> float:
    """Distance in meters between two (x, y) points."""
    return math.hypot(a[0] - b[0], a[1] - b[1])
