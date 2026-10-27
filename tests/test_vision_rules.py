"""Seam 2: frame observations -> detected events, built and graded without video.

The harness turns simulator tracking into frame observations (anonymous
tracks, no ball height); the rules turn those into detected events, which the
grader scores against the true events. The simulator clips (`sim_clips`) are
built once per session in conftest.py; tests/test_vision_noise.py grades the
same clips with noise added. Lineup assignment names the tracks, so
the events' players are graded too.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import random
from pathlib import Path

import pytest

from vision.grader import grade, match_events
from vision.harness import observations_from_tracking
from vision.observation import validate_observations, write_observations
from vision.rules import EventRules, detect_events

ROOT = Path(__file__).resolve().parent.parent
CALIBRATION = ROOT / "renderer" / "fixtures" / "calibration"


def _read_jsonl(path):
    """The records of a JSON Lines file."""
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def calibration():
    """(tracking frames, team sheet, true events) of the renderer calibration fixture."""
    return (_read_jsonl(CALIBRATION / "tracking.jsonl"),
            json.loads((CALIBRATION / "match_info.json").read_text()),
            json.loads((CALIBRATION / "ground_truth.events.json").read_text()))


# Clean observations: minimum precision and recall per type over all clips.
# What keeps them below 1 is the simulator, not noise: a clearance is the
# same kick as a long pass (v1 reports it as one), and now and then the
# simulator plays a pass or a shot from a player who is meters from the ball.
# Possession changes cannot come near: the simulator labels an interception
# only when a pass is cut out in the first 30 % of the path to its intended
# target, which video cannot see, and it does not label a recovered loose
# ball or a cleared ball the other team wins (vision/README.md).
THRESHOLDS = {"kickoff": {"precision": 1.0, "recall": 1.0},
              "pass": {"precision": 0.95, "recall": 0.97},
              "possession_change": {"precision": 0.5, "recall": 0.5},
              "shot": {"precision": 0.9, "recall": 0.85},
              "goal": {"precision": 1.0, "recall": 1.0}}
# Matched events whose true event has a subtype: minimum share with the same subtype.
SUBTYPE_THRESHOLDS = {"shot": 0.9, "possession_change": 0.9}
# Matched events (all types above) naming the right players: `from`, and `to`
# where it is a player. Below 1: the first kickoff of a clip is named from one
# frame, where the taker, a striker and an attacking midfielder stand together
# on the halfway line; and the simulator now and then plays a pass or a shot
# from a player meters from the ball while another stands at it.
PLAYER_ID_THRESHOLD = 0.95


@pytest.fixture(scope="module")
def sim_detections(sim_clips):
    """The detected events of each clip in sim_clips, from clean observations."""
    return [detect_events(observations_from_tracking(tracking, team_sheet), team_sheet)
            for tracking, team_sheet, _ in sim_clips]


def test_harness_builds_valid_observations_from_the_calibration_fixture(tmp_path):
    tracking, team_sheet, _ = calibration()
    frames = observations_from_tracking(tracking, team_sheet)
    path = tmp_path / "observations.jsonl"
    write_observations(path, frames)
    assert validate_observations(path) == []
    assert len(frames) == len(tracking)
    assert all(f.ball_visible and f.period == 1 for f in frames)
    # Two anonymous tracks: the roster ids 8 and 10 do not leak into track ids.
    assert {p.track_id for f in frames for p in f.players} == {0, 1}


def test_harness_builds_valid_anonymous_observations_from_a_simulator_seed(tmp_path, sim_clips):
    tracking, team_sheet, _ = sim_clips[0]
    frames = observations_from_tracking(tracking, team_sheet)
    assert len(frames) == len(tracking)
    path = tmp_path / "observations.jsonl"
    write_observations(path, frames[:2 * 60 * 25])     # the schema check is slow; 2 minutes
    assert validate_observations(path) == []
    # Each track is a roster player seen at the same spot, under a different number.
    roster_at = {tuple(p["pos"]): p["id"] for p in tracking[0]["players"]}
    track_to_roster = {p.track_id: roster_at[p.pos] for p in frames[0].players}
    assert len(track_to_roster) == 22
    assert sum(tid == pid for tid, pid in track_to_roster.items()) < 5
    keepers = {p["id"] for side in ("home", "away") for p in team_sheet[side]["players"]
               if p["pos"] == "GK"}
    assert {track_to_roster[p.track_id] for p in frames[0].players if p.goalkeeper} == keepers


def assert_valid_events(validate, events, tmp_path):
    """The events pass scripts/validate.py and the detected-event conventions."""
    path = tmp_path / "events.json"
    path.write_text(json.dumps(events))
    assert validate.check_file(path) == []
    assert [e["id"] for e in events] == [f"e{i:04d}" for i in range(1, len(events) + 1)]
    assert all(e["source"] == "cv" and 0 < e["confidence"] < 1 for e in events)


def test_calibration_fixture_gives_one_pass_one_shot_and_a_goal(validate, tmp_path):
    tracking, team_sheet, truth = calibration()
    events = detect_events(observations_from_tracking(tracking, team_sheet), team_sheet)
    assert_valid_events(validate, events, tmp_path)
    assert [(e["type"], round(e["t"])) for e in events] == [("pass", 2), ("shot", 8), ("goal", 9)]
    report = grade(events, truth, types=["pass", "shot", "goal"])
    for ty in ("pass", "shot", "goal"):
        assert report["per_type"][ty]["precision"] == report["per_type"][ty]["recall"] == 1.0, ty
    assert report["matched"]["pass_success_accuracy"] == 1.0
    p, s = events[0], events[1]
    assert p["subtype"] == "short" and p["team"] == "home"
    assert p["distance_m"] == pytest.approx(17.7, abs=1.0)
    assert p["duration_s"] == pytest.approx(2.0, abs=0.3)
    assert s["distance_m"] == pytest.approx(18.3, abs=1.5)
    assert s["speed_kmh"] == pytest.approx(65.8, abs=10)
    assert s["subtype"] == "on_target" and s["success"] is True
    assert events[2]["score"] == {"home": 1, "away": 0}


def test_a_goal_counts_on_from_the_team_sheets_score_at_start():
    """#83: a clip cut from mid-match at 3-0; the calibration goal is the home side's fourth. Only the
    score changes: the events are the same as from a team sheet without it."""
    tracking, team_sheet, _ = calibration()
    frames = observations_from_tracking(tracking, team_sheet)
    plain = detect_events(frames, team_sheet)
    later = detect_events(frames, {**team_sheet, "score_at_start": {"home": 3, "away": 0}})
    assert plain[-1]["score"] == {"home": 1, "away": 0}
    assert later[-1]["score"] == {"home": 4, "away": 0}
    assert [{k: v for k, v in e.items() if k != "score"} for e in later] == \
        [{k: v for k, v in e.items() if k != "score"} for e in plain]


@pytest.mark.parametrize("seed, until, goal", [
    (5, 140, True),         # 2:01 penalty goal, the keeper standing within reach on the line
    (387, 640, False),      # 10:13 penalty saved: the keeper at the ball on the line
])
def test_a_penalty_goal_counts_and_a_saved_penalty_does_not(seed, until, goal):
    """#87: the ball is dead after the foul, and at a penalty the keeper waits on the line, so
    the old rules read every penalty goal with the keeper near as a save (vision/README.md)."""
    from simulator import Match, build_tracking

    m = Match(seed, 300, "short", f"penalty_{seed}")
    m.play()
    team_sheet = m.match_info()
    tracking = [fr for p in m.periods if p["start"] < until for fr in build_tracking(m, p["start"], min(p["end"], until))]
    events = detect_events(observations_from_tracking(tracking, team_sheet), team_sheet)
    kick = next(e for e in m.events if e["type"] == "free_kick" and e.get("subtype") == "penalty"
                and e["t"] > until - 60)
    shot = next(e for e in m.events if e["type"] == "shot" and e["t"] > kick["t"])
    assert any(e["type"] == "shot" and abs(e["t"] - shot["t"]) < 0.5 and e["subtype"] == "on_target"
               for e in events)
    goals = [e for e in events if e["type"] == "goal" and abs(e["t"] - shot["t"]) < 2]
    assert [g["team"] for g in goals] == ([shot["team"]] if goal else [])


def test_clean_simulator_clips_score_near_perfectly(validate, tmp_path, sim_clips, sim_detections):
    """Precision and recall per type, and shot and possession-change subtypes,
    pooled over seeds and pairings."""
    counts = {ty: {"detected": 0, "true": 0, "matched": 0} for ty in THRESHOLDS}
    subtypes = {ty: [] for ty in SUBTYPE_THRESHOLDS}            # (detected, true) subtype pairs
    for i, ((_, _, truth), events) in enumerate(zip(sim_clips, sim_detections)):
        assert_valid_events(validate, events, tmp_path)
        report = grade(events, truth, types=list(THRESHOLDS))
        assert report["matched"]["pass_success_accuracy"] >= 0.9, i
        for ty, c in counts.items():
            for k in c:
                c[k] += report["per_type"][ty][k]
        for d, t in match_events(events, truth):
            if t["type"] in subtypes and "subtype" in t:
                subtypes[t["type"]].append((d.get("subtype"), t["subtype"]))
    for ty, pairs in subtypes.items():
        assert pairs, f"no true {ty} subtype in the clips"
        accuracy = sum(d == t for d, t in pairs) / len(pairs)
        assert accuracy >= SUBTYPE_THRESHOLDS[ty], (ty, accuracy, len(pairs))
    for ty, c in counts.items():
        assert c["true"] > 0, f"no true {ty} in the clips: pick other seeds"
        precision, recall = c["matched"] / max(1, c["detected"]), c["matched"] / c["true"]
        assert precision >= THRESHOLDS[ty]["precision"], (ty, c)
        assert recall >= THRESHOLDS[ty]["recall"], (ty, c)


def test_kickoffs_are_found_at_both_half_starts_and_after_every_goal(sim_clips, sim_detections):
    """Exactly one detected kickoff per half start and per goal, on the center
    spot, by the right team."""
    for i, ((_, team_sheet, truth), events) in enumerate(zip(sim_clips, sim_detections)):
        true_kickoffs = [e for e in truth if e["type"] == "kickoff"]
        goals = [e for e in truth if e["type"] == "goal"]
        after_goal = [next(k for k in true_kickoffs if k["t"] > g["t"]) for g in goals
                      if any(k["t"] > g["t"] for k in true_kickoffs)]
        starts = [k for k in true_kickoffs
                  if any(abs(k["t"] - p["start"]) < 0.1 for p in team_sheet["periods"])]
        assert len(starts) == 2, i
        expected = sorted(starts + after_goal, key=lambda k: k["t"])
        detected = [e for e in events if e["type"] == "kickoff"]
        assert len(detected) == len(expected), (i, [d["t"] for d in detected],
                                                [k["t"] for k in expected])
        for d, k in zip(detected, expected):
            assert abs(d["t"] - k["t"]) <= 0.5, (i, d, k)
            assert d["team"] == k["team"] and d["period"] == k["period"], (i, d, k)
            assert abs(d["start"][0] - 52.5) <= 1 and abs(d["start"][1] - 34) <= 1, (i, d)


def roster_of_tracks(tracking, frames) -> dict[int, int]:
    """Track id -> the roster id it stands for, from the positions the
    harness copied from the tracking."""
    out = {}
    for fr, ob in zip(tracking, frames):
        at = {tuple(p["pos"]): p["id"] for p in fr["players"]}
        for p in ob.players:
            out.setdefault(p.track_id, at[p.pos])
    return out


def test_events_name_the_right_players(sim_clips, sim_detections):
    """Player-id accuracy over matched events, pooled over seeds and pairings."""
    right = total = 0
    for i, ((_, _, truth), events) in enumerate(zip(sim_clips, sim_detections)):
        m = grade(events, truth, types=list(THRESHOLDS))["matched"]
        right += m["player_id_accuracy"] * m["count"]
        total += m["count"]
    assert total > 1000
    assert right / total >= PLAYER_ID_THRESHOLD, right / total


def test_every_player_is_a_roster_id_or_null_where_the_schema_allows(sim_clips, sim_detections):
    """`from`/`to` are roster ids from the team sheet; `to` is null for shots,
    goals and failed passes and kickoffs. Every event after the first kickoff
    names its player."""
    for i, ((_, team_sheet, _), events) in enumerate(zip(sim_clips, sim_detections)):
        roster = {p["id"]: side for side in ("home", "away") for p in team_sheet[side]["players"]}
        for e in events:
            assert e["from"] is None or e["from"] in roster, (i, e)
            assert e["to"] is None or e["to"] in roster, (i, e)
            if e["type"] in ("shot", "goal") or (e["type"] in ("pass", "kickoff") and not e["success"]):
                assert e["to"] is None, (i, e)
            if e["from"] is not None and e["type"] != "possession_change":
                assert roster[e["from"]] == e["team"], (i, e)
            if e["type"] == "possession_change" and e["to"] is not None:
                assert roster[e["from"]] == e["team"] != roster[e["to"]], (i, e)
        first = next(e["t"] for e in events if e["type"] == "kickoff")
        named = [e["from"] is not None for e in events if e["t"] >= first]
        assert sum(named) / len(named) >= 0.97, (i, sum(named), len(named))


def test_names_over_time_follow_the_tracks_without_changing_the_events(sim_clips, sim_detections):
    """`names` collects, per frame, the roster id each named track stands for
    (what the AI view draws). Nobody is named before the first kickoff; after
    it, the names are the right players; the events are the same as without it."""
    for i, (tracking, team_sheet, _) in enumerate(sim_clips):
        frames = observations_from_tracking(tracking, team_sheet)
        names: list[dict[int, int]] = []
        assert detect_events(frames, team_sheet, names=names) == sim_detections[i], i
        assert len(names) == len(frames), i
        roster = roster_of_tracks(tracking, frames)
        first = next(e["t"] for e in sim_detections[i] if e["type"] == "kickoff")
        right = total = 0
        for f, named in zip(frames, names):
            assert set(named) <= {p.track_id for p in f.players}, (i, f.frame)
            if f.t < first - 1.0:
                assert named == {}, (i, f.frame, named)
            elif f.t > first + 1.0:
                assert len(named) >= 20, (i, f.frame, len(named))
                right += sum(roster[tid] == pid for tid, pid in named.items())
                total += len(named)
        assert right / total >= 0.95, (i, right, total)


def break_tracks(frames, seed=0, every_s=20.0, lost_frames=10, per_break=3):
    """Frames where, every `every_s` from the third minute, `per_break` tracks
    (at times of the same team) vanish for `lost_frames` and come back under
    new track ids, as a video tracker loses players. Returns the frames and
    each new track id's original."""
    rng = random.Random(seed)
    alias = {}                          # original track -> current track id
    origin = {}                         # new track id -> original track
    gone = {}                           # original track -> frames left unseen
    back = set()                        # original tracks due back under a new id
    next_id = 1000
    next_break = frames[0].t + 180.0
    out = []
    for f in frames:
        if f.t >= next_break:
            next_break = f.t + every_s
            ready = sorted(p.track_id for p in f.players
                           if gone.get(p.track_id, 0) == 0 and p.track_id not in back)
            for tid in rng.sample(ready, per_break):
                gone[tid] = lost_frames
        players = []
        for p in f.players:
            tid = p.track_id
            if gone.get(tid, 0) > 0:
                gone[tid] -= 1
                if gone[tid] == 0:
                    back.add(tid)
                continue
            if tid in back:                         # its first frame back
                back.discard(tid)
                alias[tid], origin[next_id] = next_id, tid
                next_id += 1
            players.append(dataclasses.replace(p, track_id=alias.get(tid, tid)))
        out.append(dataclasses.replace(f, players=players))
    return out, origin


