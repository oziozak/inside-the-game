"""Footage script: the seed record check, clip preparation, ignored output."""

from __future__ import annotations

import copy
import json
import subprocess

import pytest

from simulator import iter_tracking
from vision import footage


def clip(name, role, seed, home="bosphorus", away="thames", minutes=2, **extra):
    return {"name": name, "role": role, "seed": seed, "home": home, "away": away,
            "minutes": minutes, **extra}


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
    (lambda r: r["clips"][4].update(start_minute=-1), "start_minute"),
    (lambda r: r["clips"][4].update(start_minute=50, minutes=10), "before any substitution"),
    (lambda r: r["clips"][4].update(home="thames", away="thames"), "different teams"),
    (lambda r: r["clips"][4].pop("seed"), "missing seed"),
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
    assert [(c["name"], footage.window(c)) for c in by_role["test"]] == \
        [("test1", (0, 600)), ("test2", (2400, 3000))]
    assert all(c["minutes"] == 2 for c in by_role["training"])
    assert "disjoint" in record["rule"]


def test_prepare_clip_simulates_the_match_and_plans_a_cv_export(tmp_path):
    seven = clip("seven", "dev", 7)
    plan = footage.prepare_clip(seven, tmp_path)
    folder = tmp_path / "seven"
    assert plan.video == folder / "seven.mp4"
    assert plan.metadata == folder / "match_info.json"
    assert plan.tracking == folder / "truth" / "tracking.jsonl"
    assert {p.name for p in folder.iterdir()} == {"match_info.json", "truth"}   # truth kept apart
    info = json.loads(plan.metadata.read_text())
    assert info["match_id"] == "seven"
    assert info["periods"][0]["end"] > 45 * 60              # the first minutes of a full match
    frames = plan.tracking.read_text().splitlines()
    assert len(frames) == 2 * 60 * 25                       # tracking covers exactly 2 minutes
    assert json.loads(frames[-1])["t"] == 119.96
    args = plan.export_args
    for flag, value in [("--metadata", str(plan.metadata)), ("--tracking", str(plan.tracking)),
                        ("--out", str(plan.video)), ("--start", "0"), ("--end", "120"),
                        ("--camera", "cv_full_pitch"), ("--ball-scale", "2"),
                        ("--player-scale", "1"), ("--width", "1920"), ("--height", "1080")]:
        assert args[args.index(flag) + 1] == value, flag
    assert "--cv_visibility" in args


def test_prepare_clip_trims_true_events_to_the_clip(tmp_path):
    folder = tmp_path / "seven"
    footage.prepare_clip(clip("seven", "dev", 7), tmp_path)
    events = json.loads((folder / "truth" / "events.json").read_text())
    full = json.loads((folder / "truth" / "events.full.json").read_text())
    assert events and all(e["t"] < 120 for e in events)
    assert full[:len(events)] == events and full[len(events)]["t"] >= 120   # a prefix, ids kept
    assert full[-1]["type"] == "full_time"


def test_window_defaults_to_the_kickoff():
    assert footage.window(clip("a", "dev", 1, minutes=2)) == (0, 120)
    assert footage.window(clip("a", "dev", 1, minutes=10, start_minute=40)) == (2400, 3000)
    assert footage.check_record({**VALID, "clips": VALID["clips"] + [
        clip("late", "training", 9, minutes=10, start_minute=48)]}) == []    # ends at 58'


def test_prepare_clip_cuts_truth_and_tracking_to_a_later_window(tmp_path):
    late = clip("late", "dev", 7, minutes=1, start_minute=1)
    plan = footage.prepare_clip(late, tmp_path)
    frames = [json.loads(line) for line in plan.tracking.read_text().splitlines()]
    # The same frames as the full match's tracking over the window, not re-placed players.
    assert frames == list(iter_tracking(footage.simulate(late), 0, 120))[60 * 25:]
    events = json.loads((tmp_path / "late" / "truth" / "events.json").read_text())
    full = json.loads((tmp_path / "late" / "truth" / "events.full.json").read_text())
    assert events == [e for e in full if 60 <= e["t"] < 120] and events
    args = plan.export_args
    assert (args[args.index("--start") + 1], args[args.index("--end") + 1]) == ("60", "120")


