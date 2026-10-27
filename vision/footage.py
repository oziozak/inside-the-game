"""Footage for the vision work: one command per clip in the seed record.

    python -m vision.footage check                      # the seed record is valid
    python -m vision.footage list                       # clips, roles, pairings
    python -m vision.footage render dev1 test1          # simulate, export, validate
    python -m vision.footage render --role dev [--force]
    python -m vision.footage render --all
    python -m vision.footage info dev1 test2            # add score_at_start to a rendered clip
    python -m vision.footage find-seed --after 2101 --start-minute 40 --minutes 10
    python -m vision.footage find-showcase --first 2301 --last 2500

A clip is `minutes` of a full 90-minute match (seeded, `full` profile), from
`start_minute` (default 0, the kickoff), so [start_minute, start_minute +
minutes) * 60 seconds of match time, and it ends before the first
substitution can happen (58'). Each clip goes to data/renders/footage/<name>/
(ignored by git): the video, its export manifest and metrics, the simulator's
match_info.json and clip.json (seed record entry + render settings, written
last once the export validated). The simulator's true events and tracking for
the clip's window go to truth/, which the vision stage never reads. Renders
are never committed.

`find-seed` applies a test clip's selection rule using the simulator only: the
first seed after --after, used by no clip, whose window holds at least --goals
goals. `find-showcase` applies the showcase rule, also simulator only: of the
seeds --first..--last used by no clip, the 10-minute window (whole-minute
start, ending by 58') with the most action (see action_rank). The showcase
clip is chosen for its content, so it is never a held-out grade.
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
from typing import Iterator

from simulator import Match, iter_tracking
from simulator.config import FPS
from simulator.io import write_json, write_jsonl
from simulator.teams import load_team, resolve_kits

ROOT = Path(__file__).resolve().parent.parent
RECORD = Path(__file__).with_name("footage_seeds.json")
OUT = ROOT / "data" / "renders" / "footage"          # ignored by git
FIELDS = ("name", "role", "seed", "home", "away", "minutes")   # plus optional start_minute
REQUIRED_ROLES = ("dev", "test", "training", "highlight")
ROLES = REQUIRED_ROLES + ("showcase",)               # showcase: chosen for content, never held out
ACTION = ("goal", "yellow_card", "red_card")         # what a showcase window is ranked by
MIN_DEV_KIT_COMBINATIONS = 3
HALF = 45 * 60                                        # clips are cut from regulation matches
SUBS_FROM = 58                                        # minute of the earliest substitution
# v1 footage settings (see #9): static full-pitch camera, yellow CV ball at 2x, real-size
# players, 1080p at 25 fps. `render` checks the export manifest recorded exactly these.
RENDER_SETTINGS = {"camera": "cv_full_pitch", "cvVisibility": True, "playerScale": 1, "ballScale": 2,
                   "jerseyNumbers": False, "animatePlayers": False}
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
    for role in REQUIRED_ROLES:
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
    start = c.get("start_minute", 0)
    if not c["minutes"] > 0:
        errors.append(f"{who}: minutes must be more than 0")
    if not start >= 0:
        errors.append(f"{who}: start_minute must be at least 0")
    if start + c["minutes"] > SUBS_FROM:
        errors.append(f"{who}: start_minute + minutes must be at most {SUBS_FROM} "
                      f"(before any substitution)")
    if c["home"] == c["away"]:
        errors.append(f"{who}: home and away must be different teams")
    try:
        worn_kits(c)
    except ValueError as e:                     # unknown team or unresolvable kit clash
        errors.append(f"{who}: {e}")
    return errors


def window(clip: dict) -> tuple[float, float]:
    """A clip's [start, end) in seconds of match time (the continuous clock)."""
    start = clip.get("start_minute", 0) * 60
    return start, start + clip["minutes"] * 60


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


def simulate(clip: dict) -> Match:
    """The clip's full match, played (events only; tracking is built on demand)."""
    m = Match(clip["seed"], HALF, "full", clip["name"],
              home=load_team(clip["home"]), away=load_team(clip["away"]))
    m.play()
    return m


def clip_tracking(m: Match, start: float, end: float) -> Iterator[dict]:
    """The match's tracking frames for start <= t < end. Built from the kickoff
    and cut, so they are the frames of the full match's tracking (the movement
    layer carries player positions from frame to frame)."""
    first = round(start * FPS)
    return (f for f in iter_tracking(m, 0, min(end, m.t)) if f["frame"] >= first)


