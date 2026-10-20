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
from typing import Iterator

from .config import FPS, L, W
from .engine import Match

JOG = 7.0       # m/s, moving with the team shape
SPRINT = 9.5    # m/s, a planned run (receiver, tackler, set-piece taker)
CARRY = 10.5    # m/s, the ball carrier keeping up with the ball


def _paint_runs(runs: list, n0: int, n1: int) -> dict[int, tuple]:
    """frame -> run target for one player, for frames n0 <= frame < n1.

    A run (r0, r1, x, y) is active at time t when r0 - 0.5 <= t <= r1 + 0.3
    (start a little early, arrive a little late). When runs overlap, the one
    planned first wins, so runs are painted last-to-first."""
    out: dict[int, tuple] = {}
    for r0, r1, rx, ry in reversed(runs):
        lo = max(n0, math.ceil((r0 - 0.5) * FPS) - 1)
        hi = min(n1 - 1, math.floor((r1 + 0.3) * FPS) + 1)
        for fr in range(lo, hi + 1):
            t = fr / FPS
            if r0 - 0.5 <= t <= r1 + 0.3:       # the exact test, safe at the edges
                out[fr] = (rx, ry)
    return out


def iter_tracking(m: Match, t0: float, t1: float) -> Iterator[dict]:
    """Yield tracking frames (dicts following tracking.schema.json) for
    t0 <= t < t1. The match must have been played (m.play())."""
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

    n0, n1 = int(round(t0 * FPS)), int(round(t1 * FPS))
    run_at = {pid: _paint_runs(runs, n0, n1) for pid, runs in m.runs.items()}
    kickoffs = [(kt, taker, period_at(kt)) for kt, taker in m.kickoffs]
    spans = list(m.spans.items())

    pos: dict[int, list] = {}
    last_period = None
    dt = 1 / FPS
    for fr in range(n0, n1):
        t = fr / FPS
        period = period_at(t)
        if period != last_period:                 # broadcast cuts at half-time: re-place everyone
            pos.clear()
            last_period = period
        bx, by, bz = ball_at(t)
        ref = ball_at(max(0.0, t - 0.8))[:2]       # shapes react with a small delay
        tp = team_poss_at(t)
        car = carrier_at(t)
        # Kickoff in the next 5 s: everyone except the taker waits in his own half.
        kick_takers = [k[1] for k in kickoffs if k[0] - 5 <= t <= k[0] and k[2] == period]
        players = []
        for pid, (on, off) in spans:
            if not (on <= t < off):
                pos.pop(pid, None)
                continue
            team = m.players[pid]["team"]
            # +1 if this team attacks toward x = 105 in this period.
            sign = 1 if (team == "home") == (period == 1) else -1
            tgt = m.slot_world(pid, ref, tp, period)
            # A gentle wobble so players are never perfectly still.
            wob = 0.8 * math.sin(0.4 * t + pid) , 0.8 * math.cos(0.33 * t + 2 * pid)
            tgt = (tgt[0] + wob[0], tgt[1] + wob[1])
            vmax = JOG
            run = run_at.get(pid)
            if run is not None and fr in run:
                tgt, vmax = run[fr], SPRINT
            if car == pid:
                back = 0.6 * sign
                tgt, vmax = (bx - back, by), CARRY
            if kick_takers and (car != pid) and pid not in kick_takers:
                # Same as the team-frame clamp x <= 51 (own half), in world coordinates.
                x, y = tgt
                tgt = (min(x, 51.0), y) if sign == 1 else (L - min(L - x, 51.0), W - (W - y))
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
            # Players may stand just off the pitch (throw-ins, walking on).
            px, py = p[0], p[1]
            px = px if px < L + 2 else L + 2
            px = px if px > -2 else -2
            py = py if py < W + 2 else W + 2
            py = py if py > -2 else -2
            p[0], p[1] = px, py
            players.append({"id": pid, "team": team, "pos": [round(px, 2), round(py, 2)]})
        yield {"match_id": m.match_id, "frame": fr, "t": round(t, 2), "period": period,
               "ball": [round(bx, 2), round(by, 2), round(bz, 2)], "players": players}


def build_tracking(m: Match, t0: float, t1: float) -> list[dict]:
    """All tracking frames for t0 <= t < t1 as a list (see iter_tracking)."""
    return list(iter_tracking(m, t0, t1))
