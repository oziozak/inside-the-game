"""Vision tracer: a match video and its team sheet in, detected events out.

    python -m vision VIDEO --out EVENTS.json [--match-info PATH] [--observations PATH]
                     [--frame-boxes PATH] [--weights PATH] [--start SECONDS] [--frames N]

Inputs (the only files it reads):
  VIDEO               the rendered match video (mp4, fixed full-pitch camera)
  match_info.json     the team sheet: kit colors, periods, kickoff direction
                      (default: next to the video; --match-info to point elsewhere)
  YOLO weights        --weights (default data/models/yolo11s.pt, downloaded on first use)

Outputs (the only files it writes):
  --out               detected events, a JSON array in schemas/event.schema.json,
                      every event `source: cv`, sorted by t, ids e0001...
  --observations      optional: the frame observations in between (JSON Lines)
  --frame-boxes       optional: per frame, the same players as pixel boxes with
                      the roster id lineup assignment names them for (or null),
                      and the ball's pixel point (JSON Lines), for
                      `python -m vision.annotate`. Events are the same with or without it.

It chains the video stage (vision.video: pixels -> frame observations) and the
event rules (vision.rules: observations -> events) in one batch run, with no
state kept between runs and no interactive steps. It never opens simulator
events or tracking; a test runs it with those files beside the video and
checks that it opens none of them.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from vision.detect import DEFAULT_WEIGHTS
from vision.observation import write_observations
from vision.rules import detect_events
from vision.video import observe


def run(video: Path, match_info: dict, weights: Path | str = DEFAULT_WEIGHTS, start: float = 0.0,
        max_frames: int | None = None, observations: Path | None = None,
        frame_boxes: Path | None = None) -> list[dict]:
    """Detected events for a video (or its first `max_frames`), optionally saving the
    observations and the frame boxes."""
    boxes: list[dict] | None = [] if frame_boxes is not None else None
    names: list[dict[int, int]] | None = [] if frame_boxes is not None else None
    frames = observe(video, match_info, weights=weights, start=start, max_frames=max_frames,
                     pixel_boxes=boxes)
    if observations is not None:
        observations.parent.mkdir(parents=True, exist_ok=True)
        write_observations(observations, frames)
    events = detect_events(frames, match_info, names=names)
    if frame_boxes is not None:
        frame_boxes.parent.mkdir(parents=True, exist_ok=True)
        write_frame_boxes(frame_boxes, boxes, names)
    return events


def write_frame_boxes(path: Path, boxes: list[dict], names: list[dict[int, int]]) -> None:
    """Write the frame boxes as JSON Lines, each player with the roster id it is named for (or null)."""
    with Path(path).open("w", encoding="utf-8") as f:
        for record, named in zip(boxes, names, strict=True):
            players = [{**p, "player": named.get(p["track_id"])} for p in record["players"]]
            f.write(json.dumps({**record, "players": players}, separators=(",", ":")) + "\n")


def main(argv: list[str] | None = None) -> int:
    """Run the tracer on one video and write its detected events."""
    ap = argparse.ArgumentParser(prog="python -m vision", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video", type=Path, help="the match video")
    ap.add_argument("--out", type=Path, required=True, help="where to write the detected events (JSON)")
    ap.add_argument("--match-info", type=Path, help="team sheet (default: match_info.json next to the video)")
    ap.add_argument("--observations", type=Path, help="also write the frame observations here (JSON Lines)")
    ap.add_argument("--frame-boxes", type=Path,
                    help="also write per-frame pixel boxes and names here (JSON Lines)")
    ap.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS, help="YOLO weights")
    ap.add_argument("--start", type=float, default=0.0, help="match time of the first frame, seconds")
    ap.add_argument("--frames", type=int, help="only the first N frames")
    args = ap.parse_args(argv)
    info_path = args.match_info or args.video.with_name("match_info.json")
    match_info = json.loads(info_path.read_text(encoding="utf-8"))
    events = run(args.video, match_info, weights=args.weights, start=args.start,
                 max_frames=args.frames, observations=args.observations, frame_boxes=args.frame_boxes)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(events, indent=2) + "\n", encoding="utf-8")
    counts = ", ".join(f"{n} {ty}" for ty, n in Counter(e["type"] for e in events).items()) or "none"
    print(f"{args.out}: {len(events)} events ({counts})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
