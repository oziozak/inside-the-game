"""Event rules: frame observations -> detected events (source: cv).

The event stage. It sees only frame observations and the team sheet
(match_info.json), frame by frame, so a live wrapper can feed it later.

- **Possession**: the track nearest a visible ball, within reach, with the
  ball moving with it (a ball flying past is not possessed: there is no ball
  height, so this stands in for "at ground level"), for a minimum number of
  frames.
- **Kick**: possession ends and the ball travels fast to where it next stops:
  where it comes to rest, the next possession, a touch (the ball suddenly
  turns or speeds up, e.g. a header or a one-touch shot), the goal line or
  out of play. Rules use the two ends of that path, never mid-flight
  positions: an airborne ball's ground projection is wrong.
- **Shot**: a fast kick near a goal, on a line into the goal mouth.
- **Pass**: any other kick in open play. Successful when the next track in
  possession is on the kicker's team. Restarts (the first kick after the ball
  went out or a goal, from a ball still for STILL_S, from the center spot or
  a corner arc) are not passes; v1 does not report them.
- **Goal**: a shot reaches the goal line between the posts with no player at
  the ball (that is a save), and comes to rest on or behind the line between
  the posts, not wide of the goal.
- **Kickoff**: the ball rests on the center spot with each team in its own
  half, then is played. At a half start the broadcast cuts straight to the
  kickoff, so the ball on the spot in the period's first frame is enough.
  Team: the track nearest the ball. Success: like a pass.
- **Possession change**: the other team takes the ball in play: off the
  holder within TACKLE_S of its last touch, without a kick (`tackle`, or
  `interception` for a goalkeeper); or cutting out a pass within INTERCEPT_S
  of it being played, or a blocked shot (`interception`). It stands once the
  winner keeps the ball WON_S or plays it on; a ball taken straight back is
  flicker, and neither change is reported.

Each kick is decided a fixed, short time after the ball lands: MIN_HOLD_FRAMES
after a reception, TOUCH_FRAMES after a touch, at most DECIDE_S after it
comes to rest, GOAL_CONFIRM_S after it reaches the goal line. A possession
change is decided WON_S after the ball was won, or with the winner's kick.
`from`/`to` are null: tracks are anonymous until lineup assignment names them.

Usage:
    python -m vision.rules OBSERVATIONS.jsonl --match-info match_info.json --out events.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from vision.observation import FrameObservation, PlayerObservation, read_observations

REACH_M = 1.5               # a track can have the ball this close to its feet ...
WITH_BALL_V = 3.0           # ... moving with it: at most this many m/s faster or slower
MIN_HOLD_FRAMES = 4         # frames with the ball before it counts as possession
LOSE_FRAMES = 3             # frames without it before the ball has left the holder
VEL_FRAMES = 2              # velocities are differences over this many frames
TOUCH_FRAMES = 3            # a touch compares the ball's velocity over this many frames each side
TOUCH_DEG = 30.0            # ... a turn of at least this many degrees
TOUCH_SPEEDUP = 1.5         # ... or a speed-up to more than this times the speed before, plus
TOUCH_SPEEDUP_V = 2.0       # ... this many m/s
MIN_KICK_M = 3.0            # a kick moves the ball at least this far ...
MIN_KICK_V = 4.0            # ... at an average ground speed of at least this (m/s)
STOP_V = 2.0                # m/s: a flying ball slower than this has come to rest
DECIDE_S = 1.0              # a ball at rest nobody has taken is decided this long after
ARRIVE_M = 0.5              # the ball has arrived when this close to where it stopped
STILL_S = 3.0               # a ball this long still before a kick: a set piece
STILL_M = 0.3               # ... moving less than this
CENTER_SPOT_M = 1.0         # a kick from this close to the center spot: a kickoff
KICKOFF_HALF_M = 1.0        # at a kickoff a track may stand this far into the other half
CORNER_M = 1.5              # a kick from this close to a corner flag: a corner
LONG_PASS_M = 25.0          # short/long split (schemas/README.md)
SHOT_MIN_KMH = 70.0
SHOT_NEAR_M = 25.0          # closer than this to the goal center ...
SHOT_MIN_KMH_NEAR = 65.0    # ... a shot needs only this speed
SHOT_MIN_KMH_TOUCH = 50.0   # for a ball redirected in flight (a header)
SHOT_RANGE_M = 45.0         # from the goal center
SHOT_MOUTH_M = 9.5          # the kick's line meets the goal line this close to the center
                            # (wider than the mouth: off-target shots are shots too)
SHOT_MIN_ANGLE_DEG = 3.0    # the goal mouth as seen from the kick (not from a corner flag)
GOAL_HALF_M = 3.66          # half the goal width
BALL_RADIUS_M = 0.11
GOAL_LINE_M = 0.1           # the ball center within this of the goal line has reached it
GOAL_REST_M = 0.3           # ... and rests in the goal this close to the line or behind it
OUT_M = 0.2                 # the ball center this far over a line is out of play
GOAL_CONFIRM_S = 0.5        # a ball at the goal line is decided this long after
SAVE_FRAMES = 3             # a track within reach this soon after the ball reaches the line: a save
INTERCEPT_S = 1.0           # a failed pass taken by an opponent within this time: an interception
TACKLE_S = 0.5              # a ball taken this soon after the other team last had it: a tackle
WON_S = 0.5                 # a possession change stands once the winner keeps the ball this long
RULE_CONFIDENCE = {"pass": 0.9, "shot": 0.8, "goal": 0.9, "kickoff": 0.9,
                   "possession_change": 0.7}


@dataclass
class _Possession:
    """A track in possession of the ball from `first` to `last` (frame times).
    `track_id` and `team` are None for an unseen kicker."""

    track_id: int | None
    team: str | None
    goalkeeper: bool
    first_t: float
    first_pos: tuple[float, float]
    last_t: float
    last_pos: tuple[float, float]
    frames: int = 1

    @classmethod
    def starting(cls, p: PlayerObservation, t: float, pos: tuple[float, float]) -> _Possession:
        """Track `p` with the ball at `pos` from time `t`."""
        return cls(p.track_id, p.team, p.goalkeeper, t, pos, t, pos)


@dataclass
class _Flight:
    """The ball after leaving a track's possession, until it next stops."""

    kicker: _Possession
    period: int
    restart: bool                       # a set piece: not reported as a pass
    redirect: bool = False              # started by a touch in flight
    kickoff: bool = False               # played from the center spot at a kickoff
    stop: tuple[float, tuple[float, float]] | None = None   # (t, pos) where it came to rest
    balls: list[tuple[float, tuple[float, float], float]] = field(default_factory=list)  # (t, pos, conf)


