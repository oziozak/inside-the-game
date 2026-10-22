"""Frame observations: what the video stage saw in one frame, in pitch meters.

This is the contract between the two vision stages. The video stage
(pixels -> observations) writes one record per video frame as JSON Lines; the
event stage (observations -> detected events) reads them. Players are anonymous
tracks; mapping tracks to roster ids is the event stage's job.

Usage:
    python -m vision.observation FILE.jsonl [...]   # validate; exit 1 on errors
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from jsonschema import Draft202012Validator

SCHEMA = Path(__file__).with_name("frame_observation.schema.json")
_VALIDATOR = Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))


@dataclass(frozen=True)
class Ball:
    """The ball's ground projection in meters. Height is not recovered."""

    pos: tuple[float, float]
    confidence: float


@dataclass(frozen=True)
class PlayerObservation:
    """One detected player, known only by an anonymous track id (not a roster player id)."""

    track_id: int
    team: Literal["home", "away"]
    goalkeeper: bool
    pos: tuple[float, float]        # foot point, meters
    confidence: float


@dataclass(frozen=True)
class FrameObservation:
    """Everything the video stage observed in one video frame.

    `ball_visible` says whether the ball was detected in this frame. When it is
    false, `ball` may still hold a predicted position, or be None.
    """

    frame: int
    t: float
    period: int
    ball: Ball | None
    ball_visible: bool
    players: list[PlayerObservation] = field(default_factory=list)

    def to_dict(self) -> dict:
        """The serialized (JSON) form of this record."""
        return {
            "frame": self.frame,
            "t": self.t,
            "period": self.period,
            "ball": None if self.ball is None else {"pos": list(self.ball.pos),
                                                    "confidence": self.ball.confidence},
            "ball_visible": self.ball_visible,
            "players": [{"track_id": p.track_id, "team": p.team, "goalkeeper": p.goalkeeper,
                         "pos": list(p.pos), "confidence": p.confidence} for p in self.players],
        }

    @classmethod
    def from_dict(cls, d: dict) -> FrameObservation:
        """Build a record from its serialized form (assumed valid)."""
        ball = d["ball"]
        return cls(
            frame=d["frame"],
            t=d["t"],
            period=d["period"],
            ball=None if ball is None else Ball(pos=tuple(ball["pos"]), confidence=ball["confidence"]),
            ball_visible=d["ball_visible"],
            players=[PlayerObservation(track_id=p["track_id"], team=p["team"],
                                       goalkeeper=p["goalkeeper"], pos=tuple(p["pos"]),
                                       confidence=p["confidence"]) for p in d["players"]],
        )


def write_observations(path: Path, frames: list[FrameObservation]) -> None:
    """Write frame observations as JSON Lines, one frame per line."""
    with Path(path).open("w", encoding="utf-8") as f:
        for frame in frames:
            f.write(json.dumps(frame.to_dict(), separators=(",", ":")) + "\n")


def read_observations(path: Path) -> list[FrameObservation]:
    """Read a JSON Lines observations file."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [FrameObservation.from_dict(json.loads(line)) for line in lines if line.strip()]


def validate_observations(path: Path) -> list[str]:
    """Check an observations file against the schema and the cross-record rules.

    Rules beyond the schema: a visible ball has a position, track ids are
    unique within a frame, and frame indices and times strictly increase.
    Returns a list of error messages; empty means valid.
    """
    path = Path(path)
    errors: list[str] = []
    prev = None
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        where = f"{path.name} line {n}"
        try:
            record = json.loads(line)
        except json.JSONDecodeError as e:
            errors.append(f"{where}: not JSON ({e.msg})")
            continue
        schema_errors = [f"{where} at {'/'.join(str(p) for p in err.path) or '(root)'}: {err.message}"
                         for err in _VALIDATOR.iter_errors(record)]
        errors.extend(schema_errors)
        if schema_errors:
            continue
        if record["ball_visible"] and record["ball"] is None:
            errors.append(f"{where}: ball_visible is true but ball is null")
        ids = [p["track_id"] for p in record["players"]]
        for dupe in sorted({i for i in ids if ids.count(i) > 1}):
            errors.append(f"{where}: duplicate track_id {dupe}")
        if prev is not None:
            if record["frame"] <= prev["frame"]:
                errors.append(f"{where}: frame {record['frame']} does not follow frame {prev['frame']}")
            if record["t"] <= prev["t"]:
                errors.append(f"{where}: t {record['t']} does not follow t {prev['t']}")
        prev = record
    return errors


def main(argv: list[str] | None = None) -> int:
    """Validate the observations files named on the command line."""
    paths = [Path(a) for a in (sys.argv[1:] if argv is None else argv)]
    if not paths:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    errors = [e for p in paths for e in validate_observations(p)]
    for e in errors:
        print("ERROR", e)
    print(f"Checked {len(paths)} file(s): {'OK' if not errors else f'{len(errors)} error(s)'}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
