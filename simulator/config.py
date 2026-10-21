"""Constants shared by the event and movement layers.

Pitch geometry, position groups, probability profiles and the real-football
norms the realism report checks against. Teams live in simulator/teams/*.json.
"""

from __future__ import annotations

L, W = 105.0, 68.0          # pitch length and width in meters
FPS = 25
GOAL_HALF = 3.66            # half the goal width
BALL_GROUND = 0.11          # ball center height when rolling

# Position -> line. The line decides formation behavior (how deep a player
# drops, who takes corners, who the keeper is).
# Covers every position in match_info.schema.json.
GROUP = {"GK": "gk", "RB": "def", "CB": "def", "LB": "def", "RWB": "def", "LWB": "def",
         "DM": "mid", "CM": "mid", "AM": "mid", "RM": "mid", "LM": "mid",
         "RW": "fwd", "LW": "fwd", "ST": "fwd", "CF": "fwd"}
# Positions that take corners (wide players); falls back to the nearest player.
WIDE = ("RW", "LW", "RM", "LM", "AM", "RWB", "LWB")
MIN_X = {"gk": 1, "def": 6, "mid": 14, "fwd": 22}     # deepest a line drops (team frame)

# Probabilities. "short" boosts rare events so a 10-minute sample covers them all.
#   challenge             chance a dribble is challenged by an opponent
#   foul_given_challenge  share of challenges that are fouls
#   yellow / red          card chances per foul
#   offside               chance a forward ball in behind is flagged
#   shot_boost            multiplier on shot weights near goal
#   subs_per_team         substitutions each team makes (58'-82')
PROFILES = {
    "full": dict(challenge=0.26, foul_given_challenge=0.33, yellow=0.12, red=0.004,
                 offside=0.06, shot_boost=1.0, subs_per_team=3),
    "short": dict(challenge=0.19, foul_given_challenge=0.50, yellow=0.40, red=0.25,
                  offside=0.30, shot_boost=2.5, subs_per_team=1),
}

# --------------------------------------------------------------------------
# Team styles (team JSON: "style"). Every knob is relative to "balanced",
# which is neutral: all multipliers 1, no shifts, no pressing. A team plays
# its style the whole match.
#
#   weights     multipliers on the ball carrier's action weights in
#               Match.step() (short, long, through, cross, dribble, shot)
#   transition  extra multipliers for the first TRANSITION_S seconds after
#               winning the ball (a counter-attacking team goes forward fast)
#   tempo       multiplier on how long the carrier holds the ball before
#               acting (> 1 = patient build-up, < 1 = quick play)
#   line        defensive line height: meters the outfield block is pushed
#               up (+) or dropped (-) from its formation slots while the
#               OTHER team has the ball (in possession the team keeps its
#               formation shape). A high line is
#               easier to beat in behind: the OPPONENT's offside chance and
#               through-ball success both grow with it (LINE_OFFSIDE,
#               LINE_THROUGH per meter)
#   press       pressing intensity 0-1, applied when the team does NOT have
#               the ball:
#                 event layer: opponent dribbles are challenged more often
#                   (x (1 + PRESS_CHALLENGE * press)) and opponent short
#                   passes fail more often (- PRESS_PASS * press success)
#                 movement layer: round(PRESSERS * press) players close down
#                   the ball carrier, stopping PRESS_STANDOFF m from the ball
# --------------------------------------------------------------------------
STYLES = {
    "balanced": dict(weights={}, transition={}, tempo=1.0, line=0.0, press=0.0),
    # Quick short passing, few long balls, a slightly high block.
    "possession": dict(weights={"short": 1.3, "long": 0.6, "through": 0.8, "dribble": 0.85},
                       transition={}, tempo=0.9, line=3.0, press=0.3),
    # Sit deep, win it, then go forward fast with through balls and long passes.
    "counter": dict(weights={"long": 1.15},
                    transition={"through": 2.0, "long": 1.3, "dribble": 1.3},
                    tempo=1.0, line=-5.0, press=0.1),
    # High line, hunt the ball in packs, play quickly once it is won.
    "pressing": dict(weights={"through": 1.1}, transition={"through": 1.3},
                     tempo=0.85, line=5.0, press=0.6),
    # Long balls and crosses early, little build-up.
    "direct": dict(weights={"long": 2.0, "cross": 1.3, "short": 0.9},
                   transition={}, tempo=0.85, line=0.0, press=0.4),
}
TRANSITION_S = 8.0
LINE_OFFSIDE = 0.08         # opponent offside chance x (1 + 0.08 per meter of line height)
LINE_THROUGH = 0.015        # opponent through-ball success x (1 + 0.015 per meter)
PRESS_CHALLENGE = 0.6       # challenge chance x (1 + 0.6 * press)
PRESS_PASS = 0.03           # opponent short-pass success - 0.03 * press
PRESSERS = 3                # players closing down the carrier at press = 1
PRESS_STANDOFF = 3.5        # m; pressers stay this far from the ball (the carrier stays nearest)

# --------------------------------------------------------------------------
# Player attributes (team JSON, per player: passing, shooting, pace,
# tackling; 0-100, missing = 70). 70 is the league average and neutral: a
# player rated 70 plays exactly like the base model. Ratings follow the
# position (forwards shoot better than defenders, defenders tackle better),
# so what matters for match totals is the rating of the players who
# actually make each action: the team files are tuned so the realism report
# stays inside the norms, and each attribute's outfield average must stay
# within ATTR_TEAM_MEAN.
#
#   passing   pass-like deliveries: success chance + 0.004 per point over 70
#   shooting  goal chance x (1 + 0.015 per point) (penalties: 0.005 per point)
#   tackling  share of challenges won by the defender + 0.004 per point
#   pace      planned-run speed 9.5 + 0.03 per point m/s (max 10.4 at 100);
#             with the ball 10.5 + 0.005 per point (max 10.65)
# --------------------------------------------------------------------------
ATTRS = ("passing", "shooting", "pace", "tackling")
ATTR_NEUTRAL = 70
ATTR_TEAM_MEAN = (60, 80)
PASS_PER_POINT = 0.004
SHOT_PER_POINT = 0.015
PENALTY_PER_POINT = 0.005
TACKLE_PER_POINT = 0.004
SPRINT_BASE, SPRINT_PER_POINT = 9.5, 0.03
CARRY_BASE, CARRY_PER_POINT = 10.5, 0.005

# A failed pass cut out in the first 30% of its path is recorded as a
# possession_change (interception) only if the defender's position was within
# this many meters of the cut-out point. Otherwise it is just a failed pass.
INTERCEPT_REACH = 10.0

ALL_TYPES = ["kickoff", "pass", "possession_change", "clearance", "throw_in", "shot",
             "free_kick", "foul", "goal_kick", "corner", "substitution", "offside",
             "yellow_card", "red_card", "goal", "half_time", "full_time"]

# Typical counts per 90 minutes, both teams combined (approximate norms).
NORMS = {"pass": (850, 1050), "possession_change": (45, 80), "clearance": (25, 55),
         "throw_in": (35, 50), "shot": (20, 30), "free_kick": (18, 30), "foul": (18, 26),
         "goal_kick": (14, 22), "corner": (8, 13), "offside": (3, 6), "goal": (1, 5)}
