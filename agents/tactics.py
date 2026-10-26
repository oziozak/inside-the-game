"""Tactical facts: frame observations + detected events + team sheet in, tactics.json out. Code only, no LLM.

Inputs are the vision AI's output and the team sheet, nothing else: observations.jsonl (what the video
stage saw, anonymous tracks in pitch meters), the detected events and match_info.json. It never opens a
truth/ folder or simulator tracking (tests/test_vision_pipeline.py checks the files it opens).

- **Who is who**: the vision rules (vision/rules.py) are replayed over the observations, so each track is
  named by the same lineup assignment that named the events' players. A track's line (defence, midfield,
  attack) is its roster player's team-sheet position. Unnamed tracks and goalkeepers are left out.
- **Who has the ball**: possession spells from the detected events. After a completed pass (or kickoff) or a
  possession change the team that has the ball keeps it until the next event; after a failed pass, a shot or
  anything else, the next event says who had it (its team, or for a possession change the team that lost
  it). Frames in neither team's spell count only for "all".
- **Team frame**: depth is meters from the team's own goal line, y as the team sees it attacking (right
  side y < 34), so both halves and both teams read the same way.

Usage:
    python -m agents.tactics OBSERVATIONS.jsonl --events EVENTS --match-info MI --out tactics.json
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from agents.stats import PASS_TYPES, PITCH_X, PITCH_Y, attacks_positive_x, forward_x, other, zone
from vision.observation import FrameObservation, read_observations
from vision.rules import EventRules

LINE = {"RB": "defence", "CB": "defence", "LB": "defence", "RWB": "defence", "LWB": "defence",
        "DM": "midfield", "CM": "midfield", "AM": "midfield", "RM": "midfield", "LM": "midfield",
        "RW": "attack", "LW": "attack", "ST": "attack", "CF": "attack"}
PHASES = ("all", "in_possession", "out_of_possession")
THIRD = {"final_third": "high", "middle_third": "mid", "defensive_third": "low"}   # where a regain is: pressing height
FINAL_THIRD_M = 70.0            # depth where the final third starts (agents.stats.zone)
FLANKS = ("left", "centre", "right")
LONG_BALL_M = 30.0              # a pass longer than this is a long ball
HALFWAY_M = PITCH_X / 2
# A completed pass is progressive when it moves the ball this far toward the opponent goal line: within the
# own half, from the own half into the opponent's, within the opponent's half (Wyscout's thresholds).
PROGRESSIVE_M = {("own", "own"): 30.0, ("own", "opp"): 15.0, ("opp", "own"): 15.0, ("opp", "opp"): 10.0}
SIDES = ("home", "away")


@dataclass
class _Spell:
    """A team in possession from t0 until t1, as the events `event_ids` say."""

    t0: float
    t1: float
    period: int
    team: str
    event_ids: list[str]


def _owner_after(e: dict) -> str | None:
    """The team that has the ball right after event `e`, if the event says so."""
    if e["type"] in PASS_TYPES:
        return e["team"] if e.get("success") else None
    return e["team"] if e["type"] == "possession_change" else None


def _owner_before(e: dict) -> str | None:
    """The team that had the ball just before event `e`, if the event says so."""
    if e["type"] in PASS_TYPES or e["type"] == "shot":
        return e["team"]
    return other(e["team"]) if e["type"] == "possession_change" else None


def possession_spells(events: list[dict]) -> list[_Spell]:
    """Possession spells between consecutive events of the same period (see the module docstring)."""
    spells = []
    for a, b in zip(events, events[1:]):
        if a.get("period") != b.get("period"):
            continue
        team, ids = _owner_after(a), [a["id"]]
        if team is None:
            team, ids = _owner_before(b), [b["id"]]
        elif _owner_before(b) == team:
            ids.append(b["id"])
        if team in SIDES:
            spells.append(_Spell(a["t"], b["t"], a["period"], team, ids))
    return spells


def regains(events: list[dict]) -> list[tuple[dict, list[str]]]:
    """Ball regains in play, as (the event where the team has the ball back, cited event ids): every
    possession change, and a failed pass whose next event (same period) is the other team playing the ball."""
    out = []
    for i, e in enumerate(events):
        if e["type"] == "possession_change" and e.get("start"):
            out.append((e, [e["id"]]))
        nxt = events[i + 1] if i + 1 < len(events) else None
        if (e["type"] in PASS_TYPES and e.get("success") is False and nxt is not None
                and nxt.get("period") == e.get("period") and nxt.get("team") == other(e["team"])
                and (nxt["type"] in PASS_TYPES or nxt["type"] == "shot") and nxt.get("start")):
            out.append((nxt, [e["id"], nxt["id"]]))
    return out


def _flank(y: float) -> str:
    """The flank of a y in the team frame (attacking toward x = length, the right side y < width / 3)."""
    return "right" if y < PITCH_Y / 3 else ("left" if y > 2 * PITCH_Y / 3 else "centre")


def _pct(part: int, whole: int) -> float | None:
    """`part` of `whole` in percent, 1 decimal (None of nothing)."""
    return round(100 * part / whole, 1) if whole else None


def _ranges(frames: list[int]) -> list[list[int]]:
    """Sorted frame indices as [first, last] runs of consecutive frames."""
    out: list[list[int]] = []
    for f in frames:
        if out and f == out[-1][1] + 1:
            out[-1][1] = f
        else:
            out.append([f, f])
    return out


@dataclass
class _FrameFact:
    """One per-frame measurement collected over frames: its values and which frames gave them."""

    values: list[float] = field(default_factory=list)
    frames: list[int] = field(default_factory=list)
    event_ids: set[str] = field(default_factory=set)

    def add(self, frame: int, value: float, event_ids: Iterable[str] = ()) -> None:
        self.values.append(value)
        self.frames.append(frame)
        self.event_ids.update(event_ids)

    def result(self) -> dict:
        """The fact: the mean value (m, 1 decimal; None with no frames), its frames and cited events."""
        out = {"value": round(statistics.fmean(self.values), 1) if self.values else None,
               "frames": _ranges(self.frames), "n_frames": len(self.frames)}
        if self.event_ids:
            out["event_ids"] = sorted(self.event_ids)
        return out


def actual_formation(depths: dict[int, float], n_lines: int) -> list[list[int]]:
    """Players split into `n_lines` lines, back to front, by their mean depth: the split with the least
    squared spread around each line's mean (natural breaks). Empty with fewer players than lines."""
    order = sorted(depths, key=lambda pid: (depths[pid], pid))
    if n_lines < 1 or len(order) < n_lines:
        return []

    def spread(group: list[int]) -> float:
        mean = statistics.fmean(depths[pid] for pid in group)
        return sum((depths[pid] - mean) ** 2 for pid in group)

    best = min(itertools.combinations(range(1, len(order)), n_lines - 1),
               key=lambda cuts: sum(spread(order[a:b]) for a, b in zip((0, *cuts), (*cuts, len(order)))))
    return [order[a:b] for a, b in zip((0, *best), (*best, len(order)))]