def score_at(events: list[dict], t: float) -> dict:
    """The score just before t: the last goal's score before it, else 0-0."""
    goals = [e for e in events if e["type"] == "goal" and e["t"] < t]
    return dict(goals[-1]["score"]) if goals else {"home": 0, "away": 0}


def clip_match_info(m: Match, start: float) -> dict:
    """The clip's match_info.json: the team sheet and the score when the clip
    starts, which the broadcast's scoreboard shows like it shows the teams (#83)."""
    return {**m.match_info(), "score_at_start": score_at(m.events, start)}


def refresh_info(clip: dict, root: Path = OUT) -> dict:
    """Rewrite a rendered clip's match_info.json with score_at_start (clips
    rendered before #83 lack it); returns the score. Re-simulates the match,
    so it raises ValueError, writing nothing, if any other field would change."""
    path = Path(root) / clip["name"] / "match_info.json"
    old = json.loads(path.read_text(encoding="utf-8"))
    new = json.loads(json.dumps(clip_match_info(simulate(clip), window(clip)[0])))   # as written: tuples are lists
    changed = sorted(k for k in old.keys() | new.keys() if k != "score_at_start" and old.get(k) != new.get(k))
    if changed:
        raise ValueError(f"{path}: {', '.join(changed)} would change; not this clip's team sheet?")
    write_json(path, new)
    return new["score_at_start"]


def prepare_clip(clip: dict, root: Path) -> ClipPlan:
    """Simulate a clip's match into root/<name>/ and plan its export to
    root/<name>/<name>.mp4: the clip's window of the match (see window()).

    match_info.json (the team sheet, and the score when the clip starts)
    goes next to the video. The truth goes to truth/: events.json (true
    events in the window, ids unchanged), events.full.json (the whole match)
    and tracking.jsonl (the window only)."""
    folder = Path(root) / clip["name"]
    truth = folder / "truth"
    m = simulate(clip)
    start, end = window(clip)
    metadata, tracking = folder / "match_info.json", truth / "tracking.jsonl"
    write_json(metadata, clip_match_info(m, start))
    write_json(truth / "events.full.json", m.events)
    write_json(truth / "events.json", [e for e in m.events if start <= e["t"] < end])
    write_jsonl(tracking, clip_tracking(m, start, end))
    video = folder / f"{clip['name']}.mp4"
    args = ["--metadata", str(metadata), "--tracking", str(tracking),
            "--start", f"{start:g}", "--end", f"{end:g}",
            "--camera", RENDER_SETTINGS["camera"], "--cv_visibility",
            "--ball-scale", f"{RENDER_SETTINGS['ballScale']:g}",
            "--player-scale", f"{RENDER_SETTINGS['playerScale']:g}",
            "--width", str(VIDEO["width"]), "--height", str(VIDEO["height"]), "--out", str(video)]
    return ClipPlan(video, metadata, tracking, args)


def goals_in_window(clip: dict) -> list[dict]:
    """The true goals in a clip's window, from the simulator alone."""
    start, end = window(clip)
    return [e for e in simulate(clip).events if e["type"] == "goal" and start <= e["t"] < end]


def find_seed(after: int, home: str, away: str, start_minute: float, minutes: float,
              used: set[int], goals: int = 1, tries: int = 1000) -> int:
    """The first seed after `after`, not in `used`, whose clip window holds at
    least `goals` goals. Runs the simulator only (no tracking, no vision)."""
    for seed in range(after + 1, after + 1 + tries):
        if seed in used:
            continue
        clip = {"name": f"seed{seed}", "seed": seed, "home": home, "away": away,
                "start_minute": start_minute, "minutes": minutes}
        if len(goals_in_window(clip)) >= goals:
            return seed
    raise ValueError(f"no seed in {after + 1}..{after + tries} has {goals} goal(s) in the window")


def action_rank(events: list[dict], start: float, end: float) -> tuple:
    """How much action the window [start, end) shows, as a sort key (higher is
    better): a red card, 2+ goals, a yellow card, a second-yellow red, then the
    number of goals and cards, then how far the first and last of them sit from
    the window's edges (seconds; a centered window shows the build-up and the
    restart after)."""
    inside = [e for e in events if start <= e["t"] < end and e["type"] in ACTION]
    n = Counter(e["type"] for e in inside)
    second_yellow = any(e["type"] == "red_card" and e.get("subtype") == "second_yellow" for e in inside)
    margin = min(inside[0]["t"] - start, end - inside[-1]["t"]) if inside else 0.0
    return (n["red_card"] >= 1, n["goal"] >= 2, n["yellow_card"] >= 1, second_yellow,
            len(inside), margin)


