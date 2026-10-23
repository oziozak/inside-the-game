# AGENTS.md: brief for coding agents

Read this before changing anything in this repository. It applies to every coding agent (Claude Code, GitHub Copilot, Codex, Cursor) and to humans.

## What we are building

An entry for the Microsoft x Premier League **"Inside the Game"** hackathon (submission deadline **2026-10-27 23:59 Pacific**). The challenge: turn **synthetic** football match events into **explainable match intelligence** that can sit on screen during a broadcast and is **personalized** for different viewers.

Our project: **an AI watches a synthetic match video, detects every pass and shot on its own, and an AI director decides which graphic to show on screen, when, and for whom.**

```
simulator ──> renderer ──> video ──> vision AI ──> events ──> stats ──> agents ──> overlays ──> web player
    │                                     (source: cv)                (explain,      (timed JSON)   (video + canvas,
    └── true events (source: sim) ── used ONLY to grade accuracy       verify,                     mode + language
                                       and as a fallback feed          direct)                     switch)
```

| Stage | Folder | Language | Does |
| --- | --- | --- | --- |
| Simulator | `simulator/` | Python | Generates a fictional match: true events + per-frame positions |
| Renderer | `renderer/` | Three.js | Turns positions into a broadcast-style video, 25 fps |
| Vision AI | `vision/` | Python, YOLO | Video in, events out: detect, track, map pixels to meters, rules for events |
| Stats | `vision/` or `agents/` | Python | Exact numbers (distance, speed, possession). Plain code |
| Agents | `agents/` | Python, Microsoft Foundry / Agent Framework | Explainer (why it matters), verifier (recomputes every number), director (which graphic, when, how long, for whom) |
| Web player | `web/` | HTML/JS | Plays the video, draws overlays on a canvas, switches mode and language live |

## Non-negotiable rules

1. **The schemas in `schemas/` are the contract.** Every file you read or write must match them. Do not add, rename or remove fields without the team agreeing; if you must, update the schema, its example, and `scripts/validate.py` in the same change. Run `python scripts/validate.py` before committing data.
2. **The vision AI never reads simulator data at runtime.** It receives video frames only. Simulator truth is used only for grading accuracy and as a labeled fallback (`"source": "sim"`).
3. **Numbers come from code, never from an LLM.** Agents may write words; every number shown on screen is computed by code and placed in an overlay's `values`. The verifier rejects any text whose numbers do not match the events it cites.
4. **Every claim cites evidence.** Overlays list the `event_ids` they are based on.
5. **Fictional only.** No real clubs, players, logos, kits, footage or Premier League marks. Our clubs: Bosphorus FC (home, red) and Thames United (away, blue).
6. **Runtime AI runs on Microsoft's stack** (Microsoft Foundry, Agent Framework, Azure services). This is part of the judging. Coding tools are unrestricted.
7. **No secrets in git.** Use `.env` (ignored). The repo becomes public at submission.
8. **No large binaries in git.** Videos, frames, model weights and full-match tracking go in ignored folders (`data/generated/`, `data/renders/`, `runs/`). Regenerate them with scripts. **One deliberate exception:** the 12-second vision calibration clip `vision/fixtures/calibration/calibration.mp4` is committed through **Git LFS** (pattern in `.gitattributes`), so the vision end-to-end test always runs. Run `git lfs install` once per machine and `git lfs pull` if the file is a text pointer. No other video goes in git.
9. **Keep it demo-able.** We have one week. Prefer the simplest thing that works end to end over a clever partial solution.

## Data conventions (see `schemas/README.md`)

- `t` = seconds since kick-off, decimal (2052.4 = 34:12.4). Format as `mm:ss` only for display.
- Positions in **meters** on a **105 x 68** pitch, origin `(0, 0)` bottom-left. `x` goal to goal, `y` sideline to sideline. Ball is `[x, y, z]`, `z` = height.
- **Home attacks toward x = 105 in the first half**, toward x = 0 in the second (`kickoff_direction` in match info).
- Player ids are unique across teams: home 1-99, away 101-199 (away id = 100 + shirt number).
- Event ids `e0001`..., overlay ids `o0001`..., both sorted by time in their files.
- Events: JSON array. Tracking: JSON Lines, one frame per line, 25 fps.
- `source`: `cv` (detected from video) or `sim` (from the simulator). `confidence` is 1.0 for `sim`.
- The clock is continuous across halves (the break is cut). `match_info.periods` holds each half's start and end.

Event types: `kickoff, pass, possession_change, clearance, throw_in, shot, free_kick, foul, goal_kick, corner, substitution, offside, yellow_card, red_card, goal, half_time, full_time`. Subtypes and the meaning of `from`/`to` per type are in `schemas/README.md`.

Events the vision AI cannot see in v1 (`foul`, `yellow_card`, `red_card`, `offside`, `substitution`) are passed from the simulator with `"source": "sim"`.

## Repository layout

```
schemas/           shared formats (JSON Schema) + examples
data/fake/         small committed sample data for development
data/generated/    big generated files (ignored by git)
scripts/           validate.py, generate_fake_data.py, merge_events.py
simulator/ renderer/ vision/ agents/ web/   one folder per stage, each with its own README
```

## Commands

```bash
pip install -r requirements.txt
python scripts/validate.py                              # check data against schemas
python scripts/generate_fake_data.py                    # rebuild data/fake/ (deterministic, seeded)
python scripts/generate_fake_data.py --full-tracking    # + full 25 fps tracking in data/generated/ (~150 MB)
python scripts/generate_fake_data.py --report           # event counts vs. real-football norms
python -m simulator --home bosphorus --away thames --seed 7 --out data/generated/m007   # one match (see simulator/README.md)
python -m simulator.realism --matches 40                # realism report; exits 1 if a check fails
python -m vision.footage render dev1                    # one footage clip from the seed record (see vision/README.md)
python scripts/merge_events.py DETECTED TRUTH --out OUT  # detected (cv) + sim's foul/card/offside/sub -> events.json
pytest                                                  # tests
```

## Fake data (available now)

`data/fake/sample_a/` is a short match (2 x 5 min) containing every event type, with tracking for the first 60 s and template overlays. `data/fake/sample_b/` is a full 90-minute match whose event counts match real-football norms. Build against these until the real stages exist. `scripts/generate_fake_data.py` is also the starting point for the real simulator.

## Git workflow

- `main`: demo-ready only, no direct pushes. `develop`: integration. `feature/<name>`: one per task.
- Branch from `develop`, PR back into `develop`, one teammate reviews. Merge to `main` only when `develop` runs end to end.
- Small commits with clear messages. Do not commit generated files, `.env`, or notebooks with large outputs.

## How to work in this repo (for agents)

- Read the README of the folder you are changing first.
- Develop against `data/fake/` until the real upstream stage exists; do not invent your own format.
- When adding a dependency, add it to `requirements.txt` (Python) or the folder's `package.json` (JS).
- Write small functions with docstrings; add a short test or a runnable `__main__` check for non-trivial logic.
- Fixed random seeds for anything generated, so outputs are reproducible.
- If a request conflicts with the rules above, stop and say so instead of working around it.
