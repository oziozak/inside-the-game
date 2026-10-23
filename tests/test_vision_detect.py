"""Video-stage detectors on small synthetic frames: the ball finder and the pitch-line homography."""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from vision.detect import Box, KitClassifier, find_ball
from vision.pitch import calibrate

GRASS = (85, 143, 62)            # BGR, as rendered
BALL = (82, 240, 255)            # #fff052, the CV-visibility ball
KEEPER = (17, 174, 204)          # #f2c500 goalkeeper shirt as rendered (shaded): same hue family


def _frame(width=320, height=200):
    frame = np.zeros((height, width, 3), np.uint8)
    frame[:] = GRASS
    return frame


def _blob(frame, x, y, w, h, color):
    frame[y:y + h, x:x + w] = color


def test_ball_finder_rejects_keeper_shirts():
    """A yellow keeper shirt has the ball's hue. The finder keeps only blobs no
    larger than a ball (~4 px here) that are not in a player's body, so a ball
    at a player's feet still counts."""
    frame = _frame()
    _blob(frame, 40, 150, 4, 4, BALL)                 # loose ball
    keeper = Box(196, 92, 206, 110, confidence=0.6)   # detected keeper, shirt in the box's body
    _blob(frame, 198, 96, 6, 5, KEEPER)
    _blob(frame, 250, 40, 14, 8, KEEPER)              # keeper shirt with no player box: too big
    striker = Box(100, 60, 110, 78, confidence=0.6)   # ball at the striker's feet, inside the box
    _blob(frame, 106, 75, 4, 4, BALL)
    found = find_ball(frame, [keeper, striker], lambda x, y: 4.0)
    points = sorted((round(c.point[0]), round(c.point[1])) for c in found)
    assert points == [(42, 154), (108, 79)]


def test_ball_finder_ignores_grass_skin_and_white():
    frame = _frame()
    _blob(frame, 50, 50, 3, 3, (120, 160, 210))       # skin tone
    _blob(frame, 80, 50, 40, 2, (255, 255, 255))      # pitch marking
    assert find_ball(frame, [], lambda x, y: 4.0) == []


@pytest.mark.parametrize("shirt, expected", [
    ((40, 22, 165), ("home", False)),     # #c8102e shaded
    ((132, 67, 27), ("away", False)),     # #1b4d9b shaded
    ((31, 32, 32), ("home", True)),       # #1d1d1d keeper
    ((17, 174, 204), ("away", True)),     # #f2c500 keeper
])
def test_kits_from_the_team_sheet(shirt, expected):
    info = {"home": {"kit": {"shirt": "#c8102e", "goalkeeper": "#1d1d1d"}},
            "away": {"kit": {"shirt": "#1b4d9b", "goalkeeper": "#f2c500"}}}
    frame = _frame()
    _blob(frame, 100, 60, 10, 18, shirt)
    assert KitClassifier(info).classify(frame, Box(100, 60, 110, 78, confidence=0.5)) == expected


def _draw_pitch(to_image, size=(1920, 1080)):
    """A grass frame with the pitch markings drawn through a pitch -> image homography."""
    frame = np.zeros((size[1], size[0], 3), np.uint8)
    frame[:] = (60, 75, 50)
    pitch = np.array([[0, 0], [105, 0], [105, 68], [0, 68]], float)
    corners = cv2.perspectiveTransform(pitch[None], to_image)[0]
    cv2.fillConvexPoly(frame, np.round(corners).astype(np.int32), GRASS)

    def line(points):
        pts = cv2.perspectiveTransform(np.array(points, float)[None], to_image)[0]
        cv2.polylines(frame, [np.round(pts * 16).astype(np.int32)], False, (255, 255, 255), 2,
                      cv2.LINE_AA, shift=4)

    line([[0, 0], [105, 0], [105, 68], [0, 68], [0, 0]])
    line([[52.5, 0], [52.5, 68]])
    line([[52.5 + 9.15 * np.cos(a), 34 + 9.15 * np.sin(a)] for a in np.linspace(0, 2 * np.pi, 97)])
    for x, s in ((0, 1), (105, -1)):
        for depth, width in ((16.5, 40.32), (5.5, 18.32)):
            line([[x, 34 - width / 2], [x + s * depth, 34 - width / 2],
                  [x + s * depth, 34 + width / 2], [x, 34 + width / 2]])
    return frame


def test_homography_from_pitch_lines():
    """Calibrating from drawn markings recovers the pitch positions to a few centimeters."""
    image = np.array([[197.4, 871.1], [1722.6, 871.1], [1442.0, 330.7], [478.0, 330.7]])
    pitch = np.array([[0, 0], [105, 0], [105, 68], [0, 68]], float)
    to_image = cv2.getPerspectiveTransform(pitch.astype(np.float32), image.astype(np.float32))
    pitch_map = calibrate(_draw_pitch(to_image))
    grid = np.array([[x, y] for x in np.linspace(0, 105, 8) for y in np.linspace(0, 68, 6)])
    seen = cv2.perspectiveTransform(grid[None], to_image)[0]
    error = np.linalg.norm(pitch_map.to_pitch(seen) - grid, axis=1)
    assert error.max() < 0.2, error.max()


def test_calibration_fails_without_lines():
    with pytest.raises(ValueError):
        calibrate(_frame(640, 360))
