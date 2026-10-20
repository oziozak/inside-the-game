"""Movement layer: per-frame positions (25 fps) from the event layer's records.

Every player has a formation slot. The whole team shifts with the ball, the
ball carrier is pinned to the ball, and pass receivers, interceptors,
tacklers and set-piece takers run to where the ball goes. Player speed is
capped so nobody teleports (except at the half-time cut, where the broadcast
cuts and everyone is re-placed).
"""

from __future__ import annotations

import bisect
import math

from .config import FPS, L, W
from .engine import Match
from .geometry import clamp


def build_tracking(m: Match, t0: float, t1: float):
    """Tracking frames (dicts following tracking.schema.json) for t0 <= t < t1."""
    bt = [w[0] for w in m.ball_path]
    carry_t = [c[0] for c in m.carry]
    poss_t = [p[0] for p in m.poss]
    period_bounds = [(p["start"], p["end"], p["period"]) for p in m.periods]

    def ball_at(t):
        # Linear interpolation between ball waypoints.
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
            # A gentle wobble so players are never perfectly still.
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
            # Before a kickoff everyone except the taker stays in his own half.
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
