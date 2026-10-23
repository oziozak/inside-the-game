"""Footage for the vision work: one command per clip in the seed record.

    python -m vision.footage check                      # the seed record is valid
    python -m vision.footage list                       # clips, roles, pairings
    python -m vision.footage render dev1 test1          # simulate, export, validate
    python -m vision.footage render --role dev [--force]
    python -m vision.footage render --all

A clip is the first `minutes` of a full 90-minute match (seeded, `full`
profile): it starts at the kickoff, and substitutions (58'-82') never fall in
it. Each clip goes to data/renders/footage/<name>/ (ignored by git): the video,
its export manifest and metrics, the simulator's match_info.json and clip.json
(seed record entry + render settings, written last once the export
validated). The simulator's true events and tracking go to truth/, which the
vision stage never reads. Renders are never committed.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from simulator import Match, iter_tracking
from simulator.io import write_json, write_jsonl
from simulator.teams import load_team, resolve_kits

ROOT = Path(__file__).resolve().parent.parent
RECORD = Path(__file__).with_name("footage_seeds.json")
OUT = ROOT / "data" / "renders" / "footage"          # ignored by git
FIELDS = ("name", "role", "seed", "home", "away", "minutes")
ROLES = ("dev", "test", "training")
MIN_DEV_KIT_COMBINATIONS = 3
HALF = 45 * 60                                        # clips are cut from regulation matches
# v1 footage settings (see #9): static full-pitch camera, yellow CV ball at 2x, real-size
# players, 1080p at 25 fps. `render` checks the export manifest recorded exactly these.
RENDER_SETTINGS = {"camera": "cv_full_pitch", "cvVisibility": True, "playerScale": 1, "ballScale": 2}
VIDEO = {"width": 1920, "height": 1080, "fps": 25}


@dataclass(frozen=True)
class ClipPlan:
    """A simulated clip, ready to export: its files and the renderer arguments."""
    video: Path
    metadata: Path
    tracking: Path
    export_args: list[str]


def load_record(path: Path = RECORD) -> dict:
    """The seed record: every footage clip with its role, seed, pairing and length."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def check_record(record: dict) -> list[str]:
    """Problems with a seed record (empty list = valid)."""
    errors = []
    clips, playable = [], []
    for c in record["clips"]:
        missing = [f for f in FIELDS if f not in c]
        if missing:
            errors.append(f"clip {c.get('name', '?')}: missing {', '.join(missing)}")
        else:
            clips.append(c)
    for c in clips:
        clip_errors = _check_clip(c)
        errors += clip_errors
        if not clip_errors:
            playable.append(c)
    for role in ROLES:
        if not any(c["role"] == role for c in clips):
            errors.append(f"no {role} clip")
    clips_by_seed: dict[int, list[dict]] = {}
    for c in clips:
        clips_by_seed.setdefault(c["seed"], []).append(c)
    for seed, same in sorted(clips_by_seed.items()):
        roles = sorted({c["role"] for c in same})
        if len(roles) > 1:
            errors.append(f"seed {seed} is used in several roles: {', '.join(roles)}")
        elif len(same) > 1:
            errors.append(f"seed {seed} is used by several clips: "
                          f"{', '.join(c['name'] for c in same)}")
    names = Counter(c["name"] for c in clips)
    errors += [f"clip name {n} is used {k} times" for n, k in names.items() if k > 1]
    errors += _check_dev_kits([c for c in playable if c["role"] == "dev"])
    return errors


def _check_clip(c: dict) -> list[str]:
    """Problems with one clip entry: its role, length and teams."""
    who = f"clip {c['name']}"
    errors = []
    if c["role"] not in ROLES:
        errors.append(f"{who}: role must be one of {', '.join(ROLES)}, not {c['role']!r}")
    if not 0 < c["minutes"] <= HALF / 60:
        errors.append(f"{who}: minutes must be more than 0 and at most {HALF // 60} (first half)")
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


def prepare_clip(clip: dict, root: Path) -> ClipPlan:
    """Simulate a clip's match into root/<name>/ and plan its export to
    root/<name>/<name>.mp4: the first `minutes` of the match, from the kickoff.

    match_info.json (the team sheet) goes next to the video. The truth goes to
    truth/: events.json (true events before the clip's end, ids unchanged),
    events.full.json (the whole match) and tracking.jsonl (the clip only)."""
    folder = Path(root) / clip["name"]
    truth = folder / "truth"
    m = Match(clip["seed"], HALF, "full", clip["name"],
              home=load_team(clip["home"]), away=load_team(clip["away"]))
    m.play()
    end = clip["minutes"] * 60
    metadata, tracking = folder / "match_info.json", truth / "tracking.jsonl"
    write_json(metadata, m.match_info())
    write_json(truth / "events.full.json", m.events)
    write_json(truth / "events.json", [e for e in m.events if e["t"] < end])
    write_jsonl(tracking, iter_tracking(m, 0, min(end, m.t)))
    video = folder / f"{clip['name']}.mp4"
    args = ["--metadata", str(metadata), "--tracking", str(tracking),
            "--start", "0", "--end", f"{end:g}",
            "--camera", RENDER_SETTINGS["camera"], "--cv_visibility",
            "--ball-scale", f"{RENDER_SETTINGS['ballScale']:g}",
            "--player-scale", f"{RENDER_SETTINGS['playerScale']:g}",
            "--width", str(VIDEO["width"]), "--height", str(VIDEO["height"]), "--out", str(video)]
    return ClipPlan(video, metadata, tracking, args)


def render_clip(clip: dict, root: Path = OUT, force: bool = False) -> Path:
    """Simulate, export and validate one clip; returns its folder. A finished
    clip (clip.json present) is kept unless force; anything else is rebuilt."""
    folder = Path(root) / clip["name"]
    if (folder / "clip.json").exists() and not force:
        print(f"{clip['name']}: already rendered in {folder} (use --force to rebuild)")
        return folder
    if folder.exists():
        shutil.rmtree(folder)                   # partial or forced: the renderer refuses old outputs
    plan = prepare_clip(clip, root)
    video = plan.video
    _npm("export", *plan.export_args)
    _npm("validate:export", "--video", str(video), "--metadata", str(plan.metadata),
         "--tracking", str(plan.tracking))
    manifest = json.loads(Path(f"{video}.manifest.json").read_text(encoding="utf-8"))
    recorded = {k: manifest[k] for k in VIDEO}
    if manifest["render"] != RENDER_SETTINGS or recorded != VIDEO:
        raise RuntimeError(f"{video}: manifest records {manifest['render']} {recorded}, "
                           f"expected {RENDER_SETTINGS} {VIDEO}")
    summary = {"clip": clip, "render": manifest["render"], **recorded,
               "start": manifest["start"], "end": manifest["end"],
               "frames": len(manifest["frames"])}
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
