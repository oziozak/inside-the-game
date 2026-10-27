"""scripts/validate.py: which schema a file name selects, and the report's extra checks."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_file_names_select_their_schema(validate):
    kinds = {name: validate.kind_of_name(name) for name in (
        "tactics.json", "tactics.example.json", "report.json", "report.example.json", "agents_report.json",
        "vision_report.json", "analyst_report.json", "events.json", "overlays.json", "match_info.json",
        "tracking.jsonl", "observations.jsonl")}
    assert kinds == {"tactics.json": "tactics", "tactics.example.json": "tactics", "report.json": "report",
                     "report.example.json": "report", "agents_report.json": None, "vision_report.json": None,
                     "analyst_report.json": None, "events.json": "event", "overlays.json": "overlay",
                     "match_info.json": "match_info", "tracking.jsonl": "tracking", "observations.jsonl": None}


def test_a_score_at_start_is_two_counts_or_the_match_info_is_rejected(validate, tmp_path):
    """#83: a clip cut from mid-match carries the score at its start."""
    info = json.loads((ROOT / "schemas/examples/match_info.example.json").read_text(encoding="utf-8"))
    assert info["score_at_start"] == {"home": 0, "away": 0}
    assert validate.check_file(ROOT / "schemas/examples/match_info.example.json") == []
    for bad in ({"home": 1}, {"home": -1, "away": 0}, {"home": 1, "away": 0, "minute": 40}):
        (tmp_path / "match_info.json").write_text(json.dumps({**info, "score_at_start": bad}), encoding="utf-8")
        assert validate.check_file(tmp_path / "match_info.json"), bad


def test_the_examples_pass_and_a_wrongly_hedged_insight_does_not(validate, tmp_path):
    assert validate.check_file(ROOT / "schemas/examples/tactics.example.json") == []
    report = json.loads((ROOT / "schemas/examples/report.example.json").read_text(encoding="utf-8"))
    assert validate.check_file(ROOT / "schemas/examples/report.example.json") == []
    report["insights"][0]["hedged"] = True
    (tmp_path / "report.json").write_text(json.dumps(report), encoding="utf-8")
    assert any("hedged" in e for e in validate.check_file(tmp_path / "report.json"))
