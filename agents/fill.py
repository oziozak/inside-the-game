"""Placeholder filler: code, not the model, writes every number and unit on a graphic.

Text arrives with placeholders such as `{distance_m}` or `{score}`. `fill` replaces each with
the overlay's number, formatted for the language by the table below, then normalises the text
(one apostrophe character, single spaces, no space before punctuation).
Templates, the mock backend and the template fallback all go through here, so they format
numbers identically.
"""

from __future__ import annotations

import re

LANGS = ("en", "tr", "es")

# kind -> lang -> format; "{n}" is the number, "{h}"/"{a}" the home/away score.
FORMATS = {
    "distance": {"en": "{n} m", "tr": "{n} m", "es": "{n} m"},
    "speed": {"en": "{n} km/h", "tr": "{n} km/sa", "es": "{n} km/h"},
    "percentage": {"en": "{n}%", "tr": "%{n}", "es": "{n} %"},
    "score": {"en": "{h}-{a}", "tr": "{h}-{a}", "es": "{h}-{a}"},
    "difficulty": {"en": "{n}/10", "tr": "{n}/10", "es": "{n}/10"},
    "minute": {"en": "{n}'", "tr": "{n}'", "es": "{n}'"},
    "number": {"en": "{n}", "tr": "{n}", "es": "{n}"},
}
PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")
APOSTROPHE = "'"
OTHER_APOSTROPHES = re.compile("[’‘ʼ′`´]")
SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.!?:])")


# values key -> kind; keys not listed are plain numbers (counts such as shots_home, window_min).
KINDS = {
    "distance_m": "distance", "goal_distance_m": "distance", "progress_m": "distance",
    "speed_kmh": "speed",
    "momentum_home": "percentage", "momentum_away": "percentage",
    "score": "score", "difficulty": "difficulty", "minute": "minute",
}


class UnknownPlaceholder(ValueError):
    """A placeholder that is not a key of this overlay's `values` (nor minute or score)."""


def known(values: dict, facts: dict | None = None) -> dict:
    """Every placeholder this overlay may use -> its number: the `values` keys, plus `minute`
    and `score` (as (home, away)). `values` wins over the moment's facts."""
    pool = {**{k: (facts or {})[k] for k in ("minute", "score_home", "score_away") if k in (facts or {})}, **values}
    out = dict(values)
    if "minute" in pool:
        out["minute"] = pool["minute"]
    if "score_home" in pool and "score_away" in pool:
        out["score"] = (pool["score_home"], pool["score_away"])
    return out


def fill(text: str, values: dict, lang: str, facts: dict | None = None) -> str:
    """`text` with every placeholder replaced by its formatted number."""
    lang = lang if lang in LANGS else "en"
    nums = known(values, facts)

    def one(m: re.Match) -> str:
        key = m.group(1)
        if key not in nums:
            raise UnknownPlaceholder(f"unknown placeholder {{{key}}} (allowed: "
                                     + ", ".join(f"{{{k}}}" for k in sorted(nums)) + ")")
        kind = KINDS.get(key, "number")
        if kind == "score":
            h, a = nums[key]
            return FORMATS["score"][lang].format(h=h, a=a)
        return FORMATS[kind][lang].format(n=nums[key])

    return normalise(PLACEHOLDER_RE.sub(one, text))


def normalise(text: str) -> str:
    """One apostrophe character, single spaces, no space before , . ! ? : (Spanish ¡ ¿ stay)."""
    text = OTHER_APOSTROPHES.sub(APOSTROPHE, text)
    text = " ".join(text.split())
    return SPACE_BEFORE_PUNCT.sub(r"\1", text)
