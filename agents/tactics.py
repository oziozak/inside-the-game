"""Tactical facts: frame observations + detected events + team sheet in, tactics.json out. Code only, no LLM.

Inputs are the vision AI's output and the team sheet, nothing else: observations.jsonl (what the video
stage saw, anonymous tracks in pitch meters), the detected events and match_info.json. It never opens a
truth/ folder or simulator tracking (tests/test_vision_pipeline.py checks the files it opens).

- **Who is who**: the vision rules (vision/rules.py) are replayed over the observations, so each track is
  named by the same lineup assignment that named the events' players. A track's line (defence, midfield,
  attack) is its roster player's team-sheet position. Unnamed tracks and goalkeepers are left out.
- **Who has the ball**: per frame, from the same replay (`EventRules.team_with_ball`): the team of the track
  in possession, or while a kick is in flight the kicker's. Frames with the ball dead (out of play, in the
  net) or loose are in neither team's possession and count only for "all".
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

from agents.stats import PASS_TYPES, PITCH_X, PITCH_Y, attacks_positive_x, forward_x, other, zone
from vision.lineup import SLOT
from vision.observation import FrameObservation, read_observations
from vision.rules import EventRules

LINE = {"RB": "defence", "CB": "defence", "LB": "defence", "RWB": "defence", "LWB": "defence",
        "DM": "midfield", "CM": "midfield", "AM": "midfield", "RM": "midfield", "LM": "midfield",
        "RW": "attack", "LW": "attack", "ST": "attack", "CF": "attack"}
LINE_RANK = {"defence": 0, "midfield": 1, "attack": 2}
PHASES = ("all", "in_possession", "out_of_possession")
THIRD = {"final_third": "high", "middle_third": "mid", "defensive_third": "low"}   # where a regain is: pressing height
FINAL_THIRD_M = 70.0            # depth where the final third starts (agents.stats.zone)
FLANKS = ("left", "centre", "right")
# A long ball is a pass longer than this (#67). Not the event subtype "long", which splits at 25 m
# (schemas/README.md): that one says how a pass was played, this one how direct a team plays.
LONG_BALL_M = 30.0
OPEN_PLAY = {"pass", "shot"}    # events that show a team had the ball in play (restarts follow a dead ball)
HALFWAY_M = PITCH_X / 2
# A completed pass is progressive when it moves the ball this far toward the opponent goal line: within the
# own half, from the own half into the opponent's, within the opponent's half (Wyscout's thresholds).
PROGRESSIVE_M = {("own", "own"): 30.0, ("own", "opp"): 15.0, ("opp", "own"): 15.0, ("opp", "opp"): 10.0}
SIDES = ("home", "away")


def regains(events: list[dict]) -> list[tuple[dict, list[str]]]:
    """Ball regains in play, as (the event where the team has the ball back, cited event ids): every
    possession change, and a failed pass whose next event (same period) is the other team playing the ball in
    open play (a restart after the ball went out is not a regain)."""
    out = []
    for i, e in enumerate(events):
        if e["type"] == "possession_change" and e.get("start"):
            out.append((e, [e["id"]]))
        nxt = events[i + 1] if i + 1 < len(events) else None
        if (e["type"] in PASS_TYPES and e.get("success") is False and nxt is not None
                and nxt.get("period") == e.get("period") and nxt.get("team") == other(e["team"])
                and nxt["type"] in OPEN_PLAY and nxt.get("start")):
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


def _evidence(frames: list[int]) -> dict:
    """The frames a fact came from: [first, last] runs, and how many."""
    return {"frames": _ranges(frames), "n_frames": len(frames)}


@dataclass
class _FrameFact:
    """One per-frame measurement collected over frames: its values and which frames gave them."""

    values: list[float] = field(default_factory=list)
    frames: list[int] = field(default_factory=list)

    def add(self, frame: int, value: float) -> None:
        self.values.append(value)
        self.frames.append(frame)

    def result(self) -> dict:
        """The fact: the mean value (m, 1 decimal; None with no frames) and its frames."""
        return {"value": round(statistics.fmean(self.values), 1) if self.values else None,
                **_evidence(self.frames)}


def sheet_lines(players: list[dict], formation: str | None) -> list[list[int]]:
    """The team sheet's lines, back to front: the outfield starters ordered by line (defence, midfield,
    attack) and, within one, by how far forward their position stands (vision.lineup.SLOT), cut by the
    formation's counts (a 4-2-3-1's AM and wingers make its third line). By line alone when the counts
    do not add up to the starters."""
    order = sorted((p for p in players if p["starter"] and p["pos"] in LINE),
                   key=lambda p: (LINE_RANK[LINE[p["pos"]]], SLOT[p["pos"]][0], p["id"]))
    counts = [int(n) for n in formation.split("-")] if formation else []
    if sum(counts) != len(order):
        counts = [sum(1 for p in order if LINE[p["pos"]] == line) for line in LINE_RANK]
    cuts = list(itertools.accumulate(counts, initial=0))
    return [[p["id"] for p in order[a:b]] for a, b in zip(cuts, cuts[1:]) if b > a]


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


@dataclass
class _Seen:
    """One player's position sums over the frames they were seen in."""

    frames: int = 0
    depth: float = 0.0
    y: float = 0.0


