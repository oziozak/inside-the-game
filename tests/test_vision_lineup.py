"""Lineup assignment (vision/lineup.py) on hand-built frames."""

from __future__ import annotations

import itertools
import random

from vision.lineup import Lineup, _hungarian, formation_slots
from vision.observation import PlayerObservation

# A 4-3-3 and a 4-4-2 as a team sheet lists them: back line right to left, then midfield, then attack.
HOME = [(1, "GK"), (2, "RB"), (4, "CB"), (5, "CB"), (3, "LB"), (6, "DM"), (8, "CM"), (10, "AM"),
        (7, "RW"), (9, "ST"), (11, "LW")]
AWAY = [(101, "GK"), (102, "RB"), (104, "CB"), (105, "CB"), (103, "LB"), (107, "RM"), (106, "CM"),
        (108, "CM"), (111, "LM"), (109, "ST"), (110, "ST")]
# Where each stands at a kickoff in its team's frame (attacking toward x = 105, right side y < 34).
KICKOFF_SPOTS = {1: (4, 34), 2: (33, 12), 4: (26, 26), 5: (26, 42), 3: (33, 56), 6: (40, 34),
                 8: (44, 26), 10: (50, 42), 7: (51, 10), 9: (51, 30), 11: (51, 58),
                 101: (4, 34), 102: (30, 12), 104: (24, 27), 105: (24, 41), 103: (30, 56),
                 107: (42, 12), 106: (40, 28), 108: (40, 40), 111: (42, 56), 109: (51, 28), 110: (51, 40)}


def team_sheet() -> dict:
    """A team sheet with the two lineups above and a substitute each."""
    def players(rows, sub):
        return [{"id": i, "number": i % 100, "name": f"P{i}", "pos": pos, "starter": True}
                for i, pos in rows] + [{"id": sub, "number": sub % 100, "name": "Sub", "pos": "CM",
                                        "starter": False}]
    return {"match_id": "t", "pitch": [105, 68], "home": {"players": players(HOME, 14)},
            "away": {"players": players(AWAY, 114)}}


def kickoff_frame(seed: int = 0) -> tuple[list[PlayerObservation], dict[int, int]]:
    """Both teams lined up for a kickoff, home attacking toward x = 105, under
    shuffled anonymous track ids. Returns the players and track -> roster id."""
    rng = random.Random(seed)
    ids = list(KICKOFF_SPOTS)
    tracks = rng.sample(range(50), len(ids))
    players, truth = [], {}
    for tid, pid in zip(tracks, ids):
        x, y = KICKOFF_SPOTS[pid]
        if pid > 100:                                   # away attacks toward x = 0
            x, y = 105 - x, 68 - y
        players.append(PlayerObservation(tid, "home" if pid < 100 else "away", pid in (1, 101),
                                         (x + rng.uniform(-0.8, 0.8), y + rng.uniform(-0.8, 0.8)), 1.0))
        truth[tid] = pid
    return players, truth


def test_hungarian_finds_the_cheapest_assignment():
    rng = random.Random(1)
    for n, m in [(3, 3), (4, 6), (5, 5)]:
        cost = [[rng.uniform(0, 10) for _ in range(m)] for _ in range(n)]
        cols = _hungarian(cost)
        assert len(set(cols)) == n
        best = min(sum(cost[r][c] for r, c in enumerate(p)) for p in itertools.permutations(range(m), n))
        assert abs(sum(cost[r][c] for r, c in enumerate(cols)) - best) < 1e-9


def test_starters_sharing_a_slot_spread_right_to_left_in_team_sheet_order():
    slots = formation_slots(team_sheet()["away"]["players"])
    assert 114 not in slots                             # substitutes have no slot
    assert slots[104][1] < slots[105][1] and slots[106][1] < slots[108][1] and slots[109][1] < slots[110][1]
    assert slots[102][1] < slots[104][1] and slots[105][1] < slots[103][1]


def test_a_lined_up_kickoff_names_every_track():
    for seed in range(5):
        players, truth = kickoff_frame(seed)
        lineup = Lineup(team_sheet())
        lineup.assign(players, home_attacks_right=True)
        assert {tid: lineup.player(tid) for tid in truth} == truth


def test_the_taker_on_the_center_spot_gets_the_starter_left_over():
    players, truth = kickoff_frame()
    taker = next(tid for tid, pid in truth.items() if pid == 7)     # the right winger takes it
    players = [PlayerObservation(p.track_id, p.team, p.goalkeeper, (52.5, 34.0), 1.0)
               if p.track_id == taker else p for p in players]
    lineup = Lineup(team_sheet())
    lineup.assign(players, home_attacks_right=True, taker=taker)
    assert {tid: lineup.player(tid) for tid in truth} == truth


def test_second_half_mirrors_the_frame():
    players, truth = kickoff_frame()
    mirrored = [PlayerObservation(p.track_id, p.team, p.goalkeeper, (105 - p.pos[0], 68 - p.pos[1]), 1.0)
                for p in players]
    lineup = Lineup(team_sheet())
    lineup.assign(mirrored, home_attacks_right=False)
    assert {tid: lineup.player(tid) for tid in truth} == truth


def test_a_new_track_takes_the_missing_player_last_seen_nearest():
    players, truth = kickoff_frame()
    lineup = Lineup(team_sheet())
    lineup.assign(players, home_attacks_right=True)
    lineup.observe(0.0, players, True)
    # Two home players vanish; one comes back under a new id near where it was.
    gone = [tid for tid, pid in truth.items() if pid in (4, 5)]
    rest = [p for p in players if p.track_id not in gone]
    lineup.observe(0.04, rest, True)
    back = next(p for p in players if truth[p.track_id] == 5)
    new = PlayerObservation(999, "home", False, (back.pos[0] + 1.0, back.pos[1]), 1.0)
    lineup.observe(0.08, rest + [new], True)
    assert lineup.player(999) == 5
    assert lineup.player(back.track_id) is None
    # An outfield track never takes the keeper's name, nor one of the other team's.
    keeper = next(tid for tid, pid in truth.items() if pid == 1)
    rest = [p for p in rest if p.track_id != keeper]
    lineup.observe(0.12, rest + [new, PlayerObservation(998, "away", False, (5.0, 34.0), 1.0)], True)
    assert lineup.player(998) is None
