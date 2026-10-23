"""Per-frame detectors for the video stage: players (YOLO), the ball (color) and kits.

Everything here works on one BGR frame in image pixels. Tracking and the
pixel -> meter mapping live in `vision.video` and `vision.pitch`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WEIGHTS = ROOT / "data" / "models" / "yolo11s.pt"   # ignored by git; downloaded on first use
PERSON = 0                                                    # COCO class id

# Players are about 16 px tall at 1080p: pretrained YOLO finds none of them on
# the whole frame at its native 640 px input. On the pitch region upscaled 2x,
# yolo11s finds ~98 % (see README). Detections below MIN_HEIGHT x the frame's
# median box height are body-part fragments, and so are boxes lying NESTED
# (share of their area) inside a more confident box.
UPSCALE = 2
MIN_CONFIDENCE = 0.03
MIN_HEIGHT = 0.5
NESTED = 0.7

# v1 footage: the renderer's CV-visibility ball, unlit #fff052, at ball scale 2
# (0.22 m radius). The grass hides its lower part, so the visible blob is
# roughly the ball's width and its bottom edge sits on the ground.
BALL_COLOR = "#fff052"
BALL_DIAMETER_M = 0.44
BALL_HUE_TOLERANCE = 8          # OpenCV hue units (0-180)
BALL_MIN_SATURATION = 110       # excludes skin and white markings
BALL_MIN_VALUE = 140
BALL_MIN_AREA = 3               # pixels
BALL_MAX_SIZE = 1.6             # largest blob side, in expected ball diameters
BODY_FRACTION = 0.7             # the top 70 % of a player box is the body; the rest is feet

# Kit colors in the team sheet are the material colors; rendered shirts are
# shaded darker, so lightness counts for less than hue and saturation.
KIT_LIGHTNESS_WEIGHT = 0.4
GRASS_RING_PX = 3               # grass sampled in a band this wide around each player box
GRASS_DISTANCE = 18             # Lab distance below which a torso pixel counts as grass
MIN_SHIRT_PIXELS = 2


@dataclass(frozen=True)
class Box:
    """An axis-aligned image box in pixels with a detector confidence."""

    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float

    @property
    def foot(self) -> tuple[float, float]:
        """Bottom center: where the person stands."""
        return ((self.x1 + self.x2) / 2, self.y2)


class PlayerDetector:
    """People on the pitch, from a YOLO model (COCO person class unless the weights are fine-tuned)."""

    def __init__(self, weights: Path | str = DEFAULT_WEIGHTS, upscale: float = UPSCALE,
                 min_confidence: float = MIN_CONFIDENCE, device: str | None = None):
        from ultralytics import YOLO   # heavy import, only when detecting

        weights = Path(weights)
        if weights == DEFAULT_WEIGHTS:
            weights.parent.mkdir(parents=True, exist_ok=True)
        self.model = YOLO(str(weights))
        self.upscale = upscale
        self.min_confidence = min_confidence
        self.device = device or _best_device()

    def detect(self, frame: np.ndarray, roi: tuple[int, int, int, int]) -> list[Box]:
        """Person boxes inside the region (x1, y1, x2, y2), in full-frame pixels."""
        x1, y1, x2, y2 = roi
        crop = frame[y1:y2, x1:x2]
        if self.upscale != 1:
            crop = cv2.resize(crop, None, fx=self.upscale, fy=self.upscale,
                              interpolation=cv2.INTER_CUBIC)
        size = int(np.ceil(max(crop.shape[:2]) / 32) * 32)
        result = self.model.predict(crop, imgsz=size, conf=self.min_confidence, classes=[PERSON],
                                    device=self.device, verbose=False)[0]
        xyxy = result.boxes.xyxy.cpu().numpy() / self.upscale + (x1, y1, x1, y1)
        conf = result.boxes.conf.cpu().numpy()
        boxes = [Box(*map(float, b), confidence=float(c)) for b, c in zip(xyxy, conf)]
        if len(boxes) >= 3:
            floor = MIN_HEIGHT * float(np.median([b.y2 - b.y1 for b in boxes]))
            boxes = [b for b in boxes if b.y2 - b.y1 >= floor]
        return _drop_nested(boxes)


def _drop_nested(boxes: list[Box]) -> list[Box]:
    """Drop boxes lying mostly inside a more confident one: a second box on part of the same body."""
    kept: list[Box] = []
    for b in sorted(boxes, key=lambda b: -b.confidence):
        area = (b.x2 - b.x1) * (b.y2 - b.y1)
        if all(_overlap(b, k) < NESTED * area for k in kept):
            kept.append(b)
    return kept


def _overlap(a: Box, b: Box) -> float:
    """Intersection area of two boxes."""
    return max(0.0, min(a.x2, b.x2) - max(a.x1, b.x1)) * max(0.0, min(a.y2, b.y2) - max(a.y1, b.y1))


def _best_device() -> str:
    """Apple GPU or CUDA when present, else CPU."""
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


@dataclass(frozen=True)
class BallCandidate:
    """A ball-colored blob: its ground point (bottom center) in pixels and a 0-1 score."""

    point: tuple[float, float]
    score: float


def find_ball(frame: np.ndarray, players: list[Box], ball_px) -> list[BallCandidate]:
    """Ball-colored blobs that can be the ball, best first.

    `ball_px(x, y)` is the expected ball diameter in pixels at an image point.
    A blob is rejected when it is larger than a ball there (a yellow
    goalkeeper shirt is the same hue), or when it sits in the body of a
    detected player rather than at the feet, where a ball being played is.
    """
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    hue = _hue(BALL_COLOR)
    diff = np.abs(hsv[..., 0].astype(np.int16) - hue)
    mask = ((np.minimum(diff, 180 - diff) <= BALL_HUE_TOLERANCE)
            & (hsv[..., 1] >= BALL_MIN_SATURATION) & (hsv[..., 2] >= BALL_MIN_VALUE))
    n, _, stats, centroids = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    candidates = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area < BALL_MIN_AREA:
            continue
        cx = float(centroids[i][0]) + 0.5
        point = (cx, float(y + h))
        expected = max(ball_px(*point), 1.0)
        if max(w, h) > BALL_MAX_SIZE * expected:
            continue
        if any(_in_body(cx, float(centroids[i][1]) + 0.5, p) for p in players):
            continue
        fill = min(1.0, area / (np.pi / 4 * expected ** 2))
        candidates.append(BallCandidate(point=point, score=float(0.5 + 0.5 * fill)))
    return sorted(candidates, key=lambda c: -c.score)


def _in_body(x: float, y: float, box: Box) -> bool:
    """Whether an image point is inside the upper (body) part of a player box."""
    return box.x1 <= x <= box.x2 and box.y1 <= y <= box.y1 + BODY_FRACTION * (box.y2 - box.y1)


def _hue(hex_color: str) -> int:
    """OpenCV hue (0-180) of a #rrggbb color."""
    return int(cv2.cvtColor(_bgr(hex_color)[None, None], cv2.COLOR_BGR2HSV)[0, 0, 0])


