"""Grader: detected events vs. true events, on small hand-built lists."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from vision import grader
from vision.grader import grade

ROOT = Path(__file__).resolve().parent.parent
CALIBRATION_TRUTH = ROOT / "renderer" / "fixtures" / "calibration" / "ground_truth.events.json"


def ev(id, type, t, start, frm=8, to=None, **extra):
    """A minimal shared-schema event."""
    return {"id": id, "match_id": "m", "t": t, "period": 1, "type": type, "team": "home",
            "from": frm, "to": to, "start": list(start), "source": "cv", "confidence": 0.9, **extra}


def test_exact_match_scores_perfectly():
    truth = [ev("e0001", "pass", 2.0, (50, 30), to=10, success=True),
             ev("e0002", "shot", 8.0, (88, 33))]
    report = grade(truth, truth)
    for t in ("pass", "shot"):
        assert report["per_type"][t] == {"detected": 1, "true": 1, "matched": 1,
                                         "precision": 1.0, "recall": 1.0, "f1": 1.0}
    assert report["unmatched_detections"] == [] and report["missed"] == []


TRUE_PASS = ev("e0001", "pass", 10.0, (50.0, 30.0), to=10, success=True)


@pytest.mark.parametrize("t, start, matched", [
    (10.49, (50.0, 30.0), True),     # time: just inside 0.5 s
    (10.51, (50.0, 30.0), False),    # time: just outside
    (9.51, (50.0, 30.0), True),      # early detections count too
    (9.49, (50.0, 30.0), False),
    (10.0, (54.9, 30.0), True),      # space: just inside 5 m
    (10.0, (55.1, 30.0), False),     # space: just outside
    (10.0, (53.0, 33.9), True),      # 3-4-5 triangle: 4.92 m, inside
    (10.0, (53.0, 34.1), False),     # 5.08 m, outside
])
def test_time_and_space_tolerance(t, start, matched):
    report = grade([ev("e0001", "pass", t, start, to=10, success=True)], [TRUE_PASS])
    assert report["per_type"]["pass"]["matched"] == (1 if matched else 0)
    assert len(report["missed"]) == (0 if matched else 1)
    assert len(report["unmatched_detections"]) == (0 if matched else 1)


def test_two_detections_compete_for_one_true_event():
    """The closer detection wins; the other is a false positive."""
    near = ev("e0001", "pass", 10.1, (50.5, 30.0), to=10, success=True)
    far = ev("e0002", "pass", 10.3, (52.0, 30.0), to=10, success=True)
    report = grade([near, far], [TRUE_PASS])
    assert report["per_type"]["pass"] == {"detected": 2, "true": 1, "matched": 1,
                                          "precision": 0.5, "recall": 1.0, "f1": pytest.approx(2 / 3)}
    assert [e["id"] for e in report["unmatched_detections"]] == ["e0002"]


def test_closest_first_is_not_detection_order():
    """A detection that fits two true events takes the closer one, leaving the
    other true event to a second detection that only fits it."""
    true_a = ev("e0001", "pass", 10.0, (50.0, 30.0))
    true_b = ev("e0002", "pass", 10.4, (50.0, 30.0))
    det_mid = ev("e0001", "pass", 10.3, (50.0, 30.0))   # closer to b (0.1 s) than a (0.3 s)
    det_a = ev("e0002", "pass", 9.9, (50.0, 30.0))      # fits only a
    report = grade([det_mid, det_a], [true_a, true_b])
    assert report["per_type"]["pass"]["matched"] == 2
    assert report["missed"] == [] and report["unmatched_detections"] == []


def test_wrong_type_does_not_match():
    report = grade([ev("e0001", "shot", 10.0, (50.0, 30.0))], [TRUE_PASS])
    assert report["per_type"]["pass"] == {"detected": 0, "true": 1, "matched": 0,
                                          "precision": None, "recall": 0.0, "f1": 0.0}
    assert report["per_type"]["shot"] == {"detected": 1, "true": 0, "matched": 0,
                                          "precision": 0.0, "recall": None, "f1": 0.0}
    assert report["missed"] == [{"id": "e0001", "type": "pass", "t": 10.0, "start": [50.0, 30.0]}]
    assert report["unmatched_detections"][0]["type"] == "shot"


def test_wrong_player_still_matches_but_scores_player_id():
    """Matching ignores who; player-id accuracy reports it."""
    right = ev("e0001", "pass", 10.0, (50.0, 30.0), frm=8, to=10, success=True)
    wrong_passer = ev("e0002", "pass", 20.0, (50.0, 30.0), frm=7, to=10, success=True)
    wrong_receiver = ev("e0003", "pass", 30.0, (50.0, 30.0), frm=8, to=9, success=True)
    truth = [ev("e0001", "pass", 10.0, (50.0, 30.0), frm=8, to=10, success=True),
             ev("e0002", "pass", 20.0, (50.0, 30.0), frm=8, to=10, success=True),
             ev("e0003", "pass", 30.0, (50.0, 30.0), frm=8, to=10, success=True)]
    report = grade([right, wrong_passer, wrong_receiver], truth)
    assert report["per_type"]["pass"]["matched"] == 3
    assert report["matched"]["player_id_accuracy"] == pytest.approx(1 / 3)


def test_matched_event_errors():
    det = [ev("e0001", "pass", 10.2, (50.0, 30.0), to=None, success=False,
              distance_m=18.0, speed_kmh=40.0),
           ev("e0002", "pass", 19.9, (60.0, 30.0), to=10, success=True,
              distance_m=30.0, speed_kmh=50.0),
           ev("e0003", "shot", 30.0, (90.0, 34.0), distance_m=16.0, speed_kmh=90.0)]
    truth = [ev("e0001", "pass", 10.0, (50.0, 30.0), to=10, success=True,
                distance_m=20.0, speed_kmh=36.0),
             ev("e0002", "pass", 20.0, (60.0, 30.0), to=10, success=True,
                distance_m=29.0, speed_kmh=50.0),
             ev("e0003", "shot", 30.0, (90.0, 34.0), distance_m=17.0, speed_kmh=80.0)]
    m = grade(det, truth)["matched"]
    assert m["count"] == 3
    assert m["pass_success_accuracy"] == 0.5                       # one of two passes
    assert m["mean_abs_time_error_s"] == pytest.approx(0.1)        # (0.2 + 0.1 + 0) / 3
    assert m["mean_abs_distance_error_m"] == pytest.approx(4 / 3)  # (2 + 1 + 1) / 3
    assert m["mean_abs_speed_error_kmh"] == pytest.approx(14 / 3)  # (4 + 0 + 10) / 3


def test_matched_metrics_are_null_without_matches():
    m = grade([], [TRUE_PASS])["matched"]
    assert m == {"count": 0, "player_id_accuracy": None, "pass_success_accuracy": None,
                 "mean_abs_time_error_s": None, "mean_abs_distance_error_m": None,
                 "mean_abs_speed_error_kmh": None}


def test_types_limits_what_is_graded():
    """True events of types vision does not detect are left out, not missed."""
    truth = [TRUE_PASS, ev("e0002", "throw_in", 12.0, (40.0, 0.0)), ev("e0003", "foul", 14.0, (30.0, 20.0))]
    report = grade([dict(TRUE_PASS)], truth, types=["pass", "shot"])
    assert report["types"] == ["pass", "shot"]
    assert set(report["per_type"]) == {"pass", "shot"}
    assert report["per_type"]["shot"]["true"] == 0
    assert report["missed"] == []


def _manifest(path):
    """An export manifest as renderer/scripts/export.ts writes it (frames trimmed)."""
    path.write_text(json.dumps({
        "match_id": "renderer_calibration_v1", "fps": 25, "width": 1920, "height": 1080,
        "start": 0, "end": 12, "rich": False,
        "render": {"camera": "cv_full_pitch", "playerScale": 1, "ballScale": 2, "cvVisibility": True},
        "frames": [{"output_frame": 0, "t": 0, "input_frame": 0}],
    }))
    return path


def test_calibration_truth_against_itself_is_perfect(tmp_path):
    out = tmp_path / "vision_report.json"
    code = grader.main(["--detected", str(CALIBRATION_TRUTH), "--truth", str(CALIBRATION_TRUTH),
                        "--manifest", str(_manifest(tmp_path / "clip.mp4.manifest.json")),
                        "--seed", "7", "--training-seeds", "1", "2", "3", "--out", str(out)])
    assert code == 0
    report = json.loads(out.read_text())
    assert report["match_id"] == "renderer_calibration_v1"
    for ty in ("pass", "shot", "goal"):
        assert report["per_type"][ty] == {"detected": 1, "true": 1, "matched": 1,
                                          "precision": 1.0, "recall": 1.0, "f1": 1.0}
    for ty in ("kickoff", "possession_change"):      # graded by default, absent from this clip
        assert report["per_type"][ty] == {"detected": 0, "true": 0, "matched": 0,
                                          "precision": None, "recall": None, "f1": None}
    assert report["matched"] == {"count": 3, "player_id_accuracy": 1.0, "pass_success_accuracy": 1.0,
                                 "mean_abs_time_error_s": 0.0, "mean_abs_distance_error_m": 0.0,
                                 "mean_abs_speed_error_kmh": 0.0}
    assert report["unmatched_detections"] == [] and report["missed"] == []
    assert report["clip"]["render"] == {"camera": "cv_full_pitch", "playerScale": 1, "ballScale": 2,
                                        "cvVisibility": True, "width": 1920, "height": 1080, "rich": False}
    assert report["clip"]["seed"] == 7
    assert report["clip"]["training_seeds"] == [1, 2, 3]
    assert (report["clip"]["start"], report["clip"]["end"]) == (0, 12)


def test_render_settings_can_be_passed_without_a_manifest(tmp_path):
    out = tmp_path / "vision_report.json"
    assert grader.main(["--detected", str(CALIBRATION_TRUTH), "--truth", str(CALIBRATION_TRUTH),
                        "--render", "camera=cv_full_pitch", "--render", "ballScale=2",
                        "--render", "cvVisibility=true", "--types", "all", "--out", str(out)]) == 0
    report = json.loads(out.read_text())
    assert report["clip"]["render"] == {"camera": "cv_full_pitch", "ballScale": 2, "cvVisibility": True}
    assert report["clip"]["seed"] is None
    assert report["types"] == ["goal", "pass", "shot"]


def test_runtime_vision_code_never_imports_the_grader():
    """The grader reads true events, so it must stay off the runtime path."""
    for path in (ROOT / "vision").rglob("*.py"):
        if path == ROOT / "vision" / "grader.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [a.name for a in node.names]
            assert not any("grader" in n for n in names), f"{path} imports the grader"
