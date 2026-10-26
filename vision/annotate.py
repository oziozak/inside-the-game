"""AI view: the video the vision AI watched, with what it saw drawn on top.

    python -m vision.annotate CLIP_DIR RUN_DIR --out ai_view.mp4 [--video PATH]

Inputs (the only files it reads):
  the video           CLIP_DIR/<CLIP_DIR name>.mp4, else CLIP_DIR/match.mp4 (or --video):
                      the full-pitch video the tracer ran on
  match_info.json     CLIP_DIR's team sheet: kit colors and player names
  frame_boxes.jsonl   RUN_DIR: the tracer's pixel boxes and names
                      (`python -m vision VIDEO --out RUN_DIR/events.json --frame-boxes ...`)
  events.json         RUN_DIR: the tracer's detected events

Per frame it draws each detected player's box in the color of the team the AI
assigned (goalkeepers marked GK), the name lineup assignment gave the track
(or its anonymous track id until a kickoff names it), a ring on the ball when
it was seen, a short label at each detected event for LABEL_S near where it
happened, and a caption in the corner. Event positions are drawn through the
pitch calibration of the first frame, as the tracer found it.

The drawing is a transparent layer that FFmpeg lays over the decoded source,
so the pixels under it never take a round trip through RGB (which shifts every
color slightly). Output: H.264, yuv420p, +faststart, with the source's frame
rate and frame count, so it plays in sync with the broadcast video of the same
clip. Like the tracer, it never opens the simulator's truth.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

from vision.pitch import PitchMap, calibrate

CAPTION = "AI VIEW: what the vision model detects"
LABEL_S = 1.0                   # an event's label stays this long ...
LABEL_RISE_PX = 40              # ... this far above where it happened (labels on screen together stack upward)
EVENT_LABEL = {"kickoff": "KICKOFF", "pass": "PASS", "shot": "SHOT", "goal": "GOAL",
               "possession_change": "WON BALL"}
FONT = cv2.FONT_HERSHEY_SIMPLEX
NAME_SCALE, LABEL_SCALE, CAPTION_SCALE = 0.42, 0.8, 0.9
BOX_PAD_PX = 2                  # boxes are drawn this much outside the detection
BALL_RING_PX = 8
BALL_COLOR = (255, 255, 0, 255)  # BGRA cyan: stands out from the yellow ball and every kit
WHITE, BLACK = (255, 255, 255, 255), (0, 0, 0, 255)
CAPTION_SHADE = (0, 0, 0, 165)    # the caption's panel darkens what is under it
CRF = 20


def find_video(clip_dir: Path) -> Path:
    """The clip's video: <clip_dir name>.mp4 (a footage clip), else match.mp4 (a demo bundle)."""
    for video in (clip_dir / f"{clip_dir.name}.mp4", clip_dir / "match.mp4"):
        if video.is_file():
            return video
    raise FileNotFoundError(f"no {clip_dir.name}.mp4 or match.mp4 in {clip_dir} (pass --video)")


def read_frame_boxes(path: Path) -> dict[int, dict]:
    """The tracer's frame boxes by frame index."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return {r["frame"]: r for r in map(json.loads, filter(str.strip, lines))}


def _bgra(hex_color: str) -> tuple[int, int, int, int]:
    """A #rrggbb color as an opaque BGRA tuple."""
    h = hex_color.lstrip("#")
    return int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16), 255


def _text(image: np.ndarray, text: str, org: tuple[int, int], scale: float, color=WHITE,
          thickness: int = 1) -> None:
    """Text with a dark outline, readable on grass and kits alike. The outline is
    the text shifted a pixel each way: a thicker stroke would space the glyphs wider."""
    for dx, dy in ((-1, -1), (-1, 1), (1, -1), (1, 1), (-1, 0), (1, 0), (0, -1), (0, 1)):
        cv2.putText(image, text, (org[0] + dx, org[1] + dy), FONT, scale, BLACK, thickness, cv2.LINE_AA)
    cv2.putText(image, text, org, FONT, scale, color, thickness, cv2.LINE_AA)


