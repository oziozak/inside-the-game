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
from agents.fill import UnknownPlaceholder, fill
from agents.context import goal_effect, lead_in, scoring_side
from agents.data_io import load_match
from agents.director import GRAPHIC_LAYOUT, MODES, NAME_MIN_CONFIDENCE, direct, propose
from agents.explainer import build_request, explain_all, involved_names
from agents.llm import (INSTRUCTIONS, RATE_LIMIT_DELAYS_S, FoundryBackend, MockBackend, NoisyBackend, cache_key,
                        is_rate_limit, parse_json_reply, prompt_view)
from agents.stats import (MOMENTUM_WINDOW_S, PASS_TYPES, PERCENTILE_MIN_PASSES, MatchState, attacks_positive_x,
                          display_minute, event_facts, pass_difficulty, pass_difficulty_raw, threat_share,
                          threat_weight)

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

    def test_raw_difficulty_is_not_capped(self):
        # The ranking key keeps growing past 10: a 49 m switch and a 60 m through ball stay apart.
        self.assertAlmostEqual(pass_difficulty_raw(5, 30, 0, "short"), 1.625)
        self.assertAlmostEqual(pass_difficulty_raw(49, 80, 10, "long"), 10.458, places=3)  # the 49 m switch in #59
        self.assertAlmostEqual(pass_difficulty_raw(60, 90, 50, "through"), 17.167, places=3)

    def test_difficulty_falls_back_to_clamped_raw_early(self):
        few = [3.0] * (PERCENTILE_MIN_PASSES - 1)
        self.assertEqual(pass_difficulty(1.625, few), 2)
        self.assertEqual(pass_difficulty(14.0, few), 10)
        self.assertEqual(pass_difficulty(0.2, []), 1)

    def test_difficulty_is_a_percentile_once_enough_passes(self):
        past = [float(x) for x in range(1, 101)]  # 100 completed passes, raw 1..100
        self.assertEqual(pass_difficulty(0.5, past), 1)  # easier than all of them
        self.assertEqual(pass_difficulty(50.5, past), 6)  # harder than half
        self.assertEqual(pass_difficulty(89.5, past), 9)  # harder than 89%
        self.assertEqual(pass_difficulty(90.5, past), 10)  # harder than 90%
        self.assertEqual(pass_difficulty(500.0, past), 10)

    def test_difficulty_ranks_against_earlier_completed_passes_only(self):
        state = MatchState(info={"kickoff_direction": {"home": "left_to_right"}})

        def play(d, success=True):
            n = state.teams["home"].passes + 1
            e = {"id": f"e{n:04d}", "t": float(n), "type": "pass", "subtype": "short", "team": "home", "from": 7,
                 "start": [30.0, 34.0], "end": [30.0 + d, 34.0], "distance_m": d, "speed_kmh": 40.0, "success": success}
            state.update(e)
            return event_facts(e, state)["difficulty"]

        for _ in range(10):
            play(5)
        for _ in range(20):
            self.assertEqual(play(40, success=False), 10)  # rated, but never joins the pool
        self.assertEqual(play(20), 10)  # harder than every completed pass so far: the failed long ones do not count
        self.assertEqual(play(5), 5)  # ties the ten short passes, below the 20 m one: (5 + 0) / 11 -> 5

    def test_difficulty_spreads_over_the_scale_on_the_samples(self):
        # #59: the old capped score put any pass over ~40 m at 9-10. Shown difficulty must use 1-10.
        for folder in (SAMPLE_A, SAMPLE_B):
            match = load_match(folder)
            state, shown = MatchState(info=match.info), []
            for e in match.events:
                state.update(e)
                f = event_facts(e, state)
                if e["type"] in PASS_TYPES and e.get("success") and "difficulty" in f:
                    shown.append(f["difficulty"])
            with self.subTest(folder.name):
                self.assertEqual(set(shown), set(range(1, 11)))
                # ~10% at 10: a past-only rank reads 12% on both samples (sample_b's passes shuffled: 9-12%).
                self.assertLessEqual(shown.count(10) / len(shown), 0.13)


