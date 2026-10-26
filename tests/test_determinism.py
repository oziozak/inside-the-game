"""Same seed -> byte-identical files; different seed -> a different match."""

from __future__ import annotations

import os
import subprocess
import sys

from conftest import ROOT

from simulator.__main__ import main as cli


def _files(folder):
    return {p.name: p.read_bytes() for p in sorted(folder.iterdir())}


def test_same_seed_gives_identical_files(tmp_path):
    args = ["--home", "caldera", "--away", "thames", "--seed", "7", "--half-length", "5",
            "--profile", "short", "--match-id", "det"]
    assert cli(args + ["--out", str(tmp_path / "a")]) == 0
    assert cli(args + ["--out", str(tmp_path / "b")]) == 0
    a, b = _files(tmp_path / "a"), _files(tmp_path / "b")
    assert set(a) == {"match_info.json", "events.json", "tracking.jsonl"}
    assert a == b


def test_identical_across_processes(tmp_path):
    """No hidden randomness: separate interpreters with different hash seeds agree."""
    outs = []
    for hash_seed in ("0", "12345"):
        out = tmp_path / f"run{hash_seed}"
        env = dict(os.environ, PYTHONHASHSEED=hash_seed)
        subprocess.run([sys.executable, "-m", "simulator", "--seed", "3", "--half-length", "3",
                        "--match-id", "proc", "--out", str(out), "--end", "60"],
                       cwd=ROOT, env=env, check=True, capture_output=True)
        outs.append(_files(out))
    assert outs[0] == outs[1]


def test_different_seeds_give_different_matches(tmp_path):
    base = ["--half-length", "5", "--match-id", "det", "--no-tracking"]
    cli(base + ["--seed", "1", "--out", str(tmp_path / "s1")])
    cli(base + ["--seed", "2", "--out", str(tmp_path / "s2")])
    assert _files(tmp_path / "s1")["events.json"] != _files(tmp_path / "s2")["events.json"]
