"""Tactical facts (agents/tactics.py): frame observations + detected events + team sheet in, tactics.json out.

The match is simulated and turned into frame observations by the vision harness (anonymous tracks, no ball
height), and its events are the vision rules' detected events, so the facts see only what the vision AI
would give them. Frame facts are recomputed here from the simulator's own tracking over the frames each
fact cites, by roster id: the test knows who every player is; the tactics code only knows tracks.
"""

from __future__ import annotations

import ast
import copy
import statistics
from pathlib import Path

import pytest

from agents.tactics import tactics
from simulator import Match, build_tracking, load_team
from simulator.config import STYLES
from vision.harness import observations_from_tracking
from vision.rules import detect_events

ROOT = Path(__file__).resolve().parent.parent
CLIP_S = 180                        # the first minutes of each half
DEFENCE = {"RB", "CB", "LB", "RWB", "LWB"}
ATTACK = {"RW", "LW", "ST", "CF"}


def styled(key: str, style: str) -> dict:
    """A team playing `style`."""
    team = copy.deepcopy(load_team(key))
    team["style"] = style
    return team


def clip(seed: int, home: dict, away: dict) -> tuple:
    """(tracking, observations, detected events, team sheet) of the first CLIP_S of each half."""
    m = Match(seed, 2700, "full", "tactics", home=home, away=away)
    m.play()
    tracking = [fr for p in m.periods for fr in build_tracking(m, p["start"], p["start"] + CLIP_S)]
    info = m.match_info()
    assert all(len(fr["players"]) == 22 for fr in tracking), "a player was sent off: pick another seed"
    frames = observations_from_tracking(tracking, info)
    return tracking, frames, detect_events(frames, info), info


@pytest.fixture(scope="module")
def high_v_deep():
    """(tracking, observations, detected events, team sheet): home presses with a high line (+5 m out of
    possession), away sits deep on the counter (-5 m), the first CLIP_S of each half cut together."""
    return clip(61, styled("bosphorus", "pressing"), styled("thames", "counter"))


@pytest.fixture(scope="module")
def wing_backs():
    """A 5-3-2 whose wing-backs stand with the midfield (slot x 42 m, the midfield's 40-48 m, the back
    three's 23-24 m) against a 4-4-2."""
    return clip(63, load_team("saltmarsh"), load_team("thames"))


def frame_ids(ranges: list[list[int]]) -> list[int]:
    """Every frame index in a list of [first, last] ranges."""
    return [f for a, b in ranges for f in range(a, b + 1)]


def depth(x: float, team: str, period: int) -> float:
    """Meters from the team's own goal line (home attacks toward x = 105 in period 1)."""
    return x if (team == "home") == (period == 1) else 105 - x


def team_of(info: dict, pos: set[str]) -> dict[str, set[int]]:
    """Per team, the roster ids of the starters playing one of `pos`."""
    return {side: {p["id"] for p in info[side]["players"] if p["starter"] and p["pos"] in pos}
            for side in ("home", "away")}


def recomputed(tracking: list[dict], fact: dict, measure) -> float:
    """The mean of `measure(frame)` over the tracking frames a fact cites, checking it cites them all."""
    by_frame = {fr["frame"]: fr for fr in tracking}
    frames = frame_ids(fact["frames"])
    assert len(frames) == fact["n_frames"] > 500
    return statistics.fmean(measure(by_frame[f]) for f in frames)


def line_depth(fr: dict, ids: set[int], side: str) -> float:
    """The mean depth of some players in one tracking frame."""
    return statistics.fmean(depth(p["pos"][0], side, fr["period"]) for p in fr["players"] if p["id"] in ids)


def test_defensive_line_is_the_back_lines_mean_depth_over_the_cited_frames(high_v_deep):
    tracking, _, _, info = high_v_deep
    teams = tactics(*high_v_deep[1:])["segments"][0]["teams"]
    backs = team_of(info, DEFENCE)
    for side in ("home", "away"):
        for phase in ("in_possession", "out_of_possession"):
            fact = teams[side]["defensive_line_m"][phase]
            truth = recomputed(tracking, fact, lambda fr: line_depth(fr, backs[side], side))
            assert fact["value"] == pytest.approx(truth, abs=0.5), (side, phase)


