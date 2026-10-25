"""Run with:  python -m unittest discover -s agents/tests -t .   (from the repo root)"""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from jsonschema import Draft202012Validator

from agents import verifier
from agents.data_io import load_match
from agents.director import direct
from agents.explainer import explain_all
from agents.llm import (RATE_LIMIT_DELAYS_S, FoundryBackend, MockBackend, NoisyBackend, cache_key,
                        is_rate_limit, parse_json_reply)
from agents.stats import attacks_positive_x, display_minute, pass_difficulty

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


class PipelineTest(unittest.TestCase):
    def run_pipeline(self, backend):
        match = load_match(SAMPLE_A)
        candidates, _ = direct(match)
        return asyncio.run(explain_all(candidates, match, backend, ["en", "tr"]))

    def test_overlays_match_schema_and_cite_events(self):
        overlays, report = self.run_pipeline(MockBackend())
        event_ids = {e["id"] for e in load_match(SAMPLE_A).events}
        self.assertGreater(len(overlays), 0)
        self.assertEqual(report["dropped"], [])
        for o in overlays:
            self.assertEqual(list(OVERLAY_SCHEMA.iter_errors(o)), [], o)
            self.assertTrue(set(o["event_ids"]) <= event_ids)

    def test_every_goal_and_red_card_is_shown(self):
        overlays, _ = self.run_pipeline(MockBackend())
        shown = {o["graphic"] for o in overlays if o["mode"] == "casual"}
        self.assertIn("goal_banner", shown)
        self.assertIn("card_banner", shown)

    def test_noisy_llm_numbers_never_reach_the_screen(self):
        overlays, report = self.run_pipeline(NoisyBackend())
        self.assertGreater(len(report["rejected"]), 0)
        self.assertFalse(any("87" in o["text"] for o in overlays))


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
