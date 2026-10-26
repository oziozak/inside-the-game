"""Verifier: checks every piece of LLM text before it can reach the screen.

The model writes placeholders (`{distance_m}`, `{score}`...), never digits; fill.py writes the
numbers. The verifier runs in two stages on one language of an answer:

Stage 1, on the raw model text:
1. Every placeholder is one this overlay knows (a `values` key, `minute`, `score`), written exactly.
   No digit outside a placeholder; the problem names the placeholder to use instead.

Stage 2, on the text after fill.py (what the viewer would see):
2. Text must be non-empty and short enough for a broadcast graphic, units included.
3. Every number must equal a number in the overlay's `values` or facts (minute, score).
   A safety net: with stage 1 passed, only the filler wrote numbers.
4. Every player name in the text must be a player involved in the cited event.

Returns a list of problems; an empty list means the text passed.
"""

from __future__ import annotations

import re

from .fill import PLACEHOLDER_RE, fill, known

MAX_TEXT_CHARS = 110
MAX_TITLE_CHARS = 40
NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
# What is left of a placeholder the model mistyped ("{ distance_m }", "{distance-m}", "{distance_m").
MALFORMED_RE = re.compile(r"\{[^{}]*\}?|\}")
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


def stray_digit_problem(raw: str, numbers: dict, allowed: str) -> str:
    """Tell the model which placeholder writes this number, or that no placeholder does.
    `numbers` maps each placeholder to its number (fill.known)."""
    n = round(float(raw.replace(",", ".")), 1)
    keys = [k for k, v in numbers.items()
            if any(n in (round(float(x), 1), float(round(x))) for x in (v if isinstance(v, tuple) else (v,)))]
    if keys:
        use = " or ".join(f"{{{k}}}" for k in keys)
        return f"digit {raw} outside a placeholder: write {use} instead (code adds the number and unit)"
    return f"digit {raw} outside a placeholder: no number of this graphic is {raw}, remove it (placeholders: {allowed})"


def check_raw(text: str, title: str, values: dict, facts: dict) -> list[str]:
    """Stage 1: the model's text before filling."""
    numbers = known(values, facts)
    allowed = ", ".join(f"{{{k}}}" for k in sorted(numbers)) or "none"
    raw = f"{title} {text}"
    problems = [f"unknown placeholder {{{key}}} (allowed: {allowed})"
                for key in dict.fromkeys(PLACEHOLDER_RE.findall(raw)) if key not in numbers]
    bare = PLACEHOLDER_RE.sub(" ", raw)
    problems += [f"malformed placeholder '{m}': write one exactly as listed, braces included ({allowed})"
                 for m in MALFORMED_RE.findall(bare)]
    return problems + [stray_digit_problem(n, numbers, allowed) for n in NUMBER_RE.findall(bare)]


def check_filled(text: str, title: str, values: dict, facts: dict, involved_names: set[str],
                 roster_names: set[str]) -> list[str]:
    """Stage 2: the text as the viewer would see it."""
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
        if name not in roster_names:
            problems.append(f"unknown player name '{name}'")
        elif name not in involved_names:
            problems.append(f"player '{name}' is not part of the cited event")
    return problems


def check(text: str, title: str, values: dict, facts: dict, involved_names: set[str],
          roster_names: set[str], lang: str) -> list[str]:
    """Both stages on one language of the model's raw (placeholder) text."""
    problems = check_raw(text, title, values, facts)
    if problems:
        return problems
    text, title = fill(text, values, lang, facts), fill(title, values, lang, facts)
    return check_filled(text, title, values, facts, involved_names, roster_names)