class VerifierTest(unittest.TestCase):
    def test_rejects_invented_number(self):
        p = verifier.check("{distance_m} pass, 87% xG", "K. Aydin", {"distance_m": 23}, {}, {"K. Aydin"},
                           {"K. Aydin"}, "en")
        self.assertTrue(any("87" in x for x in p))

    def test_a_digit_outside_a_placeholder_names_the_placeholder_to_use(self):
        # Stage 1 runs on the model's raw text: even a correct number must be a placeholder.
        p = verifier.check("23 m pass", "K. Aydin", {"distance_m": 23}, {}, {"K. Aydin"}, {"K. Aydin"}, "en")
        self.assertEqual(len(p), 1, p)
        self.assertIn("23", p[0])
        self.assertIn("{distance_m}", p[0])

    def test_a_placeholder_not_in_values_is_rejected(self):
        # A casual pass card carries only the distance: the model may not show the difficulty.
        p = verifier.check("{distance_m} pass, difficulty {difficulty}", "", {"distance_m": 23}, {}, set(), set(), "en")
        self.assertEqual(len(p), 1, p)
        self.assertIn("{difficulty}", p[0])
        self.assertEqual(verifier.check("{score}", "", {}, {"minute": 9}, set(), set(), "en"),
                         ["unknown placeholder {score} (allowed: {minute})"])

    def test_difficulty_out_of_ten_is_one_placeholder(self):
        # {difficulty} already fills as "7/10": suggesting {difficulty_max} for the 10 led to "7/10/10".
        v = {"difficulty": 7, "difficulty_max": 10}
        p = verifier.check("difficulty 7/10", "", v, {}, set(), set(), "en")
        self.assertEqual(len(p), 2, p)
        self.assertIn("{difficulty}", p[0])
        self.assertNotIn("difficulty_max", " ".join(p))
        self.assertIn("unknown placeholder {difficulty_max}",
                      verifier.check("{difficulty}/{difficulty_max}", "", v, {}, set(), set(), "en")[0])

    def test_a_malformed_placeholder_is_rejected(self):
        for text in ("{ distance_m } pass", "{distance-m} pass", "{distance_m pass"):
            p = verifier.check(text, "", {"distance_m": 23}, {}, set(), set(), "en")
            self.assertEqual(len(p), 1, (text, p))
            self.assertIn("{distance_m}", p[0])

    def test_a_unit_next_to_a_placeholder_is_rejected(self):
        # The placeholder's format already writes the unit: "{distance_m} m" would read "23 m m".
        v = {"distance_m": 23, "speed_kmh": 112, "momentum_home": 62, "difficulty": 7, "difficulty_max": 10}
        f = {"minute": 34, "score_home": 2, "score_away": 1}
        for text, lang in (("{distance_m} m pass", "en"), ("{distance_m}m pass", "en"),
                           ("{distance_m} metrelik pas", "tr"), ("pase de {distance_m} metros", "es"),
                           ("{speed_kmh} km/h", "en"), ("{speed_kmh} km/sa hızla", "tr"),
                           ("{momentum_home}% of the threat", "en"), ("baskı %{momentum_home}", "tr"),
                           ("yüzde {momentum_home} baskı", "tr"), ("{momentum_home} por ciento", "es"),
                           ("difficulty {difficulty}/10", "en"), ("{minute}. dakikada gol", "tr"),
                           ("{minute} min", "en")):
            p = verifier.check(text, "", v, f, set(), set(), lang)
            self.assertEqual(len(p), 2 if "/10" in text else 1, (text, p))  # + "digit 10 outside a placeholder"
            self.assertRegex(p[0], r"next to \{\w+\}: code writes the unit", text)
        p = verifier.check("{momentum_home}% baskı", "", v, f, set(), set(), "tr")
        self.assertIn("already reads '%62'", p[0])

    def test_a_placeholder_followed_by_a_word_or_name_is_not_a_unit(self):
        v = {"distance_m": 23, "window_min": 5, "speed_kmh": 112}
        f = {"minute": 34, "score_home": 2, "score_away": 1}
        for text, lang in (("{distance_m} más lejos", "es"), ("{score} M. Aydin", "en"),
                           ("last {window_min} min", "en"), ("son {window_min} dakikada", "tr"),
                           ("{distance_m}'lik pas", "tr"), ("{speed_kmh}'lik şut", "tr"),
                           ("{distance_m} midfield ball", "en")):
            self.assertEqual(verifier.check(text, "", v, f, {"M. Aydin"}, {"M. Aydin"}, lang), [], text)

    def test_no_suffix_after_a_number_read_aloud(self):
        # Turkish vowel harmony depends on the number, which the model never sees; {minute} ends in '.
        f = {"minute": 34, "score_home": 2, "score_away": 1}
        p = verifier.check("{minute}'te gol", "", {}, f, set(), set(), "tr")
        self.assertEqual(p, ["apostrophe after {minute}: it already reads '34'', write nothing after it"])
        p = verifier.check("{score}'lik skor", "", {}, f, set(), set(), "tr")
        self.assertEqual(len(p), 1, p)
        self.assertIn("suffix after {score}", p[0])

    def test_a_letter_right_after_a_placeholder_is_rejected(self):
        p = verifier.check("{distance_m}lik pas", "", {"distance_m": 23}, {}, set(), set(), "tr")
        self.assertEqual(p, ["letter right after {distance_m}: it reads '23 m', put a space after it, "
                             "or an apostrophe before a suffix ({distance_m}'lik)"])

    def test_numbers_in_words_are_rejected(self):
        # An LLM-written number the digit check cannot see; "one"/"bir"/"un" are also articles.
        v = {"player_passes": 2, "player_passes_completed": 2}
        for text, lang in (("Two from two", "en"), ("İkide iki", "tr"), ("Dos de dos", "es")):
            p = verifier.check(text, "", v, {}, set(), set(), lang)
            self.assertTrue(p and all(x.startswith("number word") for x in p), (text, p))
        for text, lang in (("This one goes into the final third", "en"), ("Son üçte birlik bölgeye bir pas", "tr"),
                           ("Un robo en tres cuartos", "es"), ("Şut blok yedi", "tr"), ("A neat one-two", "en")):
            self.assertEqual(verifier.check(text, "", v, {}, set(), set(), lang), [], text)

    def test_difficulty_needs_its_noun(self):
        v = {"difficulty": 7, "difficulty_max": 10, "distance_m": 26}
        # A stat tag in its own clause: "a difficulty {difficulty} long pass" satisfied a noun-only rule.
        for text in ("a difficult {difficulty} {distance_m} pass", "a difficulty {difficulty} long pass"):
            p = verifier.check(text, "", v, {}, set(), set(), "en")
            self.assertEqual(len(p), 1, p)
            self.assertIn("its own clause", p[0])
        for text, lang in (("{distance_m} pass, difficulty {difficulty}", "en"), ("zorluk derecesi {difficulty}", "tr"),
                           ("Uzun pas. Zorluk: {difficulty}", "tr"), ("un pase de dificultad {difficulty}", "es")):
            self.assertEqual(verifier.check(text, "", v, {}, set(), set(), lang), [], text)

    def test_turkish_apostrophe_only_after_a_name_or_number(self):
        roster = {"A. Kurt"}
        p = verifier.check("son üçte bir'e uzun top", "", {}, {}, roster, roster, "tr")
        self.assertEqual(len(p), 1, p)
        self.assertIn("common word 'bir'", p[0])
        self.assertEqual(verifier.check("A. Kurt'a {distance_m}'lik pas, Bosphorus FC'yi taşıdı", "",
                                        {"distance_m": 23}, {}, roster, roster, "tr"), [])

    def test_a_surname_needs_its_initial(self):
        roster = {"A. Kurt", "S. Polat", "E. Demir"}
        p = verifier.check("Long ball", "S. Polat finds Kurt", {}, {}, {"S. Polat", "A. Kurt"}, roster, "en")
        self.assertEqual(p, ["surname 'Kurt' without its initial: write 'A. Kurt'"])
        self.assertEqual(verifier.check("Pas: A. Kurt'a", "S. Polat", {}, {}, {"S. Polat", "A. Kurt"}, roster,
                                        "tr"), [])
        p = verifier.check("Demir'e uzun top", "", {}, {}, {"S. Polat"}, roster, "tr")
        self.assertEqual(p, ["player 'Demir' is not part of the cited event"])
        p = verifier.check("Pase para Kurt", "Bosphorus FC", {}, {}, set(), roster, "es", name_players=False)
        self.assertIn("name the team", p[0])

    def test_length_is_checked_on_the_filled_text(self):
        # "{speed_kmh}" is 11 characters raw, "112 km/h" 8 in en and "112 km/sa" 9 in tr.
        v = {"speed_kmh": 112}
        text = "x" * (verifier.MAX_TEXT_CHARS - 8) + "{speed_kmh}"
        self.assertGreater(len(text), verifier.MAX_TEXT_CHARS)
        self.assertEqual(verifier.check(text, "", v, {}, set(), set(), "en"), [])
        p = verifier.check(text, "", v, {}, set(), set(), "tr")
        self.assertEqual(p, [f"text too long ({verifier.MAX_TEXT_CHARS + 1} > {verifier.MAX_TEXT_CHARS} chars)"])

    def test_rejects_wrong_player(self):
        p = verifier.check("E. Demir with the pass", "", {}, {}, {"K. Aydin"}, {"K. Aydin", "E. Demir"}, "en")
        self.assertTrue(any("not part of" in x for x in p))

    def test_accepts_backed_text(self):
        self.assertEqual(verifier.check("{distance_m} pass", "K. Aydin", {"distance_m": 23.0}, {}, {"K. Aydin"},
                                        {"K. Aydin"}, "en"), [])

    def test_turkish_suffix_on_a_real_name_passes(self):
        self.assertEqual(verifier.check("K. Aydin'den harika pas", "", {}, {}, {"K. Aydin"}, {"K. Aydin"}, "tr"), [])

    def test_turkish_suffix_on_a_name_follows_vowel_harmony(self):
        roster = {"P. Rowntree", "A. Kurt", "C. Hollis"}
        p = verifier.check("P. Rowntree'nun uzun topu", "", {}, {}, roster, roster, "tr")
        self.assertEqual(p, ["suffix after 'P. Rowntree' breaks vowel harmony: write P. Rowntree'nin, "
                             "not P. Rowntree'nun"])
        self.assertEqual(verifier.check("P. Rowntree'nin uzun topu", "", {}, {}, roster, roster, "tr"), [])

    def test_turkish_buffer_letter_and_vowel_on_accusative_and_dative(self):
        roster = {"P. Rowntree", "A. Kurt", "C. Hollis"}
        for wrong, right in (("P. Rowntree'yu", "P. Rowntree'yi"), ("P. Rowntree'e", "P. Rowntree'ye"),
                             ("C. Hollis'a", "C. Hollis'e"), ("A. Kurt'ya", "A. Kurt'a"),
                             ("C. Hollis'ı", "C. Hollis'i")):
            p = verifier.check(f"{wrong} pas", "", {}, {}, roster, roster, "tr")
            self.assertEqual(len(p), 1, (wrong, p))
            self.assertIn(f"write {right}, not {wrong}", p[0])
        for ok in ("P. Rowntree'ye", "P. Rowntree'yi", "A. Kurt'a", "A. Kurt'u", "C. Hollis'e", "C. Hollis'in"):
            self.assertEqual(verifier.check(f"{ok} pas", "", {}, {}, roster, roster, "tr"), [], ok)

    def test_turkish_t_after_a_hard_consonant_on_locative_and_ablative(self):
        roster = {"P. Rowntree", "A. Kurt", "C. Hollis", "T. Castell"}
        for wrong, right in (("A. Kurt'dan", "A. Kurt'tan"), ("C. Hollis'den", "C. Hollis'ten"),
                             ("P. Rowntree'dan", "P. Rowntree'den"), ("T. Castell'te", "T. Castell'de")):
            p = verifier.check(f"{wrong} pas", "", {}, {}, roster, roster, "tr")
            self.assertEqual(len(p), 1, (wrong, p))
            self.assertIn(f"write {right}, not {wrong}", p[0])
        for ok in ("A. Kurt'tan", "A. Kurt'ta", "C. Hollis'ten", "P. Rowntree'deki", "T. Castell'den"):
            self.assertEqual(verifier.check(f"{ok} pas", "", {}, {}, roster, roster, "tr"), [], ok)

    def test_a_final_y_after_a_consonant_reads_as_the_vowel_i(self):
        roster = {"G. Ashby", "J. Hartley", "R. Aksoy"}
        for ok in ("G. Ashby'nin", "J. Hartley'ye", "J. Hartley'den", "R. Aksoy'un", "R. Aksoy'a"):
            self.assertEqual(verifier.check(f"{ok} pas", "", {}, {}, roster, roster, "tr"), [], ok)
        p = verifier.check("G. Ashby'ın pası", "", {}, {}, roster, roster, "tr")
        self.assertIn("write G. Ashby'nin, not G. Ashby'ın", p[0])

    def test_other_suffixes_and_languages_are_not_checked(self):
        roster = {"P. Rowntree", "C. Hollis"}
        for text, lang in (("P. Rowntree'yle C. Hollis'ler", "tr"), ("P. Rowntree'nun", "en")):
            self.assertEqual(verifier.check(text, "", {}, {}, roster, roster, lang), [], text)
        self.assertEqual(verifier.check("X. Ng'nin pası", "", {}, {}, {"X. Ng"}, {"X. Ng"}, "tr"), [])  # no vowel

    def test_turkish_letters_are_read_as_one_name(self):
        p = verifier.check("K. Aydın ile hücum", "", {}, {}, {"K. Aydin"}, {"K. Aydin"}, "tr")
        self.assertEqual(p, ["unknown player name 'K. Aydın'"])

    def test_invented_name_with_turkish_initial_is_rejected(self):
        p = verifier.check("Ç. Uydurma'dan gol", "", {}, {}, {"K. Aydin"}, {"K. Aydin"}, "tr")
        self.assertEqual(p, ["unknown player name 'Ç. Uydurma'"])

    def test_no_player_may_be_named_when_naming_is_off(self):
        # Low-confidence event: even a roster player who is "involved" must not be named, in any language.
        roster = {"K. Aydin", "E. Demir"}
        for text, lang in (("Great pass from K. Aydin", "en"), ("K. Aydin'den harika pas", "tr"),
                           ("E. Demir'in şutu", "tr"), ("¡Qué disparo de K. Aydin!", "es"),
                           ("Ç. Uydurma'dan gol", "tr")):
            p = verifier.check(text, "Bosphorus FC", {}, {}, {"K. Aydin"}, roster, lang, name_players=False)
            self.assertEqual(len(p), 1, (text, p))
            self.assertIn("name the team", p[0])
        self.assertEqual(verifier.check("Bosphorus FC'den harika pas", "Bosphorus FC", {}, {}, set(), roster, "tr",
                                        name_players=False), [])

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


