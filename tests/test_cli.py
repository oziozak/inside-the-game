"""Command line: bad arguments give a clean "error: ..." and exit code 2."""

from __future__ import annotations

import copy

import pytest

import simulator.__main__ as cli
from simulator.teams import load_team


@pytest.mark.parametrize("extra, message", [
    (["--start", "-5"], "--start must be 0 or more"),
    (["--start", "999999"], "--start must be before the end of the match"),
    (["--start", "60", "--end", "30"], "--end must be after --start"),
    (["--home", "thames"], "must be different teams"),
    (["--away", "no_such_team"], "unknown team"),
])
def test_bad_arguments(extra, message, tmp_path, capsys):
    args = ["--half-length", "1", "--out", str(tmp_path / "m")] + extra
    if "--home" not in extra:
        args += ["--home", "bosphorus"]
    if "--away" not in extra:
        args += ["--away", "thames"]
    assert cli.main(args) == 2
    err = capsys.readouterr().err
    assert err.startswith("error: ") and message in err
    assert not (tmp_path / "m").exists()          # nothing written


def test_kit_clash_is_a_clean_error(tmp_path, capsys, monkeypatch):
    """An away team whose home and away kits both clash: error, exit code 2."""
    def fake_load(key):
        team = copy.deepcopy(load_team("bosphorus"))
        if key == "thames":                        # red copy: both kits clash with Bosphorus
            team["name"] = "Red Copy"
            team["away_kit"] = dict(team["kit"])
        return team

    monkeypatch.setattr(cli, "load_team", fake_load)
    assert cli.main(["--half-length", "1", "--out", str(tmp_path / "m")]) == 2
    err = capsys.readouterr().err
    assert err.startswith("error: kit clash between Bosphorus FC and Red Copy")


def test_valid_window_writes_files(tmp_path):
    assert cli.main(["--half-length", "1", "--start", "10", "--end", "20", "--out", str(tmp_path / "m")]) == 0
    lines = (tmp_path / "m" / "tracking.jsonl").read_text().splitlines()
    assert len(lines) == 250
