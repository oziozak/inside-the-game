"""Video stage: a rendered match video and its team sheet in, frame observations out.

    python -m vision.video VIDEO --out OBSERVATIONS.jsonl [--match-info PATH]
                           [--weights PATH] [--start SECONDS] [--frames N]

Reads only the video and the team sheet (`match_info.json`, by default next to
the video). Per frame: players from YOLO, the ball from its color, teams and
goalkeepers from the team sheet's kit colors, ByteTrack track ids, and pitch
meters through one homography found from the pitch lines of the first frame.
`--start` is the match time of the first video frame (default 0, the kickoff).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict, deque
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from vision.detect import (BALL_DIAMETER_M, DEFAULT_WEIGHTS, Box, KitClassifier, PlayerDetector,
                           find_ball)
from vision.observation import Ball, FrameObservation, PlayerObservation, write_observations
from vision.pitch import PitchMap, calibrate

PLAYER_MARGIN_M = 5        # players may stand this far outside the lines (run-off)
BALL_MARGIN_M = 3          # the ball may be this far outside the lines (goal nets, run-off)
HEAD_ROOM_PX = 40          # region above the far touchline where far players' bodies are
PLAYER_TRACK_SCALE = 2.0   # boxes are enlarged for association: players are only a few px wide
BALL_TRACK_PX = 24         # the ball is tracked as a fixed box so fast passes still overlap
KIT_VOTES = 25             # team and keeper flag: majority of a track's last 25 kit readings
                           # (a track can jump to another player when two cross)

# ByteTrack settings. Pretrained YOLO is unsure of these small figures: the
# calibration clip's two players score 0.05-0.2 (players in a full match
# ~0.7), so new tracks start from low-confidence detections, and association
# uses IoU alone (fuse_score would scale it by those low scores and never
# match). Tracks survive 2 s hidden behind other players.
PLAYER_TRACKER = dict(track_high_thresh=0.05, track_low_thresh=0.03, new_track_thresh=0.05,
                      track_buffer=50, match_thresh=0.8, fuse_score=False)
BALL_TRACKER = dict(track_high_thresh=0.5, track_low_thresh=0.1, new_track_thresh=0.5,
                    track_buffer=10, match_thresh=0.9, fuse_score=False)


def observe(video: Path, match_info: dict, weights: Path | str = DEFAULT_WEIGHTS,
            start: float = 0.0, max_frames: int | None = None,
            pixel_boxes: list[dict] | None = None) -> list[FrameObservation]:
    """Frame observations for every frame of a video (or its first `max_frames`).

    If `pixel_boxes` is a list, it gets one record per frame with the same
    players as the observation, in image pixels: each player's box [x1, y1,
    x2, y2] and the ball's ground point [x, y] (None when not seen). They are
    for drawing what the AI saw, not part of the observation contract.
    """
    from ultralytics.trackers.byte_tracker import BYTETracker

    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise ValueError(f"cannot open video {video}")
    fps = match_info.get("fps") or capture.get(cv2.CAP_PROP_FPS)
    detector = PlayerDetector(weights)
    kits = KitClassifier(match_info)
    player_tracker = BYTETracker(SimpleNamespace(**PLAYER_TRACKER))
    ball_tracker = BYTETracker(SimpleNamespace(**BALL_TRACKER))
    votes: dict[int, deque] = defaultdict(lambda: deque(maxlen=KIT_VOTES))
    pitch: PitchMap | None = None
    roi = ball_px = None
    ball_track = None
    frames: list[FrameObservation] = []
    index = 0
    while max_frames is None or index < max_frames:
        ok, image = capture.read()
        if not ok:
            break
        if pitch is None:
            pitch = calibrate(image, tuple(match_info.get("pitch", (105, 68))))
            roi = _region(pitch, image.shape)
            ball_px = lambda x, y, pitch=pitch: pitch.px_per_m((x, y)) * BALL_DIAMETER_M  # noqa: E731
        t = round(start + index / fps, 3)

        boxes = [b for b in detector.detect(image, roi) if _on_pitch(pitch, b.foot, PLAYER_MARGIN_M)]
        players, drawn = [], []
        for row in _track(player_tracker, boxes, PLAYER_TRACK_SCALE):
            track_id, box = int(row[4]), boxes[int(row[7])]
            kit = kits.classify(image, box)
            if kit is not None:
                votes[track_id].append(kit)
            if not votes[track_id]:
                continue
            team, goalkeeper = Counter(votes[track_id]).most_common(1)[0][0]
            players.append(PlayerObservation(
                track_id=track_id, team=team, goalkeeper=goalkeeper,
                pos=_meters(pitch, box.foot), confidence=round(box.confidence, 3)))
            drawn.append({"track_id": track_id, "team": team, "goalkeeper": goalkeeper,
                          "box": [round(v, 1) for v in (box.x1, box.y1, box.x2, box.y2)],
                          "confidence": round(box.confidence, 3)})

        candidates = [c for c in find_ball(image, boxes, ball_px)
                      if _on_pitch(pitch, c.point, BALL_MARGIN_M)]
        ball, ball_track = _pick_ball(ball_tracker, candidates, ball_track)
        frames.append(FrameObservation(
            frame=index, t=t, period=_period(match_info, t),
            ball=None if ball is None else Ball(pos=_meters(pitch, ball.point),
                                                confidence=round(ball.score, 3)),
            ball_visible=ball is not None,
            players=sorted(players, key=lambda p: p.track_id)))
        if pixel_boxes is not None:
            pixel_boxes.append({"frame": index, "t": t,
                                "players": sorted(drawn, key=lambda p: p["track_id"]),
                                "ball": None if ball is None else [round(v, 1) for v in ball.point]})
        index += 1
    capture.release()
    if pitch is None:
        raise ValueError(f"no frames in {video}")
    return frames


class _Detections:
    """The minimal results object ByteTrack reads: xywh, conf and cls arrays, boolean-indexable."""

    def __init__(self, xywh: np.ndarray, conf: np.ndarray):
        self.xywh, self.conf, self.cls = xywh, conf, np.zeros(len(conf))

    def __len__(self) -> int:
        return len(self.conf)

    def __getitem__(self, keep) -> _Detections:
        return _Detections(self.xywh[keep], self.conf[keep])


def _track(tracker, boxes: list[Box], scale: float) -> np.ndarray:
    """ByteTrack rows [x1, y1, x2, y2, track_id, score, cls, detection index] for this frame."""
    xywh = np.array([[(b.x1 + b.x2) / 2, (b.y1 + b.y2) / 2, (b.x2 - b.x1) * scale,
                      (b.y2 - b.y1) * scale] for b in boxes]).reshape(-1, 4)
    conf = np.array([b.confidence for b in boxes], dtype=float)
    return tracker.update(_Detections(xywh, conf)).reshape(-1, 8)


def _pick_ball(tracker, candidates, previous: int | None):
    """The ball among this frame's candidates: the one continuing the ball's track, else the best.

    Returns (candidate or None, track id of the ball or None).
    """
    boxes = [Box(c.point[0] - BALL_TRACK_PX / 2, c.point[1] - BALL_TRACK_PX / 2,
                 c.point[0] + BALL_TRACK_PX / 2, c.point[1] + BALL_TRACK_PX / 2, c.score)
             for c in candidates]
    rows = _track(tracker, boxes, 1.0)
    if not candidates:
        return None, previous
    for row in rows:
        if previous is not None and int(row[4]) == previous:
            return candidates[int(row[7])], previous
    best = 0                                   # candidates arrive best first
    for row in rows:
        if int(row[7]) == best:
            return candidates[best], int(row[4])
    return candidates[best], previous


def _region(pitch: PitchMap, shape) -> tuple[int, int, int, int]:
    """Image region holding the pitch, its run-off and the players standing on it."""
    length, width = pitch.size
    m = PLAYER_MARGIN_M
    corners = pitch.to_image([(-m, -m), (length + m, -m), (length + m, width + m), (-m, width + m)])
    height, full_width = shape[:2]
    x1, y1 = np.floor(corners.min(axis=0)).astype(int)
    x2, y2 = np.ceil(corners.max(axis=0)).astype(int)
    return max(x1, 0), max(y1 - HEAD_ROOM_PX, 0), min(x2, full_width), min(y2, height)


def _on_pitch(pitch: PitchMap, point, margin: float) -> bool:
    """Whether an image point lies on the grass, within `margin` meters of the lines."""
    x, y = pitch.to_pitch([point])[0]
    length, width = pitch.size
    return -margin <= x <= length + margin and -margin <= y <= width + margin


def _meters(pitch: PitchMap, point) -> tuple[float, float]:
    """An image point's pitch position, rounded to centimeters."""
    x, y = pitch.to_pitch([point])[0]
    return round(float(x), 2), round(float(y), 2)


