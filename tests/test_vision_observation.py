"""Frame observation contract: the JSON Lines file the video stage writes and
the event stage reads."""

from __future__ import annotations

import json

import pytest

from vision.observation import (Ball, FrameObservation, PlayerObservation, read_observations,
                                validate_observations, write_observations)


def two_frames():
    """Two consecutive frames: ball seen, then hidden behind a player."""
    return [
        FrameObservation(frame=0, t=0.0, period=1, ball=Ball(pos=(52.5, 34.0), confidence=0.91),
                         ball_visible=True, players=[
                             PlayerObservation(track_id=1, team="home", goalkeeper=False,
                                               pos=(50.0, 30.0), confidence=0.88),
                             PlayerObservation(track_id=2, team="away", goalkeeper=True,
                                               pos=(100.0, 34.0), confidence=0.75),
                         ]),
        FrameObservation(frame=1, t=0.04, period=1, ball=None, ball_visible=False, players=[
            PlayerObservation(track_id=1, team="home", goalkeeper=False, pos=(50.2, 30.1),
                              confidence=0.87),
        ]),
    ]


def test_round_trip(tmp_path):
    path = tmp_path / "observations.jsonl"
    frames = two_frames()
    write_observations(path, frames)
    assert len(path.read_text().splitlines()) == 2
    assert read_observations(path) == frames


def test_written_file_is_valid(tmp_path):
    path = tmp_path / "observations.jsonl"
    write_observations(path, two_frames())
    assert validate_observations(path) == []


def _write_lines(path, records):
    path.write_text("".join(json.dumps(r) + "\n" for r in records))


@pytest.mark.parametrize("breakage, message", [
    (lambda r: r[0]["players"][0].update(team="referee"), "team"),
    (lambda r: r[0]["players"][0].update(confidence=1.2), "confidence"),
    (lambda r: r[0]["players"][0].pop("track_id"), "track_id"),
    (lambda r: r[0].pop("ball_visible"), "ball_visible"),
    (lambda r: r[0]["ball"].update(pos=[52.5, 34.0, 0.1]), "pos"),
    (lambda r: r[0].update(ball=None), "ball_visible is true but ball is null"),
    (lambda r: r[1]["players"].append(dict(r[1]["players"][0])), "duplicate track_id 1"),
    (lambda r: r[1].update(frame=0), "frame"),
    (lambda r: r[1].update(t=0.0), "t"),
])
def test_invalid_records_are_reported(tmp_path, breakage, message):
    records = [f.to_dict() for f in two_frames()]
    breakage(records)
    path = tmp_path / "observations.jsonl"
    _write_lines(path, records)
    errors = validate_observations(path)
    assert errors and any(message in e for e in errors), errors


def test_unparsable_line_is_reported(tmp_path):
    path = tmp_path / "observations.jsonl"
    path.write_text('{"frame": 0,\n')
    assert "line 1" in validate_observations(path)[0]
