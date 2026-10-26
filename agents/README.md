# Agents

**Owner:** Person 3

Input: `match_info.json` + `events.json`. Output: `overlays.json` (schema: `schemas/overlay.schema.json`).
Develop against `data/fake/` until real events arrive; nothing here changes when they do.

## How it works

```
events.json ──► stats.py ──► director.py ──► explainer.py ──► verifier.py ──► fill.py ──► overlays.json
               (code: exact   (code: which      (LLM: words,      (code: raw text:   (code:
                numbers, as    moment, when,     numbers only as   no digit, known    numbers +
                of that        how long, which   placeholders,     placeholders;      units per
                moment)        mode, budget)     every mode and    filled text:       language)
                                                 language in one   length, names;
                                                 call)             1 retry with
                                                                   feedback, then
                                                                   template)
```

| File | Role | LLM? |
| --- | --- | --- |
| `stats.py` | Running match state (score, shots, pass accuracy, momentum, per-player counts) and per-event facts (distance, progress, difficulty 1-10, key pass, into the box) | No |
| `context.py` | Why a moment matters, as labels with no numbers: goal effect (equaliser, go-ahead...), score situation, how the attack came about (counter, set piece, build-up), momentum, phase | No |
| `director.py` | Rule table picks moments and graphics; schedules them per mode with slot collisions, a minimum gap and a screen-time budget. Logs every decision with a reason | No |
| `explainer.py` | Builds the request (facts, `values` and the `placeholders` the model may use), calls the backend, runs the verify / retry / fallback loop. The retry shows the model its rejected text next to each problem; both attempts are logged | Yes |
| `verifier.py` | Two stages. On the raw model text: rejects any digit outside a placeholder (the problem names the placeholder to use instead), a number in words ("two from two", "ikide iki", "dos de dos"), any placeholder not in this overlay's `values` (or minute/score), any mistyped one (`{ distance_m }`), a unit, `%` or `/10` next to a placeholder that already writes it (`{distance_m} m`, `{momentum_home}%`, tr `%{momentum_home}`), a letter glued to one (`{distance_m}lik`), a Turkish suffix on a number read aloud (`{score}'lik`), `{difficulty}` outside its own clause ("..., difficulty 7/10"), and in Turkish an apostrophe after a common word ("üçte bir'e"). On the filled text: length limits, text that only repeats the title or a name ("T. Castell"), player names not in the cited event or written without the initial ("finds Kurt"; any player name when `name_players` is false), in Turkish a case suffix on a player name out of vowel harmony or with the wrong buffer or t/d ("P. Rowntree'nun": write "P. Rowntree'nin"), and numbers not in `values` as a safety net | No |
| `llm.py` | Backends: `mock` (offline templates), `noisy` (invents stats as stray digits to demo the verifier), `foundry` (Microsoft Agent Framework on a Foundry / Azure OpenAI deployment, disk-cached, counts tokens). The model sees `placeholders` mapped to how each reads on screen (`"{distance_m}": "28 m"`), no bare `values`, and no `{minute}` | Yes |
| `fill.py` | Fills placeholders (`{distance_m}`, `{speed_kmh}`, `{score}`, `{minute}`, any `values` key) with numbers formatted per language (`28 m`; `km/h`, tr `km/sa`; `62%`, tr `%62`, es `62 %`; `2-1`; `7/10`; `34'`), then normalises apostrophes and spacing. Every backend's text goes through it once the verifier passes it: templates and the LLM both write placeholders | No |
| `templates.py` | Code-written text per graphic, mode and language (en, tr, es), numbers as placeholders. Mock backend + fallback | No |
| `run.py` | CLI | |

**Pass difficulty** (1-10) is a completed pass's percentile among this match's earlier completed passes, ranked by
a raw score of distance, forward progress, speed and pass type (10/10 = harder than ~90% of them; before 10
completed passes, the raw score clamped to 1-10), so it reads the same live and after the match.

Why the split: timing and budgets must be predictable live, and numbers on a broadcast must be right,
so code owns both. The LLM only writes words, and the verifier checks those words.

## Modes and what each viewer gets

| Mode | Shown when priority ≥ | Screen-time budget | Numbers |
| --- | --- | --- | --- |
| `analyst` | 0.5 | 35% | all `values` |
| `casual` | 0.75 | 15% | few (pass distance, shot speed, score) |
| `player_focus` | 0.4 | 40% per player | adds the player's running pass count |

