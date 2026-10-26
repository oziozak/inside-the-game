"""End to end on 22-player footage: the tracer on the dev and test clips, graded.

These run only when the clips are rendered and $VISION_FOOTAGE points at them
(the folder holding dev1/, ..., test1/, as `python -m vision.footage render`
writes them); otherwise they skip, so no machine is forced to render:

    VISION_FOOTAGE=data/renders/footage pytest tests/test_vision_footage.py -k dev

The tracer runs at about 6 frames/s on an M-series Mac: about 8 minutes per
2-minute dev clip, 40 for the 10-minute test clip. Each clip is run fresh
through `python -m vision`, graded and checked against THRESHOLDS.

The test clip is the held-out grade. Its thresholds record what the detector
and rules score on it; it is never used to tune them.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from vision.footage import RENDER_SETTINGS, load_record
from vision.grade_footage import FOOTAGE_ENV, footage_root, grade_clip
from vision.grader import DETECTED_TYPES, match_events

ROOT = Path(__file__).resolve().parent.parent
CALIBRATION = ROOT / "vision" / "fixtures" / "calibration"
TRUTH = ROOT / "renderer" / "fixtures" / "calibration" / "ground_truth.events.json"
CLIPS = {c["name"]: c for c in load_record()["clips"] if c["role"] in ("dev", "test")}

# Minimum precision and recall per clip and type. Each floor is the first
# measured grade (2026-10-24, pretrained yolo11s; test2 2026-10-26) minus a
# cross-hardware margin, because the dev clips were graded on MPS (Apple GPU)
# and test1 and test2 on CUDA (RTX PC), and a detection can flip between them:
#   - pass: the measured score minus 0.03, rounded down to 0.01;
#   - the other types (5 true events or fewer in every clip): one match fewer,
#     so recall (matched - 1) / true and precision (matched - 1) / detected.
# A floor that comes out at 0 is left out, since it asserts nothing; so is
# an undefined score (no true events, or none detected). Kickoffs (1 per
# clip, 2 in test2) get no floor; test_every_kickoff_is_found_for_the_right_team
# asserts each one instead.
# Only test2 holds a goal (1/1, so its floor is 0 and left out). Floors are
# only ever raised, from a better measured grade by the same rule, never lowered.
# Comments: first grade as matched / true, detected.
THRESHOLDS: dict[str, dict[str, dict[str, float]]] = {
    "dev1": {"pass": {"precision": 0.93, "recall": 0.88},                  # 31/34, 32
             "possession_change": {"precision": 0.66, "recall": 0.66}},   # 3/3, 3
    # shot 0/1, 0
    "dev2": {"pass": {"precision": 0.84, "recall": 0.79}},                 # 14/17, 16
    # possession change 0/2, 2; shot 1/2, 1
    "dev3": {"pass": {"precision": 0.83, "recall": 0.73},                  # 19/25, 22
             "shot": {"precision": 0.33, "recall": 0.5}},                 # 2/2, 3
    # possession change 1/2, 3
    # Held out: graded once, on CUDA.
    "test1": {"pass": {"precision": 0.93, "recall": 0.94},                 # 131/135, 136
              "possession_change": {"precision": 0.14, "recall": 0.25},   # 2/4, 7
              "shot": {"precision": 0.33, "recall": 0.5}},                # 2/2, 3
    # Held out, minutes 40-50 (#35): graded once, on CUDA (2026-10-26).
    "test2": {"pass": {"precision": 0.95, "recall": 0.90},                 # 84/90, 85
              "possession_change": {"precision": 0.25, "recall": 0.2},    # 2/5, 4
              "shot": {"precision": 0.5, "recall": 0.66}},                # 3/3, 4
    # goal 1/1, 1
}


@pytest.fixture(scope="module")
def graded(tmp_path_factory):
    """Grade a clip once per test session: name -> (report, detected events path)."""
    cache = {}

    def get(name):
        if name not in cache:
            if not os.environ.get(FOOTAGE_ENV):
                pytest.skip(f"set {FOOTAGE_ENV} to the footage root to run (clips from "
                            f"`python -m vision.footage render {name}`)")
            footage = footage_root()
            if not (footage / name / f"{name}.mp4").exists():
                pytest.skip(f"{name} is not rendered in {footage}")
            out = tmp_path_factory.mktemp(name)
            cache[name] = grade_clip(CLIPS[name], footage, out), out / "events.json"
        return cache[name]
    return get


def test_every_dev_and_test_clip_has_thresholds():
    assert set(THRESHOLDS) == set(CLIPS)
    assert any(c["role"] == "test" for c in CLIPS.values())


@pytest.mark.parametrize("name", sorted(CLIPS))
def test_footage_grade(graded, validate, name):
    report, events_file = graded(name)
    events = json.loads(events_file.read_text())
    assert validate.check_file(events_file) == []
    assert all(e["source"] == "cv" and 0 < e["confidence"] < 1 for e in events)
    clip = report["clip"]
    assert (clip["name"], clip["role"], clip["seed"]) == (name, CLIPS[name]["role"],
                                                          CLIPS[name]["seed"])
    assert {k: clip["render"][k] for k in RENDER_SETTINGS} == RENDER_SETTINGS
    assert clip["training_seeds"] == []
    assert "player_id_accuracy" in report["matched"]   # reported; asserted once graded after #18
    for ty, mins in THRESHOLDS[name].items():
        scores = report["per_type"][ty]
        for metric, floor in mins.items():
            assert scores[metric] is not None and scores[metric] >= floor, (name, ty, metric, scores)


@pytest.mark.parametrize("name", sorted(CLIPS))
def test_every_kickoff_is_found_for_the_right_team(graded, name):
    """No margin here: kickoffs anchor lineup assignment, so a lost or
    misattributed one would silently break player names."""
    report, events_file = graded(name)
    kickoffs = [e for e in json.loads(events_file.read_text()) if e["type"] == "kickoff"]
    true = [e for e in json.loads(Path(report["truth_file"]).read_text()) if e["type"] == "kickoff"]
    assert true, f"{name} has no true kickoff"
    pairs = match_events(kickoffs, true)
    assert len(pairs) == len(true), (name, kickoffs, true)
    assert [d["team"] for d, _ in pairs] == [t["team"] for _, t in pairs]


def test_grade_clip_records_settings_and_seeds(tmp_path):
    """Plumbing, no video: re-grading saved detections writes a report with the
    clip's render settings (manifest), seed and role (seed record)."""
    clip = {**CLIPS["dev1"], "name": "calib"}
    folder = tmp_path / "footage" / "calib"
    (folder / "truth").mkdir(parents=True)
    (folder / "calib.mp4").write_bytes(b"")
    shutil.copy(CALIBRATION / "calibration.mp4.manifest.json", folder / "calib.mp4.manifest.json")
    shutil.copy(TRUTH, folder / "truth" / "events.json")
    out = tmp_path / "runs" / "calib"
    out.mkdir(parents=True)
    shutil.copy(TRUTH, out / "events.json")             # perfect detections

    report = grade_clip(clip, tmp_path / "footage", out, reuse=True)
    assert json.loads((out / "vision_report.json").read_text()) == report
    assert report["types"] == DETECTED_TYPES
    assert report["clip"]["render"]["camera"] == "cv_full_pitch"
    assert (report["clip"]["seed"], report["clip"]["role"], report["clip"]["training_seeds"]) == \
        (clip["seed"], "dev", [])
    assert report["missed"] == report["unmatched_detections"] == []


