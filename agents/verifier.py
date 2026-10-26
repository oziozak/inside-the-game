"""Verifier: checks every piece of LLM text before it can reach the screen.

Rules (AGENTS.md: numbers come from code, every claim cites evidence):
1. Every number in the text must equal a number in the overlay's `values` or facts
   (minute, score). No invented stats.
2. Every player name in the text must be a player involved in the cited event. When naming is
   off (the vision AI is not sure who played the ball), no player name at all.
3. Text must be non-empty and short enough for a broadcast graphic.

Returns a list of problems; an empty list means the text passed.
"""

from __future__ import annotations

import re

MAX_TEXT_CHARS = 110
MAX_TITLE_CHARS = 40
NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
# Roster names look like "K. Aydin". Any script's letters, so "Ç. Uydurma" and "K. Aydın" are seen too.
NAME_RE = re.compile(r"\b([^\W\d_])\. ([^\W\d_][\w'’-]*)")
APOSTROPHES = "'’"


def names_in(s: str, roster_names: set[str]) -> set[str]:
    """Player-like names in `s`. A Turkish case suffix after an apostrophe ("K. Aydin'den")
    is stripped unless the full form is itself a roster name."""
    out = set()
    for m in NAME_RE.finditer(s):
        initial, surname = m.groups()
        if not (initial.isupper() and surname[0].isupper()):
            continue
        name = f"{initial}. {surname}".rstrip(APOSTROPHES + "-")
        while name not in roster_names and any(a in name for a in APOSTROPHES):
            name = name[:max(name.rfind(a) for a in APOSTROPHES)]  # drop the last suffix
        out.add(name)
    return out


def allowed_numbers(values: dict, facts: dict) -> set[float]:
    nums = set()
    # `values` wins over the moment's facts, as in fill.py.
    for k, v in {**{k: facts[k] for k in ("minute", "score_home", "score_away") if k in facts}, **values}.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            nums.add(round(float(v), 1))
            nums.add(float(round(v)))
    return nums


def check(text: str, title: str, values: dict, facts: dict, involved_names: set[str],
          roster_names: set[str], name_players: bool = True) -> list[str]:
    problems = []
    if not text.strip():
        problems.append("empty text")
    if len(text) > MAX_TEXT_CHARS:
        problems.append(f"text too long ({len(text)} > {MAX_TEXT_CHARS} chars)")
    if len(title) > MAX_TITLE_CHARS:
        problems.append(f"title too long ({len(title)} > {MAX_TITLE_CHARS} chars)")

    ok_nums = allowed_numbers(values, facts)
    for raw in NUMBER_RE.findall(f"{title} {text}"):
        n = round(float(raw.replace(",", ".")), 1)
        if n not in ok_nums:
            problems.append(f"number {raw} is not backed by the event data (allowed: {sorted(ok_nums)})")

    for name in names_in(f"{title} {text}", roster_names):
        if not name_players:
            problems.append(f"player '{name}' is named, but who played the ball is uncertain: name the team")
        elif name not in roster_names:
            problems.append(f"unknown player name '{name}'")
        elif name not in involved_names:
            problems.append(f"player '{name}' is not part of the cited event")
    return problems