def test_compactness_is_back_line_to_front_line_over_the_cited_frames(high_v_deep):
    tracking, _, _, info = high_v_deep
    teams = tactics(*high_v_deep[1:])["segments"][0]["teams"]
    backs, fronts = team_of(info, DEFENCE), team_of(info, ATTACK)
    for side in ("home", "away"):
        for phase in ("in_possession", "out_of_possession"):
            fact = teams[side]["compactness_m"][phase]
            truth = recomputed(tracking, fact,
                               lambda fr: line_depth(fr, fronts[side], side) - line_depth(fr, backs[side], side))
            assert 15 < fact["value"] == pytest.approx(truth, abs=0.5), (side, phase)


@pytest.fixture(scope="module")
def lines_set_by_style():
    """{line meters: the home team's facts}: the same match (Bosphorus v Thames, same seed) with home's
    block pushed up or dropped by that many meters out of possession and no other style."""
    out = {}
    for line in (8.0, -8.0):
        with pytest.MonkeyPatch.context() as mp:
            mp.setitem(STYLES, "test_line", {**STYLES["balanced"], "line": line})
            _, frames, events, info = clip(65, styled("bosphorus", "test_line"), styled("thames", "balanced"))
        out[line] = tactics(frames, events, info)["segments"][0]["teams"]["home"]
    return out


def test_a_team_placed_in_a_high_line_reads_higher_than_in_a_deep_one(lines_set_by_style):
    out = {line: facts["defensive_line_m"]["out_of_possession"]["value"] for line, facts in lines_set_by_style.items()}
    assert out[8.0] > out[-8.0] + 10, out
    inside = {line: facts["defensive_line_m"]["in_possession"]["value"] for line, facts in lines_set_by_style.items()}
    assert abs(inside[8.0] - inside[-8.0]) < (out[8.0] - out[-8.0]) / 2, inside   # with the ball: its formation


def test_a_team_reads_as_its_team_sheet_when_it_stands_in_it(high_v_deep):
    teams = tactics(*high_v_deep[1:])["segments"][0]["teams"]
    for side, sheet in (("home", "4-3-3"), ("away", "4-4-2")):
        for phase in ("all", "in_possession", "out_of_possession"):
            shape = teams[side]["shape"][phase]
            assert (shape["team_sheet"], shape["value"]) == (sheet, sheet), (side, phase)


def test_the_actual_shape_follows_where_players_stand_not_the_team_sheet(wing_backs):
    teams = tactics(*wing_backs[1:])["segments"][0]["teams"]
    assert (teams["home"]["shape"]["all"]["team_sheet"], teams["home"]["shape"]["all"]["value"]) == ("5-3-2", "3-5-2")
    wing_backs_ids = team_of(wing_backs[3], {"RWB", "LWB"})["home"]
    assert wing_backs_ids <= set(teams["home"]["shape"]["all"]["actual_lines"][1])


def test_average_positions_are_each_players_mean_over_the_cited_frames(wing_backs):
    tracking, _, _, info = wing_backs
    teams = tactics(*wing_backs[1:])["segments"][0]["teams"]
    for side in ("home", "away"):
        shape = teams[side]["shape"]["all"]
        assert len(shape["players"]) == 10
        for pid, where in shape["players"].items():
            truth = recomputed(tracking, shape, lambda fr: line_depth(fr, {int(pid)}, side))
            assert where["depth_m"] == pytest.approx(truth, abs=0.5), (side, pid)
            assert where["n_frames"] == shape["n_frames"]       # the simulator shows everyone in every frame
        backs = team_of(info, DEFENCE)[side]
        assert sorted(shape["lines"][0]["players"]) == sorted(backs)
        assert shape["lines"][0]["depth_m"] == pytest.approx(
            statistics.fmean(shape["players"][str(pid)]["depth_m"] for pid in backs), abs=0.05)


# ---- facts from events alone (hand-built, period 1: home attacks toward x = 105, away toward x = 0) ----
def ev(n: int, t: float, type_: str, team: str, start, end=None, success=True, period=1, **more) -> dict:
    """A detected event with the fields the tactics read."""
    e = {"id": f"e{n:04d}", "t": t, "period": period, "type": type_, "team": team, "start": list(start),
         "success": success, "source": "cv", "confidence": 0.8, **more}
    if end is not None:
        e["end"] = list(end)
    return e


