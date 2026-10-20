"""Player attributes: 70 is neutral, and each attribute moves its stat."""

from __future__ import annotations

import copy
import math
import statistics

from test_styles import neutral

from simulator import Match, build_tracking, engine, load_team, movement
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


def everyone(team: dict, values: dict) -> dict:
    """Copy of team with the given attributes for every player, keeper included."""
    t = copy.deepcopy(team)
    for p in t["players"]:
        p.update(values)
    return t


def _play(home: dict, away: dict, seeds=range(60)) -> tuple[list, list]:
    """Events of many full matches (exact equality over many matches catches
    even small changes), plus tracking of the first two minutes of one."""
    events = []
    for s in seeds:
        m = Match(s, 2700, "full", "x", home=home, away=away)
        m.play()
        events.append(m.events)
    return events, build_tracking(m, 0, 120)


def _effects_off(monkeypatch):
    """Switch every attribute effect off: ratings then change nothing."""
    for name in ("PASS_PER_POINT", "SHOT_PER_POINT", "PENALTY_PER_POINT", "TACKLE_PER_POINT"):
        monkeypatch.setattr(engine, name, 0.0)
    for name in ("SPRINT_PER_POINT", "CARRY_PER_POINT"):
        monkeypatch.setattr(movement, name, 0.0)


SEVENTY = {a: 70 for a in ATTRS}
EXTREME_HOME = {"passing": 95, "shooting": 40, "pace": 95, "tackling": 40}
EXTREME_AWAY = {"passing": 40, "shooting": 95, "pace": 40, "tackling": 95}


def test_all_seventy_is_neutral(monkeypatch):
    """Everyone rated 70 with the effects on plays exactly like extreme,
    non-default ratings with the effects off: 70 changes nothing."""
    seventy = _play(everyone(neutral("bosphorus"), SEVENTY), everyone(neutral("thames"), SEVENTY))
    _effects_off(monkeypatch)
    extreme = _play(everyone(neutral("bosphorus"), EXTREME_HOME), everyone(neutral("thames"), EXTREME_AWAY))
    assert seventy == extreme


def test_attribute_check_is_sensitive():
    """With the effects on, a one-point change (71) does change the match."""
    seventy = _play(everyone(neutral("bosphorus"), SEVENTY), everyone(neutral("thames"), SEVENTY))
    seventy_one = _play(everyone(neutral("bosphorus"), {a: 71 for a in ATTRS}),
                        everyone(neutral("thames"), SEVENTY))
    assert seventy != seventy_one


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
