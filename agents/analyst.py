"""Analyst: the post-match tactical report. tactics.json + events + team sheet in, report.json out (#69).

    tactics.json ─► candidates ─► selection ─► analyst agent ─► verifier ─► fill ─► report.json
                    (code: one per   (code: salience,  (LLM: headline +   (code: as for the    (code:
                     topic, facts     coverage: hedge   insights in every   overlays, plus       numbers)
                     and labels)      or skip)          language, numbers   uncited claims and
                                                        as placeholders)    missing hedges)

- **Candidates** (code): one per topic the tactical facts can speak to: formation matchup, line height,
  compactness, attacking width, flank use, pressing height, directness, progression, and how a team's line
  moved after a goal or red card. Each cites its facts (tactics.json paths and values) and the event ids
  behind them, and carries `labels`, the code's reading in words ("higher_line": "away").
- **Coverage** (#69): an insight's coverage is the lowest coverage of its facts (agents/tactics.py). At
  COVERAGE_MIN or above it is said plainly. Below, it is hedged (the text must say so, the evidence shows the
  coverage), and only used to reach MIN_INSIGHTS; below HEDGE_MIN it is skipped. Skips are listed with why.
- **Text** (LLM): one call writes the headline and every insight in every language; the verifier checks each
  as it checks an overlay (no digit, known placeholders, units, number words, no player name), plus: no claim
  about a topic the insight does not cite, a hedge where coverage is low, every number with its noun, and (#79)
  every language saying the same of the same teams with the same placeholders. A part is kept only whole, in
  every language. One retry with the problems, then the code template (analyst_templates.py).
- **Numbers**: every value comes from tactics.json or the match stats (the score); `recheck` reads each one
  back from tactics.json before the report is written.

Usage:
    python -m agents.analyst DATA_DIR --tactics TACTICS [--backend mock|foundry] [--out DIR]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import analyst_templates, verifier
from .data_io import load_match, Match
from .fill import fill
from .llm import FoundryBackend, load_json_reply
from .stats import MatchState

COVERAGE_MIN = 0.6          # below: hedged, or skipped when there are enough insights without it
HEDGE_MIN = 0.3             # below: skipped
MIN_INSIGHTS, MAX_INSIGHTS = 3, 5
NOTABLE = 1.0               # salience from which an insight is worth saying beyond MIN_INSIGHTS
MIN_PASSES = 8              # a team's passes before its pass shares say anything
MIN_FINAL_THIRD_PASSES = 5  # a team's passes into the final third before its flank share does
MIN_REGAINS = 3             # both teams' regains before pressing height does
MIN_SEGMENT_S = 60.0        # each side of a goal or red card, before a before/after comparison does
LEVEL = {"defensive_line": 3.0, "compactness": 3.0, "width": 3.0,      # differences that read level:
         "directness": 5.0, "progression": 2, "pressing": 1}           # meters, points, counts
SCALE = {"defensive_line": 5.0, "compactness": 5.0, "width": 6.0,      # a difference worth NOTABLE
         "directness": 15.0, "progression": 3, "pressing": 2}
# Events at which an event fact's salience is full; below, it is scaled down (3 of 5 passes is a thin story).
FULL_SAMPLE = {"directness": 20, "progression": 20, "pressing": 8, "flanks": 10}
MAX_TEXT, MAX_TITLE, MAX_HEADLINE = 240, 50, 140
SIDES = ("home", "away")
# Fact name in tactics.json -> its kind, the topic words the verifier checks (verifier.TOPIC_TERMS).
KIND = {"shape": "shape", "defensive_line_m": "defensive_line", "compactness_m": "compactness",
        "attacking_width_m": "width", "final_third_flanks": "flanks", "regains": "pressing",
        "long_balls": "directness", "progressive_passes": "progression"}
# What each topic measures, for the model (no numbers: thresholds are in the evidence).
MEASURES = {
    "shape": "formation read from where the players stood on average, next to the team sheet's",
    "defensive_line": "mean distance of the back line from its own goal line while the other team has the ball",
    "compactness": "distance from the back line to the front line while the other team has the ball",
    "width": "distance between the widest and narrowest outfield players across the pitch in possession",
    "flanks": "where a team's passes into the final third ended: left, centre or right as it attacks; the share "
              "is of all those passes, the count is the passes to that flank only",
    "pressing": "ball regains in the final third (high), a team's pressing height",
    "directness": "share of a team's passes that were long balls",
    "progression": "completed passes that moved the ball well toward the opponent's goal",
    "change": "a team's defensive line height before and after a goal or red card",
}


@dataclass
class Fact:
    """One cited fact: where it is in tactics.json, its value there, and the placeholder that shows it."""

    ref: str                     # "<segment id>/<team>/<fact path, dotted>"
    field: str                   # the value's path inside the fact ("value", "value.high", "value_pct.left")
    label: str                   # what it is, for the evidence panel
    value: float | str | None
    coverage: float | None
    key: str | None = None       # placeholder key, when the text may show it
    n_frames: int | None = None
    n_events: int | None = None

    @property
    def kind(self) -> str:
        return KIND[self.ref.split("/")[2].split(".")[0]]

    def out(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None or k in ("value", "coverage")}


@dataclass
class Candidate:
    """A possible insight: the facts it cites and the code's reading of them."""

    topic: str
    team: str                    # home | away | both
    segment: str
    facts: list[Fact]
    labels: dict
    salience: float
    event_ids: list[str] = field(default_factory=list)
    hedged: bool = False

    @property
    def coverage(self) -> float:
        """The lowest coverage among the cited facts; unknown counts as none."""
        return min((f.coverage or 0.0) for f in self.facts)

    @property
    def values(self) -> dict:
        """The numbers the text may show: each cited fact with a placeholder, rounded for the screen."""
        return {f.key: shown(f.value) for f in self.facts if f.key}

    @property
    def kinds(self) -> set[str]:
        return {f.kind for f in self.facts}

    @property
    def key(self) -> tuple[str, str, str]:
        """One insight per topic (and team, for flanks; split event, for changes)."""
        return self.topic, self.segment, self.team if self.topic == "flanks" else ""