@pytest.fixture(scope="module")
def sheet(high_v_deep):
    """A Bosphorus (4-3-3) v Thames (4-4-2) team sheet."""
    return high_v_deep[3]


PASSES = [
    ev(1, 1.0, "pass", "home", (10, 30), (45, 30)),                  # 35 m, own half, 35 m on: long, progressive
    ev(2, 3.0, "pass", "home", (50, 30), (58, 30)),                  # across halfway, 8 m on: neither
    ev(3, 5.0, "pass", "home", (60, 30), (72, 30)),                  # opponent half, 12 m on: progressive
    ev(4, 7.0, "pass", "home", (40, 10), (80, 10), success=False),   # 40 m, failed: long, not progressive
    ev(5, 9.0, "pass", "away", (80, 30), (40, 30)),                  # away, 40 m toward x = 0: long, progressive
]


def test_long_balls_are_the_share_of_passes_over_30_m(sheet):
    teams = tactics([], PASSES, sheet)["segments"][0]["teams"]
    assert teams["home"]["long_balls"] == {"value_pct": 50.0, "count": 2, "of": 4, "coverage": None,
                                           "event_ids": ["e0001", "e0002", "e0003", "e0004"],
                                           "long_event_ids": ["e0001", "e0004"]}
    assert teams["away"]["long_balls"] == {"value_pct": 100.0, "count": 1, "of": 1, "coverage": None,
                                           "event_ids": ["e0005"],
                                           "long_event_ids": ["e0005"]}


def test_progressive_passes_are_completed_passes_far_enough_toward_goal(sheet):
    teams = tactics([], PASSES, sheet)["segments"][0]["teams"]
    assert teams["home"]["progressive_passes"] == {"value": 2, "of": 3, "share_pct": 66.7, "coverage": None,
                                                   "event_ids": ["e0001", "e0002", "e0003"],
                                                   "progressive_event_ids": ["e0001", "e0003"]}
    assert teams["away"]["progressive_passes"]["value"] == 1


def test_regains_are_counted_by_the_third_they_happen_in(sheet):
    events = [
        ev(1, 1.0, "pass", "home", (60, 30), (70, 30), success=False),   # home loses it ...
        ev(2, 3.0, "pass", "away", (33, 30), (20, 30)),                   # ... away plays on 72 m from its goal: high
        ev(3, 6.0, "possession_change", "home", (20, 30)),               # home wins it 20 m from its goal: low
        ev(4, 8.0, "pass", "home", (25, 30), (50, 30), success=False),
        ev(5, 9.0, "possession_change", "away", (50, 34)),               # away wins it 55 m out: mid (once, not twice)
        ev(6, 11.0, "shot", "away", (12, 34)),
        ev(7, 12.0, "pass", "home", (5, 34), (30, 34)),                  # after a shot: not a regain
        ev(8, 14.0, "pass", "home", (30, 34), (40, 68), success=False),  # out of play ...
        ev(9, 16.0, "throw_in", "away", (40, 68), (45, 60)),             # ... a restart is not a regain
    ]
    teams = tactics([], events, sheet)["segments"][0]["teams"]
    assert teams["away"]["regains"] == {"value": {"high": 1, "mid": 1, "low": 0}, "coverage": None,
                                        "event_ids": {"high": ["e0001", "e0002"], "mid": ["e0005"], "low": []}}
    assert teams["home"]["regains"] == {"value": {"high": 0, "mid": 0, "low": 1}, "coverage": None,
                                        "event_ids": {"high": [], "mid": [], "low": ["e0003"]}}


