"""Player attributes: 70 is neutral, and each attribute moves its stat."""

from __future__ import annotations

import copy
import math
import statistics

from test_styles import neutral

from simulator import Match, build_tracking, load_team
from simulator.config import ATTRS
from simulator.movement import top_speeds
from simulator.teams import validate_team

N = 25


def rated(team: dict, **attrs) -> dict:
    """Copy of team with the given attributes set for every outfield player."""
    t = copy.deepcopy(team)
    for p in t["players"]:
        if p["pos"] != "GK":
            p.update(attrs)
    return t


def _home(team, opp, seeds=range(N)):
    for s in seeds:
        m = Match(900 + s, 2700, "full", "attr", home=team, away=opp)
        m.play()
        yield m


def test_all_seventy_is_neutral():
    base, opp = neutral("bosphorus"), neutral("thames")
    seventy = rated(base, **{a: 70 for a in ATTRS})
    for p in seventy["players"]:
        p.update({a: 70 for a in ATTRS})
    a = Match(3, 900, "full", "x", home=base, away=opp)
    b = Match(3, 900, "full", "x", home=seventy, away=opp)
    a.play()
    b.play()
    assert a.events == b.events


def test_passing_raises_pass_success():
    opp = neutral("thames")

    def acc(team):
        ps = [e for m in _home(team, opp) for e in m.events if e["type"] == "pass" and e["team"] == "home"]
        return sum(e["success"] for e in ps) / len(ps)

    assert acc(rated(neutral("bosphorus"), passing=90)) > acc(rated(neutral("bosphorus"), passing=50)) + 0.05


def test_shooting_raises_goals_per_shot():
    opp = neutral("thames")

    def conversion(team):
        evs = [e for m in _home(team, opp) for e in m.events if e["team"] == "home"]
        return sum(e["type"] == "goal" for e in evs) / sum(e["type"] == "shot" for e in evs)

    assert conversion(rated(neutral("bosphorus"), shooting=90)) > \
        1.3 * conversion(rated(neutral("bosphorus"), shooting=50))


def test_tackling_raises_tackles_won():
    opp = neutral("thames")

    def tackles(team):
        return statistics.fmean(
            sum(e.get("subtype") == "tackle" and e["team"] == "home" for e in m.events)
            for m in _home(team, opp))

    assert tackles(rated(neutral("bosphorus"), tackling=90)) > 1.15 * tackles(rated(neutral("bosphorus"), tackling=50))


def test_pace_raises_top_speed_but_stays_under_eleven():
    assert top_speeds(70) == (9.5, 10.5)
    assert top_speeds(100)[0] < top_speeds(100)[1] < 11.0
    assert top_speeds(40)[0] < top_speeds(70)[0] < top_speeds(100)[0]

    def fastest(team):
        m = Match(4, 300, "full", "x", home=team, away=neutral("thames"))
        m.play()
        frames = build_tracking(m, 0, m.t)
        best = 0.0
        for f0, f1 in zip(frames, frames[1:]):
            if f0["period"] != f1["period"]:
                continue
            a = {p["id"]: p["pos"] for p in f0["players"] if p["team"] == "home"}
            for p in f1["players"]:
                if p["id"] in a:
                    best = max(best, math.dist(a[p["id"]], p["pos"]) * 25)
        return best

    slow, quick = fastest(rated(neutral("bosphorus"), pace=40)), fastest(rated(neutral("bosphorus"), pace=99))
    assert slow < quick < 11.0


def test_validation_rejects_bad_attributes():
    t = copy.deepcopy(load_team("bosphorus"))
    t["players"][3]["pace"] = 120
    assert any("pace must be an integer 0-100" in e for e in validate_team(t))
    t = rated(load_team("bosphorus"), shooting=95)
    assert any("outfield average shooting" in e for e in validate_team(t))