class _Shape:
    """Where each named outfield player stood on average, over frames."""

    def __init__(self):
        self.sums: dict[int, list[float]] = {}            # roster id -> [frames, depth sum, y sum]
        self.frames: list[int] = []
        self.event_ids: set[str] = set()

    def add(self, frame: int, players: dict[int, tuple[float, float]], event_ids: Iterable[str]) -> None:
        for pid, (d, y) in players.items():
            s = self.sums.setdefault(pid, [0, 0.0, 0.0])
            s[0] += 1
            s[1] += d
            s[2] += y
        self.frames.append(frame)
        self.event_ids.update(event_ids)

    def result(self, formation: str | None, line_of: dict[int, str]) -> dict:
        """The actual formation next to the team sheet's, its lines, and each player's mean position."""
        where = {pid: (d / n, y / n) for pid, (n, d, y) in self.sums.items()}
        n_lines = len(formation.split("-")) if formation else 3
        actual = actual_formation({pid: d for pid, (d, _) in where.items()}, n_lines)
        lines = {}
        for line in ("defence", "midfield", "attack"):
            ids = sorted(pid for pid in where if line_of.get(pid) == line)
            if ids:
                lines[line] = {"players": ids, "depth_m": round(statistics.fmean(where[p][0] for p in ids), 1),
                               "width_m": round(max(where[p][1] for p in ids) - min(where[p][1] for p in ids), 1)}
        out = {"value": "-".join(str(len(g)) for g in actual) or None, "team_sheet": formation,
               "actual_lines": actual, "lines": lines,
               "players": {str(pid): {"depth_m": round(d, 1), "y_m": round(y, 1)}
                           for pid, (d, y) in sorted(where.items())},
               "frames": _ranges(self.frames), "n_frames": len(self.frames)}
        if self.event_ids:
            out["event_ids"] = sorted(self.event_ids)
        return out


