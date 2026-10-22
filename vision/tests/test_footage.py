"""Footage script: the seed record check, clip preparation, ignored output."""

from __future__ import annotations

import copy
import json
import subprocess

import pytest

from vision import footage


def clip(name, role, seed, home="bosphorus", away="thames", minutes=2):
    return {"name": name, "role": role, "seed": seed, "home": home, "away": away,
            "minutes": minutes}


VALID = {"clips": [
    clip("dev1", "dev", 1, "bosphorus", "thames"),
    clip("dev2", "dev", 2, "caldera", "bosphorus"),     # Bosphorus switches to white
    clip("dev3", "dev", 3, "saltmarsh", "caldera"),
    clip("test1", "test", 4, minutes=10),
    clip("train1", "training", 5, "thames", "caldera"),
]}


def test_valid_record_has_no_errors():
    assert footage.check_record(VALID) == []


def test_seed_in_two_roles_is_an_error():
    record = copy.deepcopy(VALID)
    record["clips"][3]["seed"] = 1                     # test seed reuses dev1's seed
    errors = footage.check_record(record)
    assert any("seed 1" in e and "dev" in e and "test" in e for e in errors)


def test_seed_reused_within_a_role_is_an_error():
    record = copy.deepcopy(VALID)
    record["clips"][2]["seed"] = 2                     # dev3 reuses dev2's seed
    assert any("seed 2" in e for e in footage.check_record(record))


def test_duplicate_clip_name_is_an_error():
    record = copy.deepcopy(VALID)
    record["clips"][4]["name"] = "dev1"
    assert any("dev1" in e for e in footage.check_record(record))


def test_dev_needs_three_kit_combinations():
    record = copy.deepcopy(VALID)
    record["clips"][2].update(home="bosphorus", away="thames")   # same kits as dev1
    assert any("kit combinations" in e for e in footage.check_record(record))


def test_dev_needs_a_white_away_kit():
    record = copy.deepcopy(VALID)
    record["clips"][1].update(home="thames", away="bosphorus")   # both keep home kits
    assert any("white away kit" in e for e in footage.check_record(record))


@pytest.mark.parametrize("breakage, message", [
    (lambda r: r["clips"][4].update(role="demo"), "role"),
    (lambda r: r["clips"][4].update(away="no_such_team"), "no_such_team"),
    (lambda r: r["clips"].pop(3), "no test clip"),
    (lambda r: r["clips"].pop(4), "no training clip"),
    (lambda r: r["clips"][4].update(minutes=0), "minutes"),
    (lambda r: r["clips"][4].update(home="thames", away="thames"), "different teams"),
])
def test_broken_records_are_errors(breakage, message):
    record = copy.deepcopy(VALID)
    breakage(record)
    assert any(message in e for e in footage.check_record(record))


def test_committed_seed_record_is_valid():
    record = footage.load_record()
    assert footage.check_record(record) == []
    by_role = {role: [c for c in record["clips"] if c["role"] == role] for role in footage.ROLES}
    assert len(by_role["dev"]) == 3 and all(c["minutes"] == 2 for c in by_role["dev"])
    assert [c["minutes"] for c in by_role["test"]] == [10]
    assert all(c["minutes"] == 2 for c in by_role["training"])
    assert "disjoint" in record["rule"]


def options(args):
    """Renderer CLI args as {flag: value}; bare flags map to True."""
    out, i = {}, 0
    while i < len(args):
        if i + 1 < len(args) and not args[i + 1].startswith("--"):
            out[args[i]] = args[i + 1]
            i += 2
        else:
            out[args[i]] = True
            i += 1
    return out


def test_prepare_clip_simulates_the_match_and_plans_a_cv_export(tmp_path):
    seven = clip("seven", "dev", 7)                    # seed 7, 2 x 1 min: full time at 123.28 s
    args = options(footage.prepare_clip(seven, tmp_path))
    folder = tmp_path / "seven"
    assert {p.name for p in folder.iterdir()} >= {"match_info.json", "events.json", "tracking.jsonl"}
    info = json.loads((folder / "match_info.json").read_text())
    assert info["match_id"] == "seven"
    assert args["--metadata"] == str(folder / "match_info.json")
    assert args["--tracking"] == str(folder / "tracking.jsonl")
    assert args["--out"] == str(folder / "seven.mp4")
    assert (args["--start"], args["--end"]) == ("0", "123.28")    # the whole match
    assert args["--camera"] == "cv_full_pitch" and args["--cv_visibility"] is True
    assert (args["--ball-scale"], args["--player-scale"]) == ("2", "1")


def test_prepare_clip_is_deterministic(tmp_path):
    seven = clip("seven", "dev", 7)
    footage.prepare_clip(seven, tmp_path / "a")
    footage.prepare_clip(seven, tmp_path / "b")
    for name in ("match_info.json", "events.json", "tracking.jsonl"):
        assert (tmp_path / "a/seven" / name).read_bytes() == (tmp_path / "b/seven" / name).read_bytes()


def test_footage_goes_to_an_ignored_folder():
    for name in ("dev1/dev1.mp4", "dev1/tracking.jsonl", "dev1/clip.json"):
        path = footage.OUT / name
        check = subprocess.run(["git", "check-ignore", "-q", str(path)], cwd=footage.ROOT)
        assert check.returncode == 0, f"{path} is not ignored by git"
