"""Run with:  python -m unittest discover -s agents/tests -t .   (from the repo root)"""

import asyncio
import json
import tempfile
import unittest
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from jsonschema import Draft202012Validator

from agents import templates, verifier
from agents.fill import UnknownPlaceholder, fill
from agents.context import goal_effect, lead_in, scoring_side
from agents.data_io import load_match
from agents.director import MODES, direct
from agents.explainer import explain_all
from agents.llm import (RATE_LIMIT_DELAYS_S, FoundryBackend, MockBackend, NoisyBackend, cache_key,
                        is_rate_limit, parse_json_reply)
from agents.stats import (MOMENTUM_WINDOW_S, attacks_positive_x, display_minute, pass_difficulty,
                          threat_share, threat_weight)

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_A = ROOT / "data" / "fake" / "sample_a"
SAMPLE_B = ROOT / "data" / "fake" / "sample_b"
OVERLAY_SCHEMA = Draft202012Validator(json.loads((ROOT / "schemas" / "overlay.schema.json").read_text("utf-8")))


class StatsTest(unittest.TestCase):
    def test_directions_swap_at_half_time(self):
        info = {"kickoff_direction": {"home": "left_to_right"}}
        self.assertTrue(attacks_positive_x("home", 1, info))
        self.assertFalse(attacks_positive_x("home", 2, info))
        self.assertTrue(attacks_positive_x("away", 2, info))

    def test_display_minute_second_half(self):
        info = {"periods": [{"period": 1, "start": 0, "end": 2700}, {"period": 2, "start": 2701, "end": 5400}]}
        self.assertEqual(display_minute(0, info), 1)
        self.assertEqual(display_minute(2701, info), 46)

    def test_difficulty_range(self):
        self.assertEqual(pass_difficulty(5, 30, 0, "short"), 2)
        self.assertEqual(pass_difficulty(60, 90, 50, "through"), 10)


class VerifierTest(unittest.TestCase):
    def test_rejects_invented_number(self):
        p = verifier.check("23 m pass, 87% xG", "K. Aydin", {"distance_m": 23}, {}, {"K. Aydin"}, {"K. Aydin"})
        self.assertTrue(any("87" in x for x in p))

    def test_rejects_wrong_player(self):
        p = verifier.check("E. Demir with the pass", "", {}, {}, {"K. Aydin"}, {"K. Aydin", "E. Demir"})
        self.assertTrue(any("not part of" in x for x in p))

    def test_accepts_backed_text(self):
        self.assertEqual(verifier.check("23 m pass", "K. Aydin", {"distance_m": 23.0}, {}, {"K. Aydin"}, {"K. Aydin"}), [])

    def test_turkish_suffix_on_a_real_name_passes(self):
        self.assertEqual(verifier.check("K. Aydin'den harika pas", "", {}, {}, {"K. Aydin"}, {"K. Aydin"}), [])

    def test_turkish_letters_are_read_as_one_name(self):
        p = verifier.check("K. Aydın ile hücum", "", {}, {}, {"K. Aydin"}, {"K. Aydin"})
        self.assertEqual(p, ["unknown player name 'K. Aydın'"])

    def test_invented_name_with_turkish_initial_is_rejected(self):
        p = verifier.check("Ç. Uydurma'dan gol", "", {}, {}, {"K. Aydin"}, {"K. Aydin"})
        self.assertEqual(p, ["unknown player name 'Ç. Uydurma'"])

    def test_parse_fenced_json(self):
        out = parse_json_reply('```json\n{"en": {"title": "a", "text": "b"}}\n```', ["en", "tr"])
        self.assertEqual(out["en"]["text"], "b")
        self.assertEqual(out["tr"]["text"], "")