def test_grade_clip_runs_the_tracer_from_the_clip_start(tmp_path, monkeypatch):
    """A clip from minute 40 is traced with --start 2400, so its events carry match time,
    and the same run is drawn as the AI view once the grade is written."""
    clip = {**CLIPS["test2"], "name": "calib"}
    folder = tmp_path / "footage" / "calib"
    (folder / "truth").mkdir(parents=True)
    (folder / "calib.mp4").write_bytes(b"")
    shutil.copy(CALIBRATION / "calibration.mp4.manifest.json", folder / "calib.mp4.manifest.json")
    shutil.copy(TRUTH, folder / "truth" / "events.json")
    calls = []

    out = tmp_path / "runs"

    def run(args, **kwargs):
        calls.append((args, (out / "vision_report.json").exists()))
        if args[2] == "vision":
            shutil.copy(TRUTH, out / "events.json")
    monkeypatch.setattr("vision.grade_footage.subprocess.run", run)
    grade_clip(clip, tmp_path / "footage", out)
    (tracer, graded_before), (annotate, graded_after) = calls
    assert tracer[1:3] == ["-m", "vision"] and tracer[tracer.index("--start") + 1] == "2400"
    assert tracer[tracer.index("--frame-boxes") + 1] == str(out / "frame_boxes.jsonl")
    assert annotate[1:5] == ["-m", "vision.annotate", str(folder), str(out)]
    assert annotate[annotate.index("--out") + 1] == str(out / "ai_view.mp4")
    assert (graded_before, graded_after) == (False, True)

    calls.clear()                                       # re-grading saved events draws nothing
    grade_clip(clip, tmp_path / "footage", out, reuse=True)
    assert calls == []


def test_footage_root_prefers_argument_then_environment(monkeypatch, tmp_path):
    monkeypatch.setenv(FOOTAGE_ENV, str(tmp_path))
    assert footage_root() == tmp_path
    assert footage_root(tmp_path / "x") == tmp_path / "x"
    monkeypatch.delenv(FOOTAGE_ENV)
    assert footage_root() == ROOT / "data" / "renders" / "footage"
