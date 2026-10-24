"""Seam 2 with noise: the event rules on observations that look like a real video stage's.

The clean simulator clips of tests/test_vision_rules.py (four seeds and
pairings, the first 15 minutes of both halves) get one harness noise variant
each (vision/harness.py, NOISE) at three levels, and are graded pooled over
the clips. The levels bracket what the video stage shows on the dev footage
(vision/README.md): foot points off by about 0.3 m, a few detections missing
per frame, tracks swapping between players who cross, two players boxed as
one, the ball hidden about 10 % of the time.

Floors (MEASURED minus MARGIN) hold precision and recall per type and
player-id accuracy at each level. Precision floors also catch a variant
making the rules invent events, such as a burst of kicks while the ball is
hidden behind a player.
"""

from __future__ import annotations

import pytest

from vision.grader import grade
from vision.harness import add_noise, observations_from_tracking
from vision.rules import detect_events

TYPES = ["kickoff", "pass", "possession_change", "shot", "goal"]

# Pooled grades measured 2026-10-24: per type (precision, recall), then
# player-id accuracy. Clean, for comparison: kickoff 1.00/1.00, pass
# 0.96/0.98, possession change 0.54/0.58, shot 0.91/0.91, goal 1.00/1.00
# (7 goals), players 0.967.
MEASURED = {
    "position": {        # offset per axis, meters (the dev footage: about 0.3)
        0.15: ((1.00, 1.00), (0.96, 0.98), (0.55, 0.59), (0.91, 0.89), (1.00, 1.00), 0.964),
        0.3: ((1.00, 1.00), (0.95, 0.98), (0.55, 0.61), (0.94, 0.89), (1.00, 1.00), 0.950),
        0.5: ((1.00, 1.00), (0.94, 0.91), (0.56, 0.54), (0.86, 0.89), (0.78, 1.00), 0.890)},
    "dropped": {         # share of player detections missing
        0.05: ((1.00, 1.00), (0.96, 0.95), (0.55, 0.53), (0.89, 0.91), (1.00, 1.00), 0.956),
        0.1: ((1.00, 1.00), (0.95, 0.93), (0.46, 0.41), (0.89, 0.91), (1.00, 1.00), 0.944),
        0.2: ((1.00, 1.00), (0.96, 0.86), (0.49, 0.38), (0.94, 0.91), (0.88, 1.00), 0.920)},
    "swaps": {           # chance two players coming within 1 m swap tracks
        0.1: ((1.00, 1.00), (0.96, 0.98), (0.53, 0.57), (0.91, 0.91), (1.00, 1.00), 0.949),
        0.3: ((1.00, 1.00), (0.96, 0.98), (0.54, 0.56), (0.91, 0.91), (1.00, 1.00), 0.940),
        0.6: ((1.00, 1.00), (0.96, 0.98), (0.51, 0.51), (0.91, 0.91), (1.00, 1.00), 0.947)},
    "merged": {          # chance two players coming within 1 m are boxed as one
        0.1: ((1.00, 1.00), (0.96, 0.98), (0.55, 0.58), (0.91, 0.91), (1.00, 1.00), 0.967),
        0.3: ((1.00, 1.00), (0.96, 0.98), (0.53, 0.59), (0.91, 0.91), (1.00, 1.00), 0.961),
        0.6: ((1.00, 1.00), (0.96, 0.98), (0.55, 0.57), (0.89, 0.91), (1.00, 1.00), 0.958)},
    "occlusion": {       # chance per frame near a player that the ball hides (0.05: about the dev footage)
        0.02: ((1.00, 1.00), (0.96, 0.97), (0.50, 0.52), (0.91, 0.91), (1.00, 1.00), 0.959),
        0.05: ((1.00, 1.00), (0.95, 0.93), (0.50, 0.44), (0.91, 0.89), (1.00, 1.00), 0.928),
        0.1: ((1.00, 0.93), (0.96, 0.88), (0.54, 0.37), (0.83, 0.69), (0.86, 0.86), 0.891)},
    "confidence": {      # lowest detection confidence
        0.8: ((1.00, 1.00), (0.96, 0.98), (0.54, 0.58), (0.91, 0.91), (1.00, 1.00), 0.967),
        0.5: ((1.00, 1.00), (0.96, 0.98), (0.54, 0.58), (0.91, 0.91), (1.00, 1.00), 0.967),
        0.2: ((1.00, 1.00), (0.96, 0.98), (0.54, 0.58), (0.91, 0.91), (1.00, 1.00), 0.967)},
}
# Floors are MEASURED minus this, so another platform's float rounding or a
# harmless rules change does not fail them: about one event for kickoffs (15)
# and goals (7), a few for the rest.
MARGIN = {"kickoff": 0.1, "pass": 0.03, "possession_change": 0.05, "shot": 0.05, "goal": 0.15,
          "players": 0.03}