@dataclass
class _OnSpot:
    """The ball resting at `anchor` on the center spot since a frame, last
    still at `last_t`; `taker` is the track nearest it then."""

    anchor: tuple[float, float]
    last_t: float
    taker: PlayerObservation | None
    half_start: bool                    # on the spot since the period's first frame
    lined_up: bool = False              # each team in its own half at `last_t`


@dataclass
class _PendingChange:
    """A possession change won by `winner`, reported once it stands."""

    event: dict
    winner: _Possession


@dataclass
class _GoalWatch:
    """The ball reached a goal line between the posts at `t`, `pos`: is a
    track at it (a save), where does it come to rest, does it go out?"""

    t: float
    pos: tuple[float, float]
    period: int
    confidence: float
    frames_left: int = SAVE_FRAMES      # frames in which a track at the ball makes it a save
    saved: bool = False
    rest: tuple[float, float] | None = None
    last: tuple[float, float] | None = None
    went_out: bool = False


def _sub(a, b):
    """The vector from point b to point a."""
    return a[0] - b[0], a[1] - b[1]


def _angle_deg(u, v) -> float:
    """The angle between two vectors in degrees (0 when either is zero)."""
    nu, nv = math.hypot(*u), math.hypot(*v)
    if nu == 0 or nv == 0:
        return 0.0
    cos = (u[0] * v[0] + u[1] * v[1]) / (nu * nv)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos))))


