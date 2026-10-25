"""Exact numbers, computed by code. The LLM never produces a number; it only gets these.

Two things live here:
- `event_facts(event, state)`: the numbers and flags about one event (distance, progress,
  difficulty, into the box...).
- `MatchState`: running totals updated event by event (score, shots, pass accuracy,
  momentum, per-player counts), so every fact is "as of that moment" and never uses the future.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field

PITCH_X, PITCH_Y = 105.0, 68.0
GOAL_Y = PITCH_Y / 2
MOMENTUM_WINDOW_S = 300.0  # last 5 minutes of play
PASS_TYPES = {"pass", "throw_in", "goal_kick", "corner", "free_kick", "kickoff"}


def other(side: str) -> str:
    return {"home": "away", "away": "home"}.get(side, "none")


def attacks_positive_x(side: str, period: int, info: dict) -> bool:
    """True if `side` attacks toward x = 105 in this period."""
    home_ltr = info.get("kickoff_direction", {}).get("home", "left_to_right") == "left_to_right"
    home_pos = home_ltr if period == 1 else not home_ltr
    return home_pos if side == "home" else not home_pos


def forward_x(x: float, side: str, period: int, info: dict) -> float:
    """x measured from the team's own goal line (0 = own goal, 105 = opponent goal)."""
    return x if attacks_positive_x(side, period, info) else PITCH_X - x


def display_minute(t: float, info: dict) -> int:
    """Broadcast minute: 1-based, second half continues from 46."""
    periods = info.get("periods") or []
    if len(periods) == 2 and t >= periods[1]["start"]:
        return 45 + int((t - periods[1]["start"]) // 60) + 1
    return int(t // 60) + 1


def zone(fx: float) -> str:
    """Third of the pitch, from the acting team's point of view."""
    return "defensive_third" if fx < 35 else ("middle_third" if fx < 70 else "final_third")


def in_box(fx: float, y: float) -> bool:
    return fx >= PITCH_X - 16.5 and abs(y - GOAL_Y) <= 20.16


def pass_difficulty(distance: float, speed: float, progress: float, subtype: str | None) -> int:
    """1-10 rating. Long, fast, forward, through/cross passes are harder. Deterministic."""
    score = 1.0 + distance / 8.0 + max(progress, 0) / 12.0 + max(speed - 40, 0) / 20.0
    score += {"through": 2.0, "cross": 1.5, "long": 0.5}.get(subtype or "", 0.0)
    return int(max(1, min(10, round(score))))


@dataclass
class TeamTotals:
    passes: int = 0
    passes_completed: int = 0
    shots: int = 0
    shots_on_target: int = 0
    goals: int = 0
    tackles_won: int = 0

    @property
    def pass_accuracy(self) -> int:
        return round(100 * self.passes_completed / self.passes) if self.passes else 0


@dataclass
class MatchState:
    """Running totals as of the last event fed in."""

    info: dict
    score: dict = field(default_factory=lambda: {"home": 0, "away": 0})
    teams: dict = field(default_factory=lambda: {"home": TeamTotals(), "away": TeamTotals()})
    players: dict = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))
    _recent: deque = field(default_factory=deque)  # (t, side, weight, event) for momentum

    def _trim(self, t: float) -> None:
        while self._recent and self._recent[0][0] < t - MOMENTUM_WINDOW_S:
            self._recent.popleft()

    def momentum(self, t: float) -> dict:
        """Share of attacking threat in the last 5 minutes, in percent, home + away = 100."""
        self._trim(t)
        return threat_share([(side, weight) for _, side, weight, _ in self._recent])

    def momentum_events(self, t: float) -> list[dict]:
        """The events behind momentum(t), oldest first: the evidence a momentum graphic cites."""
        self._trim(t)
        return [e for *_, e in self._recent]

    def update(self, e: dict) -> None:
        side, typ, t = e.get("team"), e["type"], e["t"]
        if side not in ("home", "away"):
            if e.get("score"):
                self.score = dict(e["score"])
            return
        team, pid = self.teams[side], e.get("from")
        pstats = self.players[pid] if pid is not None else defaultdict(int)

        if typ in PASS_TYPES and "end" in e:
            team.passes += 1
            pstats["passes"] += 1
            if e.get("success"):
                team.passes_completed += 1
                pstats["passes_completed"] += 1
        elif typ == "shot":
            team.shots += 1
            pstats["shots"] += 1
            if e.get("subtype") == "on_target":
                team.shots_on_target += 1
        elif typ == "goal":
            team.goals += 1
            pstats["goals"] += 1
        elif typ == "possession_change":
            team.tackles_won += 1
            pstats["ball_wins"] += 1
        weight = threat_weight(e, self.info)
        if weight:
            self._recent.append((t, side, weight, e))
        if e.get("score"):
            self.score = dict(e["score"])


