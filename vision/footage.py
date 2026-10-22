"""Footage for the vision work: one command per clip in the seed record.

    python -m vision.footage check                      # the seed record is valid
    python -m vision.footage list                       # clips, roles, pairings
    python -m vision.footage render dev1 test1          # simulate, export, validate
    python -m vision.footage render --role dev [--force]
    python -m vision.footage render --all

Each clip goes to data/renders/footage/<name>/ (ignored by git): the video,
its export manifest and metrics, the simulator's match_info.json, true events
and tracking, and clip.json (seed record entry + render settings), written
last once the export validated. Renders are never committed.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

from simulator import Match
from simulator.io import write_match
from simulator.teams import load_team, resolve_kits

ROOT = Path(__file__).resolve().parent.parent
RECORD = Path(__file__).with_name("footage_seeds.json")
OUT = ROOT / "data" / "renders" / "footage"          # ignored by git
ROLES = ("dev", "test", "training")
MIN_DEV_KIT_COMBINATIONS = 3
FPS = 25
# v1 footage settings (see #9): static full-pitch camera, yellow CV ball at 2x, real-size players.
RENDER_SETTINGS = {"camera": "cv_full_pitch", "cvVisibility": True, "playerScale": 1, "ballScale": 2}
RENDER = ["--camera", "cv_full_pitch", "--cv_visibility", "--ball-scale", "2", "--player-scale", "1"]


def load_record(path: Path = RECORD) -> dict:
    """The seed record: every footage clip with its role, seed, pairing and length."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def check_record(record: dict) -> list[str]:
    """Problems with a seed record (empty list = valid)."""
    errors = []
    playable = []
    for c in record["clips"]:
        clip_errors = _check_clip(c)
        errors += clip_errors
        if not clip_errors:
            playable.append(c)
    for role in ROLES:
        if not any(c["role"] == role for c in record["clips"]):
            errors.append(f"no {role} clip")
    clips_by_seed: dict[int, list[dict]] = {}
    for c in record["clips"]:
        clips_by_seed.setdefault(c["seed"], []).append(c)
    for seed, clips in sorted(clips_by_seed.items()):
        roles = sorted({c["role"] for c in clips})
        if len(roles) > 1:
            errors.append(f"seed {seed} is used in several roles: {', '.join(roles)}")
        elif len(clips) > 1:
            errors.append(f"seed {seed} is used by several clips: "
                          f"{', '.join(c['name'] for c in clips)}")
    names = Counter(c["name"] for c in record["clips"])
    errors += [f"clip name {n} is used {k} times" for n, k in names.items() if k > 1]
    errors += _check_dev_kits([c for c in playable if c["role"] == "dev"])
    return errors


def _check_clip(c: dict) -> list[str]:
    """Problems with one clip entry: its role, length and teams."""
    who = f"clip {c['name']}"
    errors = []
    if c["role"] not in ROLES:
        errors.append(f"{who}: role must be one of {', '.join(ROLES)}, not {c['role']!r}")
    if not c["minutes"] > 0:
        errors.append(f"{who}: minutes must be positive")
    if c["home"] == c["away"]:
        errors.append(f"{who}: home and away must be different teams")
    try:
        worn_kits(c)
    except ValueError as e:                     # unknown team or unresolvable kit clash
        errors.append(f"{who}: {e}")
    return errors


def worn_kits(clip: dict) -> tuple[dict, dict]:
    """The (home, away) kits worn in a clip's match, after kit-clash resolution."""
    return resolve_kits(load_team(clip["home"]), load_team(clip["away"]))


def is_white(hex_color: str) -> bool:
    """True for near-white colors (every RGB channel at least 0xe0)."""
    return all(int(hex_color[i:i + 2], 16) >= 0xE0 for i in (1, 3, 5))


def _check_dev_kits(dev: list[dict]) -> list[str]:
    """Dev clips must show at least three kit combinations, one with a white away kit."""
    kits = [worn_kits(c) for c in dev]
    combos = {(h["shirt"], a["shirt"]) for h, a in kits}
    errors = []
    if len(combos) < MIN_DEV_KIT_COMBINATIONS:
        errors.append(f"dev clips show {len(combos)} kit combinations, "
                      f"need at least {MIN_DEV_KIT_COMBINATIONS}")
    if not any(is_white(a["shirt"]) for _, a in kits):
        errors.append("no dev clip shows a white away kit")
    return errors


