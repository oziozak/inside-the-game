"""Load the shared input files and write overlays.json."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Match:
    """Everything the agents read for one match."""

    info: dict
    events: list[dict]

    @property
    def players(self) -> dict[int, dict]:
        """Player id -> player dict (with an added 'team' key)."""
        out = {}
        for side in ("home", "away"):
            for p in self.info[side]["players"]:
                out[p["id"]] = {**p, "team": side}
        return out

    def team_name(self, side: str) -> str:
        return self.info[side]["name"] if side in ("home", "away") else ""

    def player_name(self, pid: int | None) -> str | None:
        if pid is None:
            return None
        p = self.players.get(pid)
        return p["name"] if p else None


def load_match(folder: str | Path) -> Match:
    """Read match_info.json and events.json from a data folder (e.g. data/fake/sample_a)."""
    folder = Path(folder)
    info = json.loads((folder / "match_info.json").read_text(encoding="utf-8"))
    events = json.loads((folder / "events.json").read_text(encoding="utf-8"))
    events.sort(key=lambda e: e["t"])
    return Match(info=info, events=events)


def write_overlays(overlays: list[dict], path: str | Path) -> None:
    """Write overlays sorted by start time, with fresh ids o0001, o0002, ..."""
    overlays = sorted(overlays, key=lambda o: (o["start"], -o.get("priority", 0)))
    for i, o in enumerate(overlays, start=1):
        o["id"] = f"o{i:04d}"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(overlays, ensure_ascii=False, indent=1), encoding="utf-8")
