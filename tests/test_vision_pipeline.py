"""Seam 1, end to end: the calibration video (Git LFS) and its team sheet in,
detected events out, through the tracer command `python -m vision`.

The command runs once, in a child process with every file open recorded
(a Python audit hook), on a copy of the clip laid out like a footage clip:
the simulator's true events and tracking sit beside it in truth/, and as a
simulator output folder would hold them. The same run is graded (one
successful pass at 2 s, a shot at 8 s, a goal right after, nothing else) and
guarded (it opened none of the simulator files). The clip has two players and
no kickoff, so roster ids are not asserted. The same run is then carried
through the merge and the agents stage (mock backend) to overlays.json, so
the chain is proven on real detected events without a second decode. The
run takes about a minute.

The audit hook sees every open made from Python (the team sheet, the weights,
modules); the video itself is read by OpenCV's native code, which it does not see.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from agents.verifier import names_in
from vision.grader import grade

ROOT = Path(__file__).resolve().parent.parent
CLIP = ROOT / "vision" / "fixtures" / "calibration"
FIXTURE = ROOT / "renderer" / "fixtures" / "calibration"

# Runs a module as `python -m MODULE ARGS` and logs every path it opens or
# lists, and the modules it imported, to LOG as JSON.
RECORDER = r"""
import json, os, runpy, sys
log, module, *args = sys.argv[1:]
seen, recording = [], [True]
def hook(event, a):
    if recording[0] and event in ("open", "os.listdir", "os.scandir"):
        path = a[0] if a else None
        if event != "open" and path is None:
            path = "."
        if isinstance(path, (str, bytes, os.PathLike)):
            seen.append(os.path.abspath(os.fsdecode(path)))
sys.addaudithook(hook)
sys.argv = [module, *args]
code = 0
try:
    runpy.run_module(module, run_name="__main__", alter_sys=True)
except SystemExit as e:
    code = e.code or 0
finally:
    recording[0] = False
    with open(log, "w") as f:
        json.dump({"opened": seen, "modules": sorted(sys.modules)}, f)
