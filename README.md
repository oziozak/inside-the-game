# Inside the Game: Auto-Eventing + AI Overlay Director

Our entry for the Microsoft x Premier League **Inside the Game** hackathon (deadline: Oct 27, 2026, 23:59 Pacific).

An AI watches a synthetic football match video, detects every pass and shot on its own, and an AI director decides which graphic to show on screen, when, and for whom.

## Pipeline

1. **Simulator** (`simulator/`) generates a fictional match: positions + true events.
2. **Renderer** (`renderer/`) turns it into a 3D broadcast-style video.
3. **Vision AI** (`vision/`) watches the video and outputs events (pass, shot, speed, distance).
4. **Stats** compute exact numbers from those events (plain code, no LLM).
5. **Agents** (`agents/`): explainer, verifier and director produce timed overlays.
6. **Web player** (`web/`) plays the video with overlays, with live mode and language switching.

The simulator is our test track. The vision AI only ever sees video frames. The simulator's true events are used only to measure accuracy.

## Repository layout

| Folder | What lives there |
| --- | --- |
| `schemas/` | The shared data formats. Everyone builds against these. |
| `data/fake/` | Hand-crafted and generated sample data for development. |
| `simulator/` | Match engine (Python). |
| `renderer/` | 3D broadcast renderer (Three.js). |
| `vision/` | Detection, tracking, pitch mapping, event rules (Python, YOLO). |
| `agents/` | Explainer, verifier, director agents (Microsoft Foundry). |
| `web/` | Video player with overlay drawing. |
| `scripts/` | Helper scripts (e.g. schema validation). |

## Data formats

See [`schemas/README.md`](schemas/README.md). Key conventions:

- Time `t` is **seconds since kick-off** (2052.4 = 34:12).
- Positions are **meters** on a **105 x 68 m** pitch, origin `(0, 0)` at the **bottom-left** corner.
- Events have an `id` so explanations and overlays can cite the evidence behind them.
- Events have `"source": "cv"` (detected from video) or `"sim"` (copied from the simulator).

Validate any data file before committing:

```bash
pip install jsonschema
python scripts/validate.py
```

## Git workflow

- `main`: working, demo-ready version only. Protected, no direct pushes.
- `develop`: integration branch. Everything is merged and tested here with fake data.
- `feature/<name>`: one per task, e.g. `feature/simulator`, `feature/agents`.

Rules:

1. Branch from `develop`, open a pull request back into `develop`, one teammate approves.
2. Merge into `develop` at least once a day and run the whole pipeline on the fake data.
3. When `develop` runs end to end, merge it into `main`.
4. **Never commit API keys.** Put them in `.env` (it is ignored). Copy `.env.example` to start. This repo becomes public at submission.

## Team

| Person | Owns |
| --- | --- |
| Ozan | Fake data, simulator, renderer, vision AI |
| Person 2 | TBD |
| Person 3 | Agents (explainer, verifier, director) |
| Person 4 | Web player, demo video |

## Rules reminders

- Fictional clubs and players only. No real Premier League names, logos or footage.
- Demo video under 2 minutes, no copyrighted music.
- Repo must be public at submission.