def _period(match_info: dict, t: float) -> int:
    """The period whose [start, end) holds t (the last one that started, past the end)."""
    periods = sorted(match_info.get("periods") or [{"period": 1, "start": 0}], key=lambda p: p["start"])
    current = periods[0]["period"]
    for p in periods:
        if t >= p["start"]:
            current = p["period"]
    return current


def main(argv: list[str] | None = None) -> int:
    """Run the video stage on one video and write its frame observations."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("video", type=Path)
    ap.add_argument("--out", type=Path, required=True, help="frame observations (JSON Lines)")
    ap.add_argument("--match-info", type=Path, help="team sheet (default: match_info.json next to the video)")
    ap.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS, help="YOLO weights")
    ap.add_argument("--start", type=float, default=0.0, help="match time of the first frame, seconds")
    ap.add_argument("--frames", type=int, help="only the first N frames")
    args = ap.parse_args(argv)
    info_path = args.match_info or args.video.with_name("match_info.json")
    match_info = json.loads(info_path.read_text(encoding="utf-8"))
    frames = observe(args.video, match_info, weights=args.weights, start=args.start,
                     max_frames=args.frames)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_observations(args.out, frames)
    seen = sum(f.ball_visible for f in frames)
    players = sum(len(f.players) for f in frames) / max(len(frames), 1)
    print(f"{args.out}: {len(frames)} frames, ball visible in {seen}, {players:.1f} players per frame")
    return 0


if __name__ == "__main__":
    sys.exit(main())
