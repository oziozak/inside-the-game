"""Grade the tracer on footage clips: run it, score it, write vision_report.json.

    python -m vision.grade_footage dev1 dev2 dev3        # or --role dev, --all
    python -m vision.grade_footage test1 --footage ~/renders/footage
    python -m vision.grade_footage --role dev --reuse    # re-grade saved detections

Offline only: it reads the simulator's truth, so nothing on the runtime path
imports it. For each clip in the seed record (vision/footage_seeds.json) it
runs the tracer, `python -m vision`, as a child process on the clip's video,
so the run reads only the video and its team sheet, exactly as the command
does on its own, plus the match time of the clip's first frame (`--start`, the
broadcast clock). Then it grades the detected events against truth/events.json
and records with the grade the render settings (from the export manifest),
the clip's seed and role (from the seed record), the detector weights and the
seeds they were trained on (none for the pretrained detector).

Clips are read from --footage, else $VISION_FOOTAGE, else data/renders/footage.
Output per clip, in --out/<name>/ (default runs/footage/, ignored by git):
events.json (detected), observations.jsonl, vision_report.json.

The test clip is the held-out grade: grade it to report, never to tune.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from vision.detect import DEFAULT_WEIGHTS
from vision.footage import OUT as RENDERS, ROLES, load_record, window
from vision.grader import DETECTED_TYPES, build_report, clip_info, summary, write_report

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs" / "footage"                     # ignored by git
FOOTAGE_ENV = "VISION_FOOTAGE"


def footage_root(path: Path | str | None = None) -> Path:
    """Where rendered footage clips live: `path`, else $VISION_FOOTAGE, else data/renders/footage."""
    return Path(path or os.environ.get(FOOTAGE_ENV) or RENDERS).expanduser()


def detect(video: Path, out: Path, weights: Path | str = DEFAULT_WEIGHTS, start: float = 0.0) -> None:
    """Run the tracer on a video whose first frame is at match time `start`, in a child
    process: out/events.json and out/observations.jsonl."""
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "vision", str(video), "--out", str(out / "events.json"),
                    "--observations", str(out / "observations.jsonl"), "--weights", str(weights),
                    "--start", f"{start:g}"],
                   cwd=ROOT, check=True)


def grade_clip(clip: dict, footage: Path, out: Path, weights: Path | str = DEFAULT_WEIGHTS,
               training_seeds: list[int] | None = None, reuse: bool = False) -> dict:
    """Run the tracer on one seed-record clip (unless `reuse` and its events exist), grade
    it, write out/vision_report.json and return the report."""
    folder = footage / clip["name"]
    video = folder / f"{clip['name']}.mp4"
    if not video.exists():
        raise FileNotFoundError(f"{video} not found (render it: python -m vision.footage render "
                                f"{clip['name']})")
    detected_file, truth_file = out / "events.json", folder / "truth" / "events.json"
    if not (reuse and detected_file.exists()):
        detect(video, out, weights, window(clip)[0])
    manifest = json.loads(Path(f"{video}.manifest.json").read_text(encoding="utf-8"))
    info = clip_info(manifest, {}, clip["seed"], training_seeds or [])
    info.update(name=clip["name"], role=clip["role"], pairing=[clip["home"], clip["away"]],
                weights=Path(weights).name)
    report = build_report(json.loads(detected_file.read_text(encoding="utf-8")),
                          json.loads(truth_file.read_text(encoding="utf-8")),
                          info, DETECTED_TYPES, detected_file, truth_file)
    write_report(out / "vision_report.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    """Command line; returns the exit code."""
    ap = argparse.ArgumentParser(prog="python -m vision.grade_footage", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("names", nargs="*", help="clip names from the seed record, e.g. dev1 test1")
    ap.add_argument("--role", choices=ROLES, help="every clip with this role")
    ap.add_argument("--all", action="store_true", help="every dev and test clip")
    ap.add_argument("--footage", type=Path, help=f"footage root (default ${FOOTAGE_ENV} or {RENDERS})")
    ap.add_argument("--out", type=Path, default=RUNS, help=f"output root (default {RUNS})")
    ap.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS, help="YOLO weights for the tracer")
    ap.add_argument("--training-seeds", type=int, nargs="*", default=[],
                    help="seeds the weights were fine-tuned on (default: none, pretrained)")
    ap.add_argument("--reuse", action="store_true",
                    help="grade the detected events already in --out instead of running the tracer")
    args = ap.parse_args(argv)

    record = load_record()["clips"]
    by_name = {c["name"]: c for c in record}
    unknown = [n for n in args.names if n not in by_name]
    if unknown:
        print(f"error: unknown clip {', '.join(unknown)} (see: python -m vision.footage list)",
              file=sys.stderr)
        return 2
    clips = [by_name[n] for n in args.names]
    clips += [c for c in record if c not in clips
              and (c["role"] == args.role or (args.all and c["role"] in ("dev", "test")))]
    if not clips:
        print("error: name clips, or pass --role or --all", file=sys.stderr)
        return 2
    footage = footage_root(args.footage)
    for c in clips:
        report = grade_clip(c, footage, args.out / c["name"], args.weights, args.training_seeds,
                            args.reuse)
        print(f"{c['name']} ({c['role']}, seed {c['seed']})\n{summary(report)}")
        print(f"Wrote {args.out / c['name'] / 'vision_report.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
