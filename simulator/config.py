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
GROUP = {"GK": "gk", "RB": "def", "CB": "def", "LB": "def", "DM": "mid", "CM": "mid",
         "AM": "mid", "RM": "mid", "LM": "mid", "RW": "fwd", "LW": "fwd", "ST": "fwd"}
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

ALL_TYPES = ["kickoff", "pass", "possession_change", "clearance", "throw_in", "shot",
             "free_kick", "foul", "goal_kick", "corner", "substitution", "offside",
             "yellow_card", "red_card", "goal", "half_time", "full_time"]

# Typical counts per 90 minutes, both teams combined (approximate norms).
NORMS = {"pass": (850, 1050), "possession_change": (45, 80), "clearance": (25, 55),
         "throw_in": (35, 50), "shot": (20, 30), "free_kick": (18, 30), "foul": (18, 26),
         "goal_kick": (14, 22), "corner": (8, 13), "offside": (3, 6), "goal": (1, 5)}
