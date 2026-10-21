"""Team styles: "balanced" is neutral, and each style changes play the way
config.STYLES documents (compared with the same team playing "balanced")."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import statistics

import pytest

from simulator import Match, load_team
from simulator.config import STYLES
from simulator.movement import iter_tracking

N = 30  # full matches per side of each comparison (events only, fast)

# Events of a fixed neutral match (Bosphorus v Thames, seed 51, no style and
# no attributes). Changes when the base engine changes on purpose; update it
# then, and only then.
GOLDEN_NEUTRAL = "10a93b1788fdfba0f65d97099e6415b8e571a25b9e608447f0ad2ca8e3153862"


def neutral(key: str) -> dict:
    """A team with its style and player attributes removed."""
    t = copy.deepcopy(load_team(key))
    t.pop("style", None)
    for p in t["players"]:
        for a in ("passing", "shooting", "pace", "tackling"):
            p.pop(a, None)
    return t


def with_style(team: dict, style: str) -> dict:
    t = copy.deepcopy(team)
    t["style"] = style
    return t


def test_golden_neutral_match():
    m = Match(51, 2700, "full", "golden", home=neutral("bosphorus"), away=neutral("thames"))
    m.play()
    digest = hashlib.sha256(json.dumps(m.events, sort_keys=True).encode()).hexdigest()
    assert digest == GOLDEN_NEUTRAL


# A style that sets every knob to its identity value explicitly, so every
# style code path runs (re-weighting, tempo, line, press).
IDENTITY = dict(weights={k: 1.0 for k in ("short", "long", "through", "cross", "dribble", "shot", "clear")},
                transition={k: 1.0 for k in ("short", "long", "through", "cross", "dribble", "shot")},
                tempo=1.0, line=0.0, press=0.0)


def _play_both(style: str, seeds=range(30)) -> tuple[list, list]:
    """Events of full matches where both teams play `style` (exact equality
    over many matches catches even small changes), plus tracking of the
    first two minutes of the first one."""
    events, tracking = [], []
    for s in seeds:
        m = Match(s, 2700, "full", "x", home=with_style(neutral("caldera"), style),
                  away=with_style(neutral("saltmarsh"), style))
        m.play()
        events.append(m.events)
        if not tracking:
            tracking = list(iter_tracking(m, 0, 120))
    return events, tracking


def test_balanced_style_is_a_no_op(monkeypatch):
    """ "balanced" plays exactly like an explicit identity style (a different,
    non-default key). Fails if a balanced knob stops being neutral."""
    monkeypatch.setitem(STYLES, "test_identity", copy.deepcopy(IDENTITY))
    assert _play_both("balanced") == _play_both("test_identity")


def test_neutrality_check_is_sensitive(monkeypatch):
    """The comparison above does catch a small change (tempo 1.01)."""
    monkeypatch.setitem(STYLES, "test_identity", copy.deepcopy(IDENTITY))
    monkeypatch.setitem(STYLES, "test_tempo", dict(copy.deepcopy(IDENTITY), tempo=1.01))
    assert _play_both("test_tempo")[0] != _play_both("test_identity")[0]


def _home_metrics(home: dict, away: dict) -> dict:
    """Mean per-match numbers for the home side over N seeds."""
    rows = []
    for s in range(N):
        m = Match(800 + s, 2700, "full", "style", home=home, away=away)
        m.play()
        mine = [e for e in m.events if e["team"] == "home"]
        passes = [e for e in mine if e["type"] == "pass"]
        rows.append({
            "passes": len(passes),
            "long_share": sum(e.get("subtype") in ("long", "cross") for e in passes) / len(passes),
            "through": sum(e.get("subtype") == "through" for e in passes),
            "tackles_fouls": sum(e["type"] == "foul" or e.get("subtype") == "tackle" for e in mine),
            "opp_offside": sum(e["type"] == "offside" and e["team"] == "away" for e in m.events),
        })
    return {k: statistics.fmean(r[k] for r in rows) for k in rows[0]}


@pytest.mark.parametrize("style, metric, factor", [
    ("possession", "passes", 1.1),          # more passes
    ("counter", "through", 1.15),           # more through balls (after winning the ball)
    ("counter", "opp_offside", -0.85),      # deep line: opponents caught offside less (lower)
    ("pressing", "tackles_fouls", 1.1),     # more challenges
    ("pressing", "opp_offside", 1.1),       # high line: opponents caught offside more
    ("direct", "long_share", 1.06),         # more long balls and crosses
])
def test_style_changes_play(style, metric, factor):
    team = neutral("bosphorus")
    opp = neutral("thames")
    styled = _home_metrics(with_style(team, style), opp)[metric]
    base = _home_metrics(team, opp)[metric]
    if factor > 0:
        assert styled > base * factor, (styled, base)
    else:
        assert styled < base * -factor, (styled, base)


def _closing_down(home: dict, away: dict) -> float:
    """Mean distance (m) from the ball to the nearest home outfield player
    while an away player carries the ball."""
    m = Match(21, 600, "full", "press", home=home, away=away)
    m.play()
    carry = {}
    for t0, t1, pid in m.carry:
        if m.players[pid]["team"] == "away" and t0 not in m.restarts:
            for fr in range(int(t0 * 25) + 1, int(t1 * 25)):
                carry[fr] = pid
    dists = []
    for f in iter_tracking(m, 0, m.t):
        if f["frame"] in carry:
            ball = f["ball"][:2]
            dists.append(min(math.dist(p["pos"], ball) for p in f["players"]
                             if p["team"] == "home" and p["id"] != m.gk("home")))
    return statistics.fmean(dists)


def test_pressing_team_closes_down_the_carrier():
    team, opp = neutral("caldera"), neutral("thames")
    pressing = _closing_down(with_style(team, "pressing"), opp)
    balanced = _closing_down(team, opp)
    assert pressing < balanced - 1.0, (pressing, balanced)
    assert pressing > 3.0          # pressers stop short of the ball (PRESS_STANDOFF)