def test_match_info_carries_the_score_at_the_clips_start(tmp_path):
    """#83: the scoreboard's score when the clip starts, from the goals before its window."""
    plan = footage.prepare_clip(clip("seven", "dev", 7), tmp_path)
    assert json.loads(plan.metadata.read_text())["score_at_start"] == {"home": 0, "away": 0}
    full = json.loads((tmp_path / "seven" / "truth" / "events.full.json").read_text())
    goal = next(e for e in full if e["type"] == "goal")
    late = clip("late", "dev", 7, minutes=1, start_minute=int(goal["t"] // 60) + 1)
    plan = footage.prepare_clip(late, tmp_path)
    assert json.loads(plan.metadata.read_text())["score_at_start"] == goal["score"]


def test_refresh_info_adds_the_score_to_a_clip_rendered_before_it_and_changes_nothing_else(tmp_path):
    late = clip("late", "dev", 7, minutes=1, start_minute=40)
    plan = footage.prepare_clip(late, tmp_path)
    info = json.loads(plan.metadata.read_text())
    old = {k: v for k, v in info.items() if k != "score_at_start"}
    plan.metadata.write_text(json.dumps(old))                     # as rendered before #83
    assert footage.refresh_info(late, tmp_path) == info["score_at_start"]
    assert json.loads(plan.metadata.read_text()) == info
    plan.metadata.write_text(json.dumps({**old, "match_id": "other"}))
    with pytest.raises(ValueError, match="match_id"):
        footage.refresh_info(late, tmp_path)                     # not this clip's sheet: left alone
    assert json.loads(plan.metadata.read_text())["match_id"] == "other"


def test_a_window_over_half_time_holds_the_second_half_kickoff(tmp_path):
    over = clip("over", "dev", 7, minutes=2, start_minute=44)
    plan = footage.prepare_clip(over, tmp_path)
    info = json.loads(plan.metadata.read_text())
    second = info["periods"][1]["start"]
    frames = plan.tracking.read_text().splitlines()
    assert len(frames) == 2 * 60 * 25
    assert (json.loads(frames[0])["t"], json.loads(frames[-1])["t"]) == (2640, 2759.96)
    assert {json.loads(f)["period"] for f in frames} == {1, 2}
    events = json.loads((tmp_path / "over" / "truth" / "events.json").read_text())
    assert all(2640 <= e["t"] < 2760 for e in events)
    assert any(e["type"] == "half_time" for e in events)
    assert any(e["type"] == "kickoff" and e["t"] == second for e in events)


def test_find_seed_skips_used_seeds_and_needs_goals_in_the_window():
    seed = footage.find_seed(2101, "bosphorus", "thames", 40, 10, used={2102})
    assert seed > 2102
    late = {"name": "x", "seed": seed, "home": "bosphorus", "away": "thames",
            "start_minute": 40, "minutes": 10}
    assert all(2400 <= g["t"] < 3000 for g in footage.goals_in_window(late))
    assert footage.goals_in_window(late)


def test_test2_seed_follows_its_rule():
    """#35: the first seed after test1's, unused in any role, with a goal in minutes 40-50,
    found with the simulator only (the rule is in the record's `rule`)."""
    clips = footage.load_record()["clips"]
    test1, test2 = (next(c for c in clips if c["name"] == n) for n in ("test1", "test2"))
    used = {c["seed"] for c in clips if c["name"] != "test2"}
    assert (test2["home"], test2["away"]) == (test1["home"], test1["away"])
    assert footage.window(test2) == (2400, 3000)
    assert test2["seed"] == footage.find_seed(test1["seed"], test2["home"], test2["away"], 40, 10, used)
    assert "test2" in footage.load_record()["rule"]


def test_prepare_clip_is_deterministic(tmp_path):
    seven = clip("seven", "dev", 7)
    footage.prepare_clip(seven, tmp_path / "a")
    footage.prepare_clip(seven, tmp_path / "b")
    for name in ("match_info.json", "truth/events.json", "truth/events.full.json",
                 "truth/tracking.jsonl"):
        assert (tmp_path / "a/seven" / name).read_bytes() == (tmp_path / "b/seven" / name).read_bytes()


def test_footage_goes_to_an_ignored_folder():
    for name in ("dev1/dev1.mp4", "dev1/truth/tracking.jsonl", "dev1/clip.json"):
        path = footage.OUT / name
        check = subprocess.run(["git", "check-ignore", "-q", str(path)], cwd=footage.ROOT)
        assert check.returncode == 0, f"{path} is not ignored by git"
