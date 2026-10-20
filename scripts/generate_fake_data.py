#!/usr/bin/env python3
"""Generate fake (synthetic) match data for development.

Produces files that follow the shared schemas, so every part of the project
can be built before the real simulator and vision AI exist:

    data/fake/sample_a/  short match (2 x 5 min), every event type at least once
        match_info.json, events.json, tracking.jsonl (first 60 s), overlays.json
    data/fake/sample_b/  full match (2 x 45 min) with realistic event counts
        match_info.json, events.json

With --full-tracking, complete 25 fps tracking for both samples is also
written to data/generated/ (too big for git).

How it works
------------
1. Event layer: the player on the ball repeatedly picks an action (hold,
   dribble, pass, cross, shot, clearance) with weighted dice that depend on
   where he is. Success is random too. Basic football rules handle ball out
   of play (throw-in, corner, goal kick), fouls, cards, offside, penalties,
   goals, kickoffs, substitutions and half-time.
2. Movement layer: every player has a formation slot. The whole team shifts
   with the ball, the ball carrier is pinned to the ball, and pass receivers,
   interceptors, tacklers and set-piece takers run to where the ball goes.
   Player speed is capped so nobody teleports.

Everything is seeded: the same seed always gives the same match.

Usage:
    python scripts/generate_fake_data.py                 # writes data/fake/
    python scripts/generate_fake_data.py --full-tracking # + data/generated/
    python scripts/generate_fake_data.py --seed 7 --report
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
L, W = 105.0, 68.0          # pitch length and width in meters
FPS = 25
GOAL_HALF = 3.66            # half the goal width
BALL_GROUND = 0.11          # ball center height when rolling

# --------------------------------------------------------------------------
# Teams. Slots are (x, y) in the TEAM frame: own goal at x = 0, attacking
# toward x = 105, with the ball at the center spot. Facing +x, the team's
# right side is low y.
# --------------------------------------------------------------------------
TEAMS = {
    "home": {
        "name": "Bosphorus FC", "short": "BOS", "formation": "4-3-3",
        "kit": {"shirt": "#c8102e", "shorts": "#ffffff", "goalkeeper": "#1d1d1d"},
        "starters": [
            (1, "M. Yilmaz", "GK", (4, 34)),
            (2, "C. Arslan", "RB", (30, 12)),
            (4, "B. Kaya", "CB", (24, 26)),
            (5, "O. Celik", "CB", (24, 42)),
            (3, "T. Sahin", "LB", (30, 56)),
            (6, "H. Koc", "DM", (38, 34)),
            (8, "K. Aydin", "CM", (46, 24)),
            (10, "E. Demir", "AM", (48, 44)),
            (7, "S. Polat", "RW", (60, 10)),
            (9, "A. Kurt", "ST", (62, 34)),
            (11, "Y. Erdem", "LW", (60, 58)),
        ],
        "subs": [(14, "F. Ozturk", "CM"), (17, "R. Aksoy", "RW"), (19, "D. Tekin", "ST")],
    },
    "away": {
        "name": "Thames United", "short": "THU", "formation": "4-4-2",
        "kit": {"shirt": "#1b4d9b", "shorts": "#1b4d9b", "goalkeeper": "#f2c500"},
        "starters": [
            (1, "J. Hartley", "GK", (4, 34)),
            (2, "L. Pemberton", "RB", (28, 12)),
            (5, "D. Okonkwo", "CB", (23, 27)),
            (6, "R. Whitlock", "CB", (23, 41)),
            (3, "S. Marsh", "LB", (28, 56)),
            (7, "N. Fairbairn", "RM", (46, 12)),
            (4, "T. Castell", "CM", (42, 28)),
            (8, "G. Ashby", "CM", (42, 40)),
            (11, "P. Rowntree", "LM", (46, 56)),
            (9, "C. Hollis", "ST", (60, 29)),
            (10, "M. Draycott", "ST", (60, 39)),
        ],
        "subs": [(14, "A. Penrose", "CM"), (18, "B. Kettering", "ST"), (16, "W. Thorne", "LM")],
    },
}

GROUP = {"GK": "gk", "RB": "def", "CB": "def", "LB": "def", "DM": "mid", "CM": "mid",
         "AM": "mid", "RM": "mid", "LM": "mid", "RW": "fwd", "LW": "fwd", "ST": "fwd"}
MIN_X = {"gk": 1, "def": 6, "mid": 14, "fwd": 22}     # deepest a line drops (team frame)

# Probabilities. "short" boosts rare events so a 10-minute sample covers them all.
PROFILES = {
    "full": dict(challenge=0.26, foul_given_challenge=0.33, yellow=0.12, red=0.004,
                 offside=0.06, shot_boost=1.0, subs_per_team=3),
    "short": dict(challenge=0.19, foul_given_challenge=0.50, yellow=0.40, red=0.25,
                  offside=0.30, shot_boost=2.5, subs_per_team=1),
}

ALL_TYPES = ["kickoff", "pass", "possession_change", "clearance", "throw_in", "shot",
             "free_kick", "foul", "goal_kick", "corner", "substitution", "offside",
             "yellow_card", "red_card", "goal", "half_time", "full_time"]

# Typical counts per 90 minutes, both teams combined (approximate norms).
NORMS = {"pass": (850, 1050), "possession_change": (45, 80), "clearance": (25, 55),
         "throw_in": (35, 50), "shot": (20, 30), "free_kick": (18, 30), "foul": (18, 26),
         "goal_kick": (14, 22), "corner": (8, 13), "offside": (3, 6), "goal": (1, 5)}


def other(team: str) -> str:
    return "away" if team == "home" else "home"


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


class Match:
    """Event layer: plays a match and records events plus everything the
    movement layer needs (ball path, who carries the ball, planned runs)."""

    def __init__(self, seed: int, half_len: float, profile: str, match_id: str):
        self.rng = random.Random(seed)
        self.half_len = half_len
        self.p = PROFILES[profile]
        self.match_id = match_id
        self.t = 0.0
        self.period = 1
        self.period_start = 0.0
        self.score = {"home": 0, "away": 0}
        self.events: list[dict] = []

        # Movement-layer records.
        self.ball_path: list[tuple] = []          # (t, x, y, z)
        self.carry: list[tuple] = []              # (t0, t1, pid)
        self.runs: dict[int, list] = defaultdict(list)   # pid -> [(t0, t1, x, y)]
        self.poss: list[tuple] = []               # (t, team)
        self.kickoffs: list[tuple] = []           # (t, taker)
        self.periods: list[dict] = []
        self.spans: dict[int, list] = {}          # pid -> [t_on, t_off]

        self.players: dict[int, dict] = {}
        self.on_pitch = {"home": [], "away": []}
        self.bench = {"home": [], "away": []}
        for team, cfg in TEAMS.items():
            base = 0 if team == "home" else 100
            for num, name, pos, slot in cfg["starters"]:
                pid = base + num
                self.players[pid] = dict(id=pid, number=num, name=name, pos=pos, team=team,
                                         slot=slot, group=GROUP[pos])
                self.on_pitch[team].append(pid)
                self.spans[pid] = [0.0, math.inf]
            for num, name, pos in cfg["subs"]:
                pid = base + num
                self.players[pid] = dict(id=pid, number=num, name=name, pos=pos, team=team,
                                         slot=None, group=GROUP[pos])
                self.bench[team].append(pid)

        self.yellows: Counter = Counter()
        self.carrier: int | None = None
        self.carrier_since = 0.0
        self.bx, self.by = L / 2, W / 2
        self.just_won_in_own_third = False

        # Substitution plan: (match minute, team).
        self.sub_plan = []
        for team in ("home", "away"):
            for _ in range(self.p["subs_per_team"]):
                self.sub_plan.append((self.rng.uniform(58, 82), team))
        self.sub_plan.sort()

    # ---- coordinates ------------------------------------------------------
    def dirn(self, team: str) -> int:
        """+1 if the team attacks toward x = 105 in the current period."""
        return 1 if (team == "home") == (self.period == 1) else -1

    def tw(self, team: str, x: float, y: float):
        """Team frame <-> world frame (the mapping is its own inverse)."""
        return (x, y) if self.dirn(team) == 1 else (L - x, W - y)

    def match_minute(self) -> float:
        frac = (self.t - self.period_start) / self.half_len
        return frac * 45 + (0 if self.period == 1 else 45)

    def slot_world(self, pid: int, ball, team_in_poss: str | None):
        """Where a player stands given the ball position (formation shift)."""
        pl = self.players[pid]
        team = pl["team"]
        bx, by = self.tw(team, *ball)
        sx, sy = pl["slot"]
        if pl["group"] == "gk":
            x = clamp(4 + 0.10 * (bx - 52.5), 1.5, 16)
            y = clamp(34 + 0.15 * (by - 34), 28, 40)
        else:
            push = 4 if team_in_poss == team else -4
            x = clamp(sx + 0.55 * (bx - 52.5) + push, MIN_X[pl["group"]], 100)
            y = clamp(sy + 0.30 * (by - 34), 2, 66)
        return self.tw(team, x, y)

    def possessing(self) -> str | None:
        return self.players[self.carrier]["team"] if self.carrier else None

    # ---- recording helpers -----------------------------------------------
    def bp(self, t, x, y, z=BALL_GROUND):
        self.ball_path.append((t, x, y, z))
        self.bx, self.by = x, y

    def flight(self, t0, t1, a, b, peak):
        """Ball flight from a to b with a parabolic height profile."""
        n = 6
        for i in range(1, n + 1):
            f = i / n
            z = BALL_GROUND + 4 * peak * f * (1 - f)
            self.bp(t0 + f * (t1 - t0), a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1]), z)

    def run(self, pid, t0, t1, pt):
        self.runs[pid].append((t0, t1, pt[0], pt[1]))

    def gain(self, pid: int):
        team = self.players[pid]["team"]
        if not self.poss or self.poss[-1][1] != team:
            self.poss.append((self.t, team))
        self.carrier, self.carrier_since = pid, self.t

    def release(self):
        if self.carrier is not None:
            self.carry.append((self.carrier_since, self.t, self.carrier))
        self.carrier = None

    def ev(self, etype, team, frm, to, start, end=None, **kw):
        e = {"match_id": self.match_id, "t": round(self.t, 2), "period": self.period,
             "type": etype, "team": team, "from": frm, "to": to,
             "start": [round(start[0], 1), round(start[1], 1)]}
        if end is not None:
            e["end"] = [round(end[0], 1), round(end[1], 1)]
        e.update(kw)
        e["source"], e["confidence"] = "sim", 1.0
        self.events.append(e)
        return e

    # ---- player selection --------------------------------------------------
    def outfield(self, team):
        return [p for p in self.on_pitch[team] if self.players[p]["group"] != "gk"]

    def gk(self, team):
        return next(p for p in self.on_pitch[team] if self.players[p]["group"] == "gk")

    def nearest(self, team, pt, ball=None, exclude=(), gk_ok=False):
        ball = ball or (self.bx, self.by)
        pool = [p for p in self.on_pitch[team] if p not in exclude
                and (gk_ok or self.players[p]["group"] != "gk")]
        return min(pool, key=lambda p: dist(self.slot_world(p, ball, self.possessing()), pt))

    def choose_receiver(self, team, kind):
        """Pick a teammate and the point where the ball arrives."""
        me = self.carrier
        here = (self.bx, self.by)
        hx, hy = self.tw(team, *here)
        best, weights = [], []
        for p in self.on_pitch[team]:
            if p == me:
                continue
            if self.players[p]["group"] == "gk" and kind != "short":
                continue
            px, py = self.tw(team, *self.slot_world(p, here, team))
            d = math.hypot(px - hx, py - hy)
            fwd = px - hx
            if kind == "short":
                w = math.exp(-((d - 14) / 7) ** 2) * (1.6 if fwd > 0 else 1.0)
                if self.players[p]["group"] == "gk":
                    w *= 0.15 if hx < 35 else 0.0
            elif kind == "long":
                w = math.exp(-((d - 35) / 10) ** 2) * (1.0 + max(fwd, 0) / 20)
            elif kind == "through":
                w = (fwd > 8) * math.exp(-((d - 22) / 9) ** 2)
            else:  # cross: target the box
                w = (px > 80) * (1.0 + (self.players[p]["group"] == "fwd") * 2)
            if w > 1e-4:
                best.append(p)
                weights.append(w)
        if not best:
            best = [p for p in self.outfield(team) if p != me]
            weights = [1.0] * len(best)
        rec = self.rng.choices(best, weights)[0]

        # Arrival point: the receiver's slot once the ball has moved there.
        guess = self.slot_world(rec, here, team)
        tgt = self.slot_world(rec, guess, team)
        tx, ty = self.tw(team, *tgt)
        if kind == "through":
            tx += self.rng.uniform(5, 10)
        if kind == "cross":
            tx = self.rng.uniform(92, 100)
            ty = self.rng.uniform(26, 42)
        tx = clamp(tx + self.rng.gauss(0, 1.2), 1, 104)
        ty = clamp(ty + self.rng.gauss(0, 1.2), 1, 67)
        return rec, self.tw(team, tx, ty)

    # ---- set pieces ---------------------------------------------------------
    def do_subs(self) -> int:
        made = 0
        while self.sub_plan and self.sub_plan[0][0] <= self.match_minute():
            _, team = self.sub_plan.pop(0)
            if not self.bench[team]:
                continue
            on = self.bench[team].pop(0)
            grp = self.players[on]["group"]
            cands = [p for p in self.outfield(team) if self.players[p]["group"] == grp
                     and p != self.carrier] or [p for p in self.outfield(team) if p != self.carrier]
            off = self.rng.choice(cands)
            self.t += self.rng.uniform(15, 30)
            self.players[on]["slot"] = self.players[off]["slot"]
            self.on_pitch[team].remove(off)
            self.on_pitch[team].append(on)
            self.spans[off][1] = self.t
            self.spans[on] = [self.t, math.inf]
            self.ev("substitution", team, on, off, (L / 2, 0.0))
            made += 1
        return made

    def restart(self, kind, team, spot, taker=None, delay=(10, 20)):
        """Dead ball: wait, make subs, place the ball, the taker runs in."""
        self.release()
        self.t += self.rng.uniform(*delay)
        if self.do_subs():
            self.t += self.rng.uniform(8, 12)     # let the substitute jog on
        fresh = [p for p in self.on_pitch[team] if 0 < self.spans[p][0] > self.t - 15]
        if taker is None or taker not in self.on_pitch[team] or taker in fresh:
            taker = self.nearest(team, spot, ball=spot, exclude=fresh)
        self.bp(max(self.t - 1.0, self.period_start), *spot)
        self.bp(self.t, *spot)
        self.run(taker, max(self.t - 6, self.period_start - 1.0), self.t, spot)
        self.gain(taker)
        if kind == "kickoff":
            self.kickoffs.append((self.t, taker))
        return taker

    def out_of_play(self, last_team, pt):
        """Ball left the pitch at pt; last touched by last_team."""
        x, y = pt
        opp = other(last_team)
        tx, ty = self.tw(last_team, x, y)
        if tx >= L - 0.5:                         # over the goal line they attack
            self.t += 0.5
            spot = self.tw(opp, 5.5, self.rng.choice([24.8, 43.2]))
            self.restart("goal_kick", opp, spot, taker=self.gk(opp), delay=(14, 24))
            self.deliver("goal_kick", None, "long" if self.rng.random() < 0.65 else "short", opp)
        elif tx <= 0.5:                           # over their own goal line
            self.t += 0.5
            oy = self.tw(opp, x, y)[1]            # side of the pitch, opp's frame
            spot = self.tw(opp, L - 0.5, 0.5 if oy < W / 2 else W - 0.5)
            wide = [p for p in self.outfield(opp) if self.players[p]["pos"] in ("RW", "LW", "RM", "LM", "AM")]
            taker = self.rng.choice(wide) if wide else None
            self.restart("corner", opp, spot, taker=taker, delay=(20, 35))
            self.corner(opp)
        else:                                     # over a sideline
            side = 0.0 if y < W / 2 else W
            spot = (clamp(x, 1, L - 1), side)
            self.restart("throw_in", opp, spot, delay=(8, 18))
            self.deliver("throw_in", None, "short", opp)

    def corner(self, team):
        e = self.deliver("corner", None, "cross", team)
        if e["success"]:                          # failures were resolved in deliver()
            r = self.rng.random()
            if r < 0.45:
                self.shot(header=True)
            elif r < 0.75:
                self.defend_box(team)
            # else: the attacker keeps it and play goes on

    def defend_box(self, attacking):
        """Defenders or the keeper deal with a ball in their box."""
        d = other(attacking)
        if self.rng.random() < 0.25:              # keeper claims
            g = self.gk(d)
            self.run(g, self.t - 1, self.t, (self.bx, self.by))
            self.release()
            self.gain(g)
            self.ev("possession_change", d, g, None, (self.bx, self.by), subtype="interception",
                    success=True)
            self.hold(2.5, 5)
        else:
            c = self.nearest(d, (self.bx, self.by))
            self.run(c, self.t - 1, self.t, (self.bx, self.by))
            self.release()
            self.gain(c)
            self.clearance()

    # ---- core actions -------------------------------------------------------
    def hold(self, lo=0.3, hi=1.1):
        team = self.possessing()
        dt = self.rng.uniform(lo, hi)
        x, y = self.tw(team, self.bx, self.by)
        x = clamp(x + self.rng.uniform(-0.5, 1.5), 1, 104)
        y = clamp(y + self.rng.uniform(-1, 1), 1, 67)
        self.t += dt
        self.bp(self.t, *self.tw(team, x, y))

    def dribble(self):
        team = self.possessing()
        x, y = self.tw(team, self.bx, self.by)
        d = self.rng.uniform(4, 11)
        ang = self.rng.gauss(0, 0.5)
        nx = clamp(x + d * math.cos(ang), 2, 103)
        ny = clamp(y + d * math.sin(ang), 2, 66)
        dur = d / self.rng.uniform(4.5, 6.5)
        if self.rng.random() < self.p["challenge"]:
            f = self.rng.uniform(0.3, 1.0)
            cx, cy = x + f * (nx - x), y + f * (ny - y)
            self.t += dur * f
            self.bp(self.t, *self.tw(team, cx, cy))
            self.challenge()
        else:
            self.t += dur
            self.bp(self.t, *self.tw(team, nx, ny))

    def challenge(self):
        """An opponent challenges the ball carrier: tackle won, foul, or nothing."""
        att = self.possessing()
        d = other(att)
        victim = self.carrier
        tackler = self.nearest(d, (self.bx, self.by))
        self.run(tackler, self.t - 1.5, self.t, (self.bx, self.by))
        r = self.rng.random()
        if r < self.p["foul_given_challenge"]:
            self.foul(tackler, victim)
        elif r < self.p["foul_given_challenge"] + 0.42:
            self.release()
            self.gain(tackler)
            self.ev("possession_change", d, tackler, victim, (self.bx, self.by),
                    subtype="tackle", success=True)
            tx, _ = self.tw(d, self.bx, self.by)
            self.just_won_in_own_third = tx < 30
        # else: the carrier rides the challenge and keeps the ball

    def foul(self, fouler, victim):
        att = self.players[victim]["team"]
        spot = (self.bx, self.by)
        self.release()
        self.ev("foul", other(att), fouler, victim, spot, success=True)
        self.t += self.rng.uniform(3, 8)
        r = self.rng.random()
        if r < self.p["red"]:
            self.ev("red_card", other(att), fouler, None, spot, subtype="straight_red")
            self.send_off(fouler)
        elif r < self.p["red"] + self.p["yellow"]:
            self.yellows[fouler] += 1
            self.ev("yellow_card", other(att), fouler, None, spot)
            if self.yellows[fouler] == 2:
                self.ev("red_card", other(att), fouler, None, spot, subtype="second_yellow")
                self.send_off(fouler)
        x, y = self.tw(att, *spot)
        in_box = x > L - 16.5 and 13.84 < y < W - 13.84
        if in_box:
            pen = self.tw(att, L - 11, 34)
            striker = next((p for p in self.on_pitch[att] if self.players[p]["pos"] == "ST"), None)
            self.restart("free_kick", att, pen, taker=striker, delay=(40, 70))
            self.ev("free_kick", att, self.carrier, None, pen, subtype="penalty", success=True)
            self.t += 2
            self.shot(penalty=True)
        else:
            self.restart("free_kick", att, spot, taker=victim, delay=(15, 30))
            central = 18 < y < 50
            if x > 75 and central and self.rng.random() < 0.35:
                self.ev("free_kick", att, self.carrier, None, spot, subtype="direct", success=True)
                self.t += 0.5
                self.shot(direct_fk=True)
            elif x > 75:
                self.deliver("free_kick", None, "cross", att)
            else:
                self.deliver("free_kick", None, "long" if x < 45 else "short", att)

    def send_off(self, pid):
        team = self.players[pid]["team"]
        self.on_pitch[team].remove(pid)
        self.spans[pid][1] = self.t

    def deliver(self, etype, subtype, kind, team):
        """A pass-like delivery (pass, throw-in, goal kick, corner, free kick,
        kickoff). Emits one event and resolves the outcome."""
        start = (self.bx, self.by)
        passer = self.carrier
        rec, end = self.choose_receiver(team, kind)
        d = dist(start, end)
        if etype == "pass" and kind in ("short", "long"):
            subtype = "short" if d < 25 else "long"     # label by what actually happened
        speed = {"short": (38, 58), "long": (58, 85), "through": (48, 70),
                 "cross": (60, 82)}[kind]
        if etype == "throw_in":
            speed = (25, 40)
        kmh = self.rng.uniform(*speed)
        dur = max(0.4, d / (kmh / 3.6) * 1.15)
        peak = {"short": 0.2, "long": self.rng.uniform(3, 9), "through": 0.4,
                "cross": self.rng.uniform(2, 5)}[kind]
        if etype == "throw_in":
            peak = 1.5

        base = {"short": 0.88, "long": 0.60, "through": 0.52, "cross": 0.32}[kind]
        if etype == "throw_in":
            base = 0.86
        if etype == "corner":
            base = 0.45
        sx, _ = self.tw(team, *start)
        ex, _ = self.tw(team, *end)

        # Offside on forward balls in behind.
        if (etype in ("pass", "free_kick") and kind in ("through", "long") and ex - sx > 10
                and ex > 60 and self.rng.random() < self.p["offside"]):
            self.release()
            self.flight(self.t, self.t + dur, start, end, peak)
            self.run(rec, self.t, self.t + dur, end)
            self.t += dur
            self.ev("offside", team, rec, None, end, success=False)
            d_team = other(team)
            self.restart("free_kick", d_team, end, delay=(10, 18))
            self.deliver("free_kick", None, "long", d_team)
            return {"success": False}

        self.release()
        t0 = self.t
        if self.rng.random() < base:
            self.flight(t0, t0 + dur, start, end, peak)
            self.run(rec, t0, t0 + dur, end)
            e = self.ev(etype, team, passer, rec, start, end, subtype=subtype,
                        distance_m=round(d, 1), speed_kmh=round(kmh), duration_s=round(dur, 2),
                        success=True)
            if e.get("subtype") is None:
                e.pop("subtype")
            self.t = t0 + dur
            self.gain(rec)
            self.just_won_in_own_third = False
            return e

        # Failed: intercepted, or out of play.
        opp = other(team)
        if self.rng.random() < 0.78:
            # The defender closest to the ball's path cuts it out.
            best, bf, bd = None, 0.0, 1e9
            for p in self.on_pitch[opp]:
                pos = self.slot_world(p, start, team)
                for f in (0.3, 0.45, 0.6, 0.75, 0.9, 1.0):
                    pt = (start[0] + f * (end[0] - start[0]), start[1] + f * (end[1] - start[1]))
                    dd = dist(pos, pt)
                    if dd < bd:
                        best, bf, bd = p, f, dd
            ip = (start[0] + bf * (end[0] - start[0]), start[1] + bf * (end[1] - start[1]))
            idur = max(0.3, dur * bf)
            self.flight(t0, t0 + idur, start, ip, peak * bf)
            self.run(best, t0, t0 + idur, ip)
            e = self.ev(etype, team, passer, None, start, ip, subtype=subtype,
                        distance_m=round(dist(start, ip), 1), speed_kmh=round(kmh),
                        duration_s=round(idur, 2), success=False)
            if e.get("subtype") is None:
                e.pop("subtype")
            self.t = t0 + idur
            self.gain(best)
            if bf <= 0.3:
                self.ev("possession_change", opp, best, passer, ip, subtype="interception",
                        success=True)
            ix, _ = self.tw(opp, *ip)
            self.just_won_in_own_third = ix < 30
            if kind == "cross" and self.rng.random() < 0.6:
                self.clearance()
            return e

        # Out of play: over the goal line for balls into the final third,
        # otherwise over the nearest sideline.
        ex, ey = self.tw(team, *end)
        last = team
        if kind == "cross" or (kind in ("long", "through") and ex > 75):
            out = self.tw(team, L + 0.5, clamp(ey + self.rng.uniform(-10, 10), 1, 67))
            if kind == "cross" and self.rng.random() < 0.35:
                last = other(team)                # deflected behind: corner
        else:
            oy = -0.5 if ey < W / 2 else W + 0.5
            out = self.tw(team, clamp(ex + self.rng.uniform(0, 6), 1, 104), oy)
        odur = dist(start, out) / (kmh / 3.6) * 1.15
        self.flight(t0, t0 + odur, start, out, peak)
        e = self.ev(etype, team, passer, None, start, out, subtype=subtype,
                    distance_m=round(dist(start, out), 1), speed_kmh=round(kmh),
                    duration_s=round(odur, 2), success=False)
        if e.get("subtype") is None:
            e.pop("subtype")
        self.t = t0 + odur
        self.out_of_play(last, out)
        return e

    def clearance(self):
        team = self.possessing()
        start = (self.bx, self.by)
        x, y = self.tw(team, *start)
        ex = clamp(x + self.rng.uniform(30, 50), 30, 95)
        ey = clamp(y + self.rng.uniform(-20, 20), 1, 67)
        end = self.tw(team, ex, ey)
        kmh = self.rng.uniform(65, 95)
        d = dist(start, end)
        dur = d / (kmh / 3.6) * 1.15
        clearer = self.carrier
        self.release()
        r = self.rng.random()
        if x < 18 and r < 0.12:                   # sliced behind: corner
            out = self.tw(team, -0.5, clamp(y + self.rng.uniform(-10, 10), 1, 67))
            self.flight(self.t, self.t + 0.6, start, out, 1.0)
            self.ev("clearance", team, clearer, None, start, out, distance_m=round(dist(start, out), 1),
                    speed_kmh=round(kmh), duration_s=0.6, success=False)
            self.t += 0.6
            self.out_of_play(team, out)
            return
        if r < 0.27:                              # into touch
            out = self.tw(team, ex, -0.5 if ey < W / 2 else W + 0.5)
            self.flight(self.t, self.t + dur, start, out, self.rng.uniform(6, 14))
            self.ev("clearance", team, clearer, None, start, out, distance_m=round(dist(start, out), 1),
                    speed_kmh=round(kmh), duration_s=round(dur, 2), success=False)
            self.t += dur
            self.out_of_play(team, out)
            return
        self.flight(self.t, self.t + dur, start, end, self.rng.uniform(6, 14))
        win_team = team if r < 0.55 else other(team)
        rec = self.nearest(win_team, end, ball=end)
        self.run(rec, self.t, self.t + dur, end)
        self.ev("clearance", team, clearer, None, start, end, distance_m=round(d, 1),
                speed_kmh=round(kmh), duration_s=round(dur, 2), success=win_team == team)
        self.t += dur
        self.gain(rec)                            # a loose-ball recovery, not an event
        self.just_won_in_own_third = False

    def shot(self, header=False, penalty=False, direct_fk=False):
        team = self.possessing()
        shooter = self.carrier
        start = (self.bx, self.by)
        x, y = self.tw(team, *start)
        dgoal = math.hypot(L - x, 34 - y)
        if penalty:
            p_goal = 0.76
        elif direct_fk:
            p_goal = 0.08
        else:
            p_goal = clamp(0.34 * math.exp(-(dgoal - 6) / 8.0), 0.02, 0.45) * (0.6 if header else 1)
        kmh = self.rng.uniform(55, 75) if header else self.rng.uniform(75, 118)
        r = self.rng.random()
        if r < p_goal:
            outcome = "goal"
        else:
            r2 = self.rng.random()
            outcome = "blocked" if (r2 < 0.27 and not penalty) else ("saved" if r2 < 0.62 else "off")
        if outcome in ("goal", "saved"):
            end = self.tw(team, L, 34 + self.rng.uniform(-GOAL_HALF + 0.3, GOAL_HALF - 0.3))
            peak, sub = self.rng.uniform(0.2, 1.8), "on_target"
        elif outcome == "off":
            side = self.rng.choice([-1, 1])
            end = self.tw(team, L + 0.5, 34 + side * self.rng.uniform(GOAL_HALF + 0.4, 9))
            peak, sub = self.rng.uniform(0.5, 3.5), "off_target"
        else:
            f = self.rng.uniform(0.1, 0.3)
            gx, gy = self.tw(team, L, 34)
            end = (start[0] + f * (gx - start[0]), start[1] + f * (gy - start[1]))
            peak, sub = 0.3, "blocked"
        d = dist(start, end)
        dur = max(0.2, d / (kmh / 3.6))
        self.release()
        self.flight(self.t, self.t + dur, start, end, peak)
        self.ev("shot", team, shooter, None, start, end, subtype=sub, distance_m=round(d, 1),
                speed_kmh=round(kmh), duration_s=round(dur, 2), success=outcome == "goal")
        self.t += dur
        opp = other(team)

        if outcome == "goal":
            self.score[team] += 1
            gsub = "penalty" if penalty else "open_play"
            self.ev("goal", team, shooter, None, end, subtype=gsub, success=True,
                    score=dict(self.score))
            self.kickoff(opp, delay=(45, 70))
        elif outcome == "saved":
            g = self.gk(opp)
            self.run(g, self.t - dur, self.t, end)
            if self.rng.random() < 0.35:
                self.out_of_play(opp, self.tw(team, L + 0.5, 34 + self.rng.uniform(-12, 12)))
            else:
                self.gain(g)
                self.hold(3, 7)
                self.deliver("pass", "long", "long", opp)
        elif outcome == "off":
            self.out_of_play(team, end)
        else:  # blocked
            r3 = self.rng.random()
            blocker = self.nearest(opp, end, ball=end)
            self.run(blocker, self.t - dur, self.t, end)
            if r3 < 0.4:
                self.out_of_play(opp, self.tw(team, L + 0.5, 34 + self.rng.uniform(-15, 15)))
            elif r3 < 0.7:
                self.gain(self.nearest(team, end, ball=end))
            else:
                self.gain(blocker)
                self.ev("possession_change", opp, blocker, shooter, end, subtype="interception",
                        success=True)
                self.clearance()

    def kickoff(self, team, delay=(0, 0)):
        striker = next((p for p in self.on_pitch[team] if self.players[p]["group"] == "fwd"),
                       self.outfield(team)[0])
        self.restart("kickoff", team, (L / 2, W / 2), taker=striker, delay=delay)
        start = (L / 2, W / 2)
        mids = [p for p in self.on_pitch[team] if self.players[p]["group"] == "mid"] or self.outfield(team)
        rec = self.rng.choice(mids)
        end = self.tw(team, self.rng.uniform(38, 46), self.rng.uniform(24, 44))
        kmh = self.rng.uniform(30, 45)
        dur = dist(start, end) / (kmh / 3.6) * 1.15
        passer = self.carrier
        self.release()
        self.flight(self.t, self.t + dur, start, end, 0.2)
        self.run(rec, self.t, self.t + dur, end)
        self.ev("kickoff", team, passer, rec, start, end, distance_m=round(dist(start, end), 1),
                speed_kmh=round(kmh), duration_s=round(dur, 2), success=True)
        self.t += dur
        self.gain(rec)

    # ---- the match loop ------------------------------------------------------
    def step(self):
        team = self.possessing()
        x, y = self.tw(team, self.bx, self.by)
        if self.just_won_in_own_third and self.rng.random() < 0.55:
            self.clearance()
            return
        self.just_won_in_own_third = False
        self.hold()
        b = self.p["shot_boost"]
        wide = y < 16 or y > 52
        if self.players[self.carrier]["group"] == "gk":
            w = {"short": 55, "long": 45}
        elif x < 18:
            w = {"short": 50, "long": 16, "dribble": 12, "clear": 22}
        elif x < 30:
            w = {"short": 64, "long": 16, "dribble": 16}
        elif x < 65:
            w = {"short": 68, "long": 8, "through": 7, "dribble": 17}
        elif x < 88:
            w = {"short": 50, "through": 9, "cross": 14 if wide else 2, "shot": (7 * b if x > 76 else 0),
                 "dribble": 22}
        else:
            w = {"shot": 26 * b, "short": 38, "cross": 6 if wide else 0, "dribble": 28}
        act = self.rng.choices(list(w), list(w.values()))[0]
        if act == "dribble":
            self.dribble()
        elif act == "shot":
            self.shot()
        elif act == "clear":
            self.clearance()
        else:
            self.deliver("pass", act, act, team)

    def play(self):
        for period in (1, 2):
            self.period = period
            if period == 2:
                self.t += 1.0
            self.period_start = self.t
            end = self.t + self.half_len
            self.kickoff("home" if period == 1 else "away")
            while self.t < end:
                if self.carrier is None:          # safety net, should not happen
                    self.gain(self.nearest(self.possessing() or "home", (self.bx, self.by)))
                self.step()
            self.release()
            self.t += 0.5
            kind = "half_time" if period == 1 else "full_time"
            self.ev(kind, "none", None, None, (L / 2, W / 2), score=dict(self.score))
            self.periods.append({"period": period, "start": round(self.period_start, 2),
                                 "end": round(self.t, 2)})
        self.bp(self.t, self.bx, self.by)
        for pid, span in self.spans.items():
            if math.isinf(span[1]):
                span[1] = self.t
        # Number events in time order.
        self.events.sort(key=lambda e: e["t"])
        for i, e in enumerate(self.events, 1):
            e["id"] = f"e{i:04d}"
        self.events = [{"id": e.pop("id"), **e} for e in self.events]

    # ---- outputs -------------------------------------------------------------
    def match_info(self):
        info = {"match_id": self.match_id, "fps": FPS, "pitch": [L, W], "origin": "bottom-left",
                "kickoff_direction": {"home": "left_to_right"}, "periods": self.periods}
        for team, cfg in TEAMS.items():
            pl = []
            for num, name, pos, *_ in cfg["starters"]:
                pl.append({"id": num + (0 if team == "home" else 100), "number": num, "name": name,
                           "pos": pos, "starter": True})
            for num, name, pos in cfg["subs"]:
                pl.append({"id": num + (0 if team == "home" else 100), "number": num, "name": name,
                           "pos": pos, "starter": False})
            info[team] = {"name": cfg["name"], "short": cfg["short"], "kit": cfg["kit"],
                          "formation": cfg["formation"], "players": pl}
        return info


# --------------------------------------------------------------------------
# Movement layer: per-frame positions from the event layer's records.
# --------------------------------------------------------------------------
def build_tracking(m: Match, t0: float, t1: float):
    bt = [w[0] for w in m.ball_path]
    carry_t = [c[0] for c in m.carry]
    poss_t = [p[0] for p in m.poss]
    period_bounds = [(p["start"], p["end"], p["period"]) for p in m.periods]

    def ball_at(t):
        i = bisect.bisect_right(bt, t)
        if i == 0:
            return m.ball_path[0][1:]
        if i >= len(bt):
            return m.ball_path[-1][1:]
        a, b = m.ball_path[i - 1], m.ball_path[i]
        f = 0 if b[0] == a[0] else (t - a[0]) / (b[0] - a[0])
        return tuple(a[k] + f * (b[k] - a[k]) for k in (1, 2, 3))

    def carrier_at(t):
        i = bisect.bisect_right(carry_t, t) - 1
        if i >= 0 and m.carry[i][0] <= t < m.carry[i][1]:
            return m.carry[i][2]
        return None

    def team_poss_at(t):
        i = bisect.bisect_right(poss_t, t) - 1
        return m.poss[i][1] if i >= 0 else "home"

    def period_at(t):
        for s, e, p in period_bounds:
            if t <= e:
                return p
        return 2

    pos: dict[int, list] = {}
    frames = []
    last_period = None
    n0, n1 = int(round(t0 * FPS)), int(round(t1 * FPS))
    dt = 1 / FPS
    for fr in range(n0, n1):
        t = fr / FPS
        m.period = period_at(t)
        if m.period != last_period:               # broadcast cuts at half-time: re-place everyone
            pos.clear()
            last_period = m.period
        bx, by, bz = ball_at(t)
        ref = ball_at(max(0.0, t - 0.8))[:2]       # shapes react with a small delay
        tp = team_poss_at(t)
        car = carrier_at(t)
        upcoming_kick = [k for k in m.kickoffs
                         if k[0] - 5 <= t <= k[0] and period_at(k[0]) == m.period]
        players = []
        for pid, (on, off) in m.spans.items():
            if not (on <= t < off):
                pos.pop(pid, None)
                continue
            pl = m.players[pid]
            team = pl["team"]
            tgt = m.slot_world(pid, ref, tp)
            wob = 0.8 * math.sin(0.4 * t + pid) , 0.8 * math.cos(0.33 * t + 2 * pid)
            tgt = (tgt[0] + wob[0], tgt[1] + wob[1])
            vmax = 7.0
            for (r0, r1, rx, ry) in m.runs.get(pid, ()):
                if r0 - 0.5 <= t <= r1 + 0.3:
                    tgt, vmax = (rx, ry), 9.5
                    break
            if car == pid:
                back = 0.6 * m.dirn(team)
                tgt, vmax = (bx - back, by), 10.5
            if upcoming_kick and (car != pid) and all(k[1] != pid for k in upcoming_kick):
                x, y = m.tw(team, *tgt)
                tgt = m.tw(team, min(x, 51.0), y)
            if pid not in pos:
                entering = on > 0 and t - on < 1.0     # substitute walking on
                pos[pid] = [L / 2, -1.0] if entering else list(tgt)
            p = pos[pid]
            dx, dy = tgt[0] - p[0], tgt[1] - p[1]
            d = math.hypot(dx, dy)
            step = vmax * dt
            if d > step:
                p[0] += dx / d * step
                p[1] += dy / d * step
            else:
                p[0], p[1] = tgt
            p[0], p[1] = clamp(p[0], -2, L + 2), clamp(p[1], -2, W + 2)
            players.append({"id": pid, "team": team, "pos": [round(p[0], 2), round(p[1], 2)]})
        frames.append({"match_id": m.match_id, "frame": fr, "t": round(t, 2),
                       "ball": [round(bx, 2), round(by, 2), round(bz, 2)], "players": players})
    return frames


# --------------------------------------------------------------------------
# Fake overlays: a stand-in for the director agent, so the web player has
# something to draw. Templates only; the real director replaces this.
# --------------------------------------------------------------------------
def build_overlays(events, info):
    names = {p["id"]: p["name"] for t in ("home", "away") for p in info[t]["players"]}
    tname = {"home": info["home"]["name"], "away": info["away"]["name"]}
    variants = [("analyst", "en"), ("casual", "en"), ("casual", "tr")]
    out = []
    busy_until = -1.0
    for e in events:
        typ = e["type"]
        pid = e.get("from")
        nm = names.get(pid, "")
        item = None
        if typ == "goal":
            s = e["score"]
            item = ("goal_banner", 0.5, 8, 1.0, "top-left", {"home": s["home"], "away": s["away"]}, {
                ("analyst", "en"): f"GOAL {tname[e['team']]}: {nm}. {s['home']}-{s['away']}",
                ("casual", "en"): f"GOAL! {nm} scores for {tname[e['team']]}!",
                ("casual", "tr"): f"GOL! {nm}, {tname[e['team']]} için skoru değiştirdi!"})
        elif typ == "shot":
            v = {"speed_kmh": e["speed_kmh"], "distance_m": e["distance_m"]}
            item = ("shot_card", 0.8, 5, 0.8, "bottom-left", v, {
                ("analyst", "en"): f"Shot {e['speed_kmh']} km/h, {e['subtype'].replace('_', ' ')}",
                ("casual", "en"): f"What a strike from {nm}!",
                ("casual", "tr"): f"{nm} sert vurdu!"})
        elif typ in ("yellow_card", "red_card"):
            color = "Yellow" if typ == "yellow_card" else "Red"
            tr_color = "Sarı" if typ == "yellow_card" else "Kırmızı"
            item = ("card_banner", 1.0, 5, 0.9, "top-right", {}, {
                ("analyst", "en"): f"{color} card: {nm}",
                ("casual", "en"): f"{color} card for {nm}",
                ("casual", "tr"): f"{nm} {tr_color.lower()} kart gördü"})
        elif typ == "pass" and e.get("success") and e.get("distance_m", 0) >= 40:
            v = {"distance_m": e["distance_m"], "speed_kmh": e["speed_kmh"]}
            item = ("pass_card", 1.5, 5, 0.6, "bottom-left", v, {
                ("analyst", "en"): f"{e['distance_m']:.0f} m {e.get('subtype', 'pass')} pass, {e['speed_kmh']} km/h",
                ("casual", "en"): f"Great long ball from {nm}!",
                ("casual", "tr"): f"{nm}'dan harika uzun pas!"})
        if not item:
            continue
        graphic, lag, dur, prio, where, values, texts = item
        start = e["t"] + lag
        if start < busy_until and prio < 1.0:
            continue                               # one graphic at a time
        busy_until = start + dur
        for mode, lang in variants:
            out.append({"start": round(start, 2), "duration": dur, "graphic": graphic,
                        "event_ids": [e["id"]], "player": pid, "priority": prio,
                        "position": where, "title": nm or tname.get(e["team"], ""),
                        "text": texts[(mode, lang)], "values": values,
                        "mode": mode, "lang": lang})
    out.sort(key=lambda o: o["start"])
    return [{"id": f"o{i:04d}", **o} for i, o in enumerate(out, 1)]


# --------------------------------------------------------------------------
def report(events, m: Match, label: str, half_len: float):
    c = Counter(e["type"] for e in events)
    scale = 5400 / (2 * half_len)
    passes = [e for e in events if e["type"] == "pass"]
    acc = sum(e["success"] for e in passes) / max(1, len(passes))
    # Possession share by time.
    share = Counter()
    for (t, team), nxt in zip(m.poss, m.poss[1:] + [(m.t, None)]):
        share[team] += nxt[0] - t
    tot = sum(share.values()) or 1
    print(f"\n== {label}: final score {m.score['home']}-{m.score['away']} "
          f"| pass accuracy {acc:.0%} | possession home {share['home'] / tot:.0%}")
    print(f"{'type':20}{'count':>7}{'per 90':>8}   norm")
    for t in ALL_TYPES:
        lo_hi = NORMS.get(t)
        per90 = c[t] * scale
        flag = ""
        if lo_hi and scale == 1.0:
            flag = "ok" if lo_hi[0] <= per90 <= lo_hi[1] else "OUT OF RANGE"
        norm = f"{lo_hi[0]}-{lo_hi[1]}" if lo_hi else ""
        print(f"{t:20}{c[t]:7}{per90:8.0f}   {norm:10} {flag}")
    print(f"{'total':20}{len(events):7}")


def typical(events) -> bool:
    """True if every event count is inside the 90-minute norm range."""
    c = Counter(e["type"] for e in events)
    return all(lo <= c[t] <= hi for t, (lo, hi) in NORMS.items()) and c["yellow_card"] >= 1


def generate(seed, half_len, profile, match_id, require_all=False, require_typical=False,
             min_events=0):
    """Play matches with increasing seeds until the requirements are met:
    require_all = every event type appears, require_typical = counts look
    like a normal 90-minute match."""
    for s in range(seed, seed + 500):
        m = Match(s, half_len, profile, match_id)
        m.play()
        types = {e["type"] for e in m.events}
        if require_all and not set(ALL_TYPES) <= types:
            continue
        if require_typical and not typical(m.events):
            continue
        if len(m.events) < min_events:
            continue
        return m, s
    raise RuntimeError("no seed met the requirements")


def write_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--full-tracking", action="store_true", help="also write full 25 fps tracking to data/generated/")
    ap.add_argument("--report", action="store_true", help="print event counts against football norms")
    args = ap.parse_args()

    # Sample A: short, every event type.
    ma, sa = generate(args.seed, 300, "short", "fake_a", require_all=True, min_events=100)
    info_a = ma.match_info()
    out_a = ROOT / "data" / "fake" / "sample_a"
    write_json(out_a / "match_info.json", info_a)
    write_json(out_a / "events.json", ma.events)
    write_jsonl(out_a / "tracking.jsonl", build_tracking(ma, 0, 60))
    write_json(out_a / "overlays.json", build_overlays(ma.events, info_a))
    print(f"sample_a: seed {sa}, {len(ma.events)} events, score {ma.score['home']}-{ma.score['away']}")

    # Sample B: full match.
    mb, sb = generate(args.seed, 2700, "full", "fake_b", require_typical=True)
    info_b = mb.match_info()
    out_b = ROOT / "data" / "fake" / "sample_b"
    write_json(out_b / "match_info.json", info_b)
    write_json(out_b / "events.json", mb.events)
    print(f"sample_b: seed {sb}, {len(mb.events)} events, score {mb.score['home']}-{mb.score['away']}")

    if args.full_tracking:
        gen = ROOT / "data" / "generated"
        write_jsonl(gen / "sample_a" / "tracking.jsonl", build_tracking(ma, 0, ma.t))
        write_jsonl(gen / "sample_b" / "tracking.jsonl", build_tracking(mb, 0, mb.t))
        print("full tracking written to data/generated/")

    if args.report:
        report(ma.events, ma, "sample_a (short, boosted rare events)", 300)
        report(mb.events, mb, "sample_b (full match)", 2700)


if __name__ == "__main__":
    main()