class FillTest(unittest.TestCase):
    def test_speed_unit_per_language(self):
        v = {"speed_kmh": 112}
        self.assertEqual(fill("{speed_kmh}", v, "tr"), "112 km/sa")
        self.assertEqual(fill("{speed_kmh}", v, "en"), "112 km/h")
        self.assertEqual(fill("{speed_kmh}", v, "es"), "112 km/h")

    def test_distance_is_number_space_unit_in_every_language(self):
        for lang in templates.LANGS:
            self.assertEqual(fill("{distance_m}, {goal_distance_m}", {"distance_m": 28, "goal_distance_m": 13}, lang),
                             "28 m, 13 m")

    def test_percentage_per_language(self):
        v = {"momentum_home": 62}
        self.assertEqual(fill("{momentum_home}", v, "en"), "62%")
        self.assertEqual(fill("{momentum_home}", v, "tr"), "%62")
        self.assertEqual(fill("{momentum_home}", v, "es"), "62 %")

    def test_score_and_minute_from_values_or_facts(self):
        facts = {"minute": 34, "score_home": 2, "score_away": 1}
        for lang in templates.LANGS:
            self.assertEqual(fill("{score}, {minute}", {}, lang, facts), "2-1, 34'")
        self.assertEqual(fill("{score}", {"score_home": 3, "score_away": 1}, "en", facts), "3-1")
        self.assertEqual(fill("{difficulty}", {"difficulty": 7}, "tr"), "7/10")

    def test_unknown_placeholder_is_rejected(self):
        with self.assertRaises(UnknownPlaceholder) as ctx:
            fill("Shot at {speed_kmh}", {"distance_m": 28}, "en")
        self.assertIn("speed_kmh", str(ctx.exception))
        with self.assertRaises(UnknownPlaceholder):
            fill("{score}", {}, "en")  # no score known for this overlay

    def test_one_apostrophe_character_everywhere(self):
        self.assertEqual(fill("K. Aydin’den pas", {}, "tr"), "K. Aydin'den pas")
        self.assertEqual(fill("Aydin‘s strike, {minute}", {"minute": 9}, "en"), "Aydin's strike, 9'")

    def test_whitespace_collapsed_and_no_space_before_punctuation(self):
        self.assertEqual(fill("  Shot  from {goal_distance_m} ,  on target !  ", {"goal_distance_m": 13}, "en"),
                         "Shot from 13 m, on target!")
        self.assertEqual(fill("Score : {score} .", {"score_home": 1, "score_away": 0}, "en"), "Score: 1-0.")

    def test_spanish_openers_are_kept(self):
        self.assertEqual(fill("¡Qué disparo ! ¿Gol ?", {}, "es"), "¡Qué disparo! ¿Gol?")


class LlmCacheTest(unittest.TestCase):
    def test_key_changes_with_instructions_and_deployment(self):
        base = cache_key("gpt-4o-mini", "{}", "rules v1")
        self.assertEqual(base, cache_key("gpt-4o-mini", "{}", "rules v1"))
        self.assertNotEqual(base, cache_key("gpt-4o-mini", "{}", "rules v2"))
        self.assertNotEqual(base, cache_key("gpt-4o", "{}", "rules v1"))
        self.assertNotEqual(base, cache_key("gpt-4o-mini", "{ }", "rules v1"))


