# Agents

**Owner:** Person 3

Input: `match_info.json` + `events.json`. Output: `overlays.json` (schema: `schemas/overlay.schema.json`).
Develop against `data/fake/` until real events arrive; nothing here changes when they do.

## How it works

```
events.json ──► stats.py ──► director.py ──► explainer.py ──► verifier.py ──► overlays.json
               (code: exact   (code: which      (LLM: words,      (code: every number
                numbers, as    moment, when,     every mode and    and name must match
                of that        how long, which   language in one   the event; 1 retry with
                moment)        mode, budget)     call)             feedback, then template)
```

| File | Role | LLM? |
| --- | --- | --- |
| `stats.py` | Running match state (score, shots, pass accuracy, momentum, per-player counts) and per-event facts (distance, progress, difficulty 1-10, key pass, into the box) | No |
| `director.py` | Rule table picks moments and graphics; schedules them per mode with slot collisions, a minimum gap and a screen-time budget. Logs every decision with a reason | No |
| `explainer.py` | Builds the request (facts + `values`), calls the backend, runs the verify / retry / fallback loop | Yes |
| `verifier.py` | Rejects numbers not in `values` (or minute/score) and player names not in the cited event | No |
| `llm.py` | Backends: `mock` (offline templates), `noisy` (invents stats to demo the verifier), `foundry` (Microsoft Agent Framework on a Foundry / Azure OpenAI deployment, disk-cached) | Yes |
| `templates.py` | Code-written text per graphic, mode and language. Mock backend + fallback | No |
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
Every overlay is written once per language (`--langs en,tr`), so switching mode or language in the
player is instant: no LLM call at playback time.

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
2. In `.env`: `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`, and `AZURE_OPENAI_API_KEY`
   (or leave the key empty and run `az login`).
3. `python -m agents.run data/fake/sample_a --backend foundry`. Answers are cached in
   `data/generated/llm_cache.json`, so re-runs are free.

## Next steps (P3 backlog)

- [ ] Run `--backend foundry` on sample_a, tune `INSTRUCTIONS` in `llm.py` until the verifier rarely rejects.
- [ ] Richer "why it matters": feed the explainer context (previous 30 s of events, score situation, momentum change).
- [ ] Turn the pipeline into an Agent Framework workflow (director → explainer → verifier as executors) for the multi-agent category; keep the same functions inside.
- [ ] Live mode: consume events one by one (Event Hubs) and emit overlays with a measured latency.
- [ ] Match recap agent at `full_time` (key moments, cited by `event_ids`).
- [ ] Add `es` (or another language) to show multi-language reach.