class _Team:
    """Everything collected for one team in one segment."""

    def __init__(self, side: str, line_of: dict[int, str], info: dict):
        self.side, self.formation, self.line_of, self.info = side, info[side].get("formation"), line_of, info
        self.passes: list[dict] = []                    # this team's passes with a start and an end
        self.regains: dict[str, list[str]] = {third: [] for third in THIRD.values()}     # cited ids per third
        self.regain_n = {third: 0 for third in THIRD.values()}
        self.shape = {ph: _Shape() for ph in PHASES}
        self.line = {ph: _FrameFact() for ph in PHASES}
        self.compact = {ph: _FrameFact() for ph in PHASES}
        self.width = _FrameFact()                       # in possession
        self.ball_flank = {where: [] for where in FLANKS}    # in-possession frames, ball in the final third
        self.ball_flank_ids: set[str] = set()

    def frame(self, f: FrameObservation, players: dict[int, tuple[float, float]], phase: str | None,
              spell: _Spell | None) -> None:
        """Add one frame: `players` maps each named outfield player to (depth, y) in the team frame.
        In- and out-of-possession facts cite the events of the possession spell the frame is in."""
        if phase == "in_possession" and f.ball_visible and f.ball is not None:
            d, y = _team_frame(f.ball.pos, self.side, f.period, self.info)
            if d >= FINAL_THIRD_M:
                self.ball_flank[_flank(y)].append(f.frame)
                self.ball_flank_ids.update(spell.event_ids)
        if not players:
            return
        if phase == "in_possession":
            self.width.add(f.frame, max(y for _, y in players.values()) - min(y for _, y in players.values()),
                           spell.event_ids)
        depths = {line: [players[pid][0] for pid in players if self.line_of.get(pid) == line]
                  for line in ("defence", "attack")}
        back = statistics.fmean(depths["defence"]) if depths["defence"] else None
        front = statistics.fmean(depths["attack"]) if depths["attack"] else None
        for ph, ids in (("all", ()), (phase, spell.event_ids if spell else ())):
            if ph is None:
                continue
            self.shape[ph].add(f.frame, players, ids)
            if back is not None:
                self.line[ph].add(f.frame, back, ids)
                if front is not None:
                    self.compact[ph].add(f.frame, front - back, ids)

    def event(self, e: dict) -> None:
        """Add one of this team's events."""
        if e["type"] in PASS_TYPES and e.get("start") and e.get("end"):
            self.passes.append(e)

    def _flank_facts(self) -> dict:
        """Left / centre / right shares in the final third: of the passes into or within it (where they
        end), and of the in-possession frames with the ball in it."""
        into = [e for e in self.passes if self._depth(e, "end") >= FINAL_THIRD_M]
        count = {where: 0 for where in FLANKS}
        for e in into:
            count[_flank(_team_frame(e["end"], self.side, e.get("period", 1), self.info)[1])] += 1
        frames = {where: len(fs) for where, fs in self.ball_flank.items()}
        return {"passes": {"value_pct": {w: _pct(n, len(into)) for w, n in count.items()}, "count": count,
                           "event_ids": [e["id"] for e in into]},
                "possession": {"value_pct": {w: _pct(n, sum(frames.values())) for w, n in frames.items()},
                               "n_frames": frames,
                               "frames": {w: _ranges(fs) for w, fs in self.ball_flank.items()},
                               "event_ids": sorted(self.ball_flank_ids)}}

    def regain(self, e: dict, event_ids: list[str]) -> None:
        """Add a regain: this team has the ball back at event `e`."""
        third = THIRD[zone(self._depth(e, "start"))]
        self.regains[third] += event_ids
        self.regain_n[third] += 1

    def _depth(self, e: dict, point: str) -> float:
        return forward_x(e[point][0], e["team"], e.get("period", 1), self.info)

    def _pass_facts(self) -> dict:
        """Long-ball share of all passes, progressive passes among the completed ones."""
        long_ = [e for e in self.passes if math.dist(e["start"][:2], e["end"][:2]) > LONG_BALL_M]
        done = [e for e in self.passes if e.get("success")]
        half = {True: "opp", False: "own"}
        progressive = [e for e in done if self._depth(e, "end") - self._depth(e, "start") >= PROGRESSIVE_M[
            half[self._depth(e, "start") >= HALFWAY_M], half[self._depth(e, "end") >= HALFWAY_M]]]
        return {"long_balls": {"value_pct": _pct(len(long_), len(self.passes)), "count": len(long_),
                               "of": len(self.passes), "event_ids": [e["id"] for e in self.passes]},
                "progressive_passes": {"value": len(progressive), "of": len(done),
                                       "share_pct": _pct(len(progressive), len(done)),
                                       "event_ids": [e["id"] for e in done]}}

    def result(self) -> dict:
        return {**self._pass_facts(),
                "regains": {"value": self.regain_n, "event_ids": self.regains},
                "attacking_width_m": self.width.result(),
                "final_third_flanks": self._flank_facts(),
                "shape": {ph: self.shape[ph].result(self.formation, self.line_of) for ph in PHASES},
                "defensive_line_m": {ph: self.line[ph].result() for ph in PHASES},
                "compactness_m": {ph: self.compact[ph].result() for ph in PHASES}}


