"""Run with:  python -m unittest discover -s agents/tests -t .   (from the repo root)"""

import asyncio
import json
import tempfile
import unittest
from collections import deque
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from jsonschema import Draft202012Validator

from agents import templates, verifier
from agents.context import goal_effect, lead_in, scoring_side
from agents.data_io import load_match
from agents.director import GRAPHIC_LAYOUT, MODES, direct, propose
from agents.explainer import build_request, explain_all, involved_names
from agents.llm import (RATE_LIMIT_DELAYS_S, FoundryBackend, MockBackend, NoisyBackend, cache_key,
                        is_rate_limit, parse_json_reply)
from agents.stats import (MOMENTUM_WINDOW_S, MatchState, attacks_positive_x, display_minute, event_facts,
                          pass_difficulty, threat_share, threat_weight)

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

    def test_events_with_no_player_or_optional_fields_keep_team_totals(self):
        # A detected event may lack `from`, `duration_s`, `end`, `success`: facts that need them are left out.
        state = MatchState(info={"kickoff_direction": {"home": "left_to_right"}})
        shot = {"id": "e0001", "t": 10.0, "type": "shot", "team": "home", "from": None, "start": [95.0, 34.0]}
        bare_pass = {"id": "e0002", "t": 12.0, "type": "pass", "team": "home", "from": 7, "start": [50.0, 30.0]}
        for e in (shot, bare_pass):
            state.update(e)
        self.assertEqual((state.teams["home"].shots, state.teams["home"].passes), (1, 0))
        self.assertNotIn(None, state.players)
        f = event_facts(shot, state)
        self.assertEqual(f["goal_distance_m"], 10)
        self.assertFalse({"speed_kmh", "player_shots"} & set(f))
        f = event_facts(bare_pass, state)
        self.assertFalse({"difficulty", "progress_m", "into_box"} & set(f))
        self.assertIsNone(propose(bare_pass, f))

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


DETECTED_TYPES = {"kickoff", "pass", "possession_change", "shot", "goal"}  # what the vision AI detects
MERGED_SIM_TYPES = {"foul", "yellow_card", "red_card", "offside", "substitution"}  # scripts/merge_events.py


def as_detected(match):
    """sample_a as the vision AI + merge_events.py would deliver it: only detected types
    (plus the merged simulator ones), confidences below 1, no player on every other
    detected event and on the goal, some optional fields missing, no half_time/full_time."""
    events = []
    for i, e in enumerate(match.events):
        if e["type"] not in DETECTED_TYPES | MERGED_SIM_TYPES:
            continue
        e = dict(e)
        if e["type"] in DETECTED_TYPES:
            e.update(source="cv", confidence=0.62)
            if i % 2 or e["type"] == "goal":
                e["from"] = e["to"] = None
            if i % 5 == 0:
                for k in ("duration_s", "end", "success", "speed_kmh"):
                    e.pop(k, None)
        events.append(e)
    match.events = events
    return match


class DetectedEventsTest(unittest.TestCase):
    """The agents stage on detected events: nothing branches on `source`, only null players
    (and, later, confidence) change what is shown."""

    def setUp(self):
        self.match = as_detected(load_match(SAMPLE_A))
        self.by_id = {e["id"]: e for e in self.match.events}
        self.roster = {p["name"] for p in self.match.players.values()}
        candidates, _ = direct(self.match)
        self.overlays, self.report = asyncio.run(
            explain_all(candidates, self.match, MockBackend(), list(templates.LANGS)))

    def subject(self, o):
        """The event an overlay is about: the last id it cites."""
        return self.by_id[o["event_ids"][-1]]

    def test_overlays_pass_the_schema_and_nothing_is_dropped(self):
        self.assertGreater(len(self.overlays), 0)
        self.assertEqual(self.report["dropped"], [])
        for o in self.overlays:
            self.assertEqual(list(OVERLAY_SCHEMA.iter_errors(o)), [], o)
            self.assertTrue(set(o["event_ids"]) <= set(self.by_id))
            self.assertTrue(o["title"].strip() and o["text"].strip(), o)
            self.assertNotIn("None", o["title"] + o["text"])

    def test_events_with_no_player_are_worded_about_the_team(self):
        affected = [o for o in self.overlays if o["graphic"] != "momentum_bar"  # about a window, not an event
                    and self.subject(o)["from"] is None and self.subject(o)["team"] in ("home", "away")]
        self.assertTrue({"goal_banner", "shot_card", "pass_card"} <= {o["graphic"] for o in affected})
        for o in affected:
            self.assertNotEqual(o["mode"], "player_focus", o)
            self.assertEqual(verifier.names_in(f"{o['title']} {o['text']}", self.roster), set(), o)
            self.assertIn(self.match.team_name(self.subject(o)["team"]), o["title"] + o["text"], o)
        self.assertTrue({"analyst", "casual"} <= {o["mode"] for o in affected})

    def test_merged_card_still_names_the_booked_player(self):
        cards = [o for o in self.overlays if o["graphic"] == "card_banner"]
        self.assertGreater(len(cards), 0)
        for o in cards:
            self.assertIn(self.match.player_name(self.subject(o)["from"]), o["text"], o)

    def test_every_template_passes_the_verifier_named_and_team_only(self):
        # The fallback must always be valid: every graphic x mode x language, with and without a player.
        covered = set()
        for match in (load_match(SAMPLE_A), load_match(SAMPLE_B), self.match):
            roster = {p["name"] for p in match.players.values()}
            candidates, _ = direct(match)
            for c in candidates:
                no_player = replace(c, event={**c.event, "from": None, "to": None})
                for cand, form in ((c, "named"), (no_player, "team-only")):
                    for mode in MODES:
                        req = build_request(cand, mode, match, list(templates.LANGS))
                        for lang in templates.LANGS:
                            out = templates.render(req, lang)
                            where = (c.graphic, c.event["id"], mode, lang, form, out)
                            self.assertEqual(verifier.check(out["text"], out["title"], req["values"], cand.facts,
                                                            involved_names(req), roster), [], where)
                            self.assertTrue(out["title"].strip() and out["text"].strip(), where)
                            if cand.team_only:
                                self.assertNotIn("actor", req)
                                self.assertEqual(verifier.names_in(f"{out['title']} {out['text']}", roster),
                                                 set(), where)
                            covered.add((c.graphic, form))
        self.assertEqual({g for g, _ in covered}, set(GRAPHIC_LAYOUT))
        self.assertTrue({(g, "team-only") for g in ("goal_banner", "card_banner", "shot_card", "pass_card",
                                                    "insight_text")} <= covered)

    def test_no_recap_without_clock_events(self):
        self.assertNotIn("stat_compare", {o["graphic"] for o in self.overlays})


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
