"""Video stage end to end on the calibration clip (Git LFS): video + team sheet in,
frame observations out, compared with the fixture's tracking.

The clip has two home players (A holds, passes, B carries and shoots) and the
ball; see renderer/fixtures/calibration/README.md. The run takes about a minute.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import numpy as np
import pytest

from vision.observation import read_observations, validate_observations

ROOT = Path(__file__).resolve().parent.parent
CLIP = ROOT / "vision" / "fixtures" / "calibration"
FIXTURE = ROOT / "renderer" / "fixtures" / "calibration"
RUNTIME = ("video.py", "detect.py", "pitch.py", "observation.py")   # the video stage's modules

PLAYER_TOLERANCE_M = 1.0     # foot point vs tracked position
BALL_TOLERANCE_M = 0.5       # ball ground point vs tracked position, ball on the ground
PHANTOM_M = 2.0              # an observation this far from every player is not a player
MOST = 0.9                   # "most frames"


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    """Observations for the calibration clip, written by the command line entry point."""
    video = CLIP / "calibration.mp4"
    if video.read_bytes()[:40].startswith(b"version https://git-lfs"):
        pytest.fail("calibration.mp4 is a Git LFS pointer: run `git lfs install && git lfs pull`")
    from vision.video import main

    out = tmp_path_factory.mktemp("video") / "observations.jsonl"
    assert main([str(video), "--out", str(out)]) == 0
    truth = [json.loads(line) for line in (FIXTURE / "tracking.jsonl").read_text().splitlines()]
    return out, read_observations(out), truth


def test_observations_pass_the_contract_check(run):
    out, frames, truth = run
    assert validate_observations(out) == []
    assert [f.frame for f in frames] == list(range(len(truth)))
    assert all(f.t == pytest.approx(t["t"]) for f, t in zip(frames, truth))
    assert {f.period for f in frames} == {1}


def test_ball_on_the_ground_is_located(run):
    """The ball is seen on most frames and its ground point matches tracking while it rolls.
    (In the air its ground projection is off by design; height is not recovered.)"""
    _, frames, truth = run
    assert sum(f.ball_visible for f in frames) >= MOST * len(frames)
    errors = [np.hypot(f.ball.pos[0] - t["ball"][0], f.ball.pos[1] - t["ball"][1])
              for f, t in zip(frames, truth) if f.ball_visible and t["ball"][2] < 0.3]
    assert len(errors) >= MOST * sum(t["ball"][2] < 0.3 for t in truth)
    assert np.percentile(errors, 95) <= BALL_TOLERANCE_M, np.percentile(errors, 95)


def test_both_players_are_observed_on_their_team(run):
    """Each tracked player has an observed player within tolerance on most frames,
    and every observed player is on the home team and not a goalkeeper."""
    _, frames, truth = run
    for pid in (8, 10):
        hits = 0
        for f, t in zip(frames, truth):
            x, y = next(p["pos"] for p in t["players"] if p["id"] == pid)
            near = [p for p in f.players if np.hypot(p.pos[0] - x, p.pos[1] - y) <= PLAYER_TOLERANCE_M]
            hits += bool(near)
        assert hits >= MOST * len(frames), f"player {pid} observed on {hits}/{len(frames)} frames"
    observed = [p for f in frames for p in f.players]
    assert all(p.team == "home" and not p.goalkeeper for p in observed)


def test_no_phantom_players(run):
    """Nothing is observed that is not one of the two players. (A box can briefly
    take in the ball arriving at a player's feet, which moves the foot point.)"""
    _, frames, truth = run
    for f, t in zip(frames, truth):
        for p in f.players:
            gap = min(np.hypot(p.pos[0] - q["pos"][0], p.pos[1] - q["pos"][1]) for q in t["players"])
            assert gap <= PHANTOM_M, (f.frame, p)


def test_fixture_team_sheet_is_the_renderer_fixtures():
    """The committed clip's team sheet is the one it was rendered from."""
    assert (json.loads((CLIP / "match_info.json").read_text())
            == json.loads((FIXTURE / "match_info.json").read_text()))


def test_video_stage_reads_only_video_and_team_sheet():
    """The video stage never imports simulator, grading or footage code, and never
    names a simulator output file."""
    banned_imports = ("simulator", "vision.grader", "vision.baseline", "vision.footage",
                      "vision.grade_footage")
    banned_names = ("tracking.jsonl", "events.json", "truth", "ground_truth")
    for name in RUNTIME:
        path = ROOT / "vision" / name
        source = path.read_text()
        for node in ast.walk(ast.parse(source)):
            modules = []
            if isinstance(node, ast.Import):
                modules = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            for module in modules:
                assert not any(module == b or module.startswith(b + ".") for b in banned_imports), \
                    f"{name} imports {module}"
        for banned in banned_names:
            assert banned not in source, f"{name} mentions {banned}"
