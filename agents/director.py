"""Director: decides WHICH moments get a graphic, WHEN, for HOW LONG, in WHICH mode.

Plain code on purpose: timing and screen-time budgets must be predictable during a live
broadcast. The LLM only writes the words afterwards (explainer.py).

Every decision is logged with a reason, so the director is explainable too
(`decisions` in the run report).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .data_io import Match
from .stats import PASS_TYPES, MatchState, event_facts

MODES = ("analyst", "casual", "player_focus")

# Share of screen time each mode may use (per position slot), and the lowest priority shown.
MODE_RULES = {
    "analyst": {"min_priority": 0.5, "max_share": 0.35},
    "casual": {"min_priority": 0.75, "max_share": 0.15},
    # player_focus overlays are filtered by player in the web player, so the budget is per player.
    "player_focus": {"min_priority": 0.4, "max_share": 0.40},
}
BUDGET_WINDOW_S = 300.0
MIN_GAP_S = 2.0

GRAPHIC_LAYOUT = {  # graphic -> (position, seconds on screen)
    "goal_banner": ("bottom-center", 8.0),
    "card_banner": ("top-right", 5.0),
    "stat_compare": ("bottom-center", 8.0),
    "momentum_bar": ("top-left", 6.0),
    "pass_card": ("bottom-left", 5.0),
    "shot_card": ("bottom-left", 5.0),
    "insight_text": ("bottom-right", 6.0),
}


@dataclass
class Candidate:
    """A moment worth a graphic, before any words are written."""

    event: dict
    graphic: str
    priority: float
    reason: str
    facts: dict
    values: dict  # numbers the graphic shows; copied from facts, never from the LLM
    modes: set = field(default_factory=set)
    start: float = 0.0
    duration: float = 5.0
    position: str = "bottom-left"

    @property
    def player(self) -> int | None:
        return self.event.get("from")


def _pick(f: dict, *keys: str) -> dict:
    return {k: f[k] for k in keys if k in f}


def propose(e: dict, f: dict) -> Candidate | None:
    """Rule table: event + facts -> candidate graphic (or None)."""
    typ, sub = e["type"], e.get("subtype")
    if typ == "goal":
        return Candidate(e, "goal_banner", 1.0, "goal", f, _pick(f, "score_home", "score_away", "minute"))
    if typ == "red_card":
        return Candidate(e, "card_banner", 0.95, "red card", f, _pick(f, "minute"))
    if typ == "yellow_card":
        return Candidate(e, "card_banner", 0.7, "yellow card", f, _pick(f, "minute"))
    if typ in ("half_time", "full_time"):
        return Candidate(e, "stat_compare", 0.9, typ.replace("_", " "), f, _pick(f, "score_home", "score_away"))
    if typ == "substitution":
        return Candidate(e, "insight_text", 0.55, "substitution", f, {})
    if typ == "shot":
        p = 0.85 if sub == "on_target" else 0.78
        return Candidate(e, "shot_card", p, f"shot ({sub or 'unknown'})", f, _pick(f, "speed_kmh", "goal_distance_m"))
    if typ == "possession_change" and f.get("zone") == "final_third":
        return Candidate(e, "insight_text", 0.6, f"{sub or 'ball win'} high up the pitch", f, {})
    if typ in PASS_TYPES and e.get("success") and "difficulty" in f:
        vals = _pick(f, "distance_m", "speed_kmh", "difficulty", "progress_m")
        if f.get("key_pass"):
            return Candidate(e, "pass_card", 0.8, "key pass (led to a shot)", f, vals)
        if f.get("into_box"):
            return Candidate(e, "pass_card", 0.7, "pass into the box", f, vals)
        if f["difficulty"] >= 7:
            return Candidate(e, "pass_card", 0.62, f"difficult pass ({f['difficulty']}/10)", f, vals)
        if f.get("into_final_third") and f.get("distance_m", 0) >= 25:
            return Candidate(e, "pass_card", 0.55, "long pass into the final third", f, vals)
        if f["difficulty"] >= 5:
            return Candidate(e, "pass_card", 0.42, "solid pass (player focus only)", f, vals)
    return None


def _timing(c: Candidate) -> None:
    """Show the graphic once the action has played out (ball arrived), not before."""
    position, duration = GRAPHIC_LAYOUT[c.graphic]
    c.position, c.duration = position, duration
    delay = c.event.get("duration_s", 0.0) + 0.3
    if c.graphic == "goal_banner":
        delay = 1.0
    c.start = round(c.event["t"] + delay, 2)


def momentum_candidates(match: Match, snapshots: list[tuple[float, dict, dict]]) -> list[Candidate]:
    """Every 5 minutes of play, show a momentum bar if one team clearly dominates (>= 65%)."""
    out, next_t = [], BUDGET_WINDOW_S
    for t, e, f in snapshots:
        if t < next_t or "momentum_home" not in f:
            continue
        next_t = t + BUDGET_WINDOW_S
        lead = max(f["momentum_home"], f["momentum_away"])
        if lead >= 65:
            side = "home" if f["momentum_home"] >= f["momentum_away"] else "away"
            fake_event = {**e, "team": side, "from": None, "duration_s": 0.0}
            c = Candidate(fake_event, "momentum_bar", 0.5, f"{side} dominating ({lead}%)", f,
                          _pick(f, "momentum_home", "momentum_away"), modes={"analyst"})
            out.append(c)
    return out


def direct(match: Match) -> tuple[list[Candidate], list[dict]]:
    """Run the director over a whole match. Returns accepted candidates + decision log."""
    state = MatchState(info=match.info)
    candidates, snapshots = [], []
    ev = match.events
    for i, e in enumerate(ev):
        state.update(e)
        f = event_facts(e, ev[i + 1:i + 6], state)
        snapshots.append((e["t"], e, f))
        c = propose(e, f)
        if c:
            c.modes = {m for m in MODES if c.priority >= MODE_RULES[m]["min_priority"]}
            candidates.append(c)
    candidates += momentum_candidates(match, snapshots)
    for c in candidates:
        _timing(c)
    return schedule(candidates)


def schedule(candidates: list[Candidate]) -> tuple[list[Candidate], list[dict]]:
    """Greedy by priority: accept a candidate in a mode unless it collides with an
    already-accepted graphic in the same slot or blows that mode's screen-time budget."""
    taken: dict[tuple, list[tuple[float, float]]] = {}
    log = []
    for c in sorted(candidates, key=lambda c: (-c.priority, c.start)):
        accepted = set()
        for mode in sorted(c.modes):
            slot = (mode, c.position) if mode != "player_focus" else (mode, c.player, c.position)
            busy = taken.setdefault(slot, [])
            s, end = c.start, c.start + c.duration
            if any(s < b_end + MIN_GAP_S and b_start < end + MIN_GAP_S for b_start, b_end in busy):
                log.append(_log(c, mode, "skipped", "slot busy"))
                continue
            window = [(bs, be) for bs, be in busy if s - BUDGET_WINDOW_S < bs <= s]
            used = sum(be - bs for bs, be in window) + c.duration
            if c.priority < 0.9 and used / BUDGET_WINDOW_S > MODE_RULES[mode]["max_share"]:
                log.append(_log(c, mode, "skipped", "screen-time budget"))
                continue
            busy.append((s, end))
            accepted.add(mode)
            log.append(_log(c, mode, "shown", c.reason))
        c.modes = accepted
    kept = sorted((c for c in candidates if c.modes), key=lambda c: c.start)
    log.sort(key=lambda d: d["t"])
    return kept, log


def _log(c: Candidate, mode: str, decision: str, why: str) -> dict:
    return {"t": c.start, "event_id": c.event.get("id"), "graphic": c.graphic, "mode": mode,
            "priority": c.priority, "decision": decision, "why": why}
