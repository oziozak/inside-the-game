"""Director: decides WHICH moments get a graphic, WHEN, for HOW LONG, in WHICH mode.

Plain code on purpose: timing and screen-time budgets must be predictable during a live
broadcast. The LLM only writes the words afterwards (explainer.py).

Every decision is logged with a reason, so the director is explainable too
(`decisions` in the run report).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .context import moment_context, remember
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
SETUP_WINDOW_S = 6.0  # a pass is the setup of a shot if the receiver shoots within this time
# A graphic names an event's players only at or above this event `confidence`; below it the detection
# is too poor to trust who played the ball, so the graphic names the team. True events (1.0) are always
# named. Confidence measures detection, not identity: a safety floor, not a precision dial. Chosen on the
# dev clips only (agents/README.md, "Naming players"); test1 is held out.
NAME_MIN_CONFIDENCE = 0.55

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
    setup: dict | None = None  # the pass that set up a shot (shot_card only)
    context: dict = field(default_factory=dict)  # why it matters, as labels (context.py)
    key_events: list = field(default_factory=list)  # goals and red cards a recap names
    evidence: list = field(default_factory=list)  # events behind the values: recap shots, momentum window

    @property
    def player(self) -> int | None:
        """The player the graphic is about, or None when it may not name one (named_player)."""
        return named_player(self.event)

    @property
    def team_only(self) -> bool:
        """A team's event with no player to name (detected before the lineup is known, or the
        vision AI is not sure who played the ball): the graphic is worded about the team and
        gets no player_focus overlay."""
        return self.event.get("team") in ("home", "away") and self.player is None

    @property
    def player_uncertain(self) -> bool:
        """A player was detected, but not surely enough to name: the graphic names the team."""
        return self.team_only and self.event.get("from") is not None

    @property
    def event_ids(self) -> list[str]:
        """Evidence for the overlay: the setup pass, then the recapped moments and the events
        behind the values in time order, then the event itself (each id once)."""
        cited = ([self.setup] if self.setup else []) + sorted(self.key_events + self.evidence, key=lambda p: p["t"])
        ids = list(dict.fromkeys(p["id"] for p in cited))
        return ids + ([self.event["id"]] if self.event["id"] not in ids else [])


def named_player(e: dict) -> int | None:
    """The player a graphic may name for event `e` (its `from`), or None when it has none or the
    vision AI is not sure who it was. An event with no `confidence` is a true event."""
    return e.get("from") if e.get("confidence", 1.0) >= NAME_MIN_CONFIDENCE else None


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
        return Candidate(e, "stat_compare", 0.9, typ.replace("_", " "), f,
                         _pick(f, "score_home", "score_away", "shots_home", "shots_away",
                               "on_target_home", "on_target_away"))
    if typ == "substitution":
        return Candidate(e, "insight_text", 0.55, "substitution", f, {})
    if typ == "shot":
        p = 0.85 if sub == "on_target" else 0.78
        return Candidate(e, "shot_card", p, f"shot ({sub or 'unknown'})", f, _pick(f, "speed_kmh", "goal_distance_m"))
    if typ == "possession_change" and f.get("zone") == "final_third":
        return Candidate(e, "insight_text", 0.6, f"{sub or 'ball win'} high up the pitch", f, {})
    if typ in PASS_TYPES and e.get("success") and "difficulty" in f:
        vals = _pick(f, "distance_m", "speed_kmh", "difficulty", "progress_m")
        if f.get("into_box"):
            return Candidate(e, "pass_card", 0.7, "pass into the box", f, vals)
        if f["difficulty"] >= 9:  # top ~20% of the match's completed passes
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


def momentum_candidates(match: Match, snapshots: list[tuple[float, dict, dict, list[dict]]]) -> list[Candidate]:
    """Every 5 minutes of play, show a momentum bar if one team clearly dominates (>= 65%).
    The bar cites every event in the window that fed the percentages."""
    out, next_t = [], BUDGET_WINDOW_S
    for t, e, f, window in snapshots:
        if t < next_t or "momentum_home" not in f:
            continue
        next_t = t + BUDGET_WINDOW_S
        lead = max(f["momentum_home"], f["momentum_away"])
        if lead >= 65:
            side = "home" if f["momentum_home"] >= f["momentum_away"] else "away"
            fake_event = {**e, "team": side, "from": None, "duration_s": 0.0}
            c = Candidate(fake_event, "momentum_bar", 0.5, f"{side} dominating ({lead}%)", f,
                          _pick(f, "momentum_home", "momentum_away"), modes={"analyst"}, evidence=window)
            out.append(c)
    return out


def direct(match: Match) -> tuple[list[Candidate], list[dict]]:
    """Run the director over a whole match. Returns accepted candidates + decision log."""
    state = MatchState(info=match.info)
    candidates, snapshots = [], []
    last_pass_to: dict[int, dict] = {}  # receiver id -> last completed pass to them
    recent: deque = deque()  # events of the last 30 s, for the context labels
    key_events: list[dict] = []  # goals and red cards so far, for the half/full-time recap
    shots: list[dict] = []  # every shot so far: the evidence for the recap's shot counts
    for e in match.events:
        score_before = dict(state.score)
        state.update(e)
        f = event_facts(e, state)
        snapshots.append((e["t"], e, f, state.momentum_events(e["t"])))
        c = propose(e, f)
        if c:
            c.context = moment_context(e, score_before, state, recent)
            if c.graphic == "stat_compare":
                c.key_events, c.evidence = list(key_events), list(shots)
        remember(recent, e)
        if e["type"] in ("goal", "red_card"):
            key_events.append(e)
        if e["type"] == "shot":
            shots.append(e)
        if c and c.graphic == "shot_card":
            # Credit the setup on the shot card itself: a separate key-pass card would have
            # to wait for the shot and then fight it for the same slot.
            p = last_pass_to.get(e.get("from"))
            if p and p.get("team") == e.get("team") and e["t"] - p["t"] <= SETUP_WINDOW_S:
                c.setup = p
                c.reason += ", set up by a pass"
        if e["type"] in PASS_TYPES and e.get("success") and e.get("to") is not None:
            last_pass_to[e["to"]] = e
        if c:
            c.modes = {m for m in MODES if c.priority >= MODE_RULES[m]["min_priority"]
                       and not (m == "player_focus" and c.team_only)}
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