class _Shape:
    """Where each named outfield player stood on average, over frames."""

    def __init__(self):
        self.seen: dict[int, _Seen] = {}                # roster id -> sums
        self.frames: list[int] = []

    def add(self, frame: int, players: dict[int, tuple[float, float]]) -> None:
        for pid, (d, y) in players.items():
            s = self.seen.setdefault(pid, _Seen())
            s.frames += 1
            s.depth += d
            s.y += y
        self.frames.append(frame)

    def result(self, formation: str | None, lines: list[list[int]]) -> dict:
        """The actual formation next to the team sheet's, the sheet's lines, and each player's mean
        position (over the frames they were seen in, `n_frames`, of the fact's frames)."""
        where = {pid: (s.depth / s.frames, s.y / s.frames) for pid, s in self.seen.items()}
        actual = actual_formation({pid: d for pid, (d, _) in where.items()}, len(lines))
        out_lines = []
        for line in lines:
            ids = [pid for pid in line if pid in where]
            if ids:
                ys = [where[p][1] for p in ids]
                out_lines.append({"players": ids, "depth_m": round(statistics.fmean(where[p][0] for p in ids), 1),
                                  "width_m": round(max(ys) - min(ys), 1)})
        return {"value": "-".join(str(len(g)) for g in actual) or None, "team_sheet": formation,
                "actual_lines": actual, "lines": out_lines,
                "players": {str(pid): {"depth_m": round(d, 1), "y_m": round(y, 1),
                                       "n_frames": self.seen[pid].frames} for pid, (d, y) in sorted(where.items())},
                **_evidence(self.frames)}


