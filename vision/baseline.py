"""Player-detector recall against boxes projected from simulator tracking (offline only).

    python -m vision.baseline VIDEO TRACKING [--weights PATH] [--upscale K] [--conf C] [--step N]

Projects each tracked player (a 1.88 m tall, 0.6 m wide upright box on its foot
point) through the renderer's `cv_full_pitch` camera and counts a player as
found when a detection overlaps its box with IoU >= 0.5. It reads simulator
tracking, so it is grading code: nothing on the runtime path imports it.

`--native` runs the detector the way it ships (whole 1920x1080 frame at its
default 640 px input, confidence 0.25) instead of the video stage's settings.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

from vision.detect import DEFAULT_WEIGHTS, MIN_CONFIDENCE, UPSCALE, PlayerDetector
from vision.pitch import calibrate
from vision.video import _region

PLAYER_HEIGHT_M = 1.88     # renderer/README.md: base player height
PLAYER_WIDTH_M = 0.6
IOU = 0.5


def camera(width: int = 1920, height: int = 1080):
    """The renderer's `cv_full_pitch` camera (renderer/src/camera/presets.ts) as a projection.

    Returns a function mapping N x 3 pitch points (x, y, height in meters) to
    N x 2 image pixels.
    """
    eye = np.array([0.0, 75.0, 83.0])
    forward = -eye / np.linalg.norm(eye)
    right = np.cross(forward, [0.0, 1.0, 0.0])
    right /= np.linalg.norm(right)
    up = np.cross(right, forward)
    aspect = width / height

    def ndc(points: np.ndarray, fov: float) -> np.ndarray:
        rel = points - eye
        depth = rel @ forward
        f = 1 / np.tan(np.radians(fov) / 2)
        return np.stack([f / aspect * (rel @ right) / depth, f * (rel @ up) / depth], axis=1)

    # Aspect-aware zoom: fit the pitch, goals and run-off with 3 % headroom.
    box = np.array([[x, y, z] for x in (-57, 57) for z in (-38, 38) for y in (0, 10)], dtype=float)
    extent = max(1.0, float(np.max(np.abs(ndc(box, 43.0)) * 1.03)))
    fov = float(np.degrees(2 * np.arctan(np.tan(np.radians(43.0) / 2) * extent)))

    def project(points) -> np.ndarray:
        p = np.atleast_2d(np.asarray(points, dtype=float))
        three = np.stack([p[:, 0] - 52.5, p[:, 2], 34 - p[:, 1]], axis=1)  # renderer/README.md
        n = ndc(three, fov)
        return np.stack([(n[:, 0] + 1) / 2 * width, (1 - n[:, 1]) / 2 * height], axis=1)

    return project


def player_boxes(frame: dict, project) -> np.ndarray:
    """Projected N x 4 boxes (x1, y1, x2, y2) of every player in one tracking frame."""
    out = []
    for p in frame["players"]:
        x, y = p["pos"]
        half = PLAYER_WIDTH_M / 2
        corners = project([[x - half, y, 0], [x + half, y, 0], [x - half, y, PLAYER_HEIGHT_M],
                           [x + half, y, PLAYER_HEIGHT_M]])
        out.append([*corners.min(axis=0), *corners.max(axis=0)])
    return np.array(out).reshape(-1, 4)


def iou(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Pairwise IoU of N x 4 and M x 4 boxes."""
    x1 = np.maximum(a[:, None, 0], b[None, :, 0])
    y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2])
    y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area = lambda r: (r[:, 2] - r[:, 0]) * (r[:, 3] - r[:, 1])  # noqa: E731
    return inter / (area(a)[:, None] + area(b)[None, :] - inter)


def recall(video: Path, tracking: Path, weights: Path | str = DEFAULT_WEIGHTS,
           upscale: float = UPSCALE, conf: float = MIN_CONFIDENCE, step: int = 1,
           native: bool = False) -> dict:
    """Share of tracked players a detector finds, over every `step`-th frame of a video.

    Video frame i is tracking line i (renderer export from the tracking's first frame).
    """
    truth = [json.loads(line) for line in Path(tracking).read_text(encoding="utf-8").splitlines()]
    detector = PlayerDetector(weights, upscale=upscale, min_confidence=conf)
    capture = cv2.VideoCapture(str(video))
    found = total = detections = frames = 0
    project = roi = None
    for index in range(len(truth)):
        ok, image = capture.read()
        if not ok:
            break
        if project is None:
            project = camera(image.shape[1], image.shape[0])
            roi = (0, 0, image.shape[1], image.shape[0]) if native else _region(calibrate(image),
                                                                                 image.shape)
        if index % step:
            continue
        if native:
            result = detector.model.predict(image, conf=0.25, classes=[0], device=detector.device,
                                            verbose=False)[0]
            boxes = result.boxes.xyxy.cpu().numpy()
        else:
            boxes = np.array([[b.x1, b.y1, b.x2, b.y2] for b in detector.detect(image, roi)])
        expected = player_boxes(truth[index], project)
        total += len(expected)
        detections += len(boxes)
        frames += 1
        if len(boxes) and len(expected):
            found += int((iou(expected, boxes.reshape(-1, 4)).max(axis=1) >= IOU).sum())
    capture.release()
    return {"video": str(video), "weights": str(weights), "frames": frames,
            "settings": "native (640 px, conf 0.25)" if native else f"upscale {upscale}, conf {conf}",
            "players": total, "found": found, "recall": round(found / total, 3) if total else None,
            "detections_per_frame": round(detections / frames, 2) if frames else None}


def main(argv: list[str] | None = None) -> int:
    """Print the recall report as JSON."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("video", type=Path)
    ap.add_argument("tracking", type=Path, help="simulator tracking.jsonl for the clip")
    ap.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS)
    ap.add_argument("--upscale", type=float, default=UPSCALE)
    ap.add_argument("--conf", type=float, default=MIN_CONFIDENCE)
    ap.add_argument("--step", type=int, default=1, help="every N-th frame")
    ap.add_argument("--native", action="store_true", help="detector defaults, whole frame")
    args = ap.parse_args(argv)
    print(json.dumps(recall(args.video, args.tracking, args.weights, args.upscale, args.conf,
                            args.step, args.native), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
