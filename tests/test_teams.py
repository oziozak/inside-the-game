"""Team files: all load, bad files are rejected, kits never clash."""

from __future__ import annotations

import copy
from itertools import permutations

import pytest

from simulator.teams import kit_clashes, list_teams, load_team, resolve_kits, validate_team


def test_all_teams_load_and_are_valid():
    keys = list_teams()
    assert {"bosphorus", "thames", "caldera", "saltmarsh"} <= set(keys)
    names = set()
    for k in keys:
        t = load_team(k)
        assert validate_team(t) == []
        names.add(t["name"])
    assert len(names) == len(keys)


def test_unknown_team_lists_available():
    with pytest.raises(ValueError, match="available: .*bosphorus"):
        load_team("no_such_team")


@pytest.mark.parametrize("breakage, message", [
    (lambda t: t["players"].pop(0), "exactly 11 starters"),
    (lambda t: t["players"][1].update(pos="GK"), "one starting goalkeeper"),
    (lambda t: t["players"][2].update(number=t["players"][1]["number"]), "unique"),
    (lambda t: t["players"][3].update(pos="SW"), "pos must be"),
    (lambda t: t["kit"].update(shirt="red"), "hex color"),
    (lambda t: t.update(formation="4-4-3"), "formation"),
    (lambda t: t["players"][4].pop("slot"), "slot"),
])
def test_validation_rejects_broken_teams(breakage, message):
    t = copy.deepcopy(load_team("bosphorus"))
    breakage(t)
    errors = validate_team(t)
    assert any(message in e for e in errors), errors


def test_no_kit_clash_in_any_pairing():
    for h, a in permutations(list_teams(), 2):
        home_kit, away_kit = resolve_kits(load_team(h), load_team(a))
        assert kit_clashes(home_kit, away_kit) == [], (h, a)


def test_away_team_switches_kit_on_clash():
    bos, cal = load_team("bosphorus"), load_team("caldera")     # red v orange
    home_kit, away_kit = resolve_kits(bos, cal)
    assert home_kit == bos["kit"] and away_kit == cal["away_kit"]
    home_kit, away_kit = resolve_kits(bos, load_team("thames"))  # red v blue: no change
    assert away_kit == load_team("thames")["kit"]