def test_flank_share_of_passes_into_the_final_third_is_seen_from_the_attacking_team(sheet):
    events = [
        ev(1, 1.0, "pass", "home", (60, 10), (80, 10)),                  # right (y < 22.7 attacking toward 105)
        ev(2, 2.0, "pass", "home", (60, 34), (75, 34)),                  # centre
        ev(3, 3.0, "pass", "home", (80, 60), (90, 60), success=False),   # left
        ev(4, 4.0, "pass", "home", (40, 60), (60, 60)),                  # not into the final third
        ev(5, 5.0, "pass", "away", (40, 60), (20, 60)),                  # attacking toward 0: y 60 is its right
    ]
    teams = tactics([], events, sheet)["segments"][0]["teams"]
    assert teams["home"]["final_third_flanks"]["passes"] == {
        "value_pct": {"left": 33.3, "centre": 33.3, "right": 33.3}, "count": {"left": 1, "centre": 1, "right": 1},
        "coverage": None,
        "event_ids": {"left": ["e0003"], "centre": ["e0002"], "right": ["e0001"]}}
    assert teams["away"]["final_third_flanks"]["passes"]["value_pct"] == {"left": 0.0, "centre": 0.0, "right": 100.0}


def flank(y: float, side: str, period: int) -> str:
    """Left, centre or right as the team attacking sees it."""
    y = y if (side == "home") == (period == 1) else 68 - y
    return "right" if y < 68 / 3 else ("left" if y > 2 * 68 / 3 else "centre")


def test_flank_share_of_possession_is_where_the_ball_is_in_the_final_third(high_v_deep):
    tracking, _, _, _ = high_v_deep
    teams = tactics(*high_v_deep[1:])["segments"][0]["teams"]
    by_frame = {fr["frame"]: fr for fr in tracking}
    for side in ("home", "away"):
        fact = teams[side]["final_third_flanks"]["possession"]
        in_possession = set(frame_ids(teams[side]["defensive_line_m"]["in_possession"]["frames"]))
        seen = {}
        for where, ranges in fact["frames"].items():
            for f in frame_ids(ranges):
                fr = by_frame[f]
                assert f in in_possession and depth(fr["ball"][0], side, fr["period"]) >= 70
                assert flank(fr["ball"][1], side, fr["period"]) == where
                seen[where] = seen.get(where, 0) + 1
        assert sum(seen.values()) > 100, side
        assert fact["value_pct"] == {k: round(100 * seen.get(k, 0) / sum(seen.values()), 1)
                                     for k in ("left", "centre", "right")}


def test_attacking_width_is_the_outfield_spread_across_the_pitch_in_possession(high_v_deep):
    tracking, _, _, info = high_v_deep
    teams = tactics(*high_v_deep[1:])["segments"][0]["teams"]
    outfield = team_of(info, DEFENCE | ATTACK | {"DM", "CM", "AM", "RM", "LM"})
    for side in ("home", "away"):
        fact = teams[side]["attacking_width_m"]
        assert fact["frames"] == teams[side]["shape"]["in_possession"]["frames"]
        def spread(fr: dict) -> float:
            ys = [p["pos"][1] for p in fr["players"] if p["id"] in outfield[side]]
            return max(ys) - min(ys)

        width = recomputed(tracking, fact, spread)
        assert 30 < fact["value"] == pytest.approx(width, abs=0.5), side


def test_the_clip_is_also_split_before_and_after_each_goal_and_red_card(sheet):
    events = [
        ev(1, 1.0, "pass", "home", (10, 30), (50, 30)),
        ev(2, 3.0, "shot", "home", (90, 34)),
        ev(3, 3.5, "goal", "home", (105, 34)),
        ev(4, 6.0, "pass", "away", (52, 34), (60, 34)),
        ev(5, 8.0, "red_card", "away", (60, 34), source="sim"),
        ev(6, 9.0, "pass", "home", (50, 34), (60, 34)),
    ]
    segments = tactics([], events, sheet)["segments"]
    assert [(s["id"], s["split_by"], s["start"], round(s["end"], 2)) for s in segments] == [
        ("whole", None, 1.0, 9.0), ("before_e0003", "e0003", 1.0, 3.5), ("after_e0003", "e0003", 3.5, 9.0),
        ("before_e0005", "e0005", 1.0, 8.0), ("after_e0005", "e0005", 8.0, 9.0)]
    passes = [(s["teams"]["home"]["long_balls"]["event_ids"], s["teams"]["away"]["long_balls"]["event_ids"])
              for s in segments]
    assert passes == [(["e0001", "e0006"], ["e0004"]), (["e0001"], []), (["e0006"], ["e0004"]),
                      (["e0001"], ["e0004"]), (["e0006"], [])]