`player_focus` overlays carry `player`; the web player shows only the ones for the viewer's chosen player.

**`player_focus` voice (decided in #46; keep it in future prompt changes):** third person about the player,
with the player's name as the title (title "K. Aydin", text "Completes 14/16, this one 28 m"). Never the first
person and never quotes: the players are fictional, so a first-person line puts invented words in their mouth.
The prompt says so, and the templates title every `player_focus` graphic that has a player with the name.
Every overlay is written once per language (`--langs`, default `en,tr,es`), so switching mode or language in the
player is instant: no LLM call at playback time.

## Detected events (`source: cv`)

Detected and true events go through the same code; nothing here branches on `source`.

- **No player, or not sure who** (`from` is null, e.g. before the first kickoff assigns the lineup, or
  `confidence` below `NAME_MIN_CONFIDENCE`, see [Naming players](#naming-players)): the graphic names the
  team ("Bosphorus FC", "What a strike from Bosphorus FC!"). The request has `name_players: false` and no
  `actor`, `target` or `setup_by`, only `subject` (the team). No `player_focus` overlay is made; `analyst`
  and `casual` are. Every template has a team-only wording, so the fallback is always valid.
- **Missing optional fields** (`duration_s`, `end`, `success`, `speed_kmh`): the facts that need them are
  left out and the rule table skips a candidate that needs them (a pass with no `end` is not counted in
  pass totals). Per-player counters skip events with no player; team totals still count them.
- **Missing event types** (no `half_time`/`full_time`, clearances or throw-ins on a short clip): no recap.
  The agents stage never invents events.
- Merged simulator events (fouls, cards, substitutions) keep their player, so a card banner names the
  booked player.

### Naming players

A graphic names a player only when the event's `from` is not null and its `confidence` is at least
`NAME_MIN_CONFIDENCE` (`director.py`). True events (confidence 1.0, or none given) are always named, so a
merged card banner still names the booked player. The same rule applies to the pass that set up a shot
(`setup_by`) and to the goals a recap names. Below it the broadcast names the team instead of maybe the
wrong player: the verifier rejects any player name in that text, in every language, Turkish suffix forms
included ("K. Aydin'den"). `agents_report.json` counts these overlays as `low_confidence_overlays`.

**Event confidence measures detection, not identity.** The vision AI's `confidence` is the event rule's
certainty times the ball and player detections' (`vision/rules.py`); nothing in it says how sure the lineup
assignment was, and wrong names come from lineup assignment. On the dev clips it barely separates right
from wrong player ids (median 0.777 right, 0.767 wrong; every graded event between 0.60 and 0.84), so a
threshold that keeps only right names (0.805: 100% on 9 events) would team-name 88% of detected events and
empty `player_focus`. The threshold is therefore a **safety floor, not a precision dial**: it removes only
the clearly poor detections.

`NAME_MIN_CONFIDENCE = 0.55`, chosen on dev1-dev3 only (87 detected events, pooled; test1 is held out, and
its single measurement belongs to the final runs, #47). It sits in the gap above the three lowest detections
(0.516-0.538, all possession changes with no true event near them) and below the lowest correctly named one
(0.596):

| Threshold | Detected events below (team-named) | Named (matched, with a player) | Player-id accuracy of the named |
| --- | --- | --- | --- |
| 0.00 | 0.0% | 75 | 0.853 |
| **0.55** | **3.4%** (3, all unmatched) | **75** | **0.853** |
| 0.65 | 8.0% | 71 | 0.845 |
| 0.75 | 17.2% | 64 | 0.875 |
| 0.80 | 85.1% | 12 | 0.917 |

Player ids are right when `from` agrees with the true event, and `to` too where it is a player (the vision
grader's rule). Unmatched detections cannot be graded, so they are not in the accuracy. Making confidence
carry lineup certainty is a vision follow-up (#56); the threshold is re-chosen when it lands.

Reproduce: `python -m vision.footage render --role dev`, `python -m vision.grade_footage --role dev`,
then `python scripts/name_threshold.py` (dev clips only; it refuses test1). It re-detects the events
from the saved observations, prints this table and the detections below the current floor.

## Run

```bash
pip install -r requirements.txt
python -m agents.run data/fake/sample_a                      # offline, template text
python -m agents.run data/fake/sample_a --backend noisy      # verifier demo: catches invented stats
python -m agents.run data/fake/sample_b --backend foundry    # real LLM (needs .env)
python scripts/validate.py data/generated/sample_a           # schema check
python -m unittest discover -s agents/tests -t .             # tests
```

Output goes to `data/generated/<match>/` (git-ignored): `overlays.json` and `agents_report.json`
(director decisions, verifier rejections, counts, run time).

### Foundry setup

1. In Microsoft Foundry, create a project and deploy a chat model (we use `gpt-5.4-mini`, Data Zone Standard,
   Sweden Central).
2. In `.env`: `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`, `AZURE_OPENAI_API_VERSION=2025-04-01-preview`,
   and `AZURE_OPENAI_API_KEY` (or leave the key empty and run `az login`).
3. `python -m agents.run data/fake/sample_a --backend foundry`. Answers are cached in
   `data/generated/llm_cache.json` after every new answer, so re-runs are free and a crash keeps
   what was already paid for. Rate limits (HTTP 429) are retried up to 6 times with exponential
   backoff (2, 4, 8, 16, 32, 60 s plus jitter); at most 4 requests run at once.

### Prompt tuning (#46)

`INSTRUCTIONS` in `llm.py` and the request shape (`prompt_view`) were tuned on **sample_a and the dev1 footage
clip only** (test1 is held out; no 90-minute match was run). Deployment: `gpt-5.4-mini`, Data Zone Standard,
Sweden Central. Every run is all three languages (en, tr, es), one call per moment and mode.
`agents_report.json` gives `verifier.template_fallback_pct` (fallback overlays / overlays) and `llm_usage`
(paid calls, cache hits, input and output tokens).

dev1 is the clip's detected events (`runs/footage/dev1/events.json`) merged with the simulator's invisible
types (`scripts/merge_events.py`; none fall in its 2 minutes), with `match_info.json` from the render.

| Run | Input | Overlays | Rejected attempts | Fixed on retry | Template fallbacks | Dropped | Low-confidence overlays | Paid calls | Tokens (in + out) | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | dev1 | 75 | 7 | 7 | 12 (16.0%) | 0 | 0 | 32 | 40k + 3.6k | $0.05 |
| 2 | dev1 | 75 | 9 | 23 | 0 (0.0%) | 0 | 0 | 34 | 45k + 4.0k | $0.06 |
| 3 | dev1 | 75 | 6 | 18 | 0 (0.0%) | 0 | 0 | 31 | 52k + 3.7k | $0.06 |
| 4 | dev1 | 75 | 7 | 11 | 3 (4.0%) | 0 | 0 | 31 | 54k + 3.8k | $0.06 |
| 5 | dev1 | 75 | 2 | 5 | 0 (0.0%) | 0 | 0 | 27 | 46k + 3.5k | $0.06 |
| 6 | sample_a | 282 | 17 | 37 | 0 (0.0%) | 0 | 0 | 111 | 194k + 14.1k | $0.23 |
| 6 | dev1 | 75 | 4 | 6 | 0 (0.0%) | 0 | 0 | 29 | 51k + 3.8k | $0.06 |
| 7 | sample_a | 282 | 14 | 30 | 1 (0.4%) | 0 | 0 | 107 | 196k + 13.4k | $0.23 |
| 7 | dev1 | 75 | 7 | 15 | 0 (0.0%) | 0 | 0 | 32 | 60k + 4.0k | $0.07 |
| **8 (final)** | **sample_a** | 282 | 18 | 36 | **3 (1.1%)** | 0 | 0 | 110 | 206k + 14.1k | $0.24 |
| **8 (final)** | **dev1** | 75 | 3 | 9 | **0 (0.0%)** | 0 | 0 | 28 | 53k + 3.6k | $0.06 |
| 9 (#60) | sample_a | 264 | 32 | 47 | 7 (2.7%) | 0 | 0 | 113 | 218k + 13.9k | $0.25 |
| 9 (#60) | dev1 | 75 | 7 | 16 | 0 (0.0%) | 0 | 0 | 32 | 62k + 4.0k | $0.07 |

Total: 1,275k input + 90k output tokens, about **$1.49**. Cost assumes $0.75 / $4.50 per 1M input / output tokens
plus ~10% for Data Zone ($0.825 / $4.95); the Azure pricing page did not show the Data Zone rates, so check the
bill. Rejected attempts count calls with at least one language rejected (run 1 counted first attempts only);
fixed on retry counts languages. Low-confidence overlays are 0 because every detected event on these inputs is
above `NAME_MIN_CONFIDENCE`.

What each round changed, from what the previous one got wrong:

1. Rewrite: limits taken from `verifier.MAX_TEXT_CHARS` / `MAX_TITLE_CHARS` (110 / 40, the prompt said 100 / 35),
   the unit rule, the third-person `player_focus` voice. Fallbacks 16%: the model copied the numbers it saw in
   `values` as digits ("1/1, a 29 m pass"), and the retry failed because it never saw its own answer.
2. The model sees each placeholder with how it reads (`"{distance_m}": "29 m"`) instead of `values`; the retry
   shows the rejected text. New checks after reading the output: surnames without the initial, glued letters
   ("23 mlik").
3. Worked example in the prompt; `{difficulty}` with its noun. Read: numbers in words ("Two from two"), Turkish
   apostrophes on common words ("son üçte bir'e"), "a difficult 8/10 switch". Checks added for all three.
4. Fallbacks 4%: stage-2 problems (surname-only titles) were hidden while stage 1 failed, so the retry fixed one
   set and hit the other. Name problems are now reported together; `{difficulty}` must be its own clause
   ("A difficulty 7/10 long pass" passed the noun-only rule); `{minute}` hidden on pass cards; a length target.
5. Glossary: "ceza sahası", not "kutu" (a literal box); "{distance_m}'lik" needs a noun after it.
6. First sample_a run (goals, cards, recaps, casual): `{score}` forced into sentences ("wide of 1-0"),
   "must settle down at 4'", lowercase titles. `{minute}` is no longer offered at all (the clock shows it).
7. Remaining first-attempt rejections were mostly correct catches: "down to ten" after a red card (a count:
   after a second red it is nine), surname-only titles. Glossary: "a man down" / "eksik kaldı" / "con uno menos".
8. Final. An independent audit of the filled text (double units, glued letters, suffixes on numbers, number
   words, stray braces, `n/10` without its noun, first person, quotes, Turkish apostrophes) found no unit or
   format error in any language; every `player_focus` title is the player's name.
9. Turkish vowel harmony on suffixed names (#60): the model wrote "P. Rowntree'nun" / "'yu". The verifier
   checks the suffix against the name's last written vowel and letter (a final consonant + "y" or "-ey" reads
   "i": "G. Ashby'nin"); one prompt line. 5 first attempts rejected for harmony, 4 fixed on retry; the fifth
   is the one harmony fallback, "H. Koc'tan": the model reads the roster's ASCII "Koc" as "Koç", the written
   rule wants "Koc'dan".
   The other 6 of sample_a's 7 fallbacks are existing checks: surname without its initial (2), `{difficulty}`
   not its own clause (2), Turkish number words "iki", "beşinci" (2).
   sample_a has 264 overlays, not 282: pass difficulty (#59) changed which passes are picked.

Reproduce: `python -m agents.run data/fake/sample_a --backend foundry`; for dev1, merge as above into a folder
and run the same. Answers are cached by instructions + request, so a re-run with the same prompt is free.

## Demo runs (#47)

The full chain on video, for dev1 (2 min) and test1 (10 min, held out). Each clip ends in a web-player folder,
`data/demo/<clip>/` (git-ignored), in the layout of `web/README.md`: `match_info.json`, the merged `events.json`,
`overlays.json` (+ `agents_report.json`), and the full-pitch clip as `match.mp4` with its `match.mp4.manifest.json`.
No `tracking.jsonl`: that is simulator truth.

```bash
C=dev1   # then C=test1
python -m vision.footage render $C              # footage (not in git): video, manifest, team sheet, truth/
python -m vision data/renders/footage/$C/$C.mp4 --out runs/footage/$C/events.json   # detected events (cv)
mkdir -p data/demo/$C
python scripts/merge_events.py runs/footage/$C/events.json data/renders/footage/$C/truth/events.json \
    --out data/demo/$C/events.json             # + the simulator's foul / cards / offside / subs (sim)
cp data/renders/footage/$C/match_info.json data/demo/$C/
cp data/renders/footage/$C/$C.mp4 data/demo/$C/match.mp4
cp data/renders/footage/$C/$C.mp4.manifest.json data/demo/$C/match.mp4.manifest.json
python -m agents.run data/demo/$C --backend foundry --out data/demo/$C
python scripts/validate.py data/demo/$C
(cd web && MATCH=data/demo/$C npm run build)
```

`python -m vision.grade_footage $C` writes the same `runs/footage/$C/events.json` (it runs `python -m vision` as a
child process) and grades it; test1's events are the ones saved by its single vision grade (#22). The merge adds
3 fouls to test1 and nothing to dev1. Final code: commit `bada623`.

| Run | Input | Overlays | Rejected attempts | Fixed on retry | Template fallbacks | Dropped | Low-confidence overlays | Paid calls | Tokens (in + out) | Cost | Deployment |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| final | dev1 | 75 | 4 | 6 | 0 (0.0%) | 0 | 0 | 29 | 56k + 3.6k | $0.06 | gpt-5.4-mini |
| final | calibration | 12 | 0 | 0 | 0 (0.0%) | 0 | 0 | 4 | 7k + 0.4k | $0.01 | gpt-5.4-mini |
| **final (held out)** | **test1** | 270 | 25 | 51 | **2 (0.7%)** | 0 | 0 | 113 | 220k + 13.9k | $0.25 | gpt-5.4-mini |

Total for #47: 283k input + 18k output tokens, about **$0.32** (rates as above). dev1's row adds the one paid
call made after its first run: the model answered tr `{"title": "T. Castell", "text": "T. Castell"}`, the verifier
passed it, and the check for text that only repeats the title or a name was added; the retry fixed it. test1's
2 fallbacks are existing checks: `{difficulty}` not its own clause (en) and a Turkish suffix out of harmony
("S. Marsh'e"). Low-confidence overlays are 0 on both: no detected event is below `NAME_MIN_CONFIDENCE`.

**Goal banner on detected events.** Neither clip has one: dev1's 2 minutes hold one shot and no goal, and the
tracer missed the shot; test1 has no goals. The banner is shown on the calibration clip instead, whose 3 events
(pass, shot, goal) are all `cv`: "Bosphorus FC lead / ... set the tone at 1-0" (en, tr, es; analyst and casual).
It names the team, not the scorer: the clip has no kickoff, so the lineup is never assigned and `from` is null.
Reproduce: `python -m vision vision/fixtures/calibration/calibration.mp4 --out runs/calibration/events.json`,
merge with `renderer/fixtures/calibration/ground_truth.events.json` into `runs/calibration/merged/`, copy
`vision/fixtures/calibration/match_info.json` there and run the agents on it as above.

**Held-out naming result (test1, measured once).** `python scripts/name_threshold.py --held-out test1` with
`NAME_MIN_CONFIDENCE = 0.55` fixed on dev1-dev3, on the saved tracer events the demo shows:

| Clip | Detected events | Named (player shown) | Below the threshold | Player-id accuracy of the named (matched) |
| --- | --- | --- | --- | --- |
| dev1-dev3 (chosen on) | 87 | not measured | 3.4% | 0.853 (75 events) |
| **test1 (held out)** | **147** | **94.6%** (139) | **0.0%** | **0.910** (121 of 133) |

The other 8 test1 events have no player (`from` null), so they are team-named. Of the 139 named, 133 match a true
event and 121 of them name the right player(s); 6 are unmatched and cannot be graded. About 1 in 11 named
graphics on test1 names the wrong player, which is the lineup-assignment limit described above (#56). The
threshold did not change after this measurement.

## Next steps (P3 backlog)

- [x] Run `--backend foundry` on sample_a, tune `INSTRUCTIONS` in `llm.py` until the verifier rarely rejects (#46).
- [x] Richer "why it matters": `context.py` labels (goal effect, score situation, lead-in, momentum, phase).
- [ ] Turn the pipeline into an Agent Framework workflow (director → explainer → verifier as executors) for the multi-agent category; keep the same functions inside.
- [ ] Live mode: consume events one by one (Event Hubs) and emit overlays with a measured latency.
- [x] Half-time / full-time recap: score, shots, on target, scorers; cites every shot, goal and red card, so its numbers can be recomputed from the cited events. The momentum bar cites the events in its 5-minute window.
- [x] Add `es` to show multi-language reach.
