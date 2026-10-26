"""The analyst report (agents/analyst.py): candidates, coverage rule, verifier loop, numbers read back.

The tactical facts are schemas/examples/tactics.example.json (the dev1 clip's tactics.json); the coverage
cases change its coverage values. Nothing here calls Azure: the Foundry analyst gets a fake agent.
"""

import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from jsonschema import Draft202012Validator

from agents import analyst, analyst_templates, verifier
from agents.data_io import Match
from agents.llm import INSTRUCTIONS, FoundryBackend, cache_key

ROOT = Path(__file__).resolve().parents[2]
TACTICS = json.loads((ROOT / "schemas/examples/tactics.example.json").read_text("utf-8"))
INFO = json.loads((ROOT / "data/fake/sample_a/match_info.json").read_text("utf-8"))
REPORT_SCHEMA = Draft202012Validator(json.loads((ROOT / "schemas/report.schema.json").read_text("utf-8")))
TACTICS_SCHEMA = Draft202012Validator(json.loads((ROOT / "schemas/tactics.schema.json").read_text("utf-8")))
LANGS = ["en", "tr", "es"]


def match(events: list[dict] | None = None) -> Match:
    return Match(info=INFO, events=events or [])


def run(tactics: dict = TACTICS, backend=None, events=None) -> tuple[dict, dict]:
    return asyncio.run(analyst.analyse(tactics, match(events), backend or analyst.MockAnalyst(), LANGS))


