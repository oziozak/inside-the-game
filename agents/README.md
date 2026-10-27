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
| `tactics.py` | Tactical facts from frame observations + detected events: shape vs team sheet, line height, compactness, width, flanks, regains by third, long balls, progressive passes, each with its coverage and frames / event ids ([Tactical facts](#tactical-facts-67)) | No |
| `analyst.py` | Post-match report: insight candidates from `tactics.json` (code), selection by salience and coverage, the analyst agent's headline + insights in every language, the same verifier plus uncited claims, missing hedges, numbers without their noun and languages that disagree, every number read back from `tactics.json` ([Analyst report](#analyst-report-69)) | Yes |
| `analyst_templates.py` | Code-written report text per topic and language: mock backend + fallback | No |
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

## Tactical facts (#67)

`tactics.py` turns what the vision AI saw into team-level tactical facts, by code only (no LLM), as
`tactics.json` (`schemas/tactics.schema.json`). Inputs: the tracer's `observations.jsonl`, the detected (or merged)
`events.json` and `match_info.json`, nothing else; it never opens `truth/` or simulator tracking (the file-open
guard in `tests/test_vision_pipeline.py` runs it with both beside the clip). The analyst (`analyst.py`) reads it.

```bash
C=dev1
python -m agents.tactics runs/footage/$C/observations.jsonl --events runs/footage/$C/events.json \
    --match-info data/renders/footage/$C/match_info.json --out runs/footage/$C/tactics.json
```

- **Who is who.** The vision rules are replayed over the observations, so each track is named by the same
  lineup assignment that named the events' players. Goalkeepers and unnamed tracks are left out. Before the
  first kickoff nothing is named, so the shape facts are empty (the calibration clip has no kickoff).
- **Who has the ball.** Per frame, from the same replay (`EventRules.team_with_ball`): the team of the track
  in possession (GLOSSARY), or while a kick is in flight the kicker's. A dead ball (out of play, in the net)
  or a loose one is neither team's: those frames count only for `all`. On dev1-dev3, 92%, 78% and 40% of
  frames are in a team's possession; dev3's ball is often not seen.
- **Team frame.** Depth is meters from the team's own goal line; left, centre and right are thirds of the
  width as the team sees it attacking.
- **Segments.** The whole clip, then before and after each goal or red card (`split_by` is its event id).
  Red cards come from the simulator, so those splits need the merged events.

Per team and segment (`all`, `in_possession` and `out_of_possession` where it applies):

| Fact | Value | Evidence |
| --- | --- | --- |
| `shape` | actual formation next to the team sheet's: players' mean depths split back to front into as many lines as the sheet has (least squared spread; a 5-3-2 whose wing-backs push up reads 3-5-2); the sheet's own lines (a 4-2-3-1's AM and wingers make one) with mean depth and width; each player's mean position over the frames they were seen in | `frames`; per player `n_frames` |
| `defensive_line_m` | mean depth of the back line (team-sheet defenders) | `frames` |
| `compactness_m` | front line's (team-sheet attackers) mean depth minus the back line's | `frames` |
| `attacking_width_m` | in possession: outfield spread across the pitch (widest minus narrowest y) | `frames` |
| `final_third_flanks` | left / centre / right %: of passes ending in the final third (completed or not), and of in-possession frames with the ball there | `event_ids` / `frames` per flank |
| `regains` | ball won back per third (`high` = final third: pressing height): every possession change, and a failed pass the other team plays on in open play (a restart is not a regain) | `event_ids` per third |
| `long_balls` | share of passes longer than 30 m (a team's directness; the pass subtype `long` splits at 25 m) | `event_ids` counted, `long_event_ids` |
| `progressive_passes` | completed passes moving the ball at least 30 m toward the goal line within the own half, 15 m across halfway, 10 m in the opponent half | `event_ids` counted, `progressive_event_ids` |

**Coverage** (#69). Every fact has `coverage`, the share (0-1) of its segment it could see, and each segment has
`frames`: `n_frames`, `possession_known`, `ball_seen`. A whole-clip frame fact: its frames over the segment's.
An in- or out-of-possession one: its frames over the team's frames in that phase, times the share of frames whose
possession is known (in the others the phase is unknown). An event fact: the share of frames with the ball seen,
as an event can only be detected while it is (dev3: possession known in 40% of frames, ball seen in 89%; its pass
recall is 0.80). `null` with no frames.

| Clip | possession known | ball seen | in/out-of-possession facts | event facts |
| --- | --- | --- | --- | --- |
| dev1 | 0.916 | 0.922 | 0.916 | 0.922 |
| dev2 | 0.782 | 0.893 | 0.782 | 0.893 |
| dev3 | 0.402 | 0.892 | 0.40 | 0.892 |

`frames` are `[first, last]` runs of observation frame indices. Every number is recomputable from its
cited frames or events: `tests/test_tactics.py` recomputes the frame facts from the simulator's tracking
over the cited frames (by roster id, which the tactics never see). The same team given a +8 m and a -8 m
line by the simulator reads more than 10 m higher out of possession, and much less apart with the ball.

On dev1-dev3 (whole clip, 2 minutes each, under a second per clip) the 4-3-3s and the 4-4-2 read as their
sheet, the 4-2-3-1s read 4-2-1-3 (their wingers stand level with the striker) and the 5-3-2 reads 3-5-2.
Where lineup assignment swaps two players (#56), their mean positions mix, which can change the shape read.

## Analyst report (#69)

After the clip, the analyst writes `report.json` (`schemas/report.schema.json`): a headline and 3-5 tactical
insights in every language, shown by the web player's Clip analysis panel.

```bash
C=dev1
python -m agents.tactics runs/footage/$C/observations.jsonl --events data/demo/$C/events.json \
    --match-info data/demo/$C/match_info.json --out data/demo/$C/tactics.json
python -m agents.analyst data/demo/$C --backend foundry --out data/demo/$C   # report.json + analyst_report.json
python scripts/validate.py data/demo/$C
```

1. **Candidates** (code). One per topic the facts speak to, whole clip unless split: formation matchup
   (`shape`, actual against team sheet), `defensive_line` and `compactness` out of possession, attacking
   `width`, `flanks` (where a team's passes into the final third end), `pressing` (regains in the final third),
   `directness` (long-ball share), `progression` (progressive passes), and `change`: the team whose line moved
   most after a goal or red card (both sides at least a minute). Each cites its facts as `tactics.json` paths
   with their values and coverage, and the events behind event facts (frame facts cite frame counts). `labels`
   are the code's reading ("higher_line": "away", "level" within 3 m / 5 points). Salience: the difference
   over what reads as notable (5 m of line height, 15 points of long balls, 2 high regains...), scaled down
   below a full sample (20 passes, 8 regains, 10 final-third passes: 3 of 5 is a thin story).
2. **Coverage.** An insight's coverage is its facts' lowest. At `COVERAGE_MIN` (0.6) or above it is said plainly.
   Below, it is `hedged` and used only to reach 3 insights: the text must say so (the verifier checks for a
   hedge in each language) and the evidence panel shows "Based on 40% of the clip, below 60%: hedged". Below
   `HEDGE_MIN` (0.3) it is skipped. Every left-out candidate is in `skipped` with its reason. On dev3 the line,
   width and compactness insights (coverage 0.40) are skipped, as enough confident ones remain. So is every
   topic the facts cannot speak to at all (#83), with why: no value ("too little of the clip seen"), or a
   sample under its threshold ("too few passes: Bosphorus FC 1, Thames United 6; each team needs 8", too few
   regains or passes into the final third, under a minute either side of a goal). Thresholds stay as they are
   on short clips: a 2-minute highlight often gets 0-1 insights, and the web panel then says the clip is too
   short for a tactical read. Mock runs on 2-minute windows of test2: 47:40-49:40 (a 3000-frame window with no
   goal) gives 0 insights and 9 skips with their reasons; 40:00-42:00 gives one (flanks), headlined "Bosphorus FC
   3-0 Thames United: ...".
3. **Text** (LLM). One call for the headline and every insight, all languages; JSON mode. The verifier is the
   overlays' (no digit, placeholders only, units, number words, no player name) with longer limits, plus an
   **uncited claim** check: each fact kind has the words that make a claim about it in en/tr/es
   (`verifier.TOPIC_TERMS`: "wide", "pressed", "long ball", "kanat", "presión"...), and an insight may only use
   those of the facts it cites; the headline those of all insights. Formations are placeholders too
   (`{home_shape}` -> "4-3-3"). The headline starts with the score line ("Bosphorus FC {score} Thames United:").
   **Every number reads with its noun** (#79): the model sees each placeholder with what it is
   (`"{away_flank_pct}": "91% (Thames United: share of its passes into the final third that went to the
   centre)"`), and `verifier.bare_numbers` rejects a share and a count joined by a bare "and" ("with 91% and 10
   there", tr "%91 ve 10 burada") or a count followed only by "there".
   **Same meaning in every language** (#79): a part (the headline, or an insight) is kept only whole, when every
   language passes and `verifier.language_mismatch` finds they speak of the same teams ("both teams" in one
   language is both in all; a language naming no team agrees with any) with the same placeholders. On test2 the
   tr headline had fallen back to the template (Thames United only) while en and es kept the model's (both teams).
   One retry with the problems (a retried language is kept only if it agrees with the others), then the template
   in every language of that part.
4. **Numbers.** `values` are the cited facts rounded for the screen; the score comes from `stats.MatchState`:
   the score at the clip's end, counted on from `match_info.score_at_start` (#83), so a clip that starts at 1-1
   with no goal in it says 1-1, not 0-0.
   `recheck` reads every fact back from `tactics.json` and every value against its fact; the report is not
   written if anything differs.

Foundry runs (`gpt-5.4-mini`, en/tr/es). The prompt was tuned on dev1 only; test1 was run once with the final
prompt.

| Run | Input | Insights | Skipped | Rejected attempts | Fixed on retry | Template fallbacks | Paid calls | Tokens (in + out) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | dev1 | 3 | 5 | 2 | 11 | 1 | 2 | 2.7k + 1.4k |
| 2 | dev1 | 3 | 5 | 2 | 4 | 1 | 2 | 3.0k + 1.3k |
| **3 (final)** | **dev1** | 3 | 5 | 1 | 2 | **0** | 2 | 2.9k + 1.2k |
| **final (held out)** | **test1** | 5 | 4 | 1 | 3 | **0** | 2 | 3.4k + 1.8k |
| #79 | dev1 | 3 | 5 | 1 | 4 | **0** | 2 | 3.6k + 1.2k |
| #79 | test1 | 5 | 4 | 1 | 3 | **0** | 2 | 4.0k + 1.7k, retry re-run 2.2k + 1.0k |
| #79 | test2 | 3 | 6 | 1 | 3 | **0** | 2 | 3.6k + 1.2k |

About $0.03 in all. Run 1: the reply dropped a closing brace and nothing parsed, so the analyst agent asks for
JSON mode. Runs 1-2: the score written as "0-0", Turkish "iki takım" and Spanish "los dos" (number words), and a
plain insight hedged; the prompt now says how to write each. test1's one rejection was the new check catching
"narrow" and "wide" in a flank insight (width is not cited); the retry fixed it. Reading test1 showed one
placeholder read wrongly: the flank count (passes to that flank, 17) was read as the total ("17 pasın %94'ü"),
so the key is now `{side}_passes_to_flank` and the topic says what it counts. test1 was not re-run after this.

#79 regenerated dev1, test1 and test2 (8 paid calls over the iterations, 25k + 9k tokens, about $0.05). The
`#79` rows are the reports in `data/demo/`. Reading them led to three more fixes, none a threshold: dev1's
headline dropped its subject ("higher line, while Thames...": the prompt now asks to name the team), test2's
reply nested `tr` and `es` inside `en` (a misplaced brace; `parse_reply` now finds a nested language), and
test1's retried headline began "0-0:" (the score line is now checked). Rejections left: uncited claims
("compact", "narrow", "direct" in a line, flank or headline text), fixed on retry.

## Next steps (P3 backlog)

- [x] Run `--backend foundry` on sample_a, tune `INSTRUCTIONS` in `llm.py` until the verifier rarely rejects (#46).
- [x] Richer "why it matters": `context.py` labels (goal effect, score situation, lead-in, momentum, phase).
- [ ] Turn the pipeline into an Agent Framework workflow (director → explainer → verifier as executors) for the multi-agent category; keep the same functions inside.
- [ ] Live mode: consume events one by one (Event Hubs) and emit overlays with a measured latency.
- [x] Half-time / full-time recap: score, shots, on target, scorers; cites every shot, goal and red card, so its numbers can be recomputed from the cited events. The momentum bar cites the events in its 5-minute window.
- [x] Add `es` to show multi-language reach.