def shown(value):
    """A fact's value as the screen shows it: a whole number (meters, percent, count), or a string as it is."""
    return round(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else value


def lookup(tactics: dict, ref: str, path: str = "") -> object:
    """The object at `ref` in tactics.json (a fact), then at `path` inside it. KeyError when missing."""
    seg_id, side, fact_path = ref.split("/", 2)
    seg = next((s for s in tactics["segments"] if s["id"] == seg_id), None)
    if seg is None:
        raise KeyError(f"no segment {seg_id}")
    obj = seg["teams"][side]
    for part in [*fact_path.split("."), *(path.split(".") if path else [])]:
        obj = obj[part]
    return obj


def fact(tactics: dict, ref: str, field_: str, label: str, key: str | None = None, events: str | None = None) -> Fact:
    """A Fact read from tactics.json: its value, coverage and how many frames or events it rests on
    (`events`: the fact's list of event ids, by name)."""
    obj = lookup(tactics, ref)
    ev = obj.get(events) if events else None
    n_events = sum(len(v) for v in ev.values()) if isinstance(ev, dict) else (len(ev) if ev is not None else None)
    return Fact(ref, field_, label, lookup(tactics, ref, field_), obj.get("coverage"), key,
                obj.get("n_frames") if isinstance(obj.get("n_frames"), int) else None, n_events)


def _side_by(values: dict[str, float], level: float, larger: bool = True) -> str:
    """The side with the larger (or smaller) value, or "level" within `level`."""
    h, a = values["home"], values["away"]
    if abs(h - a) < level:
        return "level"
    return ("home" if h > a else "away") if larger else ("home" if h < a else "away")


def _sample(topic: str, n: int) -> float:
    """How much of its salience an event fact keeps on `n` events."""
    return min(1.0, n / FULL_SAMPLE[topic]) if topic in FULL_SAMPLE else 1.0


def _compare(tactics: dict, names: dict, topic: str, path: str, field_: str, key: str, label: str, what: str,
             larger: bool = True, events: str | None = None, event_ids=None) -> list[Candidate]:
    """A both-teams comparison of one fact on the whole clip (salience scaled by the smaller team's sample)."""
    facts = {s: fact(tactics, f"whole/{s}/{path}", field_, f"{names[s]}: {what}", f"{s}_{key}", events) for s in SIDES}
    if any(not isinstance(f.value, (int, float)) for f in facts.values()):
        return []
    vals = {s: f.value for s, f in facts.items()}
    labels = {label: _side_by(vals, LEVEL[topic], larger)}
    ids = [i for s in SIDES for i in (event_ids(s) if event_ids else [])]
    n = min((f.n_events or 0) for f in facts.values()) if events else 0
    return [Candidate(topic, "both", "whole", list(facts.values()), labels,
                      abs(vals["home"] - vals["away"]) / SCALE[topic] * _sample(topic, n), ids)]


def candidates(tactics: dict, match: Match) -> list[Candidate]:
    """Every insight the facts can support, with its salience (how much it says)."""
    names = {s: match.team_name(s) for s in SIDES}
    whole = next(s for s in tactics["segments"] if s["id"] == "whole")["teams"]
    out: list[Candidate] = []

    shapes = {s: fact(tactics, f"whole/{s}/shape.all", "value", f"{names[s]}: shape on the pitch", f"{s}_shape")
              for s in SIDES}
    if all(f.value for f in shapes.values()):
        labels, facts = {}, list(shapes.values())
        for s in SIDES:
            sheet = whole[s]["shape"]["all"]["team_sheet"]
            labels[f"{s}_as_sheet"] = sheet in (None, shapes[s].value)
            if not labels[f"{s}_as_sheet"]:
                facts.append(fact(tactics, f"whole/{s}/shape.all", "team_sheet", f"{names[s]}: shape on the team sheet",
                                  f"{s}_sheet_shape"))
        out.append(Candidate("shape", "both", "whole", facts, labels,
                             0.8 + 0.8 * sum(not v for v in labels.values())))

    out += _compare(tactics, names, "defensive_line", "defensive_line_m.out_of_possession", "value", "line_m",
                    "higher_line", "defensive line, out of possession (m from own goal)")
    out += _compare(tactics, names, "compactness", "compactness_m.out_of_possession", "value", "compact_m",
                    "more_compact", "back line to front line, out of possession (m)", larger=False)
    out += _compare(tactics, names, "width", "attacking_width_m", "value", "width_m", "wider",
                    "attacking width, in possession (m)")

    if all(whole[s]["long_balls"]["of"] >= MIN_PASSES for s in SIDES):
        out += _compare(tactics, names, "directness", "long_balls", "value_pct", "long_pct", "more_direct",
                        "long balls (passes over 30 m), % of passes", events="event_ids",
                        event_ids=lambda s: whole[s]["long_balls"]["event_ids"])
        out += _compare(tactics, names, "progression", "progressive_passes", "value", "progressive",
                        "more_progressive", "progressive passes (completed)", events="event_ids",
                        event_ids=lambda s: whole[s]["progressive_passes"]["event_ids"])

    if sum(n for s in SIDES for n in whole[s]["regains"]["value"].values()) >= MIN_REGAINS:
        out += _compare(tactics, names, "pressing", "regains", "value.high", "high_regains", "more_high_regains",
                        "regains in the final third", events="event_ids",
                        event_ids=lambda s: [i for ids in whole[s]["regains"]["event_ids"].values() for i in ids])

    for s in SIDES:
        passes = whole[s]["final_third_flanks"]["passes"]
        total = sum(passes["count"].values())
        if total < MIN_FINAL_THIRD_PASSES:
            continue
        flank = max(("left", "centre", "right"), key=lambda w: (passes["count"][w], w == "centre"))
        ref = f"whole/{s}/final_third_flanks.passes"
        facts = [fact(tactics, ref, f"value_pct.{flank}",
                      f"{names[s]}: share of its passes into the final third that went to the {flank}",
                      f"{s}_flank_pct", "event_ids"),
                 fact(tactics, ref, f"count.{flank}", f"{names[s]}: passes into the final third to the {flank}",
                      f"{s}_passes_to_flank", "event_ids")]
        out.append(Candidate("flanks", s, "whole", facts, {"flank": flank},
                             (facts[0].value - 100 / 3) / 20 * _sample("flanks", total),
                             [i for ids in passes["event_ids"].values() for i in ids]))

    out += _changes(tactics, match, names)
    return out


def _changes(tactics: dict, match: Match, names: dict) -> list[Candidate]:
    """For each goal or red card that splits the clip: the team whose line moved most, before against after."""
    by_id = {e["id"]: e for e in match.events}
    out = []
    for seg in tactics["segments"]:
        split = seg.get("split_by")
        if not seg["id"].startswith("after_") or split not in by_id:
            continue
        before = next(s for s in tactics["segments"] if s["id"] == f"before_{split}")
        if min(seg["end"] - seg["start"], before["end"] - before["start"]) < MIN_SEGMENT_S:
            continue
        e = by_id[split]
        best = None
        for s in SIDES:
            path = f"{s}/defensive_line_m.out_of_possession"
            b = fact(tactics, f"before_{split}/{path}", "value", f"{names[s]}: defensive line before (m)", "line_before_m")
            a = fact(tactics, f"after_{split}/{path}", "value", f"{names[s]}: defensive line after (m)", "line_after_m")
            if isinstance(a.value, (int, float)) and isinstance(b.value, (int, float)):
                diff = a.value - b.value
                if best is None or abs(diff) > abs(best[0]):
                    best = (diff, s, [b, a])
        if best is None or e.get("team") not in SIDES:
            continue
        diff, s, facts = best
        moved = "level" if abs(diff) < LEVEL["defensive_line"] else ("higher" if diff > 0 else "deeper")
        out.append(Candidate("change", s, seg["id"], facts, {"event": e["type"], "by": e["team"], "moved": moved},
                             0.5 + abs(diff) / 4, [split]))
    return out


def select(cands: list[Candidate]) -> tuple[list[Candidate], list[dict]]:
    """The insights to write, most telling first, and the skipped ones with why. Confident insights (coverage
    at least COVERAGE_MIN) first, up to MAX_INSIGHTS while notable; hedged ones only to reach MIN_INSIGHTS."""
    ranked, seen, dupes = [], set(), []
    for c in sorted(cands, key=lambda c: -c.salience):
        (dupes if c.key in seen else ranked).append(c)
        seen.add(c.key)
    confident = [c for c in ranked if c.coverage >= COVERAGE_MIN]
    picked = [c for c in confident if c.salience >= NOTABLE][:MAX_INSIGHTS]
    picked += [c for c in confident if c not in picked][:max(0, MIN_INSIGHTS - len(picked))]
    for c in [c for c in ranked if HEDGE_MIN <= c.coverage < COVERAGE_MIN][:max(0, MIN_INSIGHTS - len(picked))]:
        c.hedged = True
        picked.append(c)
    skipped = []
    for c in ranked + dupes:
        if c in picked:
            continue
        why = ("coverage below the hedge floor: too little of the clip seen" if c.coverage < HEDGE_MIN else
               "coverage below the threshold, and enough insights without it" if c.coverage < COVERAGE_MIN else
               "same topic as a stronger insight" if c in dupes else "less telling than the insights shown")
        skipped.append({"topic": c.topic, "team": c.team, "segment": c.segment, "coverage": round(c.coverage, 3),
                        "salience": round(c.salience, 2), "reason": why})
    return picked, skipped


def insight_request(i: int, c: Candidate) -> dict:
    """What the analyst agent sees for one insight (labels name sides; prompt_view names the teams)."""
    return {"id": f"i{i}", "topic": c.topic, "team": c.team, "measures": MEASURES[c.topic],
            "segment": c.segment, "labels": c.labels, "hedged": c.hedged, "values": c.values,
            "placeholders": [f"{{{k}}}" for k in c.values], "nouns": {f.key: f.label for f in c.facts if f.key},
            "cites": sorted(c.kinds)}


def build_request(picked: list[Candidate], match: Match, langs: list[str], score: dict) -> dict:
    """The whole report request: headline (score + the top insight's values) and every insight."""
    insights = [insight_request(i, c) for i, c in enumerate(picked, start=1)]
    values = {"score_home": score["home"], "score_away": score["away"], **(insights[0]["values"] if insights else {})}
    return {"langs": langs, "home": match.team_name("home"), "away": match.team_name("away"),
            "headline": {"values": values, "placeholders": ["{score}"] + [f"{{{k}}}" for k in values
                                                                          if k not in ("score_home", "score_away")],
                         "nouns": {"score": "the score", **(insights[0]["nouns"] if insights else {})},
                         "top": insights[0] if insights else None, "cites": sorted({k for c in picked for k in c.kinds})},
            "insights": insights}


ANALYST_INSTRUCTIONS = f"""You are a football analyst writing the post-match tactical report for a broadcast.
You get JSON: the two teams and a list of `insights`, each a finding computed by code from what a vision AI saw
in the clip: its `topic`, what it `measures`, `labels` (the code's reading: which team is higher, wider, more
direct...; "level" means no real difference) and `placeholders` (its numbers, mapped to how they read on
screen). Write, for every language in `langs`, a `headline` and a `title` and `text` for each insight.

What an insight may say:
- Only what its `labels` and `placeholders` say about this match. Do not bring in another topic: an insight on
  width says nothing about pressing, lines or long balls. The verifier rejects a claim about a topic the
  insight does not cite (`cites`).
- You may frame it with general football knowledge: what it usually means or allows ("a high line squeezes the
  space but leaves room in behind"), as long as it stays on the insight's topic and never states it as
  something that happened in this match beyond the labels.
- The headline says in one sentence why the clip went the way it did. It starts with the score line,
  "<home> {{score}} <away>:", then the first insight in a few words, naming the team it is about ("Bosphorus FC
  held a higher line", not "higher line"); no other topic than those the insights
  cite (headline `cites`). It may use "{{score}}" and the first insight's placeholders.
- If an insight is `hedged`, too little of the clip was seen to be sure: say so in its text ("seems",
  "appears", "on limited evidence"; tr "görünüyor", "sınırlı veriye göre"; es "parece", "con datos limitados").
  If it is not hedged, the evidence is good: state it plainly, without "limited" or "seems".
- Teams only: never name a player.

Numbers:
- Never write a digit, not even a formation ("4-3-3") or the score ("0-0": write "{{score}}"), and never a
  number in words ("two", "iki", "dos", "back four"). For both teams write "both teams", tr "takımlar" or
  "her takım" (never "iki takım"), es "ambos equipos" (never "los dos"). Write a number only as a key of the insight's `placeholders`, exactly as given
  ("{{home_line_m}}", "{{home_shape}}"). Fewer numbers beat a forced one.
- Every number reads with its noun: `placeholders` gives what each one is, in brackets. Write "{{away_flank_pct}}
  of their passes into the final third", "{{away_passes_to_flank}} passes"; never two numbers joined by a bare
  "and" or a count with no noun ("with 91% and 10 there", "%91 ve 10 burada", "91 % y 10 allí").
- Code replaces each placeholder with the number AND its unit or sign: "{{home_line_m}}" becomes "22 m",
  "{{home_long_pct}}" "25%" (tr "%25", es "25 %"). So never write a unit, "%", "yüzde", "por ciento" or
  "metre" next to a placeholder.
- Turkish: never put a case suffix on a placeholder ("{{score}}'lik" is wrong): rephrase. An apostrophe goes
  only after a name, never after a common word ("son üçte birlik bölgeye").

Length: headline at most {MAX_HEADLINE} characters, title at most {MAX_TITLE}, text at most {MAX_TEXT}, counted
with numbers filled in; aim for one or two sentences per text. No hashtags, no emoji. Titles start with a
capital letter, the rest lower case except names. No full stop at the end of a title.

Same meaning in every language: the headline and each insight say the same thing in en, tr and es, about the
same teams (if one language says "both teams", all do; if one names a single team, all name that team) and with
the same placeholders. The verifier rejects a headline or insight whose languages differ.

Style: write each language as a native analyst of that language would, not a translation of the English.
Football words: final third = tr "son üçte birlik bölge" / es "último tercio"; long ball = tr "uzun top" / es
"balón largo"; defensive line = tr "savunma hattı" / es "línea defensiva"; pressing = tr "pres" / es "presión";
width = tr "genişlik" / es "amplitud"; flank = tr "kanat" / es "banda". Before replying, check: no digit 0-9
anywhere outside a placeholder.

Reply with JSON only, no markdown:
{{"<lang>": {{"headline": "...", "insights": {{"<id>": {{"title": "...", "text": "..."}}, ...}}}}, ...}}"""


def prompt_view(req: dict) -> dict:
    """The request as the model sees it: sides named by team, each placeholder mapped to how it reads."""
    names = {"home": req["home"], "away": req["away"]}

    def named(v):
        return names.get(v, v) if isinstance(v, str) else v

    def item(x: dict) -> dict:
        view = {k: v for k, v in x.items() if k not in ("values", "placeholders", "nouns", "top")}
        view["team"] = named(x.get("team")) if x.get("team") != "both" else "both"
        view["labels"] = {k: named(v) for k, v in x.get("labels", {}).items()} if "labels" in x else None
        nouns = x.get("nouns", {})
        view["placeholders"] = {p: fill(p, x["values"], "en") + (f" ({nouns[p[1:-1]]})" if p[1:-1] in nouns else "")
                                for p in x["placeholders"]}
        return {k: v for k, v in view.items() if v is not None}

    return {"langs": req["langs"], "home": req["home"], "away": req["away"],
            "headline": item(req["headline"]), "insights": [item(i) for i in req["insights"]]}


class MockAnalyst:
    """Code templates: the whole pipeline offline."""

    name = "mock"

    async def write(self, req: dict, feedback: str | None = None) -> dict:
        names = {"home": req["home"], "away": req["away"]}
        return {lang: {"headline": analyst_templates.headline(req["headline"], lang, names) if req["insights"] else "",
                       "insights": {i["id"]: analyst_templates.render(i, lang, names) for i in req["insights"]}}
                for lang in req["langs"]}


class FoundryAnalyst:
    """The analyst agent on Microsoft Foundry (Agent Framework), sharing the explainer's cache and retry."""

    name = "foundry"

    def __init__(self, backend: FoundryBackend | None = None) -> None:
        self.backend = backend or FoundryBackend(instructions=ANALYST_INSTRUCTIONS, agent_name="analyst",
                                                 options={"response_format": {"type": "json_object"}})
        self.usage = self.backend.usage

    async def write(self, req: dict, feedback: str | None = None) -> dict:
        prompt = json.dumps(prompt_view(req), ensure_ascii=False)
        if feedback:
            prompt += f"\n\nYour previous answer was rejected by the verifier: {feedback}\nFix only those."
        return parse_reply(await self.backend.ask(prompt), req)


def parse_reply(raw: str, req: dict) -> dict:
    """{lang: {"headline", "insights": {id: {"title", "text"}}}} from the model's JSON; missing parts empty.
    A language left inside another by a misplaced brace ({"en": {..., "tr": {..., "es": {...}}}}) is still read."""
    data = load_json_reply(raw)

    def find(d, lang: str) -> dict:
        """`lang`'s part at the top of `d`, else nested in another language's."""
        if not isinstance(d, dict):
            return {}
        if isinstance(d.get(lang), dict):
            return d[lang]
        return next((p for k in req["langs"] if k != lang and (p := find(d.get(k), lang))), {})

    out = {}
    for lang in req["langs"]:
        part = find(data, lang)
        items = part.get("insights") if isinstance(part.get("insights"), dict) else {}
        out[lang] = {"headline": str(part.get("headline", "")),
                     "insights": {i["id"]: {"title": str((items.get(i["id"]) or {}).get("title", "")),
                                            "text": str((items.get(i["id"]) or {}).get("text", ""))}
                                  for i in req["insights"]}}
    return out


def check_item(title: str, text: str, item: dict, lang: str, match: Match, headline: bool = False) -> list[str]:
    """The verifier on one headline or insight in one language (raw, placeholder text)."""
    roster = {p["name"] for p in match.players.values()}
    teams = {match.team_name(s) for s in SIDES}
    problems = verifier.check(text, title, item["values"], {}, set(), roster, lang, name_players=False,
                              max_text=MAX_HEADLINE if headline else MAX_TEXT, max_title=MAX_TITLE)
    problems += verifier.uncited_claims(f"{title} {text}", set(item["cites"]), lang, teams)
    problems += verifier.bare_numbers(text, item["values"])
    score_line = f"{match.team_name('home')} {{score}} {match.team_name('away')}:"
    if headline and not text.startswith(score_line):
        problems.append(f"the headline starts with the score line '{score_line}', then the finding")
    if item.get("hedged"):
        problems += verifier.missing_hedge(text, lang)
    return problems


async def write_report_text(req: dict, match: Match, backend, log: dict) -> dict:
    """{lang: {"headline": str, "insights": {id: {"title", "text"}}}}, filled and verified: the backend's
    text, one retry for what the verifier rejected, then the code template. A part (the headline or an
    insight) is kept only whole: every language passes and all say the same of the same teams (#79)."""
    langs, items = req["langs"], {i["id"]: i for i in req["insights"]}
    names = {"home": req["home"], "away": req["away"]}
    head = {**req["headline"], "hedged": False}

    def item_of(part: str) -> dict:
        return head if part == "headline" else items[part]

    def raw_of(answer: dict, lang: str, part: str) -> dict:
        """The raw {"title", "text"} of one part ("headline" or an id) in one language."""
        a = answer.get(lang, {})
        if part == "headline":
            return {"title": "", "text": a.get("headline", "")}
        return (a.get("insights") or {}).get(part, {"title": "", "text": ""})

    def problems(answer: dict, part: str) -> dict[str, list[str]]:
        """lang -> the verifier's problems with this part in that language."""
        return {lang: check_item((r := raw_of(answer, lang, part))["title"], r["text"], item_of(part), lang, match,
                                 part == "headline") for lang in langs}

    def mismatch(raws: dict[str, dict]) -> list[str]:
        return verifier.language_mismatch({l: f"{r['title']} {r['text']}" for l, r in raws.items()}, names)

    def keep(part: str, raws: dict[str, dict]) -> None:
        for lang, raw in raws.items():
            out[lang][part] = {k: fill(raw[k], item_of(part)["values"], lang) for k in ("title", "text")}

    def rejected(part: str, p: dict[str, list[str]], raws: dict[str, dict]) -> dict[str, list[str]]:
        """'lang/part' -> problems, the languages' disagreement under 'all/part'."""
        found = {f"{l}/{part}": v for l, v in p.items() if v}
        if not found and (m := mismatch(raws)):
            found[f"all/{part}"] = m
        return found

    parts = (["headline"] if req["insights"] else []) + list(items)
    out = {lang: {} for lang in langs}
    answer = await backend.write(req)
    bad = {}
    for part in parts:
        p, raws = problems(answer, part), {l: raw_of(answer, l, part) for l in langs}
        if found := rejected(part, p, raws):
            bad[part] = (p, raws, found)
        else:
            keep(part, raws)
    if bad:
        log["rejected"].append({"attempt": 1, "problems": {k: v for *_, f in bad.values() for k, v in f.items()}})
        feedback = "; ".join(f"[{key.split('/')[0]}] {part} "
                             + json.dumps(raws if key.startswith("all/") else raws[key.split("/")[0]], ensure_ascii=False)
                             + ": " + ", ".join(v) for part, (_, raws, found) in bad.items() for key, v in found.items())
        retry = await backend.write(req, feedback)
        still = {}
        for part, (p1, raws1, found1) in bad.items():
            p2, raws2 = problems(retry, part), {l: raw_of(retry, l, part) for l in langs}
            # The retry as one answer, else each language's first answer that passed, kept if they agree.
            mix = {l: raws1[l] if not p1[l] else raws2[l] for l in langs if not (p1[l] and p2[l])}
            for raws in (raws2 if not any(p2.values()) else None, mix if len(mix) == len(langs) else None):
                if raws and not mismatch(raws):
                    keep(part, raws)
                    log["fixed_on_retry"] += sum(1 for l in langs if p1[l]) or len(langs)
                    break
            else:
                still[part] = rejected(part, p2, raws2) or {f"all/{part}": mismatch(mix)}
        if still:
            log["rejected"].append({"attempt": 2, "problems": {k: v for f in still.values() for k, v in f.items()}})
        bad = still
    for part in bad:
        for lang in langs:
            if part == "headline":
                t = {"title": "", "text": analyst_templates.headline(req["headline"], lang, names)}
            else:
                t = analyst_templates.render(items[part], lang, names)
            p = check_item(t["title"], t["text"], item_of(part), lang, match, part == "headline")
            if p:
                log["dropped"].append({"lang": lang, "part": part, "problems": p})
            else:
                keep(part, {lang: t})
                log["template_fallbacks"] += 1
    return out


def recheck(report: dict, tactics: dict) -> list[str]:
    """Every fact read back from tactics.json, and every shown value against its fact: what the verifier
    recomputes before the report is written. An empty list means every number checks out."""
    problems = []
    for ins in report["insights"]:
        for f in ins["facts"]:
            try:
                value, cov = lookup(tactics, f["ref"], f["field"]), lookup(tactics, f["ref"]).get("coverage")
            except (KeyError, TypeError):
                problems.append(f"{ins['id']}: no fact {f['ref']} {f['field']} in tactics.json")
                continue
            if value != f["value"] or cov != f["coverage"]:
                problems.append(f"{ins['id']}: {f['ref']} {f['field']} is {value} (coverage {cov}) in tactics.json, "
                                f"not {f['value']} ({f['coverage']})")
            if f.get("key") and ins["values"].get(f["key"]) != shown(value):
                problems.append(f"{ins['id']}: {{{f['key']}}} shows {ins['values'].get(f['key'])}, its fact is {value}")
        if min((f["coverage"] or 0.0) for f in ins["facts"]) != ins["coverage"]:
            problems.append(f"{ins['id']}: coverage {ins['coverage']} is not its facts' lowest")
        if ins["hedged"] != (ins["coverage"] < COVERAGE_MIN):
            problems.append(f"{ins['id']}: hedged is {ins['hedged']} at coverage {ins['coverage']}")
    return problems


async def analyse(tactics: dict, match: Match, backend, langs: list[str]) -> tuple[dict, dict]:
    """(report.json object, log): the whole analyst stage on one clip."""
    state = MatchState(match.info)
    for e in match.events:
        state.update(e)
    picked, skipped = select(candidates(tactics, match))
    req = build_request(picked, match, langs, state.score)
    log = {"rejected": [], "fixed_on_retry": 0, "template_fallbacks": 0, "dropped": []}
    text = await write_report_text(req, match, backend, log)  # FoundryBackend.ask saves each new answer
    whole = next(s for s in tactics["segments"] if s["id"] == "whole")
    report = {
        "match_id": match.info["match_id"], "start": whole["start"], "end": whole["end"], "langs": langs,
        "coverage_min": COVERAGE_MIN,
        "headline": {lang: text[lang]["headline"]["text"] for lang in langs if "headline" in text[lang]},
        "insights": [{
            "id": i["id"], "topic": c.topic, "team": c.team, "segment": c.segment,
            "coverage": round(c.coverage, 3), "hedged": c.hedged,
            "title": {lang: text[lang][i["id"]]["title"] for lang in langs if i["id"] in text[lang]},
            "text": {lang: text[lang][i["id"]]["text"] for lang in langs if i["id"] in text[lang]},
            "values": i["values"], "facts": [f.out() for f in c.facts], "event_ids": list(dict.fromkeys(c.event_ids)),
        } for i, c in zip(req["insights"], picked)],
        "skipped": skipped,
    }
    log["recheck"] = recheck(report, tactics)
    return report, log


def main(argv: list[str] | None = None) -> int:
    """Write report.json (and analyst_report.json, the run log) for one clip."""
    ap = argparse.ArgumentParser(prog="python -m agents.analyst", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data", type=Path, help="folder with match_info.json and events.json")
    ap.add_argument("--tactics", type=Path, help="tactics.json (python -m agents.tactics; default DATA/tactics.json)")
    ap.add_argument("--backend", default="mock", choices=["mock", "foundry"])
    ap.add_argument("--langs", default="en,tr,es")
    ap.add_argument("--out", type=Path, help="output folder (default: data/generated/<data folder name>)")
    args = ap.parse_args(argv)
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    t0 = time.perf_counter()
    match = load_match(args.data)
    tactics = json.loads((args.tactics or args.data / "tactics.json").read_text(encoding="utf-8"))
    if tactics.get("match_id") not in (None, match.info["match_id"]):
        print(f"tactics.json is for {tactics['match_id']}, not {match.info['match_id']}", file=sys.stderr)
        return 1
    backend = MockAnalyst() if args.backend == "mock" else FoundryAnalyst()
    langs = [l.strip() for l in args.langs.split(",") if l.strip()]
    report, log = asyncio.run(analyse(tactics, match, backend, langs))
    if log["recheck"]:
        print("recheck failed, report not written:\n  " + "\n  ".join(log["recheck"]), file=sys.stderr)
        return 1
    out = args.out or Path("data/generated") / args.data.name
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    log.update(backend=backend.name, llm_usage=getattr(backend, "usage", None), seconds=round(time.perf_counter() - t0, 2))
    (out / "analyst_report.json").write_text(json.dumps(log, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    hedged = sum(i["hedged"] for i in report["insights"])
    print(f"{len(report['insights'])} insights ({hedged} hedged), {len(report['skipped'])} skipped; verifier: "
          f"{len(log['rejected'])} rejected attempts, {log['fixed_on_retry']} fixed on retry, "
          f"{log['template_fallbacks']} template fallbacks, {len(log['dropped'])} dropped")
    if log["llm_usage"]:
        u = log["llm_usage"]
        print(f"llm: {u['calls']} paid calls, {u['cached']} cached, {u['input_tokens']} input + "
              f"{u['output_tokens']} output tokens")
    print(f"wrote {out / 'report.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