def test_tactics_import_nothing_that_reads_simulator_data():
    """Only the vision AI's observation format and rules (for lineup assignment) and the agents' stats."""
    tree = ast.parse((ROOT / "agents" / "tactics.py").read_text())
    modules = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    modules |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    project = {m for m in modules if m.split(".")[0] in {"vision", "simulator", "scripts", "agents"}}
    assert project == {"agents.stats", "vision.lineup", "vision.observation", "vision.rules"}


def test_after_a_goal_nobody_has_the_ball_until_the_kickoff(high_v_deep):
    _, frames, events, _ = high_v_deep
    teams = tactics(*high_v_deep[1:])["segments"][0]["teams"]
    goal = next(e for e in events if e["type"] == "goal")
    kickoff = next(e for e in events if e["type"] == "kickoff" and e["t"] > goal["t"])
    dead = {f.frame for f in frames if goal["t"] + 0.5 < f.t < kickoff["t"] - 0.5}
    assert len(dead) > 100
    for side in ("home", "away"):
        for phase in ("in_possession", "out_of_possession"):
            assert dead.isdisjoint(frame_ids(teams[side]["shape"][phase]["frames"])), (side, phase)
        assert dead <= set(frame_ids(teams[side]["shape"]["all"]["frames"]))


@pytest.fixture(scope="module")
def four_lines():
    """A 4-2-3-1 (two DMs, then an AM between two wingers, then a striker) against a 4-4-2."""
    return clip(64, load_team("caldera"), load_team("thames"))


def test_per_line_positions_follow_the_team_sheets_own_lines(four_lines):
    info = four_lines[3]
    shape = tactics(*four_lines[1:])["segments"][0]["teams"]["home"]["shape"]["all"]
    pos = {p["id"]: p["pos"] for p in info["home"]["players"]}
    assert [sorted(pos[pid] for pid in line["players"]) for line in shape["lines"]] == [
        ["CB", "CB", "LB", "RB"], ["DM", "DM"], ["AM", "LW", "RW"], ["ST"]]
    depths = [line["depth_m"] for line in shape["lines"]]
    assert depths == sorted(depths)


# ---- coverage (#69): how much of its segment each fact could see ----
def test_a_whole_clip_frame_fact_covers_its_share_of_the_segments_frames(high_v_deep):
    _, frames, events, info = high_v_deep
    seg = tactics(frames, events, info)["segments"][0]
    assert seg["frames"]["n_frames"] == len(frames)
    for side in ("home", "away"):
        fact = seg["teams"][side]["defensive_line_m"]["all"]
        assert fact["coverage"] == round(fact["n_frames"] / len(frames), 3)


def test_a_phase_fact_covers_its_phase_times_the_share_of_frames_whose_possession_is_known(high_v_deep):
    _, frames, events, info = high_v_deep
    seg = tactics(frames, events, info)["segments"][0]
    known = seg["frames"]["possession_known"]
    assert 0.5 < known < 1
    for side in ("home", "away"):
        team = seg["teams"][side]
        for phase in ("in_possession", "out_of_possession"):
            shape = team["shape"][phase]
            # Every frame of the phase is measured (all players named), so the phase's own share is 1.
            assert shape["coverage"] == pytest.approx(known, abs=0.002), (side, phase)
            assert team["defensive_line_m"][phase]["coverage"] <= shape["coverage"] + 0.001


def test_an_event_fact_covers_the_share_of_frames_with_the_ball_seen(high_v_deep):
    _, frames, events, info = high_v_deep
    seg = tactics(frames, events, info)["segments"][0]
    seen = sum(1 for f in frames if f.ball_visible and f.ball is not None)
    assert seg["frames"]["ball_seen"] == round(seen / len(frames), 3)
    for side in ("home", "away"):
        team = seg["teams"][side]
        for fact in (team["long_balls"], team["progressive_passes"], team["regains"], team["final_third_flanks"]["passes"]):
            assert fact["coverage"] == seg["frames"]["ball_seen"]


def test_tactics_output_passes_its_schema(high_v_deep):
    import json
    from jsonschema import Draft202012Validator
    schema = json.loads((ROOT / "schemas" / "tactics.schema.json").read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(tactics(*high_v_deep[1:]))) == []
    assert list(Draft202012Validator(schema).iter_errors(tactics([], PASSES, high_v_deep[3]))) == []