def test_broken_and_restarted_tracks_get_their_players_back(sim_clips):
    """Tracks lost mid-play come back under new ids: re-matching to the
    nearest last-known position names them right, before any kickoff could."""
    tracking, team_sheet, truth = sim_clips[0]
    clean = observations_from_tracking(tracking, team_sheet)
    roster = roster_of_tracks(tracking, clean)
    frames, origin = break_tracks(clean)
    assert len(origin) > 100
    rules = EventRules(team_sheet)
    checked = right = 0
    seen = {}                                       # new track -> frames seen
    events = []
    for f in frames:
        events += rules.push(f)
        for p in f.players:
            if p.track_id in origin:
                seen[p.track_id] = seen.get(p.track_id, 0) + 1
                if seen[p.track_id] == 1:           # its first frame back
                    checked += 1
                    right += rules.lineup.player(p.track_id) == roster[origin[p.track_id]]
    events += rules.finish()
    assert checked == len(origin)
    assert right / checked >= 0.95, (right, checked)
    # The events of the broken clip name players as well as the clean clip's.
    events.sort(key=lambda e: e["t"])
    events = [{"id": f"e{i:04d}", **e} for i, e in enumerate(events, start=1)]
    m = grade(events, truth, types=list(THRESHOLDS))["matched"]
    assert m["player_id_accuracy"] >= PLAYER_ID_THRESHOLD, m


def project_imports(path: Path) -> set[str]:
    """The project modules (vision, simulator, scripts, agents) a file imports."""
    tree = ast.parse(path.read_text())
    modules = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    modules |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    return {m for m in modules if m.split(".")[0] in {"vision", "simulator", "scripts", "agents"}}


def test_rules_see_only_frame_observations_and_the_team_sheet():
    """The rules and lineup modules import nothing that could read simulator data."""
    assert project_imports(ROOT / "vision" / "rules.py") == {"vision.observation", "vision.lineup"}
    assert project_imports(ROOT / "vision" / "lineup.py") == {"vision.observation"}


def test_no_vision_code_imports_the_harness():
    """The harness reads simulator tracking, so it stays out of vision code."""
    for path in (ROOT / "vision").rglob("*.py"):
        if path.name == "harness.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [a.name for a in node.names]
            assert not any("harness" in n for n in names), f"{path} imports the harness"
