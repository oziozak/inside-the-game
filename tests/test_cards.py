"""Card rules: the red-card guard never leaves a team below 7 players."""

from __future__ import annotations

from collections import Counter

from simulator import Match, load_team
from simulator.config import PROFILES
from simulator.realism import check_tracking

# Brutal referee: most challenges are fouls and most fouls are cards.
HARSH = dict(PROFILES["short"], foul_given_challenge=0.8, yellow=0.45, red=0.45, challenge=0.3)


def _harsh_match(seed: int, half_len: float = 2700) -> Match:
    m = Match(seed, half_len, "full", f"harsh_{seed}", home=load_team("caldera"),
              away=load_team("thames"))
    m.p = HARSH
    m.play()
    return m


def test_red_card_guard_under_extreme_card_rates():
    guard_used = 0
    for seed in range(12):
        m = _harsh_match(seed)
        reds = Counter(e["from"] for e in m.events if e["type"] == "red_card")
        yellows = Counter(e["from"] for e in m.events if e["type"] == "yellow_card")
        sent_off = Counter(m.players[p]["team"] for p in reds)
        for team in ("home", "away"):
            assert sent_off[team] <= 4                       # never below 7 of 11
            assert len(m.on_pitch[team]) >= 7
            guard_used += sent_off[team] == 4
        assert all(n == 1 for n in reds.values())            # nobody sent off twice
        assert all(n <= 2 for n in yellows.values())         # never a third yellow
        for pid, n in yellows.items():                       # two yellows -> exactly one red
            if n == 2:
                assert any(e["type"] == "red_card" and e["from"] == pid and e["subtype"] == "second_yellow"
                           for e in m.events)
        # A sent-off player never appears in a later event.
        off_at = {e["from"]: e["t"] for e in m.events if e["type"] == "red_card"}
        for e in m.events:
            for who in (e["from"], e["to"]):
                if who in off_at and e["type"] != "red_card":
                    assert e["t"] <= off_at[who], (e, off_at[who])
    assert guard_used > 0, "card rates too low to exercise the guard"


def test_red_card_guard_in_tracking():
    """A short match where a team is down to 7: tracking never shows fewer."""
    m = next(m for m in (_harsh_match(s, half_len=600) for s in range(50))
             if any(len(m.on_pitch[t]) == 7 for t in ("home", "away")))
    assert check_tracking(m)["count_bad"] == []
