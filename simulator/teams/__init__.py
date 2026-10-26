"""Team definitions: one JSON file per team in this folder.

The file name (without .json) is the team key used on the command line,
e.g. simulator/teams/bosphorus.json -> --home bosphorus.

A team file has:
    name, short (<= 4 letters), formation ("4-3-3"; outfield lines must add up to 10)
    style     optional key of config.STYLES (default "balanced")
    kit       {"shirt", "shorts", "goalkeeper"} hex colors
    away_kit  optional second kit, worn when the home kit clashes (see resolve_kits)
    players   list of {"number", "name", "pos", "starter"}; starters also have "slot".
              Optional attributes 0-100 (default 70): passing, shooting, pace, tackling

Slots are (x, y) in the TEAM frame: own goal at x = 0, attacking toward
x = 105, with the ball at the center spot. Facing +x, the team's right side
is low y. Substitutes have no slot; they take over the slot of the player
they replace.

All teams and players are fictional.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

from ..config import ATTR_NEUTRAL, ATTR_TEAM_MEAN, ATTRS, GROUP, STYLES, L, W

TEAMS_DIR = Path(__file__).resolve().parent
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

# Kit clash thresholds: Euclidean distance in RGB (0-441). The vision AI tells
# teams apart by shirt color, so outfield shirts must be clearly different;
# a keeper only needs to stand out from the other team's shirts and keeper.
SHIRT_CLASH = 140
KEEPER_CLASH = 100


def list_teams() -> list[str]:
    """Keys of all teams available in simulator/teams/, sorted."""
    return sorted(p.stem for p in TEAMS_DIR.glob("*.json"))


def load_team(key: str) -> dict:
    """Load and validate one team by key (file name without .json).

    Raises ValueError for an unknown key or an invalid team file."""
    path = TEAMS_DIR / f"{key}.json"
    if not path.exists():
        raise ValueError(f"unknown team {key!r}; available: {', '.join(list_teams())}")
    team = json.loads(path.read_text(encoding="utf-8"))
    errors = validate_team(team)
    if errors:
        raise ValueError(f"invalid team file {path.name}:\n  " + "\n  ".join(errors))
    team["key"] = key
    return team


def _check_kit(kit, label: str) -> list[str]:
    if not isinstance(kit, dict):
        return [f"{label} must be an object"]
    errs = []
    for part in ("shirt", "shorts", "goalkeeper"):
        if not HEX.match(str(kit.get(part, ""))):
            errs.append(f"{label}.{part} must be a hex color like #c8102e")
    return errs


def validate_team(team: dict) -> list[str]:
    """Problems with a team dict (empty list = valid)."""
    errs = []
    for k in ("name", "short", "formation", "kit", "players"):
        if k not in team:
            errs.append(f"missing {k!r}")
    if errs:
        return errs
    if not 1 <= len(team["short"]) <= 4:
        errs.append("short must be 1-4 characters")
    if team.get("style", "balanced") not in STYLES:
        errs.append(f"style must be one of {', '.join(STYLES)}")
    errs += _check_kit(team["kit"], "kit")
    if "away_kit" in team:
        errs += _check_kit(team["away_kit"], "away_kit")

    players = team["players"]
    numbers = [p.get("number") for p in players]
    if len(set(numbers)) != len(numbers):
        errs.append("shirt numbers must be unique")
    for p in players:
        who = f"player {p.get('number')} {p.get('name', '?')}"
        if not isinstance(p.get("number"), int) or not 1 <= p["number"] <= 99:
            errs.append(f"{who}: number must be an integer 1-99")
        if p.get("pos") not in GROUP:
            errs.append(f"{who}: pos must be one of {', '.join(GROUP)}")
        if not isinstance(p.get("starter"), bool):
            errs.append(f"{who}: starter must be true or false")
        for a in ATTRS:
            v = p.get(a, ATTR_NEUTRAL)
            if not isinstance(v, int) or not 0 <= v <= 100:
                errs.append(f"{who}: {a} must be an integer 0-100")
        if p.get("starter"):
            slot = p.get("slot")
            if not (isinstance(slot, list) and len(slot) == 2 and 0 <= slot[0] <= L
                    and 0 <= slot[1] <= W):
                errs.append(f"{who}: starters need a slot [x, y] on the pitch (team frame)")

    starters = [p for p in players if p.get("starter")]
    if len(starters) != 11:
        errs.append(f"need exactly 11 starters, found {len(starters)}")
    if sum(p.get("pos") == "GK" for p in starters) != 1:
        errs.append("need exactly one starting goalkeeper")
    if any(p.get("pos") == "GK" for p in players if not p.get("starter")):
        errs.append("substitute goalkeepers are not supported (keepers are never substituted)")
    outfield = [p for p in players if p.get("pos") != "GK"]
    lo, hi = ATTR_TEAM_MEAN
    for a in ATTRS:
        vals = [p.get(a, ATTR_NEUTRAL) for p in outfield if isinstance(p.get(a, ATTR_NEUTRAL), int)]
        if vals and not lo <= sum(vals) / len(vals) <= hi:
            errs.append(f"outfield average {a} must be {lo}-{hi} (keeps match totals realistic)")
    lines = str(team["formation"]).split("-")
    if not all(x.isdigit() for x in lines) or sum(int(x) for x in lines) != 10:
        errs.append("formation must be outfield lines adding up to 10, e.g. 4-3-3")
    return errs


def _rgb(hex_color: str) -> tuple[int, int, int]:
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


def color_distance(a: str, b: str) -> float:
    """Euclidean distance between two hex colors in RGB space (0-441)."""
    return math.dist(_rgb(a), _rgb(b))


def kit_clashes(home_kit: dict, away_kit: dict) -> list[str]:
    """Which colors of two kits are too similar to tell apart."""
    out = []
    if color_distance(home_kit["shirt"], away_kit["shirt"]) < SHIRT_CLASH:
        out.append("shirts")
    if color_distance(home_kit["goalkeeper"], away_kit["shirt"]) < KEEPER_CLASH:
        out.append("home keeper vs away shirts")
    if color_distance(away_kit["goalkeeper"], home_kit["shirt"]) < KEEPER_CLASH:
        out.append("away keeper vs home shirts")
    if color_distance(home_kit["goalkeeper"], away_kit["goalkeeper"]) < KEEPER_CLASH:
        out.append("keepers")
    return out


def resolve_kits(home: dict, away: dict) -> tuple[dict, dict]:
    """Kits worn in a match. Like in real football the home team always wears
    its home kit; the away team switches to its away_kit if the home kits
    clash. Raises ValueError if both away options clash."""
    if not kit_clashes(home["kit"], away["kit"]):
        return home["kit"], away["kit"]
    alt = away.get("away_kit")
    if alt and not kit_clashes(home["kit"], alt):
        return home["kit"], alt
    raise ValueError(f"kit clash between {home['name']} and {away['name']}: "
                     f"{', '.join(kit_clashes(home['kit'], alt or away['kit']))}")
