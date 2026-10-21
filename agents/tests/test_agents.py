"""Run with:  python -m unittest discover -s agents/tests -t .   (from the repo root)"""

import asyncio
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from agents import verifier
from agents.data_io import load_match
from agents.director import direct
from agents.explainer import explain_all
from agents.llm import MockBackend, NoisyBackend, parse_json_reply
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


if __name__ == "__main__":
    unittest.main()