sys.exit(code)
"""

# Code that reads simulator data; none of it may load in the vision runtime.
SIMULATOR_SIDE = ("simulator", "scripts", "vision.grader", "vision.harness", "vision.baseline",
                  "vision.footage", "vision.grade_footage")


@dataclass
class Recorded:
    """One recorded run: exit code, output, opened paths and loaded modules."""

    code: int
    stdout: str
    opened: list[Path]
    modules: list[str]


def record(module: str, args: list[str], log: Path) -> Recorded:
    """Run `python -m module args` from the repo root with file opens recorded."""
    done = subprocess.run([sys.executable, "-c", RECORDER, str(log), module, *args], cwd=ROOT,
                          capture_output=True, text=True, timeout=900)
    logged = json.loads(log.read_text()) if log.exists() else {"opened": [], "modules": []}
    return Recorded(done.returncode, done.stdout + done.stderr,
                    [Path(p).resolve() for p in logged["opened"]], logged["modules"])


def make_clip(folder: Path) -> Path:
    """A footage-style clip folder: the video, its team sheet and export manifest
    (what the vision stage may read), plus the simulator's truth in truth/ and,
    as in a simulator output folder, beside the video. Returns the video."""
    folder.mkdir(parents=True)
    for name in ("calibration.mp4", "match_info.json", "calibration.mp4.manifest.json"):
        shutil.copy(CLIP / name, folder / name)
    (folder / "truth").mkdir()
    shutil.copy(FIXTURE / "ground_truth.events.json", folder / "truth" / "events.json")
    shutil.copy(FIXTURE / "ground_truth.events.json", folder / "truth" / "events.full.json")
    shutil.copy(FIXTURE / "tracking.jsonl", folder / "truth" / "tracking.jsonl")
    shutil.copy(FIXTURE / "ground_truth.events.json", folder / "events.json")
    shutil.copy(FIXTURE / "tracking.jsonl", folder / "tracking.jsonl")
    return folder / "calibration.mp4"


def forbidden(opened: list[Path], video: Path, out: Path) -> list[Path]:
    """The opened paths the vision runtime must never touch: in the clip folder,
    anything but the video and its team sheet (so nothing in truth/); anywhere,
    a truth/ folder, simulator events or tracking, or simulator code and data."""
    clip = video.parent.resolve()
    allowed = {video.resolve(), (clip / "match_info.json").resolve(), out.resolve()}
    simulator_side = [ROOT / "simulator", ROOT / "scripts", ROOT / "renderer" / "fixtures",
                      ROOT / "data" / "generated", ROOT / "data" / "renders", ROOT / "data" / "fake"]
    bad = []
    for path in opened:
        if path in allowed:
            continue
        name = path.name
        if (path.is_relative_to(clip) or "truth" in path.parts
                or ("tracking" in name and name.endswith(".jsonl"))
                or ("events" in name and name.endswith(".json"))
                or any(path.is_relative_to(d.resolve()) for d in simulator_side)):
            bad.append(path)
    return sorted(set(bad))


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    """(recorded run, video, events path) of the tracer on the calibration clip."""
    if (CLIP / "calibration.mp4").read_bytes()[:40].startswith(b"version https://git-lfs"):
        pytest.fail("calibration.mp4 is a Git LFS pointer: run `git lfs install && git lfs pull`")
    base = tmp_path_factory.mktemp("tracer")
    video = make_clip(base / "clip")
    out = base / "out" / "events.json"
    done = record("vision", [str(video), "--out", str(out)], base / "opened.json")
    assert done.code == 0, done.stdout
    return done, video, out


def test_calibration_video_gives_one_pass_one_shot_and_a_goal(run, validate):
    _, _, out = run
    events = json.loads(out.read_text())
    assert validate.check_file(out) == []
    assert [e["id"] for e in events] == [f"e{i:04d}" for i in range(1, len(events) + 1)]
    assert all(e["source"] == "cv" and 0 < e["confidence"] < 1 for e in events)
    assert [(e["type"], round(e["t"])) for e in events] == [("pass", 2), ("shot", 8), ("goal", 9)]
    truth = json.loads((FIXTURE / "ground_truth.events.json").read_text())
    report = grade(events, truth)
    assert report["unmatched_detections"] == report["missed"] == []
    for ty in ("pass", "shot", "goal"):
        assert report["per_type"][ty]["precision"] == report["per_type"][ty]["recall"] == 1.0, ty
    assert report["matched"]["pass_success_accuracy"] == 1.0
    assert events[2]["t"] - events[1]["t"] < 2.0
    assert events[2]["score"] == {"home": 1, "away": 0}


def test_tracer_opens_only_the_video_and_team_sheet(run):
    """With true events and tracking beside the video and in truth/, the tracer
    opens none of them and loads no code that reads simulator data."""
    done, video, out = run
    assert (video.with_name("match_info.json")).resolve() in done.opened   # the hook is recording
    assert forbidden(done.opened, video, out) == []
    loaded = [m for m in done.modules if any(m == s or m.startswith(s + ".") for s in SIMULATOR_SIDE)]
    assert loaded == []


def test_calibration_chain_gives_valid_overlays_about_the_team(run, tmp_path):
    """The same run carried on, as the commands chain it: merge with the clip's true
    events, the agents stage on the mock backend (no network), then the schema check.
    The clip has no kickoff, so no detected event has a player and no overlay names one."""
    _, video, detected = run
    match = tmp_path / "calibration_cv"
    match.mkdir()
    shutil.copy(video.with_name("match_info.json"), match / "match_info.json")
    for args in ([ROOT / "scripts" / "merge_events.py", detected, FIXTURE / "ground_truth.events.json",
                  "--out", match / "events.json"],
                 ["-m", "agents.run", match, "--backend", "mock", "--out", match],
                 [ROOT / "scripts" / "validate.py", match]):
        done = subprocess.run([sys.executable, *map(str, args)], cwd=ROOT, capture_output=True, text=True,
                              timeout=120)
        assert done.returncode == 0, done.stdout + done.stderr
    events = json.loads((match / "events.json").read_text())
    overlays = json.loads((match / "overlays.json").read_text())
    assert json.loads((match / "agents_report.json").read_text())["backend"] == "mock"
    assert [e["from"] for e in events] == [None] * len(events)
    assert overlays and {i for o in overlays for i in o["event_ids"]} <= {e["id"] for e in events}
    assert "goal_banner" in {o["graphic"] for o in overlays}
    roster = {p["name"] for side in ("home", "away")
              for p in json.loads((match / "match_info.json").read_text())[side]["players"]}
    surnames = {name.split(". ")[-1] for name in roster}
    for o in overlays:
        words = f"{o['title']} {o['text']}"
        assert o["player"] is None and o["mode"] != "player_focus", o
        assert names_in(words, roster) == set(), o
        assert surnames.isdisjoint(re.findall(r"\w+", words)), o


@pytest.mark.parametrize("target", ["truth/events.json", "truth/tracking.jsonl", "truth/clip.json",
                                    "tracking.jsonl", "events.json"])
def test_guard_catches_a_read_of_simulator_data(tmp_path, target):
    """The guard is not vacuous: a run that reads a truth or simulator file is caught."""
    video = make_clip(tmp_path / "clip")
    path = video.parent / target
    if not path.exists():
        path.write_text("{}")
    done = record("json.tool", [str(path)], tmp_path / "opened.json")   # fails on JSON Lines; still opens it
    assert forbidden(done.opened, video, tmp_path / "events.json") == [path.resolve()]
