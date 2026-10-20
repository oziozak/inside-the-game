"""Tracking agrees with the events: directions, red cards, substitutions."""

from __future__ import annotations

import statistics

import pytest

from simulator.config import L
from simulator.realism import MAX_SPEED, NEAREST_MIN, check_tracking


def _ids(frame, team=None):
    return {p["id"] for p in frame["players"] if team is None or p["team"] == team}


@pytest.mark.parametrize("fixture", ["short_match", "styled_match"])
def test_teams_switch_direction_at_half_time(fixture, request):
    m, frames = request.getfixturevalue(fixture)
    home_gk, away_gk = m.gk("home"), m.gk("away")
    for period, home_side in ((1, "left"), (2, "right")):
        hx = [p["pos"][0] for f in frames if f["period"] == period
              for p in f["players"] if p["id"] == home_gk]
        ax = [p["pos"][0] for f in frames if f["period"] == period
              for p in f["players"] if p["id"] == away_gk]
        if home_side == "left":     # home attacks toward x = 105, defends x = 0
            assert statistics.fmean(hx) < L / 4 and statistics.fmean(ax) > 3 * L / 4
        else:
            assert statistics.fmean(hx) > 3 * L / 4 and statistics.fmean(ax) < L / 4
    # The event layer agrees: dirn() flips with the period.
    m.period = 1
    assert (m.dirn("home"), m.dirn("away")) == (1, -1)
    m.period = 2
    assert (m.dirn("home"), m.dirn("away")) == (-1, 1)
    assert m.match_info()["kickoff_direction"] == {"home": "left_to_right"}


def test_red_card_reduces_player_count(short_match):
    m, frames = short_match
    reds = [e for e in m.events if e["type"] == "red_card"]
    assert reds, "fixture must contain a red card"
    for e in reds:
        team, pid = e["team"], e["from"]
        before = [f for f in frames if f["t"] < e["t"]]
        after = [f for f in frames if f["t"] >= e["t"]]
        assert pid in _ids(before[-1])
        n_before = len(_ids(before[-1], team))
        for f in after:
            assert pid not in _ids(f)
            assert len(_ids(f, team)) <= n_before - 1
        # Right after the card the team is exactly one player down.
        assert len(_ids(after[0], team)) == n_before - 1


def test_substitute_appears_only_after_substitution(short_match):
    m, frames = short_match
    subs = [e for e in m.events if e["type"] == "substitution"]
    assert subs, "fixture must contain a substitution"
    for e in subs:
        on, off = e["from"], e["to"]
        assert all(on not in _ids(f) for f in frames if f["t"] < e["t"])
        assert all(off in _ids(f) for f in frames if e["t"] - 1 <= f["t"] < e["t"])
        first_after = next(f for f in frames if f["t"] >= e["t"])
        assert on in _ids(first_after)
        assert all(off not in _ids(f) for f in frames if f["t"] >= e["t"])
        # Team size does not change at a substitution.
        prev = [f for f in frames if f["t"] < e["t"]][-1]
        assert len(_ids(prev, e["team"])) == len(_ids(first_after, e["team"]))


def test_bench_players_never_tracked_before_coming_on(short_match):
    m, frames = short_match
    came_on = {e["from"]: e["t"] for e in m.events if e["type"] == "substitution"}
    bench = {pid for pid, p in m.players.items() if p["slot"] is None}
    for f in frames:
        for pid in _ids(f) & bench:
            assert pid in came_on and f["t"] >= came_on[pid]


@pytest.mark.parametrize("fixture", ["short_match", "styled_match"])
def test_realism_tracking_checks_on_short_matches(fixture, request):
    m, _ = request.getfixturevalue(fixture)
    r = check_tracking(m)
    assert r["max_speed"] < MAX_SPEED
    assert r["nearest_ok"] / r["nearest_n"] >= NEAREST_MIN
    assert r["set_piece_bad"] == [] and r["count_bad"] == [] and r["ball_bad"] == []