def find_showcase(first: int, last: int, home: str, away: str, minutes: float,
                  used: set[int]) -> tuple[int, int, tuple]:
    """The showcase rule: of seeds first..last not in `used`, the (seed,
    start_minute, rank) of the window with the best action_rank, over windows
    of `minutes` starting on a whole minute and ending by SUBS_FROM. Ties go to
    the lower seed, then the earlier start. Runs the simulator only."""
    best = None
    for seed in range(first, last + 1):
        if seed in used:
            continue
        events = simulate({"name": f"seed{seed}", "seed": seed, "home": home, "away": away}).events
        for start in range(0, int(SUBS_FROM - minutes) + 1):
            rank = action_rank(events, start * 60, (start + minutes) * 60)
            if best is None or rank > best[2]:
                best = (seed, start, rank)
    if best is None:
        raise ValueError(f"no unused seed in {first}..{last}")
    return best


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
    find = sub.add_parser("find-seed", help="first unused seed with goals in a window (simulator only)")
    find.add_argument("--after", type=int, required=True, help="search seeds after this one")
    find.add_argument("--home", default="bosphorus")
    find.add_argument("--away", default="thames")
    find.add_argument("--start-minute", type=float, default=0)
    find.add_argument("--minutes", type=float, required=True)
    find.add_argument("--goals", type=int, default=1, help="minimum goals in the window")
    show = sub.add_parser("find-showcase", help="the unused seed and window with the most goals and "
                                                "cards (simulator only)")
    show.add_argument("--first", type=int, required=True, help="first seed to search")
    show.add_argument("--last", type=int, required=True, help="last seed to search")
    show.add_argument("--home", default="bosphorus")
    show.add_argument("--away", default="thames")
    show.add_argument("--minutes", type=float, default=10)
    render = sub.add_parser("render", help="render clips from the seed record")
    info = sub.add_parser("info", help="add score_at_start to rendered clips' match_info.json (#83)")
    for p in (render, info):
        p.add_argument("names", nargs="*", help="clip names, e.g. dev1 test1")
        p.add_argument("--role", choices=ROLES, help="every clip with this role")
        p.add_argument("--all", action="store_true", help="every clip in the record")
        p.add_argument("--out", type=Path, default=OUT, help=f"output root (default {OUT})")
    render.add_argument("--force", action="store_true", help="rebuild clips already rendered")
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
            start, end = window(c)
            print(f"{c['name']:8} {c['role']:9} seed {c['seed']:<5} {start / 60:g}-{end / 60:g} min  "
                  f"{c['home']} ({home['shirt']}) v {c['away']} ({away['shirt']})")
        return 0
    if args.command == "find-seed":
        used = {c["seed"] for c in record["clips"]}
        seed = find_seed(args.after, args.home, args.away, args.start_minute, args.minutes, used,
                         args.goals)
        clip = {"name": f"seed{seed}", "seed": seed, "home": args.home, "away": args.away,
                "start_minute": args.start_minute, "minutes": args.minutes}
        times = ", ".join(f"{g['t']:g} s ({g['team']})" for g in goals_in_window(clip))
        print(f"seed {seed}: goals in the window at {times}")
        return 0
    if args.command == "find-showcase":
        used = {c["seed"] for c in record["clips"]}
        seed, start, rank = find_showcase(args.first, args.last, args.home, args.away, args.minutes, used)
        clip = {"name": f"seed{seed}", "seed": seed, "home": args.home, "away": args.away,
                "start_minute": start, "minutes": args.minutes}
        lo, hi = window(clip)
        print(f"seed {seed}: minutes {start}-{hi / 60:g} (rank {rank[:-1]}, margin {rank[-1]:.1f} s)")
        for e in simulate(clip).events:
            if lo <= e["t"] < hi and e["type"] in ACTION:
                print(f"  {int(e['t'] // 60)}:{e['t'] % 60:04.1f}  {e['type']}"
                      f"{' (' + e['subtype'] + ')' if e.get('subtype') else ''}  {e['team']}  {e['from']}")
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
        if args.command == "info":
            score = refresh_info(c, args.out)
            print(f"{c['name']}: score_at_start {score['home']}-{score['away']}")
        else:
            render_clip(c, args.out, args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