class DirectorTest(unittest.TestCase):
    def test_screen_time_spread_over_match(self):
        # The budget window must only look back; counting later graphics piled overlays at the end.
        candidates, _ = direct(load_match(SAMPLE_B))
        blocks = [0] * 6
        for c in candidates:
            if "analyst" in c.modes and c.priority < 0.9 and c.start < 5400:
                blocks[int(c.start // 900)] += 1
        mean = sum(blocks) / len(blocks)
        for n in blocks:
            self.assertLessEqual(abs(n - mean), 0.5 * mean, blocks)

    def test_setup_pass_is_credited_on_the_shot_card(self):
        # No separate key-pass card: it would show before the shot and spoil it.
        match = load_match(SAMPLE_B)
        by_id = {e["id"]: e for e in match.events}
        candidates, _ = direct(match)
        self.assertFalse(any("key pass" in c.reason for c in candidates))
        setups = [c for c in candidates if c.setup]
        self.assertGreater(len(setups), 0)
        for c in setups:
            p, shot = by_id[c.event_ids[0]], by_id[c.event_ids[1]]
            self.assertEqual(c.event_ids, [p["id"], shot["id"]])
            self.assertEqual(p["to"], shot["from"])
            self.assertLessEqual(shot["t"] - p["t"], 6.0)
            self.assertGreaterEqual(c.start, shot["t"])


class ContextTest(unittest.TestCase):
    def test_goal_effect(self):
        cases = [({"home": 0, "away": 0}, {"home": 1, "away": 0}, "opener"),
                 ({"home": 0, "away": 1}, {"home": 1, "away": 1}, "equaliser"),
                 ({"home": 1, "away": 1}, {"home": 2, "away": 1}, "go_ahead"),
                 ({"home": 1, "away": 0}, {"home": 2, "away": 0}, "extends_lead"),
                 ({"home": 0, "away": 2}, {"home": 1, "away": 2}, "pulls_one_back")]
        for before, after, want in cases:
            self.assertEqual(goal_effect(before, after, "home"), want)

    def test_own_goal_credits_the_team_whose_score_went_up(self):
        self.assertEqual(scoring_side({"home": 0, "away": 0}, {"home": 0, "away": 1}), "away")

    def test_lead_in(self):
        shot = {"t": 100.0, "type": "shot", "team": "home"}
        won = {"t": 92.0, "type": "possession_change", "team": "home"}
        self.assertEqual(lead_in(shot, "home", deque([won])), "counter_attack")
        passes = deque({"t": 70.0 + i, "type": "pass", "team": "home", "success": True} for i in range(6))
        self.assertEqual(lead_in(shot, "home", passes), "patient_build_up")
        passes.popleft()
        self.assertIsNone(lead_in(shot, "home", passes))

    def test_recap_cites_the_events_behind_its_numbers(self):
        # AGENTS.md rules 3-4: the shot counts can be recomputed from the cited events alone.
        match = load_match(SAMPLE_B)
        by_id = {e["id"]: e for e in match.events}
        candidates, _ = direct(match)
        recaps = [c for c in candidates if c.graphic == "stat_compare"]
        self.assertEqual([c.event["type"] for c in recaps], ["half_time", "full_time"])
        for c in recaps:
            cited = [by_id[i] for i in c.event_ids]
            self.assertEqual([e["t"] for e in cited], sorted(e["t"] for e in cited))
            for side in ("home", "away"):
                shots = [e for e in cited if e["type"] == "shot" and e["team"] == side]
                self.assertEqual(len(shots), c.values[f"shots_{side}"])
                self.assertEqual(sum(e.get("subtype") == "on_target" for e in shots), c.values[f"on_target_{side}"])
            goals = {e["id"] for e in match.events if e["type"] == "goal" and e["t"] < c.event["t"]}
            self.assertLessEqual(goals, set(c.event_ids))
            self.assertNotIn("pass_accuracy_home", c.values)  # would need every pass cited

    def test_momentum_bar_cites_the_window_behind_its_percentages(self):
        match = load_match(SAMPLE_B)
        by_id = {e["id"]: e for e in match.events}
        candidates, _ = direct(match)
        bars = [c for c in candidates if c.graphic == "momentum_bar"]
        self.assertGreater(len(bars), 0)
        for c in bars:
            t = c.event["t"]
            window = [by_id[i] for i in c.event_ids if threat_weight(by_id[i], match.info)]
            self.assertTrue(all(t - MOMENTUM_WINDOW_S <= e["t"] <= t for e in window))
            # Only the anchor event (when the bar appears) may carry no threat weight.
            self.assertEqual(len(window), len(c.event_ids) - (c.event["id"] not in {e["id"] for e in window}))
            share = threat_share([(e["team"], threat_weight(e, match.info)) for e in window])
            self.assertEqual(share, {"home": c.values["momentum_home"], "away": c.values["momentum_away"]})


class PipelineTest(unittest.TestCase):
    def run_pipeline(self, backend):
        match = load_match(SAMPLE_A)
        candidates, _ = direct(match)
        return asyncio.run(explain_all(candidates, match, backend, list(templates.LANGS)))

    def test_overlays_match_schema_and_cite_events(self):
        overlays, report = self.run_pipeline(MockBackend())
        event_ids = {e["id"] for e in load_match(SAMPLE_A).events}
        self.assertGreater(len(overlays), 0)
        self.assertEqual(report["dropped"], [])
        for o in overlays:
            self.assertEqual(list(OVERLAY_SCHEMA.iter_errors(o)), [], o)
            self.assertTrue(set(o["event_ids"]) <= event_ids)

    def test_templates_pass_the_verifier_in_every_language(self):
        overlays, report = self.run_pipeline(MockBackend())
        self.assertEqual(report["rejected"], [])
        self.assertEqual({o["lang"] for o in overlays}, set(templates.LANGS))

    def test_every_goal_and_red_card_is_shown(self):
        overlays, _ = self.run_pipeline(MockBackend())
        shown = {o["graphic"] for o in overlays if o["mode"] == "casual"}
        self.assertIn("goal_banner", shown)
        self.assertIn("card_banner", shown)

    def test_noisy_llm_numbers_never_reach_the_screen(self):
        overlays, report = self.run_pipeline(NoisyBackend())
        self.assertGreater(len(report["rejected"]), 0)
        self.assertFalse(any("87" in o["text"] for o in overlays))


class TemplateFormatTest(unittest.TestCase):
    """Every graphic in every mode and language, written by the templates (mock backend)."""

    @classmethod
    def setUpClass(cls):
        cls.runs = {}
        for sample in (SAMPLE_A, SAMPLE_B):
            match = load_match(sample)
            candidates, _ = direct(match)
            for c in candidates:
                c.modes = set(MODES)  # not only the slots the director scheduled
            cls.runs[sample.name] = asyncio.run(explain_all(candidates, match, MockBackend(), list(templates.LANGS)))

    def overlays(self, graphic=None, lang=None):
        return [o for overlays, _ in self.runs.values() for o in overlays
                if graphic in (None, o["graphic"]) and lang in (None, o["lang"])]

    def test_every_graphic_mode_and_language_passes_the_verifier(self):
        for name, (overlays, report) in self.runs.items():
            self.assertEqual(report["rejected"], [], name)
            self.assertEqual(report["dropped"], [], name)
            graphics = {o["graphic"] for o in overlays}
            self.assertEqual({(g, m, l) for g in graphics for m in MODES for l in templates.LANGS},
                             {(o["graphic"], o["mode"], o["lang"]) for o in overlays}, name)

    def test_turkish_speed_is_km_sa_never_km_s(self):
        tr = [o for o in self.overlays("shot_card", "tr") if "speed_kmh" in o["values"]]
        self.assertGreater(len(tr), 0)
        for o in self.overlays(lang="tr"):
            self.assertNotRegex(o["text"], r"km/s\b", o)
        for o in tr:
            self.assertIn(f"{o['values']['speed_kmh']} km/sa", o["text"])
        for lang in ("en", "es"):
            for o in self.overlays("shot_card", lang):
                if "speed_kmh" in o["values"]:
                    self.assertIn(f"{o['values']['speed_kmh']} km/h", o["text"])

    def test_distances_read_number_space_unit(self):
        for o in self.overlays():
            self.assertNotRegex(o["text"], r"\d(m|km)\b", o)
        for o in self.overlays("pass_card"):
            if o["mode"] != "casual":
                self.assertIn(f"{o['values']['distance_m']} m", o["text"])

    def test_percentages_per_language(self):
        want = {"en": "{}%", "tr": "%{}", "es": "{} %"}
        bars = self.overlays("momentum_bar")
        self.assertGreater(len(bars), 0)
        for o in bars:
            pct = max(o["values"]["momentum_home"], o["values"]["momentum_away"])
            self.assertIn(want[o["lang"]].format(pct), o["text"])

    def test_scores_read_home_dash_away(self):
        for o in self.overlays("goal_banner") + self.overlays("stat_compare"):
            self.assertIn(f"{o['values']['score_home']}-{o['values']['score_away']}", o["text"])

    def test_text_is_typeset(self):
        for o in self.overlays():
            for s in (o["title"], o["text"]):
                self.assertNotRegex(s, r"\s[,.!?:]|\s\s|^\s|\s$|[{}’‘]|[!?]\.", o)


class RateLimited(Exception):
    """Stands in for openai.RateLimitError (HTTP 429)."""
    status_code = 429


class FlakyAgent:
    """Fake Agent Framework agent: rate-limited `failures` times (wrapped, like a
    ChatClientException around the openai error), then answers."""

    def __init__(self, failures: int) -> None:
        self.failures, self.calls = failures, 0

    async def run(self, prompt: str):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("service failed to complete the prompt") from RateLimited()
        return SimpleNamespace(text='{"en": {"title": "Goal", "text": "K. Aydin scores"}}')


class FoundryRetryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache_path = Path(self.tmp.name) / "llm_cache.json"

    def tearDown(self):
        self.tmp.cleanup()

    def explain(self, agent):
        backend = FoundryBackend(self.cache_path, agent=agent, deployment="fake")
        with mock.patch("agents.llm.asyncio.sleep", new=mock.AsyncMock()) as sleep:
            out = asyncio.run(backend.explain({"langs": ["en"], "event_type": "goal"}))
        return out, sleep

    def test_retries_429_then_succeeds_and_saves_cache(self):
        agent = FlakyAgent(failures=2)
        out, sleep = self.explain(agent)
        self.assertEqual(out["en"]["text"], "K. Aydin scores")
        self.assertEqual(agent.calls, 3)
        waits = [c.args[0] for c in sleep.await_args_list]
        self.assertEqual(len(waits), 2)
        for wait, base in zip(waits, RATE_LIMIT_DELAYS_S):
            self.assertTrue(base <= wait <= base + 1, wait)
        self.assertEqual(len(json.loads(self.cache_path.read_text("utf-8"))), 1)

    def test_gives_up_after_six_retries(self):
        agent = FlakyAgent(failures=99)
        with self.assertRaises(RuntimeError):
            self.explain(agent)
        self.assertEqual(agent.calls, len(RATE_LIMIT_DELAYS_S) + 1)
        self.assertFalse(self.cache_path.exists())

    def test_other_errors_are_not_retried(self):
        self.assertFalse(is_rate_limit(ValueError("bad request")))
        self.assertTrue(is_rate_limit(SimpleNamespace(status_code=429, __cause__=None, __context__=None)))


if __name__ == "__main__":
    unittest.main()