class EventRules:
    """Frame-by-frame event rules. Feed frames in order with `push`, then call
    `finish`. Each call returns the events decided by then (without ids)."""

    def __init__(self, team_sheet: dict):
        self.match_id = team_sheet["match_id"]
        self.length, self.width = team_sheet.get("pitch", [105, 68])
        self.center_spot = (self.length / 2, self.width / 2)
        direction = team_sheet.get("kickoff_direction", {}).get("home", "left_to_right")
        self.home_right_first = direction == "left_to_right"
        self.score = {"home": 0, "away": 0}
        self._reset_period(None)

    def _reset_period(self, period: int | None) -> None:
        """Forget everything in play: a new period starts (the broadcast cuts)."""
        self.period = period
        self.dead = False                   # the ball is dead until a restart kick
        self.holder: _Possession | None = None
        self.candidate: _Possession | None = None
        self.flight: _Flight | None = None
        self.pending_goal: _GoalWatch | None = None
        self.on_spot: _OnSpot | None = None
        self.won: _PendingChange | None = None
        self.frames_in_period = 0
        self.since_held = 0                 # frames since the holder last had the ball
        self.balls: deque = deque(maxlen=int((STILL_S + 1) * 25))  # (t, pos, conf), visible ball
        self.tracks: dict[int, deque] = {}                         # track -> recent (t, pos)
        self.recent_players: deque = deque(maxlen=TOUCH_FRAMES + 1)  # (t, players) per frame

    # ---- per frame -------------------------------------------------------
    def push(self, frame: FrameObservation) -> list[dict]:
        """Process one frame; returns the events it decides."""
        if frame.period != self.period:
            self._reset_period(frame.period)
        out: list[dict] = []
        ball = frame.ball.pos if frame.ball_visible and frame.ball is not None else None
        prev_ball = self.balls[-1][:2] if self.balls else None
        if ball is not None:
            self.balls.append((frame.t, ball, frame.ball.confidence))
            if self.flight is not None:
                self.flight.balls.append((frame.t, ball, frame.ball.confidence))
        for p in frame.players:
            self.tracks.setdefault(p.track_id, deque(maxlen=VEL_FRAMES + 1)).append((frame.t, p.pos))
        self.recent_players.append((frame.t, frame.players))
        if ball is not None and not self.pending_goal:
            self._watch_center_spot(frame, ball)
        self.frames_in_period += 1

        if self.pending_goal:
            self._watch_goal(frame, ball)
            if frame.t - self.pending_goal.t > GOAL_CONFIRM_S:
                out += self._confirm_goal()
        elif ball is not None and self.flight is not None and not self.dead:
            crossing = self._goal_line_crossing(prev_ball, (frame.t, ball))
            if crossing is not None:            # decided by where it rests and who is there
                self.pending_goal = _GoalWatch(*crossing, frame.period, frame.ball.confidence)
                self._watch_goal(frame, ball)
        if self.pending_goal:
            if not self.pending_goal.saved:
                return out                      # the ball is in the net: nobody plays it
        elif ball is not None and self._out_of_play(ball):
            if self.flight is not None:
                out += self._resolve(frame.t, ball, receiver=None, went_out=True)
            # Play stopped: a possession change that has not stood yet is dropped.
            self.holder = self.candidate = self.won = None
            self.dead = True
        if self.flight is not None and not self.pending_goal:
            out += self._touch()
        f = self.flight
        if f is not None and f.stop is not None and frame.t - f.stop[0] > DECIDE_S:
            out += self._resolve(frame.t, f.stop[1], receiver=None)    # nobody took it

        possessor = self._possessor(frame, ball) if ball is not None else None
        self._update_possession(frame, ball, possessor, out)
        if self.won and self.holder is self.won.winner and self.holder.last_t - self.holder.first_t >= WON_S:
            out += self._stand_won()
        return out

    def finish(self) -> list[dict]:
        """End of input: a goal nobody took back stands; an unfinished kick and a
        possession change that has not stood yet are dropped."""
        return self._confirm_goal() if self.pending_goal else []

    # ---- possession ------------------------------------------------------
    @staticmethod
    def _velocity(history) -> tuple[float, float] | None:
        """Velocity (m/s) over the last VEL_FRAMES samples of a (t, pos, ...) history."""
        if len(history) < 2:
            return None
        (t0, a), (t1, b) = history[max(0, len(history) - 1 - VEL_FRAMES)][:2], history[-1][:2]
        if t1 <= t0:
            return None
        return (b[0] - a[0]) / (t1 - t0), (b[1] - a[1]) / (t1 - t0)

    def _ball_velocity(self) -> tuple[float, float] | None:
        """The visible ball's current velocity (m/s), or None."""
        return self._velocity(list(self.balls)[-(VEL_FRAMES + 1):])

    def _possessor(self, frame: FrameObservation, ball: tuple[float, float]):
        """The track that has the ball this frame (within reach, moving with
        it), or None."""
        p = self._nearest(frame.players, ball)
        if p is None:
            return None
        vb = self._ball_velocity()
        vp = self._velocity(self.tracks[p.track_id])
        if vb is None or vp is None or math.hypot(*_sub(vb, vp)) > WITH_BALL_V:
            return None
        return p

    @staticmethod
    def _nearest(players, ball):
        """The track nearest the ball if within reach, else None."""
        near = min(players, key=lambda p: math.dist(p.pos, ball), default=None)
        return near if near is not None and math.dist(near.pos, ball) <= REACH_M else None

    def _update_possession(self, frame, ball, possessor, out: list[dict]) -> None:
        """Advance the holder and candidate; start and resolve kicks."""
        if possessor is not None and self.holder and possessor.track_id == self.holder.track_id:
            self.holder.last_t, self.holder.last_pos = frame.t, ball
            self.holder.frames += 1
            self.since_held = 0
            self.candidate = None
            return
        if possessor is None:
            self.candidate = None
        elif self.candidate and self.candidate.track_id == possessor.track_id:
            self.candidate.last_t, self.candidate.last_pos = frame.t, ball
            self.candidate.frames += 1
        else:
            self.candidate = _Possession.starting(possessor, frame.t, ball)
        if self.holder is not None:
            self.since_held += 1
            if self.since_held >= LOSE_FRAMES:
                self._kick()
        if self.candidate is not None and self.candidate.frames >= MIN_HOLD_FRAMES:
            new, self.candidate = self.candidate, None
            if self.holder is not None:
                self._kick()
            if self.pending_goal:                       # taken at the line: a save
                g, self.pending_goal = self.pending_goal, None
                out += self._resolve(g.t, g.pos, receiver=new, goal_line=True)
                self.dead = self.dead or g.went_out
            elif self.flight is not None:
                out += self._resolve(new.first_t, new.first_pos, receiver=new)
            self.holder = new
            self.since_held = 0

    # ---- kickoffs --------------------------------------------------------
    def _watch_center_spot(self, frame: FrameObservation, ball) -> None:
        """Follow a ball resting on the center spot; when it is played fast
        with the teams lined up, a kickoff flight starts from where it rested."""
        s = self.on_spot
        if s is not None and math.dist(ball, s.anchor) > STILL_M:
            v = self._ball_velocity()
            if v is not None and math.hypot(*v) >= MIN_KICK_V and s.lined_up and s.taker:
                k = _Possession.starting(s.taker, s.last_t, s.anchor)
                # Whatever was in play before the kickoff is over.
                self.holder = self.candidate = self.on_spot = self.won = None
                self.flight = _Flight(k, self.period, restart=True, kickoff=True,
                                      balls=[b for b in self.balls if b[0] > s.last_t])
                return
            s = self.on_spot = None                     # it rolled on: look again
        if math.dist(ball, self.center_spot) > CENTER_SPOT_M:
            return
        if s is None:
            s = self.on_spot = _OnSpot(ball, frame.t, None, half_start=self.frames_in_period == 0)
        s.last_t = frame.t
        s.taker = min(frame.players, key=lambda p: math.dist(p.pos, ball), default=None)
        s.lined_up = s.half_start or self._lined_up(frame.players)

    def _lined_up(self, players) -> bool:
        """Whether every track stands in its own team's half (within KICKOFF_HALF_M)."""
        home_right = self._home_attacks_right(self.period)
        half = self.length / 2
        for p in players:
            own_left = (p.team == "home") == home_right
            if (p.pos[0] - half if own_left else half - p.pos[0]) > KICKOFF_HALF_M:
                return False
        return True

    # ---- kicks -----------------------------------------------------------
    def _kick(self) -> None:
        """The holder has lost the ball: a flight starts where it last had it."""
        k, self.holder = self.holder, None
        self.flight = _Flight(k, self.period, restart=self._restart(k.last_t, k.last_pos),
                              balls=[b for b in self.balls if b[0] > k.last_t])

    def _restart(self, t: float, pos: tuple[float, float]) -> bool:
        """Whether a kick at `t` from `pos` is a set piece: the ball is dead (out
        of play, a goal), was still for STILL_S, or sits on the center spot or
        in a corner arc."""
        recent = [p for bt, p, _ in self.balls if t - STILL_S <= bt <= t]
        still = (self.balls[0][0] <= t - STILL_S + 1e-6
                 and max(math.dist(p, pos) for p in recent) < STILL_M)
        center = math.dist(pos, self.center_spot) <= CENTER_SPOT_M
        corner = any(math.dist(pos, c) <= CORNER_M for c in self._corners())
        return self.dead or still or center or corner

    def _corners(self):
        """The four corner flags."""
        return [(x, y) for x in (0.0, float(self.length)) for y in (0.0, float(self.width))]

    def _touch(self) -> list[dict]:
        """A touch in flight: the ball turns or speeds up. It ends the flight
        there, received by the track within reach (if any), which kicks it on.
        A ball that slows to rest marks where the flight ends."""
        f = self.flight
        n = TOUCH_FRAMES
        if len(f.balls) < 2 * n + 1:
            return []
        (ta, a, _), (tm, m, _), (tb, b, _) = f.balls[-2 * n - 1], f.balls[-n - 1], f.balls[-1]
        if tm <= ta or tb <= tm:
            return []
        v_in = [c / (tm - ta) for c in _sub(m, a)]
        v_out = [c / (tb - tm) for c in _sub(b, m)]
        s_in, s_out = math.hypot(*v_in), math.hypot(*v_out)
        if f.stop is None and s_in >= MIN_KICK_V and s_out < STOP_V:
            f.stop = (tm, m)                    # it ends here, whoever takes it later
            return []
        turned = s_in >= MIN_KICK_V and _angle_deg(v_in, v_out) >= TOUCH_DEG
        sped_up = s_out > TOUCH_SPEEDUP * s_in + TOUCH_SPEEDUP_V
        if s_out < MIN_KICK_V or not (turned or sped_up):
            return []
        players = next((ps for t, ps in self.recent_players if t == tm), [])
        p = self._nearest(players, m)
        toucher = (_Possession.starting(p, tm, m) if p is not None
                   else _Possession(None, None, False, tm, m, tm, m))
        after = [s for s in f.balls if s[0] > tm]
        events = self._resolve(tm, m, receiver=toucher if p is not None else None)
        self.flight = _Flight(toucher, f.period, restart=self._restart(tm, m), redirect=True,
                              balls=after)
        return events

    def _resolve(self, t: float, pos: tuple[float, float], receiver: _Possession | None,
                 went_out: bool = False, goal_line: bool = False) -> list[dict]:
        """The flight stopped at `pos` at time `t`, or earlier where the ball
        came to rest: decide what the kick was."""
        f, self.flight = self.flight, None
        if f.stop is not None and not goal_line:
            t, pos = f.stop
        k = f.kicker
        d = math.dist(k.last_pos, pos)
        # The ball arrived when it first came within ARRIVE_M of where it stopped.
        dur = next((bt for bt, b, _ in f.balls if math.dist(b, pos) <= ARRIVE_M), t) - k.last_t
        conf = sum(c for _, _, c in f.balls) / len(f.balls) if f.balls else 1.0
        speed_kmh = d / dur * 3.6 if dur > 0 else 0.0
        base = {"match_id": self.match_id, "t": round(k.last_t, 2), "period": f.period,
                "team": k.team, "from": None, "to": None,
                "start": [round(k.last_pos[0], 2), round(k.last_pos[1], 2)],
                "end": [round(pos[0], 2), round(pos[1], 2)],
                "distance_m": round(d, 1), "speed_kmh": round(speed_kmh, 1),
                "duration_s": round(max(dur, 0.0), 2), "source": "cv"}
        if f.kickoff:                                   # reported however it ends
            self.dead = False
            success = (receiver is not None and receiver.team == k.team
                       and receiver.track_id != k.track_id)
            return [{**base, "type": "kickoff", "success": success,
                     "confidence": _confidence("kickoff", conf)}]
        if receiver is not None and receiver.track_id == k.track_id:
            return []                                   # the kicker kept it: a dribble
        if d < MIN_KICK_M or dur <= 0 or d / dur < MIN_KICK_V:
            return self._lost(k, receiver, conf)        # not a kick: lost, tackled, drifting
        was_dead, self.dead = self.dead, False
        stood = self._stand_won() if self._just_won(k) else []   # the winner played it on
        aim = self._aim(k.last_pos, pos)
        if aim is not None and speed_kmh >= self._shot_min_kmh(k.last_pos, f.redirect):
            if went_out:
                sub = "off_target"
            elif receiver is not None and not receiver.goalkeeper and not goal_line:
                sub = "blocked"
            else:
                sub = "on_target" if abs(aim - self.width / 2) <= GOAL_HALF_M else "off_target"
            team = k.team or self._attacker(self._goal_x(k.last_pos), f.period)
            if sub == "blocked" and self._turnover(k, receiver):
                self._win(receiver, "interception", conf)
            return stood + [{**base, "team": team, "type": "shot", "subtype": sub, "success": False,
                             "confidence": _confidence("shot", conf)}]
        if self._turnover(k, receiver) and not f.restart and receiver.first_t - k.last_t <= INTERCEPT_S:
            self._win(receiver, "interception", conf)   # cut out soon after it was played
        if f.restart or was_dead or k.team is None:
            return stood
        success = receiver is not None and receiver.team == k.team
        return stood + [{**base, "type": "pass", "subtype": "long" if d >= LONG_PASS_M else "short",
                         "success": success, "confidence": _confidence("pass", conf)}]

    def _lost(self, k: _Possession, receiver: _Possession | None, conf: float) -> list[dict]:
        """The ball left `k` without a kick. Taken by the other team in play,
        within TACKLE_S of k's last touch: a possession change. If k had only
        just won the ball, k's change stands unless the other team takes it
        straight back: that swing is flicker, and neither change is reported."""
        if self._just_won(k):
            if self._turnover(k, receiver):
                self.won = None
                return []
            return self._stand_won()
        if not self.dead and self._turnover(k, receiver) and receiver.first_t - k.last_t <= TACKLE_S:
            self._win(receiver, "interception" if receiver.goalkeeper else "tackle", conf)
        return []

    def _just_won(self, k: _Possession) -> bool:
        """Whether `k` won the ball in a possession change that has not stood yet."""
        return self.won is not None and self.won.winner is k

    @staticmethod
    def _turnover(kicker: _Possession, receiver: _Possession | None) -> bool:
        """Whether the ball went from a seen track of one team to the other team."""
        return (receiver is not None and kicker.team is not None and receiver.team is not None
                and receiver.team != kicker.team)

    def _win(self, winner: _Possession, subtype: str, conf: float) -> None:
        """The other team won the ball: a possession change where and when
        `winner` first had it. It stands once the winner keeps the ball for
        WON_S or plays it on (see push and _resolve)."""
        self.won = _PendingChange({"match_id": self.match_id, "t": round(winner.first_t, 2), "period": self.period,
                "type": "possession_change", "subtype": subtype, "team": winner.team,
                "from": None, "to": None,
                "start": [round(winner.first_pos[0], 2), round(winner.first_pos[1], 2)],
                "success": True, "source": "cv",
                "confidence": _confidence("possession_change", conf)}, winner)

    def _stand_won(self) -> list[dict]:
        """The pending possession change stands."""
        event, self.won = self.won.event, None
        return [event]

    def _shot_min_kmh(self, start, redirect: bool) -> float:
        """The slowest kick from `start` that counts as a shot."""
        if redirect:
            return SHOT_MIN_KMH_TOUCH
        near = math.dist(start, (self._goal_x(start), self.width / 2)) <= SHOT_NEAR_M
        return SHOT_MIN_KMH_NEAR if near else SHOT_MIN_KMH

    def _goal_x(self, pos) -> float:
        """The x of the goal line nearer a point."""
        return 0.0 if pos[0] < self.length / 2 else float(self.length)

    def _attacker(self, goal_x: float, period: int) -> str:
        """The team attacking the goal at `goal_x` in a period (from the team sheet)."""
        return "home" if (goal_x > 0) == self._home_attacks_right(period) else "away"

    def _home_attacks_right(self, period: int) -> bool:
        """Whether home attacks toward x = length in a period (from the team sheet)."""
        return self.home_right_first == (period == 1)

    def _aim(self, start, end) -> float | None:
        """Where a kick from `start` through `end` meets the nearer goal line (y),
        if it is close enough to that goal and heading into its mouth."""
        gx = self._goal_x(start)
        cy = self.width / 2
        if math.dist(start, (gx, cy)) > SHOT_RANGE_M:
            return None
        posts = (_sub((gx, cy - GOAL_HALF_M), start), _sub((gx, cy + GOAL_HALF_M), start))
        if _angle_deg(*posts) < SHOT_MIN_ANGLE_DEG:
            return None
        dx = end[0] - start[0]
        if dx == 0 or (gx - start[0]) * dx <= 0:
            return None
        y = start[1] + (gx - start[0]) * (end[1] - start[1]) / dx
        return y if abs(y - cy) <= SHOT_MOUTH_M else None

    # ---- goals and out of play -------------------------------------------
    def _out_of_play(self, ball) -> bool:
        """Whether the ball is over a touchline or goal line."""
        x, y = ball
        return x < -OUT_M or x > self.length + OUT_M or y < -OUT_M or y > self.width + OUT_M

    def _goal_line_crossing(self, prev, cur):
        """(t, pos) where the ball first reaches a goal line between the posts, or None."""
        t1, (x1, y1) = cur
        for gx in (0.0, float(self.length)):
            inward = 1 if gx == 0 else -1               # toward the pitch from this line
            if (x1 - gx) * inward > GOAL_LINE_M:
                continue                                # not at or over this goal line
            t, x, y = t1, x1, y1
            if prev is not None:
                t0, (x0, y0) = prev
                if (x0 - gx) * inward <= GOAL_LINE_M:
                    continue                            # already there last frame
                if (x1 - gx) * inward < 0:              # crossed between frames: interpolate
                    f = (gx - x0) / (x1 - x0)
                    t, x, y = t0 + f * (t1 - t0), gx, y0 + f * (y1 - y0)
            if abs(y - self.width / 2) <= GOAL_HALF_M + BALL_RADIUS_M:
                return t, (x, y)
        return None

    def _watch_goal(self, frame: FrameObservation, ball) -> None:
        """One frame of watching the ball at the goal line (see _GoalWatch)."""
        g = self.pending_goal
        if ball is None:
            return
        if g.frames_left > 0:
            g.frames_left -= 1
            g.saved = g.saved or self._nearest(frame.players, ball) is not None
        v = self._ball_velocity()
        if g.rest is None and v is not None and math.hypot(*v) < STOP_V:
            g.rest = ball
        g.went_out = g.went_out or self._out_of_play(ball)
        g.last = ball

    def _in_goal(self, pos) -> bool:
        """Whether a ball at rest is between the posts, on or behind a goal line."""
        x, y = pos
        if abs(y - self.width / 2) > GOAL_HALF_M + BALL_RADIUS_M:
            return False
        return x <= GOAL_REST_M or x >= self.length - GOAL_REST_M

    def _confirm_goal(self) -> list[dict]:
        """GOAL_CONFIRM_S after the ball reached the line: resolve the kick. A
        shot that nobody was at and that came to rest in the goal is a goal;
        play then restarts with a kickoff."""
        g, self.pending_goal = self.pending_goal, None
        in_goal = not g.saved and self._in_goal(g.rest or g.last or g.pos)
        events = self._resolve(g.t, g.pos, receiver=None, goal_line=in_goal,
                               went_out=g.went_out and not in_goal)
        shot = next((e for e in events if e["type"] == "shot"), None)
        if shot is None or not in_goal:
            self.dead = self.dead or g.went_out
            return events
        shot["success"] = True
        self.score[shot["team"]] += 1
        self.dead = True
        self.holder = self.candidate = None
        return events + [{
            "match_id": self.match_id, "t": round(g.t, 2), "period": g.period,
            "type": "goal", "team": shot["team"], "from": None, "to": None,
            "start": [round(g.pos[0], 2), round(g.pos[1], 2)],
            "success": True, "score": dict(self.score), "source": "cv",
            "confidence": _confidence("goal", g.confidence)}]


