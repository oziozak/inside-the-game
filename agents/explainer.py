"""Explainer + verifier loop: turns director candidates into finished overlays.

For each accepted (candidate, mode):
  1. build a request with facts and values (all computed by code),
  2. ask the explainer backend for title + text in every language,
  3. verify each language; on failure, retry ONCE with the verifier's feedback,
  4. if it still fails, fall back to the code template (and log it).
"""

from __future__ import annotations

import asyncio

from . import templates, verifier
from .data_io import Match
from .director import BUDGET_WINDOW_S, Candidate

FACT_KEYS = ("minute", "score_home", "score_away", "zone", "into_box",
             "into_final_third", "team_shots", "team_pass_accuracy")


def mode_values(c: Candidate, mode: str) -> dict:
    """Numbers drawn on the graphic for this mode. Casual viewers get fewer numbers."""
    v = dict(c.values)
    if c.graphic == "momentum_bar":
        v["window_min"] = int(BUDGET_WINDOW_S // 60)
    if "difficulty" in v:
        v["difficulty_max"] = 10  # so "7/10" is a backed number
    if mode == "casual":
        keep = {"pass_card": ("distance_m",), "shot_card": ("speed_kmh",),
                "stat_compare": ("score_home", "score_away")}.get(c.graphic)
        if keep:
            v = {k: v[k] for k in keep if k in v}
    if mode == "player_focus" and c.graphic == "pass_card":
        for k in ("player_passes", "player_passes_completed"):
            if k in c.facts:
                v[k] = c.facts[k]
    return v


def build_request(c: Candidate, mode: str, match: Match, langs: list[str]) -> dict:
    """What the explainer sees. A team-only candidate has no `actor`, `target` or `setup_by`:
    `subject` (the team) is who the text is about, so no player can be named."""
    e = c.event
    side = e.get("team")
    req = {
        "graphic": c.graphic,
        "mode": mode,
        "langs": langs,
        "event_type": e["type"],
        "subtype": e.get("subtype"),
        "success": e.get("success"),
        "why_selected": c.reason,
        "actor": match.player_name(e.get("from")),
        "actor_team": match.team_name(side) if side in ("home", "away") else None,
        "target": match.player_name(e.get("to")),
        "home": match.team_name("home"),
        "away": match.team_name("away"),
        "setup_by": match.player_name(c.setup["from"]) if c.setup else None,
        "key_moments": [{"type": k["type"], "player": match.player_name(k.get("from")),
                         "own_goal": k.get("subtype") == "own_goal"} for k in c.key_events],
        "context": c.context,
        "facts": {k: c.facts[k] for k in FACT_KEYS if k in c.facts},
        "values": mode_values(c, mode),
    }
    if c.team_only:
        for k in ("actor", "target", "setup_by"):
            del req[k]
        req["subject"] = req["actor_team"]
    return req


def involved_names(req: dict) -> set[str]:
    """The players a request's text may name: the ones it was given."""
    named = [req.get("actor"), req.get("target"), req.get("setup_by")] + [k["player"] for k in req["key_moments"]]
    return {n for n in named if n}


async def explain_one(c: Candidate, mode: str, match: Match, backend, langs: list[str],
                      report: dict) -> list[dict]:
    req = build_request(c, mode, match, langs)
    roster = {p["name"] for p in match.players.values()}
    involved = involved_names(req)

    def problems(out: dict, lang: str) -> list[str]:
        t = out.get(lang, {"title": "", "text": ""})
        return verifier.check(t["text"], t["title"], req["values"], c.facts, involved, roster)

    out = await backend.explain(req)
    bad = {lang: p for lang in langs if (p := problems(out, lang))}
    if bad:
        report["rejected"].append({"event_id": c.event.get("id"), "mode": mode, "attempt": 1,
                                   "problems": bad, "text": {l: out.get(l) for l in bad}})
        feedback = "; ".join(f"[{l}] " + ", ".join(p) for l, p in bad.items())
        retry = await backend.explain(req, feedback)
        for lang in list(bad):
            if not problems(retry, lang):
                out[lang] = retry[lang]
                report["fixed_on_retry"] += 1
                del bad[lang]
    for lang in bad:
        fallback = templates.render(req, lang)
        if problems({lang: fallback}, lang):
            report["dropped"].append({"event_id": c.event.get("id"), "mode": mode, "lang": lang})
            continue
        out[lang] = fallback
        report["template_fallbacks"] += 1

    overlays = []
    for lang in langs:
        if lang not in out or any(d["event_id"] == c.event.get("id") and d["mode"] == mode and d["lang"] == lang
                                  for d in report["dropped"]):
            continue
        overlays.append({
            "id": "o0000",
            "start": c.start,
            "duration": c.duration,
            "graphic": c.graphic,
            "event_ids": c.event_ids,
            "player": c.player,
            "priority": c.priority,
            "position": "follow-player" if mode == "player_focus" and c.graphic == "pass_card" else c.position,
            "title": out[lang]["title"],
            "text": out[lang]["text"],
            "values": req["values"],
            "mode": mode,
            "lang": lang,
        })
    return overlays


async def explain_all(candidates: list[Candidate], match: Match, backend, langs: list[str],
                      concurrency: int = 4) -> tuple[list[dict], dict]:
    report = {"rejected": [], "fixed_on_retry": 0, "template_fallbacks": 0, "dropped": []}
    sem = asyncio.Semaphore(concurrency)

    async def run(c: Candidate, mode: str) -> list[dict]:
        async with sem:
            return await explain_one(c, mode, match, backend, langs, report)

    jobs = [run(c, m) for c in candidates for m in sorted(c.modes)]
    results = await asyncio.gather(*jobs)
    if hasattr(backend, "save_cache"):
        backend.save_cache()
    return [o for batch in results for o in batch], report
