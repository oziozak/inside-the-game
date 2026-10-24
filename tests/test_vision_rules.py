"""Seam 2: frame observations -> detected events, built and graded without video.

The harness turns simulator tracking into frame observations (anonymous
tracks, no ball height); the rules turn those into detected events, which the
grader scores against the true events.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from simulator import Match, build_tracking, load_team
from vision.grader import grade, match_events
from vision.harness import observations_from_tracking
from vision.observation import validate_observations, write_observations
from vision.rules import detect_events

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


# Simulator clips: the first minutes of each half of a full match, cut
# together as the broadcast cuts the break, so kickoff direction and the
# second-half switch are covered. Not the tuning seeds (201-204), though their
# grades were looked at while tuning (vision/README.md). Between them the clips
# hold 7 goals, each followed by a kickoff.
CLIP_SEEDS = [(401, "bosphorus", "thames"), (402, "caldera", "saltmarsh"),
              (403, "saltmarsh", "bosphorus"), (404, "thames", "caldera")]
CLIP_MINUTES = 15                       # from the start of each half

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


@pytest.fixture(scope="module")
def sim_clips():
    """[(tracking, team sheet, true events in the clip)] for a few seeds and
    pairings, each clip the first CLIP_MINUTES of both halves."""
    out = []
    for seed, home, away in CLIP_SEEDS:
        m = Match(seed, 2700, "full", f"seam2_{seed}", home=load_team(home), away=load_team(away))
        m.play()
        windows = [(p["start"], min(p["end"], p["start"] + CLIP_MINUTES * 60)) for p in m.periods]
        tracking = [fr for start, end in windows for fr in build_tracking(m, start, end)]
        out.append((tracking, m.match_info(),
                    [e for e in m.events if any(start <= e["t"] < end for start, end in windows)]))
    return out


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


def test_clean_simulator_clips_score_near_perfectly(validate, tmp_path, sim_clips):
    """Precision and recall per type, and shot and possession-change subtypes,
    pooled over seeds and pairings."""
    counts = {ty: {"detected": 0, "true": 0, "matched": 0} for ty in THRESHOLDS}
    subtypes = {ty: [] for ty in SUBTYPE_THRESHOLDS}            # (detected, true) subtype pairs
    for i, (tracking, team_sheet, truth) in enumerate(sim_clips):
        events = detect_events(observations_from_tracking(tracking, team_sheet), team_sheet)
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


def test_kickoffs_are_found_at_both_half_starts_and_after_every_goal(sim_clips):
    """Exactly one detected kickoff per half start and per goal, on the center
    spot, by the right team."""
    for i, (tracking, team_sheet, truth) in enumerate(sim_clips):
        events = detect_events(observations_from_tracking(tracking, team_sheet), team_sheet)
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


def test_rules_see_only_frame_observations_and_the_team_sheet():
    """The rules module imports nothing that could read simulator data."""
    tree = ast.parse((ROOT / "vision" / "rules.py").read_text())
    modules = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    modules |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    project = {m for m in modules if m.split(".")[0] in {"vision", "simulator", "scripts", "agents"}}
    assert project == {"vision.observation"}


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