def prepare_clip(clip: dict, root: Path) -> list[str]:
    """Simulate a clip's match into root/<name>/ and return the renderer export
    arguments that turn it into root/<name>/<name>.mp4.

    A clip is a whole short match (two halves of minutes / 2), so its true
    events and match_info periods cover exactly the rendered video."""
    folder = Path(root) / clip["name"]
    m = Match(clip["seed"], clip["minutes"] * 30, "full", clip["name"],
              home=load_team(clip["home"]), away=load_team(clip["away"]))
    m.play()
    files = write_match(folder, m)
    start, end = _coverage(files["tracking.jsonl"])
    return ["--metadata", str(files["match_info.json"]), "--tracking", str(files["tracking.jsonl"]),
            "--start", _seconds(start), "--end", _seconds(end),
            *RENDER, "--out", str(folder / f"{clip['name']}.mp4")]


def _coverage(tracking: Path) -> tuple[float, float]:
    """[first t, last t + one frame): the interval the renderer can export."""
    first = last = None
    with tracking.open(encoding="utf-8") as f:
        for line in f:
            last = line
            first = first or line
    return json.loads(first)["t"], json.loads(last)["t"] + 1 / FPS


def _seconds(t: float) -> str:
    """Seconds for the renderer CLI, to the 0.01 s precision of tracking times."""
    return f"{t:.2f}".rstrip("0").rstrip(".")


def render_clip(clip: dict, root: Path = OUT, force: bool = False) -> Path:
    """Simulate, export and validate one clip; returns its folder. A finished
    clip (clip.json present) is kept unless force; anything else is rebuilt."""
    folder = Path(root) / clip["name"]
    if (folder / "clip.json").exists() and not force:
        print(f"{clip['name']}: already rendered in {folder} (use --force to rebuild)")
        return folder
    if folder.exists():
        shutil.rmtree(folder)                   # partial or forced: the renderer refuses old outputs
    args = prepare_clip(clip, root)
    opts = dict(zip(args, args[1:]))
    video = Path(opts["--out"])
    _npm("export", *args)
    _npm("validate:export", "--video", str(video), "--metadata", opts["--metadata"],
         "--tracking", opts["--tracking"])
    manifest = json.loads(Path(f"{video}.manifest.json").read_text(encoding="utf-8"))
    if manifest["render"] != RENDER_SETTINGS:
        raise RuntimeError(f"{video}: manifest render settings {manifest['render']} "
                           f"are not {RENDER_SETTINGS}")
    summary = {"clip": clip, "render": manifest["render"], "start": manifest["start"],
               "end": manifest["end"], "frames": len(manifest["frames"]),
               "width": manifest["width"], "height": manifest["height"], "fps": manifest["fps"]}
    (folder / "clip.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(f"{clip['name']}: {video} ({summary['frames']} frames) validated")
    return folder


def _npm(script: str, *args: str) -> None:
    """Run a renderer npm script in renderer/; raises if it fails."""
    renderer = ROOT / "renderer"
    if not (renderer / "node_modules").is_dir():
        raise RuntimeError("renderer dependencies missing: cd renderer && npm ci && "
                           "npx playwright install chromium")
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        raise RuntimeError("ffmpeg and ffprobe (with libx264) must be on PATH")
    subprocess.run(["npm", "run", "--silent", script, "--", *args], cwd=renderer, check=True)


def main(argv=None) -> int:
    """Command line; returns the exit code."""
    ap = argparse.ArgumentParser(prog="python -m vision.footage", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="check the seed record")
    sub.add_parser("list", help="list the clips in the seed record")
    render = sub.add_parser("render", help="render clips from the seed record")
    render.add_argument("names", nargs="*", help="clip names, e.g. dev1 test1")
    render.add_argument("--role", choices=ROLES, help="every clip with this role")
    render.add_argument("--all", action="store_true", help="every clip in the record")
    render.add_argument("--force", action="store_true", help="rebuild clips already rendered")
    render.add_argument("--out", type=Path, default=OUT, help=f"output root (default {OUT})")
    args = ap.parse_args(argv)

    record = load_record()
    errors = check_record(record)
    if errors:
        print("seed record is invalid:\n  " + "\n  ".join(errors), file=sys.stderr)
        return 1
    if args.command == "check":
        print(f"seed record OK: {len(record['clips'])} clips; {record['rule']}")
        return 0
    if args.command == "list":
        for c in record["clips"]:
            home, away = worn_kits(c)
            print(f"{c['name']:8} {c['role']:9} seed {c['seed']:<5} {c['minutes']:>2} min  "
                  f"{c['home']} ({home['shirt']}) v {c['away']} ({away['shirt']})")
        return 0

    by_name = {c["name"]: c for c in record["clips"]}
    unknown = [n for n in args.names if n not in by_name]
    if unknown:
        print(f"error: unknown clip {', '.join(unknown)} (see: python -m vision.footage list)",
              file=sys.stderr)
        return 2
    clips = [by_name[n] for n in args.names]
    clips += [c for c in record["clips"]
              if (args.all or c["role"] == args.role) and c not in clips]
    if not clips:
        print("error: name clips, or pass --role or --all", file=sys.stderr)
        return 2
    for c in clips:
        render_clip(c, args.out, args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