class _Team:
    """Everything collected for one team in one segment."""

    def __init__(self, side: str, line_of: dict[int, str], info: dict):
        self.side, self.formation, self.line_of, self.info = side, info[side].get("formation"), line_of, info
        self.lines = sheet_lines(info[side]["players"], self.formation)
        self.passes: list[dict] = []                    # this team's passes with a start and an end
        self.regains: dict[str, list[str]] = {third: [] for third in THIRD.values()}     # cited ids per third
        self.regain_n = {third: 0 for third in THIRD.values()}
        self.shape = {ph: _Shape() for ph in PHASES}
        self.line = {ph: _FrameFact() for ph in PHASES}
        self.compact = {ph: _FrameFact() for ph in PHASES}
        self.width = _FrameFact()                       # in possession
        self.ball_flank: dict[str, list[int]] = {where: [] for where in FLANKS}   # in possession, ball in the final third

    def frame(self, f: FrameObservation, players: dict[int, tuple[float, float]], phase: str | None) -> None:
        """Add one frame: `players` maps each named outfield player to (depth, y) in the team frame,
        `phase` is whether the team has the ball (None: neither team has it)."""
        if phase == "in_possession" and f.ball_visible and f.ball is not None:
            d, y = _team_frame(f.ball.pos, self.side, f.period, self.info)
            if d >= FINAL_THIRD_M:
                self.ball_flank[_flank(y)].append(f.frame)
        if not players:
            return
        if phase == "in_possession":
            self.width.add(f.frame, max(y for _, y in players.values()) - min(y for _, y in players.values()))
        depths = {line: [players[pid][0] for pid in players if self.line_of.get(pid) == line]
                  for line in ("defence", "attack")}
        back = statistics.fmean(depths["defence"]) if depths["defence"] else None
        front = statistics.fmean(depths["attack"]) if depths["attack"] else None
        for ph in ("all", phase):
            if ph is None:
                continue
            self.shape[ph].add(f.frame, players)
            if back is not None:
                self.line[ph].add(f.frame, back)
                if front is not None:
                    self.compact[ph].add(f.frame, front - back)

    def event(self, e: dict) -> None:
        """Add one of this team's events."""
        if e["type"] in PASS_TYPES and e.get("start") and e.get("end"):
            self.passes.append(e)

    def _flank_facts(self) -> dict:
        """Left / centre / right shares in the final third: of the passes into or within it (where they
        end), and of the in-possession frames with the ball in it."""
        into = [e for e in self.passes if self._depth(e, "end") >= FINAL_THIRD_M]
        ids: dict[str, list[str]] = {where: [] for where in FLANKS}
        for e in into:
            ids[_flank(_team_frame(e["end"], self.side, e.get("period", 1), self.info)[1])].append(e["id"])
        frames = {where: len(fs) for where, fs in self.ball_flank.items()}
        return {"passes": {"value_pct": {w: _pct(len(i), len(into)) for w, i in ids.items()},
                           "count": {w: len(i) for w, i in ids.items()}, "event_ids": ids},
                "possession": {"value_pct": {w: _pct(n, sum(frames.values())) for w, n in frames.items()},
                               "n_frames": frames,
                               "frames": {w: _ranges(fs) for w, fs in self.ball_flank.items()}}}

    def regain(self, e: dict, event_ids: list[str]) -> None:
        """Add a regain: this team has the ball back at event `e`."""
        third = THIRD[zone(self._depth(e, "start"))]
        self.regains[third] += event_ids
        self.regain_n[third] += 1

    def _depth(self, e: dict, point: str) -> float:
        """Meters from this team's goal line of an event's `start` or `end`."""
        return forward_x(e[point][0], e["team"], e.get("period", 1), self.info)

    def _pass_facts(self) -> dict:
        """Long-ball share of all passes, progressive passes among the completed ones."""
        long_ = [e for e in self.passes if math.dist(e["start"][:2], e["end"][:2]) > LONG_BALL_M]
        done = [e for e in self.passes if e.get("success")]
        half = {True: "opp", False: "own"}
        progressive = [e for e in done if self._depth(e, "end") - self._depth(e, "start") >= PROGRESSIVE_M[
            half[self._depth(e, "start") >= HALFWAY_M], half[self._depth(e, "end") >= HALFWAY_M]]]
        return {"long_balls": {"value_pct": _pct(len(long_), len(self.passes)), "count": len(long_),
                               "of": len(self.passes), "event_ids": [e["id"] for e in self.passes],
                               "long_event_ids": [e["id"] for e in long_]},
                "progressive_passes": {"value": len(progressive), "of": len(done),
                                       "share_pct": _pct(len(progressive), len(done)),
                                       "event_ids": [e["id"] for e in done],
                                       "progressive_event_ids": [e["id"] for e in progressive]}}

    def result(self) -> dict:
        """The team's facts for its segment."""
        return {**self._pass_facts(),
                "regains": {"value": self.regain_n, "event_ids": self.regains},
                "attacking_width_m": self.width.result(),
                "final_third_flanks": self._flank_facts(),
                "shape": {ph: self.shape[ph].result(self.formation, self.lines) for ph in PHASES},
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
        """Whether time `t` is in this segment."""
        return self.start <= t < self.end

    def result(self) -> dict:
        """The segment's tactics.json object."""
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
    rules = EventRules(team_sheet)
    for f in frames:
        rules.push(f)
        with_ball = rules.team_with_ball()
        named: dict[str, dict[int, tuple[float, float]]] = {side: {} for side in SIDES}
        for p in f.players:
            pid = rules.lineup.player(p.track_id)
            if pid in outfield and not p.goalkeeper and pid not in named[p.team]:
                named[p.team][pid] = _team_frame(p.pos, p.team, f.period, team_sheet)
        for seg in segments:
            if seg.holds(f.t):
                for side in SIDES:
                    phase = None if with_ball is None else ("in_possession" if with_ball == side
                                                            else "out_of_possession")
                    seg.teams[side].frame(f, named[side], phase)
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
