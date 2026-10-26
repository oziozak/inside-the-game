"""Choosing NAME_MIN_CONFIDENCE: the lowest confidence above which named players are right often enough."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def name_threshold():
    """scripts/name_threshold.py loaded as a module."""
    spec = importlib.util.spec_from_file_location("name_threshold", ROOT / "scripts" / "name_threshold.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_detection_gets_an_outcome(name_threshold):
    def ev(i, t, conf, frm, to=None, typ="pass"):
        return {"id": f"e{i:04d}", "type": typ, "t": t, "start": [50.0, 30.0], "from": frm, "to": to,
                "confidence": conf}

    truth = [ev(1, 1.0, 1.0, 7, 9), ev(2, 5.0, 1.0, 9, 7), ev(3, 9.0, 1.0, 4, 7), ev(4, 13.0, 1.0, 7, 9)]
    detected = [ev(1, 1.1, 0.9, 7, 9),        # right
                ev(2, 5.1, 0.3, 9, 4),        # wrong receiver
                ev(3, 9.1, 0.8, None, None),  # no player: never named
                ev(4, 30.0, 0.2, 7, 9),       # no true event near it
                ev(5, 1.0, 0.9, None, typ="foul")]  # not a type the vision AI detects
    assert name_threshold.outcomes(detected, truth) == [
        (0.9, "right"), (0.3, "wrong"), (0.8, "no player"), (0.2, "unmatched")]


def test_measure_splits_team_named_and_named(name_threshold):
    graded = [(0.9, "right"), (0.3, "wrong"), (0.8, "no player"), (0.2, "unmatched"), (0.7, "wrong"),
              (0.6, "right"), (0.95, "right")]
    assert name_threshold.measure(graded, 0.5) == {
        "threshold": 0.5, "detected": 7, "share_below": 2 / 7, "below": {"unmatched": 1, "wrong": 1},
        "named": 4, "player_id_accuracy_named": 0.75}
    assert name_threshold.measure(graded, 0.99)["player_id_accuracy_named"] is None


def test_test1_is_never_used_to_choose(name_threshold, tmp_path):
    assert name_threshold.main(["dev1", "test1", "--runs", str(tmp_path), "--footage", str(tmp_path)]) == 2