def threat_weight(e: dict, info: dict) -> float:
    """How much an event adds to its team's momentum: a completed pass into the final third 1,
    a ball win in the final third 2, a shot 3, a goal 5, anything else 0."""
    side, typ = e.get("team"), e["type"]
    if side not in ("home", "away"):
        return 0.0
    period = e.get("period", 1)
    if typ in PASS_TYPES and "end" in e:
        return 1.0 if e.get("success") and forward_x(e["end"][0], side, period, info) >= 70 else 0.0
    if typ == "possession_change":
        return 2.0 if forward_x(e["start"][0], side, period, info) >= 70 else 0.0
    return {"shot": 3.0, "goal": 5.0}.get(typ, 0.0)


def threat_share(weighted: list[tuple[str, float]]) -> dict:
    """(side, weight) pairs -> percent of the threat per side, home + away = 100 (50/50 if none)."""
    w = {"home": 0.0, "away": 0.0}
    for side, weight in weighted:
        w[side] += weight
    total = w["home"] + w["away"]
    if total == 0:
        return {"home": 50, "away": 50}
    home = round(100 * w["home"] / total)
    return {"home": home, "away": 100 - home}


def event_facts(e: dict, state: MatchState) -> dict:
    """Numbers and flags about one event, as of that moment.

    `state` must already include this event (call state.update(e) first).
    """
    info = state.info
    side, typ = e.get("team", "none"), e["type"]
    period = e.get("period", 1)
    f: dict = {
        "minute": display_minute(e["t"], info),
        "score_home": state.score["home"],
        "score_away": state.score["away"],
    }
    if side not in ("home", "away"):
        if typ in ("half_time", "full_time"):
            for s in ("home", "away"):
                team = state.teams[s]
                f[f"shots_{s}"] = team.shots
                f[f"on_target_{s}"] = team.shots_on_target
        return f

    sx, sy = e["start"]
    fx = forward_x(sx, side, period, info)
    f["zone"] = zone(fx)

    if "distance_m" in e:
        f["distance_m"] = round(e["distance_m"])
    if "speed_kmh" in e:
        f["speed_kmh"] = round(e["speed_kmh"])

    if typ in PASS_TYPES and "end" in e:
        ex, ey = e["end"]
        end_fx = forward_x(ex, side, period, info)
        progress = end_fx - fx
        f["progress_m"] = round(progress)
        f["difficulty"] = pass_difficulty(e.get("distance_m", 0), e.get("speed_kmh", 0), progress, e.get("subtype"))
        f["into_final_third"] = bool(e.get("success")) and fx < 70 <= end_fx
        f["into_box"] = bool(e.get("success")) and in_box(end_fx, ey)
    elif typ == "shot":
        goal_x = PITCH_X if attacks_positive_x(side, period, info) else 0.0
        f["goal_distance_m"] = round(((sx - goal_x) ** 2 + (sy - GOAL_Y) ** 2) ** 0.5)

    team = state.teams[side]
    f["team_shots"] = team.shots
    f["team_pass_accuracy"] = team.pass_accuracy
    mom = state.momentum(e["t"])
    f["momentum_home"], f["momentum_away"] = mom["home"], mom["away"]
    pid = e.get("from")
    if pid is not None:
        ps = state.players[pid]
        f["player_passes"] = ps["passes"]
        f["player_passes_completed"] = ps["passes_completed"]
        f["player_shots"] = ps["shots"]
        f["player_goals"] = ps["goals"]
    return f