class AlwaysDigits(MockBackend):
    """An LLM that never learns: writes a digit every time, so every text falls back to the template."""

    def __init__(self) -> None:
        self.feedback = []

    async def explain(self, req: dict, feedback: str | None = None) -> dict:
        self.feedback.append(feedback)
        return {l: {"title": "x", "text": "a 99 m pass"} for l in req["langs"]}


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

    def test_request_lists_the_placeholders_the_model_may_use(self):
        match = load_match(SAMPLE_A)
        candidates, _ = direct(match)
        c = next(c for c in candidates if c.graphic == "pass_card" and "difficulty" in c.values)
        casual = build_request(c, "casual", match, ["en"])
        self.assertEqual(casual["placeholders"], ["{distance_m}", "{minute}", "{score}"])
        analyst = build_request(c, "analyst", match, ["en"])
        self.assertIn("{difficulty}", analyst["placeholders"])

    def test_noisy_llm_numbers_never_reach_the_screen(self):
        overlays, report = self.run_pipeline(NoisyBackend())
        self.assertGreater(len(report["rejected"]), 0)
        for r in report["rejected"]:
            self.assertEqual(set(r["problems"]), set(templates.LANGS), r)  # kept after the retry fixed them
            for problems in r["problems"].values():
                self.assertTrue(any(p.startswith("digit 87 outside a placeholder") for p in problems), r)
        self.assertGreater(report["fixed_on_retry"], 0)
        self.assertEqual(report["template_fallbacks"], 0)
        self.assertFalse(any("87" in o["text"] for o in overlays))

    def test_the_model_sees_each_placeholder_with_how_it_reads(self):
        # Next to its placeholder, with the unit: the model copied bare `values` numbers as digits.
        match = load_match(SAMPLE_A)
        candidates, _ = direct(match)
        c = next(c for c in candidates if c.graphic == "pass_card" and "difficulty" in c.values)
        req = build_request(c, "analyst", match, ["en"])
        view = prompt_view(req)
        self.assertNotIn("values", view)
        self.assertEqual(view["placeholders"]["{distance_m}"], f"{req['values']['distance_m']} m")
        self.assertEqual(view["placeholders"]["{difficulty}"], f"{req['values']['difficulty']}/10")
        self.assertNotIn("{minute}", view["placeholders"])  # the broadcast clock shows it
        self.assertIn("{minute}", req["placeholders"])  # still accepted by the verifier

    def test_prompt_length_limits_are_the_verifiers(self):
        self.assertIn(f"`text` at most {verifier.MAX_TEXT_CHARS} characters", INSTRUCTIONS)
        self.assertIn(f"`title` at most {verifier.MAX_TITLE_CHARS}", INSTRUCTIONS)

    def test_retry_shows_the_rejected_text_and_both_attempts_are_logged(self):
        backend = AlwaysDigits()
        match = load_match(SAMPLE_A)
        candidates, _ = direct(match)
        overlays, report = asyncio.run(explain_all(candidates[:1], match, backend, ["en"]))
        self.assertIn('"text": "a 99 m pass"', backend.feedback[1])
        self.assertEqual([r["attempt"] for r in report["rejected"]][:2], [1, 2])
        self.assertEqual(report["template_fallbacks"], len(overlays))

    def test_player_focus_templates_are_titled_with_the_players_name(self):
        overlays, _ = self.run_pipeline(MockBackend())
        match = load_match(SAMPLE_A)
        focus = [o for o in overlays if o["mode"] == "player_focus" and o["player"] is not None]
        self.assertGreater(len(focus), 0)
        for o in focus:
            self.assertEqual(o["title"], match.player_name(o["player"]), o)

    def test_report_gives_the_template_fallback_share(self):
        from agents import run
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch("sys.argv", ["run", str(SAMPLE_A), "--out", tmp]), \
                mock.patch("agents.run.make_backend", return_value=AlwaysDigits()), mock.patch("builtins.print"):
            run.main()
            report = json.loads((Path(tmp) / "agents_report.json").read_text("utf-8"))
        v = report["verifier"]
        self.assertEqual(v["template_fallbacks"], report["overlays_out"])  # every text is the template
        self.assertEqual(v["template_fallback_pct"], 100.0)

    def test_mock_run_needs_no_fallback_and_drops_nothing(self):
        overlays, report = self.run_pipeline(MockBackend())
        self.assertGreater(len(overlays), 0)
        self.assertEqual((report["rejected"], report["template_fallbacks"], report["dropped"]), ([], 0, []))


