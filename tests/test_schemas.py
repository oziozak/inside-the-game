"""Every simulator output passes the shared JSON schemas (scripts/validate.py)."""

from __future__ import annotations

import pytest

from simulator.io import write_json, write_jsonl


@pytest.mark.parametrize("fixture", ["short_match", "styled_match"])
def test_outputs_pass_schemas(fixture, request, validate, tmp_path):
    m, frames = request.getfixturevalue(fixture)
    write_json(tmp_path / "match_info.json", m.match_info())
    write_json(tmp_path / "events.json", m.events)
    write_jsonl(tmp_path / "tracking.jsonl", frames)
    for name in ("match_info.json", "events.json", "tracking.jsonl"):
        assert validate.check_file(tmp_path / name) == [], name


def test_full_matches_pass_schemas(full_matches, validate, tmp_path):
    for m in full_matches:
        write_json(tmp_path / "match_info.json", m.match_info())
        write_json(tmp_path / "events.json", m.events)
        assert validate.check_file(tmp_path / "match_info.json") == []
        assert validate.check_file(tmp_path / "events.json") == []
