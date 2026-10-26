# Agents

**Owner:** Person 3

Input: `match_info.json` + `events.json`. Output: `overlays.json` (schema: `schemas/overlay.schema.json`).
Develop against `data/fake/` until real events arrive; nothing here changes when they do.

## How it works

```
events.json ──► stats.py ──► director.py ──► explainer.py ──► fill.py ──► verifier.py ──► overlays.json
               (code: exact   (code: which      (LLM: words,      (code:       (code: every number
                numbers, as    moment, when,     every mode and    numbers +    and name must match
                of that        how long, which   language in one   units per    the event; 1 retry with
                moment)        mode, budget)     call)             language)    feedback, then template)
```

| File | Role | LLM? |
| --- | --- | --- |
| `stats.py` | Running match state (score, shots, pass accuracy, momentum, per-player counts) and per-event facts (distance, progress, difficulty 1-10, key pass, into the box) | No |
| `context.py` | Why a moment matters, as labels with no numbers: goal effect (equaliser, go-ahead...), score situation, how the attack came about (counter, set piece, build-up), momentum, phase | No |
| `director.py` | Rule table picks moments and graphics; schedules them per mode with slot collisions, a minimum gap and a screen-time budget. Logs every decision with a reason | No |
| `explainer.py` | Builds the request (facts + `values`), calls the backend, runs the verify / retry / fallback loop | Yes |
| `verifier.py` | Rejects numbers not in `values` (or minute/score) and player names not in the cited event; any player name when `name_players` is false | No |
| `llm.py` | Backends: `mock` (offline templates), `noisy` (invents stats to demo the verifier), `foundry` (Microsoft Agent Framework on a Foundry / Azure OpenAI deployment, disk-cached) | Yes |
| `fill.py` | Fills placeholders (`{distance_m}`, `{speed_kmh}`, `{score}`, `{minute}`, any `values` key) with numbers formatted per language (`28 m`; `km/h`, tr `km/sa`; `62%`, tr `%62`, es `62 %`; `2-1`; `7/10`; `34'`), then normalises apostrophes and spacing. Every backend's text goes through it before the verifier (templates write placeholders; the LLM prompt still asks for digits until it moves to placeholders) | No |
| `templates.py` | Code-written text per graphic, mode and language (en, tr, es), numbers as placeholders. Mock backend + fallback | No |
| `run.py` | CLI | |

Why the split: timing and budgets must be predictable live, and numbers on a broadcast must be right,
so code owns both. The LLM only writes words, and the verifier checks those words.

## Modes and what each viewer gets

| Mode | Shown when priority ≥ | Screen-time budget | Numbers |
| --- | --- | --- | --- |
| `analyst` | 0.5 | 35% | all `values` |
| `casual` | 0.75 | 15% | few (pass distance, shot speed, score) |
| `player_focus` | 0.4 | 40% per player | adds the player's running pass count |

`player_focus` overlays carry `player`; the web player shows only the ones for the viewer's chosen player.
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

1. In Microsoft Foundry, create a project and deploy a chat model (e.g. `gpt-4o-mini`).
2. In `.env`: `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`, `AZURE_OPENAI_API_VERSION=2025-04-01-preview`,
   and `AZURE_OPENAI_API_KEY` (or leave the key empty and run `az login`).
3. `python -m agents.run data/fake/sample_a --backend foundry`. Answers are cached in
   `data/generated/llm_cache.json` after every new answer, so re-runs are free and a crash keeps
   what was already paid for. Rate limits (HTTP 429) are retried up to 6 times with exponential
   backoff (2, 4, 8, 16, 32, 60 s plus jitter); at most 4 requests run at once.

## Next steps (P3 backlog)

- [ ] Run `--backend foundry` on sample_a, tune `INSTRUCTIONS` in `llm.py` until the verifier rarely rejects.
- [x] Richer "why it matters": `context.py` labels (goal effect, score situation, lead-in, momentum, phase).
- [ ] Turn the pipeline into an Agent Framework workflow (director → explainer → verifier as executors) for the multi-agent category; keep the same functions inside.
- [ ] Live mode: consume events one by one (Event Hubs) and emit overlays with a measured latency.
- [x] Half-time / full-time recap: score, shots, on target, scorers; cites every shot, goal and red card, so its numbers can be recomputed from the cited events. The momentum bar cites the events in its 5-minute window.
- [x] Add `es` to show multi-language reach.
