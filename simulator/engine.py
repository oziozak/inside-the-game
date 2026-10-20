"""Event layer: plays a match with weighted dice and basic football rules.

The player on the ball repeatedly picks an action (hold, dribble, pass,
cross, shot, clearance) with weights that depend on where he is. Success is
random too. Basic football rules handle ball out of play (throw-in, corner,
goal kick), fouls, cards, offside, penalties, goals, kickoffs, substitutions
and half-time.

Besides the events, the Match records everything the movement layer needs:
the ball path, who carries the ball when, planned runs (receivers,
interceptors, tacklers, set-piece takers) and who is on the pitch when.
Everything is driven by one seeded random.Random, so the same seed always
gives the same match.
"""

from __future__ import annotations

import math
import random
from collections import Counter, defaultdict

from .config import ALL_TYPES, BALL_GROUND, FPS, GOAL_HALF, GROUP, MIN_X, NORMS, PROFILES, WIDE, L, W
from .geometry import clamp, dist, other
from .teams import load_team, resolve_kits


class Match:
    """Event layer: plays a match and records events plus everything the
    movement layer needs (ball path, who carries the ball, planned runs).

    Args:
        seed: seed for the match's random generator.
        half_len: length of each half in seconds.
        profile: key of config.PROFILES ("full" or "short").
        match_id: written into every event and frame.
        home, away: team dicts from teams.load_team(); default Bosphorus FC
            (home) and Thames United (away).
    """

    def __init__(self, seed: int, half_len: float, profile: str, match_id: str,
                 home: dict | None = None, away: dict | None = None):
        self.rng = random.Random(seed)
        self.half_len = half_len
        self.p = PROFILES[profile]
        self.match_id = match_id
        self.teams = {"home": home or load_team("bosphorus"), "away": away or load_team("thames")}
        # The away side changes kit if the colors clash (the vision AI separates teams by color).
        home_kit, away_kit = resolve_kits(self.teams["home"], self.teams["away"])
        self.kits = {"home": home_kit, "away": away_kit}
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

        # Player ids are unique across teams: home = shirt number, away = 100 + shirt number.
        self.players: dict[int, dict] = {}
        self.on_pitch = {"home": [], "away": []}
        self.bench = {"home": [], "away": []}
        for team, cfg in self.teams.items():
            base = 0 if team == "home" else 100
            for pl in cfg["players"]:
                pid = base + pl["number"]
                self.players[pid] = dict(id=pid, number=pl["number"], name=pl["name"], pos=pl["pos"],
                                         team=team, slot=pl.get("slot") if pl["starter"] else None,
                                         group=GROUP[pl["pos"]])
                if pl["starter"]:
                    self.on_pitch[team].append(pid)
                    self.spans[pid] = [0.0, math.inf]
                else:
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
        """Display minute of the current time (0-90), used for the substitution plan."""
        frac = (self.t - self.period_start) / self.half_len
        return frac * 45 + (0 if self.period == 1 else 45)

    def slot_world(self, pid: int, ball, team_in_poss: str | None, period: int | None = None):
        """Where a player stands given the ball position (formation shift).

        `period` defaults to the current period; the movement layer passes it
        explicitly. This runs for every player in every frame, so the team
        frame flip and clamp() are written out inline (same results)."""
        pl = self.players[pid]
        team = pl["team"]
        flip = (team == "home") != ((self.period if period is None else period) == 1)
        if flip:
            bx, by = L - ball[0], W - ball[1]
        else:
            bx, by = ball[0], ball[1]
        if pl["group"] == "gk":
            # The keeper follows the ball a little, staying near his goal.
            x = 4 + 0.10 * (bx - 52.5)
            y = 34 + 0.15 * (by - 34)
            lo_x, hi_x, lo_y, hi_y = 1.5, 16, 28, 40
        else:
            # Outfield players shift with the ball and push up when their team has it.
            sx, sy = pl["slot"]
            x = sx + 0.55 * (bx - 52.5) + (4 if team_in_poss == team else -4)
            y = sy + 0.30 * (by - 34)
            lo_x, hi_x, lo_y, hi_y = MIN_X[pl["group"]], 100, 2, 66
        # clamp(v, lo, hi) == max(lo, min(hi, v)), written out.
        x = x if x < hi_x else hi_x
        x = x if x > lo_x else lo_x
        y = y if y < hi_y else hi_y
        y = y if y > lo_y else lo_y
        return (L - x, W - y) if flip else (x, y)

    def possessing(self) -> str | None:
        """Team of the current ball carrier, or None when the ball is loose."""
        return self.players[self.carrier]["team"] if self.carrier else None

    # ---- recording helpers -----------------------------------------------
    def bp(self, t, x, y, z=BALL_GROUND):
        """Record a ball waypoint and move the ball there."""
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
        """Plan a run: player pid sprints to pt between t0 and t1."""
        self.runs[pid].append((t0, t1, pt[0], pt[1]))

    def gain(self, pid: int):
        """Player pid gets the ball (records a possession switch if needed)."""
        team = self.players[pid]["team"]
        if not self.poss or self.poss[-1][1] != team:
            self.poss.append((self.t, team))
        self.carrier, self.carrier_since = pid, self.t

    def release(self):
        """The carrier lets go of the ball (pass, shot, dead ball)."""
        if self.carrier is not None:
            self.carry.append((self.carrier_since, self.t, self.carrier))
        self.carrier = None

    def ev(self, etype, team, frm, to, start, end=None, **kw):
        """Append one event at the current time and return it."""
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
        """On-pitch players of a team except the goalkeeper."""
        return [p for p in self.on_pitch[team] if self.players[p]["group"] != "gk"]

    def gk(self, team):
        """The team's goalkeeper."""
        return next(p for p in self.on_pitch[team] if self.players[p]["group"] == "gk")

    def nearest(self, team, pt, ball=None, exclude=(), gk_ok=False):
        """Player of `team` whose formation position (for the given ball
        position) is closest to pt."""
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
                # Around 14 m, forward options preferred; back to the keeper only deep.
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
            tx += self.rng.uniform(5, 10)          # played into space ahead of him
        if kind == "cross":
            tx = self.rng.uniform(92, 100)
            ty = self.rng.uniform(26, 42)
        tx = clamp(tx + self.rng.gauss(0, 1.2), 1, 104)
        ty = clamp(ty + self.rng.gauss(0, 1.2), 1, 67)
        return rec, self.tw(team, tx, ty)

    # ---- set pieces ---------------------------------------------------------
    def do_subs(self) -> int:
        """Make any substitutions that are due (only at a dead ball)."""
        made = 0
        while self.sub_plan and self.sub_plan[0][0] <= self.match_minute():
            _, team = self.sub_plan.pop(0)
            if not self.bench[team]:
                continue
            on = self.bench[team].pop(0)
            grp = self.players[on]["group"]
            # Like for like where possible; never the player about to take the restart.
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
        # A substitute who only just came on cannot reach the ball in time.
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
            wide = [p for p in self.outfield(opp) if self.players[p]["pos"] in WIDE]
            taker = self.rng.choice(wide) if wide else None
            self.restart("corner", opp, spot, taker=taker, delay=(20, 35))
            self.corner(opp)
        else:                                     # over a sideline
            side = 0.0 if y < W / 2 else W
            spot = (clamp(x, 1, L - 1), side)
            self.restart("throw_in", opp, spot, delay=(8, 18))
            self.deliver("throw_in", None, "short", opp)

    def corner(self, team):
        """Corner kick: a cross into the box, then a header, a clearance or play on."""
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
        """The carrier keeps the ball for a moment, drifting slightly forward."""
        team = self.possessing()
        dt = self.rng.uniform(lo, hi)
        x, y = self.tw(team, self.bx, self.by)
        x = clamp(x + self.rng.uniform(-0.5, 1.5), 1, 104)
        y = clamp(y + self.rng.uniform(-1, 1), 1, 67)
        self.t += dt
        self.bp(self.t, *self.tw(team, x, y))

    def dribble(self):
        """Carry the ball 4-11 m, roughly forward; may be challenged on the way."""
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
        """A foul: maybe a card, then a free kick or (in the box) a penalty."""
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
            striker = next((p for p in self.on_pitch[att] if self.players[p]["pos"] in ("ST", "CF")), None)
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
        """Player pid leaves the pitch for good (red card)."""
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

        # Base success rate by kind of ball.
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
                # Cut out right at the passer's feet: a clear interception.
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
        """Hoof it upfield: may go out (corner, throw-in) or be won by either side."""
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
        """A shot: goal, saved, off target or blocked, then the follow-up."""
        team = self.possessing()
        shooter = self.carrier
        start = (self.bx, self.by)
        x, y = self.tw(team, *start)
        dgoal = math.hypot(L - x, 34 - y)
        # Goal probability falls off with distance (a simple xG curve).
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
                # Parried behind: corner.
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
        """Kick off from the center spot: a forward plays it back to a midfielder."""
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
        """One decision by the ball carrier: pick an action by zone and do it."""
        team = self.possessing()
        x, y = self.tw(team, self.bx, self.by)
        # Just won the ball deep in our own third: often clear the danger first.
        if self.just_won_in_own_third and self.rng.random() < 0.55:
            self.clearance()
            return
        self.just_won_in_own_third = False
        self.hold()
        b = self.p["shot_boost"]
        wide = y < 16 or y > 52
        # Action weights by zone (x in the team frame: 0 = own goal, 105 = their goal).
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
        """Play both halves, then number the events in time order."""
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
        """The match_info.json object (teams, kits, lineups, periods)."""
        info = {"match_id": self.match_id, "fps": FPS, "pitch": [L, W], "origin": "bottom-left",
                "kickoff_direction": {"home": "left_to_right"}, "periods": self.periods}
        for team, cfg in self.teams.items():
            base = 0 if team == "home" else 100
            pl = [{"id": p["number"] + base, "number": p["number"], "name": p["name"],
                   "pos": p["pos"], "starter": p["starter"]} for p in cfg["players"]]
            info[team] = {"name": cfg["name"], "short": cfg["short"], "kit": self.kits[team],
                          "formation": cfg["formation"], "players": pl}
        return info


def typical(events) -> bool:
    """True if every event count is inside the 90-minute norm range."""
    c = Counter(e["type"] for e in events)
    return all(lo <= c[t] <= hi for t, (lo, hi) in NORMS.items()) and c["yellow_card"] >= 1


def generate(seed, half_len, profile, match_id, require_all=False, require_typical=False,
             min_events=0, home=None, away=None):
    """Play matches with increasing seeds until the requirements are met:
    require_all = every event type appears, require_typical = counts look
    like a normal 90-minute match. Returns (match, seed used)."""
    for s in range(seed, seed + 500):
        m = Match(s, half_len, profile, match_id, home=home, away=away)
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