DETECTED_TYPES = {"kickoff", "pass", "possession_change", "shot", "goal"}  # what the vision AI detects
MERGED_SIM_TYPES = {"foul", "yellow_card", "red_card", "offside", "substitution"}  # scripts/merge_events.py
UNSURE, SURE = round(NAME_MIN_CONFIDENCE / 2, 3), round((NAME_MIN_CONFIDENCE + 0.99) / 2, 3)


def as_detected(match):
    """sample_a as the vision AI + merge_events.py would deliver it: only detected types
    (plus the merged simulator ones), confidences below 1 on both sides of NAME_MIN_CONFIDENCE,
    no player on every other detected event and on the goal, some optional fields missing,
    no half_time/full_time."""
    events = []
    for i, e in enumerate(match.events):
        if e["type"] not in DETECTED_TYPES | MERGED_SIM_TYPES:
            continue
        e = dict(e)
        if e["type"] in DETECTED_TYPES:
            e.update(source="cv", confidence=UNSURE if i % 4 == 0 else SURE)
            if i % 2 or e["type"] == "goal":
                e["from"] = e["to"] = None
            if i % 5 == 0:
                for k in ("duration_s", "end", "success", "speed_kmh"):
                    e.pop(k, None)
        events.append(e)
    match.events = events
    return match