def _confidence(event_type: str, detection_confidence: float) -> float:
    """Event confidence: the rule's own certainty times the detections', in (0, 1)."""
    return round(min(0.99, max(0.01, RULE_CONFIDENCE[event_type] * detection_confidence)), 3)


def detect_events(frames: Iterable[FrameObservation], team_sheet: dict) -> list[dict]:
    """Detected events for a run of frame observations, sorted by t, ids e0001..."""
    rules = EventRules(team_sheet)
    events = [e for frame in frames for e in rules.push(frame)] + rules.finish()
    events.sort(key=lambda e: e["t"])
    return [{"id": f"e{i:04d}", **e} for i, e in enumerate(events, start=1)]


def main(argv: list[str] | None = None) -> int:
    """Detect events in one observations file and write events.json."""
    ap = argparse.ArgumentParser(prog="python -m vision.rules", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("observations", type=Path, help="frame observations (JSON Lines)")
    ap.add_argument("--match-info", type=Path, required=True, help="the team sheet")
    ap.add_argument("--out", type=Path, required=True, help="where to write events.json")
    args = ap.parse_args(argv)
    team_sheet = json.loads(args.match_info.read_text(encoding="utf-8"))
    events = detect_events(read_observations(args.observations), team_sheet)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(events, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(events)} events to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
