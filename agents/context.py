"""Why a moment matters, as words the explainer can use: no numbers, so nothing to verify.

`moment_context` looks only at the past (the events before this one and the score), so it
works the same live. Every label is computed by code; the LLM only turns them into prose.

    goal_effect     opener | equaliser | go_ahead | extends_lead | pulls_one_back  (goals only)
    score_situation leading | level | trailing        (acting team, after the event)
    lead_in         counter_attack | set_piece | patient_build_up                (how it came about)
    momentum        team_on_top | opponent_on_top | balanced                      (last 5 minutes)
    phase           early | before_half_time | late
"""

from __future__ import annotations

from collections import deque

from .stats import MatchState, display_minute, other

LOOKBACK_S = 30.0
COUNTER_S = 12.0      # a shot or goal this soon after winning the ball is a counter-attack
SET_PIECE_S = 10.0
BUILD_UP_PASSES = 6   # completed passes in a row by the same team
SET_PIECES = {"corner", "free_kick"}


def scoring_side(before: dict, after: dict) -> str | None:
    """The team whose score went up. Reliable for own goals, whatever `team` says."""
    for side in ("home", "away"):
        if after.get(side, 0) > before.get(side, 0):
            return side
    return None


def goal_effect(before: dict, after: dict, side: str) -> str:
    b_for, b_against = before[side], before[other(side)]
    a_for, a_against = after[side], after[other(side)]
    if b_for == b_against == 0:
        return "opener"
    if a_for == a_against:
        return "equaliser"
    if b_for == b_against:
        return "go_ahead"
    return "extends_lead" if b_for > b_against else "pulls_one_back"


def lead_in(e: dict, side: str, recent: deque) -> str | None:
    """How the attack came about, from the events just before `e` (oldest first)."""
    for p in reversed(recent):
        if p.get("team") != side:
            continue
        if p["type"] == "possession_change" and e["t"] - p["t"] <= COUNTER_S:
            return "counter_attack"
        if p["type"] in SET_PIECES and e["t"] - p["t"] <= SET_PIECE_S:
            return "set_piece"
    streak = 0
    for p in reversed(recent):
        if p["type"] in ("shot", "goal") and p.get("team") == side:
            continue
        if p["type"] == "pass" and p.get("team") == side and p.get("success"):
            streak += 1
            continue
        break
    return "patient_build_up" if streak >= BUILD_UP_PASSES else None


def phase(t: float, info: dict) -> str | None:
    minute = display_minute(t, info)
    periods = info.get("periods") or []
    first_half = t < (periods[1]["start"] if len(periods) == 2 else 45 * 60)
    if minute <= 10:
        return "early"
    if first_half and minute >= 40:  # includes first-half stoppage time (46', 47'...)
        return "before_half_time"
    if minute >= 80:
        return "late"
    return None


def moment_context(e: dict, score_before: dict, state: MatchState, recent: deque) -> dict:
    """Context labels for `e`. `state` already includes `e`; `recent` holds the events before it."""
    ctx: dict = {}
    side = e.get("team")
    if e["type"] == "goal":
        side = scoring_side(score_before, state.score) or side
        if side in ("home", "away"):
            ctx["goal_effect"] = goal_effect(score_before, state.score, side)
    if side in ("home", "away"):
        mine, theirs = state.score[side], state.score[other(side)]
        ctx["score_situation"] = "leading" if mine > theirs else ("trailing" if mine < theirs else "level")
        if e["type"] in ("shot", "goal"):
            how = lead_in(e, side, recent)
            if how:
                ctx["lead_in"] = how
        mom = state.momentum(e["t"])[side]
        ctx["momentum"] = "team_on_top" if mom >= 60 else ("opponent_on_top" if mom <= 40 else "balanced")
    p = phase(e["t"], state.info) if e["type"] not in ("half_time", "full_time") else None
    if p:
        ctx["phase"] = p
    return ctx


def remember(recent: deque, e: dict) -> None:
    """Add `e` to the look-back window and forget events older than LOOKBACK_S."""
    recent.append(e)
    while recent and recent[0]["t"] < e["t"] - LOOKBACK_S:
        recent.popleft()