class NamesAnyone(MockBackend):
    """A careless LLM: names the first roster player in every text."""

    def __init__(self, name: str) -> None:
        self.player_name = name

    async def explain(self, req: dict, feedback: str | None = None) -> dict:
        out = await super().explain(req, feedback)
        return {l: {**t, "text": f"{self.player_name}: {t['text']}"[:100]} for l, t in out.items()}


class DetectedEventsTest(unittest.TestCase):
    """The agents stage on detected events: nothing branches on `source`, only null players
    and low confidence change what is shown."""

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

    def detected_with_player(self, e, confidence):
        """Whether `e` is a detected event with a player, at this confidence."""
        return e["from"] is not None and e["confidence"] == confidence

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

    def test_low_confidence_events_are_worded_about_the_team(self):
        unsure = [o for o in self.overlays if self.detected_with_player(self.subject(o), UNSURE)]
        self.assertTrue({"shot_card", "pass_card"} <= {o["graphic"] for o in unsure}, unsure)
        for o in unsure:
            self.assertNotEqual(o["mode"], "player_focus", o)
            self.assertIsNone(o["player"], o)
            self.assertEqual(verifier.names_in(f"{o['title']} {o['text']}", self.roster), set(), o)
            self.assertIn(self.match.team_name(self.subject(o)["team"]), o["title"] + o["text"], o)
        self.assertEqual(self.report["low_confidence_overlays"], len(unsure))

    def test_confident_detected_events_keep_the_players_name(self):
        sure = [o for o in self.overlays if o["graphic"] in ("shot_card", "pass_card")
                and self.detected_with_player(self.subject(o), SURE)]
        self.assertIn("player_focus", {o["mode"] for o in sure})
        for o in sure:
            self.assertEqual(o["player"], self.subject(o)["from"])
            self.assertIn(self.match.player_name(self.subject(o)["from"]), o["title"], o)

    def test_verifier_rejects_a_name_on_a_low_confidence_graphic(self):
        candidates, _ = direct(self.match)
        overlays, report = asyncio.run(explain_all(candidates, self.match, NamesAnyone(min(self.roster)),
                                                   list(templates.LANGS)))
        uncertain = [r for r in report["rejected"]
                     if self.detected_with_player(self.by_id[r["event_id"]], UNSURE)]
        self.assertGreater(len(uncertain), 0)
        for r in uncertain:
            self.assertTrue(all("name the team" in " ".join(p) for p in r["problems"].values()), r)
        self.assertEqual(report["dropped"], [])

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
                            raw = templates.render(req, lang)
                            out = {k: fill(raw[k], req["values"], lang, req["facts"]) for k in raw}
                            where = (c.graphic, c.event["id"], mode, lang, form, raw)
                            self.assertNotRegex(raw["title"] + raw["text"], r"\d", where)  # numbers only via placeholders
                            self.assertEqual(verifier.check(raw["text"], raw["title"], req["values"], req["facts"],
                                                            involved_names(req), roster, lang, req["name_players"]),
                                             [], where)
                            self.assertTrue(out["title"].strip() and out["text"].strip(), where)
                            if cand.team_only:
                                self.assertNotIn("actor", req)
                                self.assertEqual(verifier.names_in(f"{out['title']} {out['text']}", roster),
                                                 set(), where)
                            covered.add((c.graphic, form))
        self.assertEqual({g for g, _ in covered}, set(GRAPHIC_LAYOUT))
        self.assertTrue({(g, "team-only") for g in ("goal_banner", "card_banner", "shot_card", "pass_card",
                                                    "insight_text")} <= covered)

    def test_low_confidence_requests_name_no_player(self):
        match = load_match(SAMPLE_B)
        candidates, _ = direct(match)
        shot = next(c for c in candidates if c.graphic == "shot_card" and c.setup)
        at, below = NAME_MIN_CONFIDENCE, round(NAME_MIN_CONFIDENCE - 0.01, 3)
        sure = replace(shot, event={**shot.event, "confidence": at}, setup={**shot.setup, "confidence": at})
        unsure = replace(shot, event={**shot.event, "confidence": below})
        unsure_setup = replace(sure, setup={**shot.setup, "confidence": below})
        for mode in ("analyst", "casual"):
            req = build_request(sure, mode, match, ["en"])
            self.assertTrue(req["name_players"])
            self.assertEqual((req["actor"], req["setup_by"]),
                             (match.player_name(shot.event["from"]), match.player_name(shot.setup["from"])))
            req = build_request(unsure, mode, match, ["en"])
            self.assertFalse(req["name_players"])
            self.assertFalse({"actor", "target", "setup_by"} & set(req), req)
            self.assertEqual(req["subject"], match.team_name(shot.event["team"]))
            # A confident shot set up by an unsure pass names the shooter, not the passer.
            req = build_request(unsure_setup, mode, match, ["en"])
            self.assertTrue(req["name_players"])
            self.assertIsNone(req["setup_by"])
        self.assertIsNone(unsure.player)

    def test_no_recap_without_clock_events(self):
        self.assertNotIn("stat_compare", {o["graphic"] for o in self.overlays})


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
            out = asyncio.run(backend.explain({"langs": ["en"], "event_type": "goal", "values": {}, "facts": {},
                                               "placeholders": []}))
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