def _label(image: np.ndarray, text: str, center: tuple[int, int], color,
           taken: list[tuple[int, int, int, int]]) -> None:
    """An event label: text on a dark panel edged in the team's color, centered on a
    point, moved up past the panels already drawn in this frame (`taken`, which it joins)."""
    (w, h), base = cv2.getTextSize(text, FONT, LABEL_SCALE, 2)
    height, width = image.shape[:2]
    x = int(min(max(center[0] - w / 2, 6), width - w - 6))
    y = int(center[1])
    while any(_overlaps((x - 6, y - h - 6, x + w + 6, y + base + 4), r) for r in taken):
        y -= h + base + 12
    y = int(min(max(y, h + 6), height - base - 6))
    panel = (x - 6, y - h - 6, x + w + 6, y + base + 4)
    taken.append(panel)
    cv2.rectangle(image, panel[:2], panel[2:], BLACK, -1)
    cv2.rectangle(image, panel[:2], panel[2:], color, 2)
    cv2.putText(image, text, (x, y), FONT, LABEL_SCALE, WHITE, 2, cv2.LINE_AA)


def _overlaps(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    """Whether two (x1, y1, x2, y2) rectangles overlap."""
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


class Painter:
    """Draws one frame's detections, names, ball and event labels onto a BGRA layer."""

    def __init__(self, match_info: dict, events: list[dict], pitch: PitchMap):
        self.colors = {side: _bgra(match_info[side]["kit"]["shirt"]) for side in ("home", "away")}
        self.player_names = {p["id"]: p["name"] for side in ("home", "away")
                             for p in match_info[side]["players"]}
        self.events = [e for e in events if e["type"] in EVENT_LABEL]
        self.pitch = pitch

    def draw(self, image: np.ndarray, record: dict | None, t: float) -> None:
        """Draw onto the BGRA layer `image` (in place) what the tracer saw in this frame,
        at match time `t`."""
        for p in (record or {}).get("players", []):
            x1, y1, x2, y2 = (int(round(v)) for v in p["box"])
            color = self.colors[p["team"]]
            cv2.rectangle(image, (x1 - BOX_PAD_PX, y1 - BOX_PAD_PX), (x2 + BOX_PAD_PX, y2 + BOX_PAD_PX),
                          color, 2)
            name = self.player_names.get(p["player"], f"track {p['track_id']}")
            text = f"GK {name}" if p["goalkeeper"] else name
            (w, _), _ = cv2.getTextSize(text, FONT, NAME_SCALE, 1)
            _text(image, text, ((x1 + x2 - w) // 2, y1 - BOX_PAD_PX - 4), NAME_SCALE)
        ball = (record or {}).get("ball")
        if ball is not None:
            cv2.circle(image, (int(round(ball[0])), int(round(ball[1] - BALL_RING_PX / 2))),
                       BALL_RING_PX, BALL_COLOR, 2, cv2.LINE_AA)
        taken: list[tuple[int, int, int, int]] = []
        for e in self.events:
            if e["t"] <= t < e["t"] + LABEL_S:
                x, y = self.pitch.to_image([e["start"]])[0]
                _label(image, EVENT_LABEL[e["type"]], (int(x), int(y) - LABEL_RISE_PX),
                       self.colors.get(e.get("team"), WHITE), taken)
        _caption(image)


def _caption(image: np.ndarray) -> None:
    """The corner caption saying what this feed is."""
    (w, h), base = cv2.getTextSize(CAPTION, FONT, CAPTION_SCALE, 2)
    cv2.rectangle(image, (12, 12), (32 + w, 28 + h + base), CAPTION_SHADE, -1)
    cv2.putText(image, CAPTION, (22, 20 + h), FONT, CAPTION_SCALE, WHITE, 2, cv2.LINE_AA)


def probe(video: Path) -> tuple[str, int]:
    """The video's exact frame rate as FFprobe reports it (e.g. '25/1') and its frame count."""
    def stream(*extra: str) -> dict:
        done = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", *extra,
                               "-show_entries", "stream=r_frame_rate,nb_frames,nb_read_frames",
                               "-of", "json", str(video)], capture_output=True, text=True, check=True)
        return json.loads(done.stdout)["streams"][0]

    info = stream()
    frames = info.get("nb_frames")
    if not str(frames).isdigit():               # not in the container: decode and count
        frames = stream("-count_frames")["nb_read_frames"]
    return info["r_frame_rate"], int(frames)


def annotate(video: Path, match_info: dict, records: dict[int, dict], events: list[dict],
             out: Path) -> int:
    """Write the AI view of `video` to `out`; returns the number of frames written."""
    capture = cv2.VideoCapture(str(video))
    ok, image = capture.read()
    capture.release()
    if not ok:
        raise ValueError(f"cannot read a frame of {video}")
    rate, count = probe(video)
    num, _, den = rate.partition("/")
    fps = float(num) / float(den or 1)
    first = records[min(records)] if records else {"frame": 0, "t": 0.0}
    t0 = first["t"] - first["frame"] / fps          # match time of frames the tracer did not see
    missing = count - sum(0 <= i < count for i in records)
    if missing:
        print(f"warning: {missing} of {count} frames have no frame boxes (a run with --start or "
              f"--frames?): nothing is drawn on them but the caption and event labels", file=sys.stderr)
    painter = Painter(match_info, events, calibrate(image, tuple(match_info.get("pitch", (105, 68)))))
    height, width = image.shape[:2]
    out.parent.mkdir(parents=True, exist_ok=True)
    encoder = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-i", str(video),
         "-f", "rawvideo", "-pix_fmt", "bgra", "-s", f"{width}x{height}", "-framerate", rate, "-i", "-",
         "-filter_complex", "[0:v]setpts=PTS-STARTPTS[clip];[1:v]setpts=PTS-STARTPTS[layer];"
                            "[clip][layer]overlay=format=auto,format=yuv420p", "-an",
         "-c:v", "libx264", "-crf", str(CRF), "-movflags", "+faststart", str(out)],
        stdin=subprocess.PIPE)
    try:
        for index in range(count):
            layer = np.zeros((height, width, 4), dtype=np.uint8)
            record = records.get(index)
            painter.draw(layer, record, record["t"] if record else round(t0 + index / fps, 3))
            encoder.stdin.write(layer.tobytes())
    except BrokenPipeError:
        pass                                        # ffmpeg stopped: its exit code says why
    finally:
        try:
            encoder.stdin.close()
        except BrokenPipeError:
            pass
        code = encoder.wait()
    if code != 0:
        raise RuntimeError(f"ffmpeg failed with exit code {code}")
    return count


def main(argv: list[str] | None = None) -> int:
    """Write the AI view of one clip."""
    ap = argparse.ArgumentParser(prog="python -m vision.annotate", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("clip_dir", type=Path, help="the clip: its video and match_info.json")
    ap.add_argument("run_dir", type=Path, help="the tracer's outputs: frame_boxes.jsonl and events.json")
    ap.add_argument("--out", type=Path, required=True, help="where to write the AI view (mp4)")
    ap.add_argument("--video", type=Path, help="the video (default: found in CLIP_DIR, see above)")
    args = ap.parse_args(argv)
    video = args.video or find_video(args.clip_dir)
    match_info = json.loads((args.clip_dir / "match_info.json").read_text(encoding="utf-8"))
    records = read_frame_boxes(args.run_dir / "frame_boxes.jsonl")
    events = json.loads((args.run_dir / "events.json").read_text(encoding="utf-8"))
    frames = annotate(video, match_info, records, events, args.out)
    print(f"{args.out}: {frames} frames, {len(records)} with detections, "
          f"{sum(e['type'] in EVENT_LABEL for e in events)} event labels")
    return 0


if __name__ == "__main__":
    sys.exit(main())
