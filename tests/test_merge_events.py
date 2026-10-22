"""Merge step: detected events + the simulator's invisible event types -> one events.json."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_A = ROOT / "data" / "fake" / "sample_a"
INVISIBLE = {"foul", "yellow_card", "red_card", "offside", "substitution"}


@pytest.fixture(scope="module")
def merge_events():
    """scripts/merge_events.py loaded as a module."""
    spec = importlib.util.spec_from_file_location("merge_events", ROOT / "scripts" / "merge_events.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def ev(eid: str, t: float, type_: str, source: str, **extra) -> dict:
    """A minimal valid event."""
    return {"id": eid, "match_id": "m", "t": t, "type": type_, "team": "home",
            "start": [50.0, 30.0], "source": source, "confidence": 1.0 if source == "sim" else 0.8,
            **extra}


def test_takes_exactly_the_five_invisible_types_from_truth(merge_events):
    truth = [ev(f"e{i:04d}", float(i), type_, "sim") for i, type_ in enumerate(
        ["kickoff", "pass", "foul", "free_kick", "yellow_card", "shot", "red_card", "offside",
         "substitution", "corner", "goal", "full_time"], start=1)]
    merged = merge_events.merge([], truth)
    assert sorted(e["type"] for e in merged) == sorted(INVISIBLE)


def test_sorted_by_time_and_renumbered(merge_events):
    detected = [ev("e0001", 3.0, "pass", "cv"), ev("e0002", 10.0, "shot", "cv")]
    truth = [ev("e0001", 1.0, "foul", "sim"), ev("e0002", 5.0, "yellow_card", "sim")]
    merged = merge_events.merge(detected, truth)
    assert [(e["id"], e["t"], e["type"]) for e in merged] == [
        ("e0001", 1.0, "foul"), ("e0002", 3.0, "pass"), ("e0003", 5.0, "yellow_card"),
        ("e0004", 10.0, "shot")]


def test_keeps_every_other_field_intact(merge_events):
    shot = ev("e0007", 4.0, "shot", "cv", subtype="on_target", **{"from": 9}, end=[100.0, 34.0],
              distance_m=18.2, speed_kmh=95.0)
    card = ev("e0042", 2.0, "red_card", "sim", subtype="straight_red", **{"from": 104, "to": None})
    merged = merge_events.merge([shot], [card])
    assert merged == [{**card, "id": "e0001"}, {**shot, "id": "e0002"}]
    assert shot["id"] == "e0007" and card["id"] == "e0042"     # inputs not modified


def test_source_labels(merge_events):
    detected = [ev("e0001", 1.0, "pass", "cv"), ev("e0002", 2.0, "shot", "cv")]
    truth = [{**ev("e0001", 1.5, "offside", "sim"), "source": "cv", "confidence": 0.4},
             ev("e0002", 2.5, "substitution", "sim")]
    merged = merge_events.merge(detected, truth)
    assert [(e["type"], e["source"], e["confidence"]) for e in merged] == [
        ("pass", "cv", 0.8), ("offside", "sim", 1.0), ("shot", "cv", 0.8),
        ("substitution", "sim", 1.0)]


def test_rejects_detected_events_not_from_video(merge_events):
    """Guards against swapping the two files: the truth would be copied in whole."""
    with pytest.raises(ValueError, match="source"):
        merge_events.merge([ev("e0001", 1.0, "pass", "sim")], [])


def stand_in_detected(truth: list[dict]) -> list[dict]:
    """Until the vision AI exists: true events relabelled cv, minus the types video cannot see."""
    return [{**e, "source": "cv", "confidence": 0.9} for e in truth if e["type"] not in INVISIBLE]


@pytest.fixture(scope="module")
def merged_dir(merge_events, tmp_path_factory):
    """A match folder with sample_a's match_info and an events.json written by the merge command."""
    out = tmp_path_factory.mktemp("merged")
    truth = json.loads((SAMPLE_A / "events.json").read_text("utf-8"))
    (out / "detected_events.json").write_text(json.dumps(stand_in_detected(truth)), "utf-8")
    (out / "match_info.json").write_text((SAMPLE_A / "match_info.json").read_text("utf-8"), "utf-8")
    code = merge_events.main([str(out / "detected_events.json"), str(SAMPLE_A / "events.json"),
                              "--out", str(out / "events.json")])
    assert code == 0
    return out


def test_command_writes_a_valid_events_file(merged_dir, validate):
    assert validate.check_file(merged_dir / "events.json") == []
    merged = json.loads((merged_dir / "events.json").read_text("utf-8"))
    truth = json.loads((SAMPLE_A / "events.json").read_text("utf-8"))
    assert len(merged) == len(truth)        # stand-in + invisible types = the whole sample again
    assert {e["type"] for e in merged if e["source"] == "sim"} == INVISIBLE


def test_agents_run_on_the_merged_file(merged_dir, validate):
    """The agents' own CLI, unchanged, turns the merged folder into valid overlays."""
    out = merged_dir / "agents_out"
    subprocess.run([sys.executable, "-m", "agents.run", str(merged_dir), "--out", str(out)],
                   cwd=ROOT, check=True, capture_output=True)
    overlays = json.loads((out / "overlays.json").read_text("utf-8"))
    assert overlays
    assert validate.check_file(out / "overlays.json") == []
    ids = {e["id"] for e in json.loads((merged_dir / "events.json").read_text("utf-8"))}
    assert {i for o in overlays for i in o["event_ids"]} <= ids
