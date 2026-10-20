"""Event-file invariants: ids, ordering, scores, and event-type coverage."""

from __future__ import annotations

import re
from collections import Counter

from conftest import SHORT

from simulator import Match
from simulator.config import ALL_TYPES


def _all(short_match, full_matches):
    return [short_match[0]] + full_matches


def test_ids_unique_and_sorted_by_time(short_match, full_matches):
    for m in _all(short_match, full_matches):
        ids = [e["id"] for e in m.events]
        assert len(set(ids)) == len(ids)
        assert all(re.fullmatch(r"e\d{4,}", i) for i in ids)
        assert ids == [f"e{i:04d}" for i in range(1, len(ids) + 1)]
        times = [e["t"] for e in m.events]
        assert times == sorted(times)


def test_goal_and_final_scores_match_goal_count(short_match, full_matches):
    for m in _all(short_match, full_matches):
        running = Counter()
        for e in m.events:
            if e["type"] == "goal":
                running[e["team"]] += 1
                assert e["score"] == {"home": running["home"], "away": running["away"]}
        goals = Counter(e["team"] for e in m.events if e["type"] == "goal")
        ft = [e for e in m.events if e["type"] == "full_time"]
        assert len(ft) == 1 and ft[0] is m.events[-1]
        assert ft[0]["score"] == {"home": goals["home"], "away": goals["away"]} == m.score
        ht = next(e for e in m.events if e["type"] == "half_time")
        first_half = Counter(e["team"] for e in m.events if e["type"] == "goal" and e["period"] == 1)
        assert ht["score"] == {"home": first_half["home"], "away": first_half["away"]}


def test_every_event_type_can_occur(short_match):
    """The short profile boosts rare events, so one short match has them all."""
    m, _ = short_match
    assert set(ALL_TYPES) <= {e["type"] for e in m.events}


def test_event_types_appear_across_short_seeds():
    """Not just one lucky seed: a handful of short matches cover every type."""
    seen = set()
    for seed in range(20):
        m = Match(seed, SHORT, "short", "cov")
        m.play()
        seen |= {e["type"] for e in m.events}
    assert seen == set(ALL_TYPES)


def test_offside_follows_the_ball_that_was_played(short_match, full_matches):
    """Every offside comes right after the failed pass or free kick that
    played the ball to the offside player (tracking shows that flight)."""
    n = 0
    for m in _all(short_match, full_matches):
        for i, e in enumerate(m.events):
            if e["type"] != "offside":
                continue
            n += 1
            ball = m.events[i - 1]
            assert ball["type"] in ("pass", "free_kick"), ball
            assert ball["team"] == e["team"] and ball["success"] is False and ball["to"] is None
            assert ball["end"] == e["start"]
            assert abs(ball["t"] + ball["duration_s"] - e["t"]) <= 0.02
    assert n > 0