def _bgr(hex_color: str) -> np.ndarray:
    """A #rrggbb color as a BGR uint8 triple."""
    h = hex_color.lstrip("#")
    return np.array([int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)], dtype=np.uint8)


class KitClassifier:
    """Team and goalkeeper from the shirt color, matched to the team sheet's kits."""

    def __init__(self, match_info: dict):
        self.kits = []      # (team, goalkeeper, Lab color)
        for team in ("home", "away"):
            kit = match_info[team]["kit"]
            for goalkeeper, color in ((False, kit["shirt"]), (True, kit["goalkeeper"])):
                self.kits.append((team, goalkeeper, _lab(_bgr(color)[None])[0]))

    def classify(self, frame: np.ndarray, box: Box) -> tuple[str, bool] | None:
        """(team, goalkeeper) for a player box, or None when no shirt pixels are visible."""
        shirt = self.shirt_color(frame, box)
        if shirt is None:
            return None
        weights = np.array([KIT_LIGHTNESS_WEIGHT, 1.0, 1.0])
        dists = [float(np.linalg.norm((shirt - lab) * weights)) for _, _, lab in self.kits]
        team, goalkeeper, _ = self.kits[int(np.argmin(dists))]
        return team, goalkeeper

    @staticmethod
    def shirt_color(frame: np.ndarray, box: Box) -> np.ndarray | None:
        """Mean Lab color of the torso region (below the head, above the shorts).

        Torso pixels that look like the grass just around the box are left
        out, unless that leaves too few (a green shirt on green grass).
        """
        h, w = box.y2 - box.y1, box.x2 - box.x1
        y1, y2 = int(round(box.y1 + 0.2 * h)), int(round(box.y1 + 0.5 * h))
        x1, x2 = int(round(box.x1 + 0.2 * w)), int(round(box.x2 - 0.2 * w))
        patch = _lab(frame[max(y1, 0):max(y2, y1 + 1), max(x1, 0):max(x2, x1 + 1)])
        if not len(patch):
            return None
        grass = _lab(_ring(frame, box, GRASS_RING_PX))
        if len(grass):
            shirt = patch[np.linalg.norm(patch - np.median(grass, axis=0), axis=1) > GRASS_DISTANCE]
            if len(shirt) >= MIN_SHIRT_PIXELS:
                patch = shirt
        return patch.mean(axis=0)


def _ring(frame: np.ndarray, box: Box, width: int) -> np.ndarray:
    """Pixels in a band `width` wide just outside a box (N x 3 BGR)."""
    height, full_width = frame.shape[:2]
    x1, y1 = max(int(box.x1) - width, 0), max(int(box.y1) - width, 0)
    x2, y2 = min(int(np.ceil(box.x2)) + width, full_width), min(int(np.ceil(box.y2)) + width, height)
    region = frame[y1:y2, x1:x2]
    inside = np.zeros(region.shape[:2], dtype=bool)
    inside[int(box.y1) - y1:int(np.ceil(box.y2)) - y1, int(box.x1) - x1:int(np.ceil(box.x2)) - x1] = True
    return region[~inside]


def _lab(bgr: np.ndarray) -> np.ndarray:
    """N x 3 BGR uint8 -> N x 3 float Lab (OpenCV 8-bit scaling)."""
    return cv2.cvtColor(bgr.reshape(-1, 1, 3).astype(np.uint8), cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(float)