def with_coverage(tactics: dict, cover) -> dict:
    """A copy of `tactics` with every fact's coverage replaced by cover(old coverage)."""
    t = copy.deepcopy(tactics)

    def walk(o):
        if isinstance(o, dict):
            if "coverage" in o:
                o["coverage"] = cover(o["coverage"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(t["segments"])
    return t


class FixedAnswers:
    """An analyst backend that answers from a list (then repeats the last), recording each feedback."""

    name = "fixed"

    def __init__(self, *answers):
        self.answers, self.feedback = list(answers), []

    async def write(self, req, feedback=None):
        self.feedback.append(feedback)
        make = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        return await make(req)


async def template_answer(req, change=None):
    """The mock's answer, with `change(lang, id, item) -> item` applied to each insight."""
    out = await analyst.MockAnalyst().write(req)
    if change:
        for lang in out:
            for i, item in out[lang]["insights"].items():
                out[lang]["insights"][i] = change(lang, i, dict(item))
    return out


class ReportTest(unittest.TestCase):
    def test_the_example_tactics_pass_their_schema(self):
        self.assertEqual(list(TACTICS_SCHEMA.iter_errors(TACTICS)), [])

    def test_report_passes_its_schema_and_every_number_reads_back_from_tactics(self):
        report, log = run()
        self.assertEqual(list(REPORT_SCHEMA.iter_errors(report)), [])
        self.assertEqual(log["recheck"], [])
        self.assertTrue(analyst.MIN_INSIGHTS <= len(report["insights"]) <= analyst.MAX_INSIGHTS)
        for ins in report["insights"]:
            self.assertEqual(set(ins["title"]) | set(ins["text"]), set(LANGS))
            self.assertTrue(ins["facts"])
            for f in ins["facts"]:
                self.assertEqual(f["value"], analyst.lookup(TACTICS, f["ref"], f["field"]))
        self.assertEqual(set(report["headline"]), set(LANGS))

    def test_the_example_report_is_the_mock_report_on_the_example_tactics(self):
        example = json.loads((ROOT / "schemas/examples/report.example.json").read_text("utf-8"))
        report, _ = run()
        self.assertEqual([i["values"] for i in example["insights"]], [i["values"] for i in report["insights"]])

    def test_recheck_catches_a_value_that_is_not_its_fact(self):
        report, _ = run()
        ins = report["insights"][0]
        key = next(f["key"] for f in ins["facts"] if f.get("key"))
        ins["values"][key] = 999
        self.assertTrue(any("shows 999" in p for p in analyst.recheck(report, TACTICS)))
        report, _ = run()
        report["insights"][0]["facts"][0]["value"] = "made up"
        self.assertTrue(analyst.recheck(report, TACTICS))

    def test_an_insight_cites_the_events_its_event_facts_count(self):
        report, _ = run()
        whole = TACTICS["segments"][0]["teams"]
        for ins in report["insights"]:
            if ins["topic"] == "directness":
                self.assertEqual(set(ins["event_ids"]),
                                 set(whole["home"]["long_balls"]["event_ids"]) | set(whole["away"]["long_balls"]["event_ids"]))
            if ins["topic"] in ("defensive_line", "width", "compactness", "shape"):
                self.assertEqual(ins["event_ids"], [])
                self.assertTrue(all(f.get("n_frames") for f in ins["facts"]))


class CoverageTest(unittest.TestCase):
    """#69: insights rest on facts with uneven coverage; low coverage is hedged or skipped, and said."""

    def test_full_coverage_is_said_plainly(self):
        report, _ = run(with_coverage(TACTICS, lambda c: 1.0))
        self.assertFalse(any(i["hedged"] for i in report["insights"]))

    def test_below_the_threshold_insights_are_hedged_in_every_language(self):
        report, log = run(with_coverage(TACTICS, lambda c: 0.45))
        self.assertEqual(log["recheck"], [])
        self.assertEqual(len(report["insights"]), analyst.MIN_INSIGHTS)
        for ins in report["insights"]:
            self.assertTrue(ins["hedged"])
            self.assertEqual(ins["coverage"], 0.45)
            for lang in LANGS:
                self.assertEqual(verifier.missing_hedge(ins["text"][lang], lang), [], ins["text"][lang])
        self.assertTrue(all("below the threshold" in s["reason"] for s in report["skipped"]))

    def test_below_the_hedge_floor_nothing_is_said(self):
        report, _ = run(with_coverage(TACTICS, lambda c: 0.2))
        self.assertEqual((report["insights"], report["headline"]), ([], {}))
        self.assertTrue(report["skipped"])
        self.assertTrue(all("hedge floor" in s["reason"] for s in report["skipped"]))
        self.assertEqual(list(REPORT_SCHEMA.iter_errors(report)), [])

    def test_hedged_insights_only_fill_up_to_the_minimum(self):
        """dev3's case: possession known in 40% of frames, so every in/out-of-possession fact is low; the
        event facts are not. Confident insights first; a hedged one only if they are too few."""
        def possession_low(t):
            t = copy.deepcopy(t)
            for side in ("home", "away"):
                team = t["segments"][0]["teams"][side]
                for fact in ("defensive_line_m", "compactness_m"):
                    team[fact]["out_of_possession"]["coverage"] = 0.4
                team["attacking_width_m"]["coverage"] = 0.4
            return t
        report, _ = run(possession_low(TACTICS))
        topics = {i["topic"]: i for i in report["insights"]}
        self.assertNotIn("defensive_line", topics)
        skipped = {s["topic"]: s for s in report["skipped"]}
        self.assertEqual(skipped["defensive_line"]["coverage"], 0.4)
        self.assertIn("below the threshold", skipped["defensive_line"]["reason"])
        self.assertFalse(any(i["hedged"] for i in report["insights"]))

        # Only one confident candidate: two hedged ones join it, the confident one first.
        t = with_coverage(TACTICS, lambda c: 0.5)
        t["segments"][0]["teams"]["home"]["long_balls"]["coverage"] = 0.9
        t["segments"][0]["teams"]["away"]["long_balls"]["coverage"] = 0.9
        report, _ = run(t)
        self.assertEqual([i["hedged"] for i in report["insights"]], [False, True, True])
        self.assertEqual(report["insights"][0]["topic"], "directness")

    def test_unknown_coverage_counts_as_none(self):
        report, _ = run(with_coverage(TACTICS, lambda c: None))
        self.assertEqual(report["insights"], [])


class ChangeTest(unittest.TestCase):
    def test_a_line_that_drops_after_a_goal_is_an_insight_citing_the_goal(self):
        t = copy.deepcopy(TACTICS)
        whole = t["segments"][0]
        before, after = copy.deepcopy(whole), copy.deepcopy(whole)
        before.update(id="before_e0040", split_by="e0040", end=59.0)
        after.update(id="after_e0040", split_by="e0040", start=59.0)
        after["teams"]["away"]["defensive_line_m"]["out_of_possession"]["value"] -= 9.0
        t["segments"] += [before, after]
        goal = {"id": "e0040", "t": 59.0, "type": "goal", "team": "home", "from": None, "source": "cv"}
        with mock.patch.object(analyst, "MIN_SEGMENT_S", 50.0):   # the example clip is 2 minutes
            report, log = run(t, events=[goal])
        self.assertEqual(log["recheck"], [])
        change = next(i for i in report["insights"] if i["topic"] == "change")
        self.assertEqual((change["team"], change["segment"], change["event_ids"]), ("away", "after_e0040", ["e0040"]))
        self.assertEqual(change["values"]["line_before_m"] - change["values"]["line_after_m"], 9)
        self.assertIn("deeper", change["text"]["en"])

    def test_no_comparison_on_a_side_shorter_than_a_minute(self):
        t = copy.deepcopy(TACTICS)
        whole = t["segments"][0]
        t["segments"] += [{**copy.deepcopy(whole), "id": "before_e0040", "split_by": "e0040", "end": 20.0},
                          {**copy.deepcopy(whole), "id": "after_e0040", "split_by": "e0040", "start": 20.0}]
        goal = {"id": "e0040", "t": 20.0, "type": "goal", "team": "home", "source": "cv"}
        self.assertFalse([c for c in analyst.candidates(t, match([goal])) if c.topic == "change"])


class VerifierLoopTest(unittest.TestCase):
    def test_digits_uncited_claims_names_and_missing_hedges_are_rejected(self):
        report, _ = run()
        req = analyst.build_request(analyst.select(analyst.candidates(TACTICS, match()))[0], match(), LANGS,
                                    {"home": 0, "away": 0})
        item = next(i for i in req["insights"] if i["topic"] == "directness")
        m = match()

        def problems(text, lang="en", hedged=False):
            return analyst.check_item("Directness", text, {**item, "hedged": hedged}, lang, m)

        self.assertEqual(problems("Thames United went long: {away_long_pct} of their passes"), [])
        self.assertTrue(problems("Thames United went long: 29% of their passes"))           # digit
        self.assertTrue(problems("Thames United went long with a 4-4-2"))                   # formation as digits
        self.assertTrue(problems("Thames United went long and pressed high"))               # pressing: uncited
        self.assertTrue(problems("Thames United juegan por la banda izquierda", "es"))      # flanks: uncited
        self.assertTrue(problems("Thames United sahayı geniş kullandı", "tr"))              # width: uncited
        self.assertTrue(problems("K. Aydin went long more often"))                          # a player
        self.assertTrue(problems("Thames United went long: {home_line_m}"))                 # not its placeholder
        self.assertTrue(problems("Thames United went long", hedged=True))                   # no hedge
        self.assertEqual(problems("Thames United seem to have gone long", hedged=True), [])

    def test_a_formation_is_a_placeholder_and_reads_as_written(self):
        cands = analyst.candidates(TACTICS, match())
        shape = next(c for c in cands if c.topic == "shape")
        item = analyst.insight_request(1, shape)
        self.assertEqual(analyst.check_item("Shape", "Bosphorus FC lined up in a {home_shape}", item, "en", match()), [])
        self.assertIn("{home_shape} instead", " ".join(
            analyst.check_item("Shape", "Bosphorus FC lined up in a 4-3-3", item, "en", match())))

    def test_a_rejected_answer_is_retried_with_its_problems_then_falls_back_to_the_template(self):
        async def bad(req):
            return await template_answer(req, lambda lang, i, it: {**it, "text": it["text"] + " (87% xG)"})
        backend = FixedAnswers(bad, template_answer)
        report, log = run(backend=backend)
        self.assertIsNone(backend.feedback[0])
        self.assertIn("87", backend.feedback[1])
        self.assertEqual(log["fixed_on_retry"], len(report["insights"]) * len(LANGS))
        self.assertEqual(log["template_fallbacks"], 0)

        backend = FixedAnswers(bad)
        report, log = run(backend=backend)
        self.assertEqual(log["template_fallbacks"], len(report["insights"]) * len(LANGS))
        self.assertEqual(list(REPORT_SCHEMA.iter_errors(report)), [])
        self.assertFalse(any("87" in t for i in report["insights"] for t in i["text"].values()))

    def test_every_template_passes_the_verifier(self):
        """Each topic, every reading of its labels, hedged or not, in every language."""
        m = match()
        cands = analyst.candidates(TACTICS, m)
        base = {c.topic: c for c in cands}
        for c in cands:
            for side in ("home", "away", "level"):
                for hedged in (False, True):
                    for labels in self._readings(c, side):
                        cand = copy.copy(c)
                        cand.labels, cand.hedged = labels, hedged
                        if c.topic == "shape":  # a side not as on its sheet cites its sheet shape
                            cand.facts = c.facts[:2] + [
                                analyst.fact(TACTICS, f"whole/{s}/shape.all", "team_sheet", "sheet", f"{s}_sheet_shape")
                                for s in ("home", "away") if not labels[f"{s}_as_sheet"]]
                        item = analyst.insight_request(1, cand)
                        for lang in LANGS:
                            t = analyst_templates.render(item, lang, {"home": "Bosphorus FC", "away": "Thames United"})
                            self.assertEqual(analyst.check_item(t["title"], t["text"], item, lang, m), [],
                                             (c.topic, labels, hedged, lang, t))
        self.assertTrue({"shape", "defensive_line", "directness"} <= set(base))

    @staticmethod
    def _readings(c, side):
        if c.topic == "shape":
            return [{"home_as_sheet": h, "away_as_sheet": a} for h in (True, False) for a in (True, False)]
        if c.topic == "flanks":
            return [{"flank": f} for f in ("left", "centre", "right")]
        label = analyst_templates.COMPARE[c.topic][0]
        return [{label: side}]

    def test_shape_readings_cite_the_sheet_shape_they_name(self):
        c = next(c for c in analyst.candidates(TACTICS, match()) if c.topic == "shape")
        c = copy.copy(c)
        c.labels = {"home_as_sheet": False, "away_as_sheet": True}
        c.facts = c.facts + [analyst.fact(TACTICS, "whole/home/shape.all", "team_sheet", "sheet", "home_sheet_shape")]
        item = analyst.insight_request(1, c)
        t = analyst_templates.render(item, "en", {"home": "Bosphorus FC", "away": "Thames United"})
        self.assertIn("{home_sheet_shape}", t["text"])


class FoundryAnalystTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cache = Path(tmp.name) / "cache.json"

    def test_the_agent_gets_placeholders_not_numbers_and_answers_are_cached(self):
        prompts = []

        class Agent:
            async def run(self, prompt):
                prompts.append(prompt)
                req = json.loads(prompt.split("\n\nYour previous")[0])
                return SimpleNamespace(text=json.dumps(fake_reply(req)), usage_details={"input_token_count": 10,
                                                                                         "output_token_count": 5})

        def fake_reply(view):
            return {lang: {"headline": "Bosphorus FC {score} Thames United: a tight clip",
                           "insights": {i["id"]: {"title": "Directness", "text": f"{view['home']} went long"}
                                        for i in view["insights"]}} for lang in view["langs"]}

        backend = analyst.FoundryAnalyst(FoundryBackend(self.cache, agent=Agent(), deployment="fake",
                                                        instructions=analyst.ANALYST_INSTRUCTIONS))
        report, log = run(backend=backend)
        view = json.loads(prompts[0])
        self.assertNotIn("values", view["insights"][0])
        self.assertTrue(all(p.startswith("{") for p in view["insights"][0]["placeholders"]))
        self.assertIn(view["home"], json.dumps(view["insights"][0]["labels"]) + view["home"])
        self.assertEqual(backend.usage["calls"], len(prompts))
        # The model's words passed only where they were true of the insight; the rest are templates.
        self.assertEqual(list(REPORT_SCHEMA.iter_errors(report)), [])
        self.assertEqual(log["recheck"], [])

        calls = backend.usage["calls"]
        backend2 = analyst.FoundryAnalyst(FoundryBackend(self.cache, agent=Agent(), deployment="fake",
                                                         instructions=analyst.ANALYST_INSTRUCTIONS))
        run(backend=backend2)
        self.assertEqual(backend2.usage["calls"], 0)
        self.assertEqual(backend2.usage["cached"], calls)

    def test_analyst_and_explainer_answers_never_share_a_cache_entry(self):
        self.assertNotEqual(cache_key("d", "{}", INSTRUCTIONS), cache_key("d", "{}", analyst.ANALYST_INSTRUCTIONS))


if __name__ == "__main__":
    unittest.main()
