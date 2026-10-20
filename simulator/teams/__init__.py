"""Team definitions: one JSON file per team in this folder.

The file name (without .json) is the team key used on the command line,
e.g. simulator/teams/bosphorus.json -> --home bosphorus.

Slots are (x, y) in the TEAM frame: own goal at x = 0, attacking toward
x = 105, with the ball at the center spot. Facing +x, the team's right side
is low y. Substitutes have no slot; they take over the slot of the player
they replace.
"""

from __future__ import annotations

import json
from pathlib import Path

TEAMS_DIR = Path(__file__).resolve().parent


def list_teams() -> list[str]:
    """Keys of all teams available in simulator/teams/, sorted."""
    return sorted(p.stem for p in TEAMS_DIR.glob("*.json"))


def load_team(key: str) -> dict:
    """Load one team by key (file name without .json)."""
    path = TEAMS_DIR / f"{key}.json"
    if not path.exists():
        raise ValueError(f"unknown team {key!r}; available: {', '.join(list_teams())}")
    team = json.loads(path.read_text(encoding="utf-8"))
    team["key"] = key
    return team
