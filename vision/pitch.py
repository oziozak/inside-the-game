"""Pixel -> meter mapping for the static full-pitch camera, found from the pitch lines.

One homography maps image points on the grass to pitch meters. It is computed
once per video from the white markings of a single frame: the two touchlines,
the two goal lines and the halfway line. Their six intersections (four corners
and both ends of the halfway line) fix the homography. No camera parameters or
simulator data are used.

Orientation (the v1 `cv_full_pitch` view, as a broadcaster would set it up):
the near touchline at the bottom of the image is y = 0 and the goal line on the
left is x = 0.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

LINE_CONTRAST = 40        # a marking pixel is this much brighter than the grass around it
LINE_MAX_SATURATION = 110  # and nearly colorless (H.264 tints thin lines green)
LINE_REFINE_PX = 3         # pixels within this distance of a Hough line refine it


@dataclass(frozen=True)
class PitchMap:
    """The homography between image pixels and pitch meters for one fixed camera."""

    to_pitch_h: np.ndarray            # 3x3, image (x, y) -> pitch (x, y) in meters
    size: tuple[float, float]         # pitch length and width in meters

    def to_pitch(self, points) -> np.ndarray:
        """Image points (N x 2, pixels) -> ground points on the pitch (N x 2, meters)."""
        pts = np.asarray(points, dtype=np.float64).reshape(-1, 1, 2)
        return cv2.perspectiveTransform(pts, self.to_pitch_h).reshape(-1, 2)

    def to_image(self, points) -> np.ndarray:
        """Pitch points (N x 2, meters) -> image points (N x 2, pixels)."""
        pts = np.asarray(points, dtype=np.float64).reshape(-1, 1, 2)
        return cv2.perspectiveTransform(pts, np.linalg.inv(self.to_pitch_h)).reshape(-1, 2)

    def px_per_m(self, point) -> float:
        """How many pixels one meter of grass spans near an image point (geometric mean of x and y)."""
        ground = self.to_pitch([point])[0]
        steps = self.to_image([ground, ground + (1, 0), ground + (0, 1)])
        return float(np.sqrt(np.linalg.norm(steps[1] - steps[0]) * np.linalg.norm(steps[2] - steps[0])))


def calibrate(frame: np.ndarray, size: tuple[float, float] = (105.0, 68.0)) -> PitchMap:
    """Find the pitch homography from the markings in one BGR frame.

    Raises ValueError when the touchlines, goal lines and halfway line cannot all be found.
    """
    mask = _line_mask(frame)
    groups = _line_groups(mask)
    level = [g for g in groups if abs(g.normal[1]) > 0.95]
    steep = [g for g in groups if abs(g.normal[1]) <= 0.95]
    if len(level) < 2:
        raise ValueError("pitch calibration: touchlines not found")
    far, near = sorted(sorted(level, key=lambda g: -g.length)[:2], key=lambda g: g.offset)
    mid_y = (far.offset + near.offset) / 2
    # Goal lines and the halfway line run the whole width of the pitch; box edges do not.
    across = sorted((g for g in steep if g.y_extent() > 0.7 * (near.offset - far.offset)),
                    key=lambda g: g.x_at(mid_y))
    if len(across) < 3:
        raise ValueError("pitch calibration: goal lines and halfway line not found")
    lines = {"far": far, "near": near, "left": across[0], "half": across[len(across) // 2],
             "right": across[-1]}
    ys, xs = np.nonzero(mask)
    pixels = np.stack([xs, ys], axis=1) + 0.5     # pixel centers, continuous image coordinates
    fit = {name: _refine(g, pixels) for name, g in lines.items()}
    length, width = size
    pairs = [(("near", "left"), (0, 0)), (("near", "right"), (length, 0)),
             (("far", "right"), (length, width)), (("far", "left"), (0, width)),
             (("near", "half"), (length / 2, 0)), (("far", "half"), (length / 2, width))]
    image = np.array([_intersect(fit[a], fit[b]) for (a, b), _ in pairs])
    pitch = np.array([p for _, p in pairs], dtype=np.float64)
    h, _ = cv2.findHomography(image, pitch)
    if h is None:
        raise ValueError("pitch calibration: degenerate line intersections")
    return PitchMap(to_pitch_h=h, size=(length, width))


def _line_mask(frame: np.ndarray) -> np.ndarray:
    """White marking pixels: brighter than their surroundings and nearly colorless."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    value = hsv[..., 2]
    local = cv2.medianBlur(value, 15)
    bright = value.astype(np.int16) - local.astype(np.int16) > LINE_CONTRAST
    return ((hsv[..., 1] < LINE_MAX_SATURATION) & bright).astype(np.uint8) * 255


@dataclass
class _LineGroup:
    """Collinear Hough segments: unit normal, offset (normal . p = offset), segments, total length."""

    normal: np.ndarray
    offset: float
    segments: list
    length: float

    def y_extent(self) -> float:
        ys = [y for s in self.segments for y in (s[1], s[3])]
        return max(ys) - min(ys)

    def x_at(self, y: float) -> float:
        return (self.offset - self.normal[1] * y) / self.normal[0]


def _line_groups(mask: np.ndarray) -> list[_LineGroup]:
    """Long straight segments of the marking mask, merged into lines."""
    found = cv2.HoughLinesP(mask, 1, np.pi / 720, threshold=100, minLineLength=100, maxLineGap=15)
    groups: list[_LineGroup] = []
    for seg in ([] if found is None else found.reshape(-1, 4).astype(np.float64)):
        x1, y1, x2, y2 = seg
        d = np.array([x2 - x1, y2 - y1])
        length = float(np.linalg.norm(d))
        normal = np.array([-d[1], d[0]]) / length
        if normal[1] < 0 or (normal[1] == 0 and normal[0] < 0):
            normal = -normal
        offset = float(normal @ (x1, y1))
        for g in groups:
            if g.normal @ normal > np.cos(np.radians(2)) and abs(g.offset - offset) < 6:
                g.segments.append(seg)
                g.length += length
                break
        else:
            groups.append(_LineGroup(normal, offset, [seg], length))
    return groups


def _refine(group: _LineGroup, pixels: np.ndarray) -> tuple[np.ndarray, float]:
    """Least-squares line through the marking pixels near a Hough line: (normal, offset)."""
    near = pixels[np.abs(pixels @ group.normal - group.offset) < LINE_REFINE_PX]
    vx, vy, x0, y0 = cv2.fitLine(near.astype(np.float32), cv2.DIST_HUBER, 0, 0.01, 0.01).ravel()
    normal = np.array([-vy, vx], dtype=np.float64)
    return normal, float(normal @ (x0, y0))


def _intersect(a: tuple[np.ndarray, float], b: tuple[np.ndarray, float]) -> np.ndarray:
    """Intersection point of two lines given as (normal, offset)."""
    return np.linalg.solve(np.array([a[0], b[0]]), np.array([a[1], b[1]]))
