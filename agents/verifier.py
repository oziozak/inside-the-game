"""Verifier: checks every piece of LLM text before it can reach the screen.

Rules (AGENTS.md: numbers come from code, every claim cites evidence):
1. Every number in the text must equal a number in the overlay's `values` or facts
   (minute, score). No invented stats.
2. Every player name in the text must be a player involved in the cited event.
3. Text must be non-empty and short enough for a broadcast graphic.

Returns a list of problems; an empty list means the text passed.
"""

from __future__ import annotations

import re

MAX_TEXT_CHARS = 110
MAX_TITLE_CHARS = 40
NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
NAME_RE = re.compile(r"\b[A-Z]\. [A-Z][a-zA-Z'-]+")  # roster names look like "K. Aydin"


def allowed_numbers(values: dict, facts: dict) -> set[float]:
    nums = set()
    for k, v in {**values, **{k: facts[k] for k in ("minute", "score_home", "score_away") if k in facts}}.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            nums.add(round(float(v), 1))
            nums.add(float(round(v)))
    return nums


def check(text: str, title: str, values: dict, facts: dict, involved_names: set[str],
          roster_names: set[str]) -> list[str]:
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

    for name in set(NAME_RE.findall(f"{title} {text}")):
        if name not in roster_names:
            problems.append(f"unknown player name '{name}'")
        elif name not in involved_names:
            problems.append(f"player '{name}' is not part of the cited event")
    return problems