@pytest.fixture(scope="module")
def clean_frames(sim_clips):
    """Clean observations of each simulator clip."""
    return [observations_from_tracking(tracking, team_sheet) for tracking, team_sheet, _ in sim_clips]


def pooled(sim_clips, frames_per_clip):
    """Detected events per clip, and per type (detected, true, matched) and
    player-id (right, total) pooled over the clips."""
    counts = {ty: [0, 0, 0] for ty in TYPES}
    right = total = 0
    events_per_clip = []
    for (_, team_sheet, truth), frames in zip(sim_clips, frames_per_clip):
        events = detect_events(frames, team_sheet)
        events_per_clip.append(events)
        report = grade(events, truth, types=TYPES)
        for ty, c in counts.items():
            v = report["per_type"][ty]
            c[0], c[1], c[2] = c[0] + v["detected"], c[1] + v["true"], c[2] + v["matched"]
        m = report["matched"]
        right += m["player_id_accuracy"] * m["count"]
        total += m["count"]
    return events_per_clip, counts, (right, total)


@pytest.mark.parametrize("variant,level", [(v, lv) for v, levels in MEASURED.items() for lv in levels])
def test_rules_hold_up_under_noise(sim_clips, clean_frames, variant, level):
    noisy = [add_noise(frames, variant, level, seed=k) for k, frames in enumerate(clean_frames)]
    events_per_clip, counts, (right, total) = pooled(sim_clips, noisy)
    *per_type, players = MEASURED[variant][level]
    for ty, (precision, recall) in zip(TYPES, per_type):
        detected, true, matched = counts[ty]
        assert true > 0, ty
        assert matched / max(1, detected) >= precision - MARGIN[ty], (ty, counts[ty])
        assert matched / true >= recall - MARGIN[ty], (ty, counts[ty])
    assert right / total >= players - MARGIN["players"], right / total
    assert all(0 < e["confidence"] < 1 for events in events_per_clip for e in events)


def test_event_confidence_follows_detection_confidence(sim_clips, clean_frames):
    """Less certain detections give less certain events, never 0 or 1."""
    means = []
    for low in (1.0, 0.6, 0.2):
        noisy = [add_noise(frames, "confidence", low, seed=k) for k, frames in enumerate(clean_frames[:1])]
        events = pooled(sim_clips[:1], noisy)[0][0]
        assert all(0 < e["confidence"] < 1 for e in events)
        means.append(sum(e["confidence"] for e in events) / len(events))
    assert means[0] > means[1] + 0.1 > means[2] + 0.2, means


def test_noise_variants_change_what_they_say(sim_clips, clean_frames):
    """Each variant does what its name says, on the first clip's first minute."""
    clean = clean_frames[0][:1500]
    n_players = sum(len(f.players) for f in clean)
    tracks = {p.track_id for f in clean for p in f.players}

    moved = add_noise(clean, "position", 0.3)
    offsets = [abs(a.pos[0] - b.pos[0]) for f, g in zip(clean, moved) for a, b in zip(f.players, g.players)]
    assert 0.15 < sum(offsets) / len(offsets) < 0.4

    dropped = add_noise(clean, "dropped", 0.1)
    missing = 1 - sum(len(f.players) for f in dropped) / n_players
    assert 0.07 < missing < 0.13
    assert {p.track_id for f in dropped for p in f.players} == tracks          # same ids when back

    swapped = add_noise(clean, "swaps", 1.0)
    # A track now follows another player: its position jumps to theirs.
    assert any(next(p.pos for p in g.players if p.track_id == a.track_id) != a.pos
               for f, g in zip(clean, swapped) for a in f.players)
    assert {p.track_id for f in swapped for p in f.players} == tracks

    merged = add_noise(clean, "merged", 1.0)
    assert sum(len(f.players) for f in merged) < n_players
    assert {p.track_id for f in merged for p in f.players} - tracks             # new ids after parting

    hidden = add_noise(clean, "occlusion", 0.1)
    assert all(f.ball is None for f in hidden if not f.ball_visible)
    assert 0.05 < sum(not f.ball_visible for f in hidden) / len(hidden) < 0.5

    unsure = add_noise(clean, "confidence", 0.5)
    assert all(0.5 <= p.confidence <= 1 for f in unsure for p in f.players)
    assert all(0.5 <= f.ball.confidence <= 1 for f in unsure)
