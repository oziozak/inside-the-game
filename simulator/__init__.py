"""Match simulator: generates a fictional match (true events + 25 fps tracking).

Two layers:
    engine.Match            event layer (weighted dice + football rules)
    movement.build_tracking movement layer (positions per frame)

Quick use:
    from simulator import Match, build_tracking, load_team
    m = Match(7, 2700, "full", "m007", home=load_team("bosphorus"), away=load_team("thames"))
    m.play()
    frames = build_tracking(m, 0, m.t)
"""

from .engine import Match, generate
from .movement import build_tracking, iter_tracking
from .teams import list_teams, load_team

__all__ = ["Match", "generate", "build_tracking", "iter_tracking", "list_teams", "load_team"]