@dataclass
class _Segment:
    """A stretch of the clip: [start, end), with the event that splits the clip, if any."""

    id: str
    start: float
    end: float
    split_by: str | None = None
    teams: dict[str, _Team] = field(default_factory=dict)

    def holds(self, t: float) -> bool:
        return self.start <= t < self.end

    def result(self) -> dict:
        return {"id": self.id, "start": round(self.start, 2), "end": round(self.end, 2), "split_by": self.split_by,
                "teams": {side: self.teams[side].result() for side in SIDES}}


def _segments(frames: list[FrameObservation], events: list[dict], team_sheet: dict) -> list[_Segment]:
    """The whole clip, then before and after each goal or red card."""
    times = [f.t for f in frames] + [e["t"] for e in events]
    start, end = (min(times), max(times) + 1e-6) if times else (0.0, 0.0)
    out = [_Segment("whole", start, end)]
    for e in events:
        if e["type"] in ("goal", "red_card"):
            out += [_Segment(f"before_{e['id']}", start, e["t"], e["id"]),
                    _Segment(f"after_{e['id']}", e["t"], end, e["id"])]
    line_of = {p["id"]: LINE.get(p["pos"]) for side in SIDES for p in team_sheet[side]["players"]}
    for seg in out:
        seg.teams = {side: _Team(side, line_of, team_sheet) for side in SIDES}
        for e in events:
            if seg.holds(e["t"]) and e.get("team") in SIDES:
                seg.teams[e["team"]].event(e)
        for e, ids in regains(events):
            if seg.holds(e["t"]) and e.get("team") in SIDES:
                seg.teams[e["team"]].regain(e, ids)
    return out


def _team_frame(pos: tuple[float, float], side: str, period: int, info: dict) -> tuple[float, float]:
    """(depth from own goal, y as the team sees it attacking)."""
    if attacks_positive_x(side, period, info):
        return pos[0], pos[1]
    return PITCH_X - pos[0], PITCH_Y - pos[1]


def tactics(frames: list[FrameObservation], events: list[dict], team_sheet: dict) -> dict:
    """Tactical facts per team and segment (see the module docstring); the tactics.json object."""
    events = sorted(events, key=lambda e: e["t"])
    outfield = {p["id"] for side in SIDES for p in team_sheet[side]["players"] if p["pos"] in LINE}
    segments = _segments(frames, events, team_sheet)
    spells = possession_spells(events)
    rules = EventRules(team_sheet)
    k = 0
    for f in frames:
        rules.push(f)
        while k < len(spells) and (spells[k].period, spells[k].t1) <= (f.period, f.t):
            k += 1
        spell = spells[k] if k < len(spells) and spells[k].period == f.period and spells[k].t0 <= f.t else None
        named: dict[str, dict[int, tuple[float, float]]] = {side: {} for side in SIDES}
        for p in f.players:
            pid = rules.lineup.player(p.track_id)
            if pid in outfield and not p.goalkeeper and pid not in named[p.team]:
                named[p.team][pid] = _team_frame(p.pos, p.team, f.period, team_sheet)
        for seg in segments:
            if seg.holds(f.t):
                for side in SIDES:
                    phase = None if spell is None else ("in_possession" if spell.team == side
                                                        else "out_of_possession")
                    seg.teams[side].frame(f, named[side], phase, spell)
    return {"match_id": team_sheet.get("match_id"), "n_frames": len(frames),
            "segments": [seg.result() for seg in segments]}


def main(argv: list[str] | None = None) -> int:
    """Compute the tactical facts of one clip and write tactics.json."""
    ap = argparse.ArgumentParser(prog="python -m agents.tactics", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("observations", type=Path, help="the vision AI's frame observations (JSON Lines)")
    ap.add_argument("--events", type=Path, required=True, help="the detected events (or merged events.json)")
    ap.add_argument("--match-info", type=Path, required=True, help="the team sheet")
    ap.add_argument("--out", type=Path, required=True, help="where to write tactics.json")
    args = ap.parse_args(argv)
    team_sheet = json.loads(args.match_info.read_text(encoding="utf-8"))
    events = json.loads(args.events.read_text(encoding="utf-8"))
    out = tactics(read_observations(args.observations), events, team_sheet)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"Wrote {args.out}: {len(out['segments'])} segment(s), {out['n_frames']} frames")
    return 0


if __name__ == "__main__":
    sys.exit(main())
