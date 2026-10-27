# Inside the Game: an AI that watches the match and directs the graphics
 
Our entry for the Microsoft x Premier League **Inside the Game** hackathon.
 
**Live demo:** https://kind-meadow-0717f920f.1.azurestaticapps.net/
 
An AI watches a broadcast-style video of a football match and finds the passes, shots, goals and kickoffs **from the pixels alone**. It also works out who is who. A team of agents on **Microsoft Foundry** then decides which graphic goes on screen, when, for how long and for which viewer. They write the words in English, Turkish and Spanish, and a verifier checks every number before it airs.
 
> **Everything is synthetic.** The clubs (Bosphorus FC, Thames United, Caldera SC, Saltmarsh FC), the players and the matches are fictional. We generate them with our own simulator and render them to video. No real clubs, players, logos or footage are used.
 
## What you see in the demo
 
- **Clip picker:** the showcase (minutes 30–40: two goals, a red card), the two held-out test clips and four short highlights.
- **Three viewers, one feed.** ANALYST shows every stat. CASUAL shows only the big moments. PLAYER follows one player you pick.
- **EN / TR / ES** switch instantly. Every overlay is written in all three languages ahead of time, so playback makes no model calls.
- **AI VIEW** swaps to the video exactly as the AI saw it, with detection boxes and track labels.
- **Evidence on every card.** Click a card to see the events it cites. A small chip shows where each event came from: `AI · 81%` (detected from video, with confidence) or `SIM` (simulator).
- **ANALYSIS:** a clip report written by the analyst agent from tactical facts that code computes from the tracking: flanks, progression, line height, compactness.
- **LINEUPS:** who is on the pitch right now, updated through cards and substitutions as you play or seek.
- **LIVE:** the overlays appear as the moments happen.
## Pipeline
 
```
simulator ──► renderer ──► video ──► vision AI ──► events ──► stats ──► agents ──► overlays ──► web player
    │                                 (source: cv)            (code)    (Foundry)   (timed JSON)   (Azure Static Web Apps)
    └── true events: used only to grade the vision AI, and for the event types video can't see (source: sim)
```
 
| Stage | Folder | What it does |
| --- | --- | --- |
| Simulator | [`simulator/`](simulator/README.md) | Generates a full 90-minute fictional match: per-frame positions and the true events. Seeded, so every match can be reproduced. |
| Renderer | [`renderer/`](renderer/README.md) | Three.js, headless Chromium: turns the positions into a 1080p, 25 fps video from a fixed full-pitch camera. |
| Vision AI | [`vision/`](vision/README.md) | Reads the video only. Pretrained YOLO11s player and ball detection, ByteTrack tracking, a pitch homography from the line markings, rule-based event detection, and naming of players from the team sheet at each kickoff. |
| Merge | [`scripts/merge_events.py`](scripts/merge_events.py) | Adds the event types video cannot see (fouls, cards, offsides, substitutions) from the simulator, labelled `source: sim`. |
| Stats | [`agents/stats.py`](agents/README.md) | Exact numbers, computed by code: score, distance, speed, pass difficulty, momentum, per-player counts. |
| Agents | [`agents/`](agents/README.md) | **Director** (code rules): which moment, when, how long, for which mode, within a screen-time budget. **Explainer** (LLM): the words, in three languages, with numbers only as placeholders. **Verifier** (code): rejects any number the model writes itself, wrong names and Turkish suffix errors, and retries once with feedback before falling back to a template. **Analyst** (LLM): the clip report, checked the same way. |
| Web player | [`web/`](web/README.md) | Vite + TypeScript. Plays the video and draws the overlays on a canvas, with mode, language, LIVE, AI VIEW, ANALYSIS and LINEUPS. |
 
**Two rules hold everywhere:**
1. The vision AI never reads simulator data. It gets video frames and the team sheet, nothing else.
2. Numbers come from code, never from the LLM. The model writes `{distance_m}`, code fills in `28 m`, and the verifier rejects any digit the model wrote on its own.
## Built on Microsoft
 
- **Microsoft Foundry** (Azure OpenAI): `gpt-5.4-mini`, Data Zone Standard deployment, Sweden Central.
- **Microsoft Agent Framework** (`agent-framework-core`, `agent-framework-openai`) runs the explainer and the analyst agents.
- **Azure Static Web Apps** hosts the web player and the demo clips.
Writing all overlays for the 10-minute held-out clip took 113 model calls and cost about **$0.25**. The whole agents evaluation came to about $0.32 (see [`agents/README.md`](agents/README.md)).
 
## How accurate is it? Held-out results
 
The rules and settings were tuned only on dev clips. **test1** (minutes 0–10) and **test2** (minutes 40–50, over half-time) come from seeds never used for tuning. Each was graded once, against the simulator's true events. Detector: pretrained YOLO11s, no fine-tuning.
 
Precision / recall (matched / true, detected):
 
| Event | test1 (0–10') | test2 (40–50') |
| --- | --- | --- |
| Pass | **0.96 / 0.97** (131/135, 136) | **0.99 / 0.93** (84/90, 85) |
| Shot | 0.67 / 1.00 (2/2, 3) | 0.75 / 1.00 (3/3, 4) |
| Goal | none in clip | **1.00 / 1.00** (1/1, 1) |
| Kickoff | 1/1, right team | 2/2, right team, incl. second half with ends switched |
| Possession change | 0.43 / 0.75 (3/4, 7) | 0.50 / 0.40 (2/5, 4) |
| Player named correctly | **0.88** | 0.52 (0.00 before the first kickoff, **0.98** after) |
 
- On matched passes, timing is within 0.03 s on average, and success or failure is right 92 % (test1) and 98 % (test2) of the time.
- test2 joins mid-half, so tracks have no names until the 44:23 kickoff. We report that as it is instead of tuning it away, because a broadcast joined mid-play has the same problem.
- Agents on test1: 270 overlays. The verifier rejected 25 attempts, 51 were fixed on retry, and 2 (0.7 %) fell back to a template.
- The **showcase** clip was picked for its content (two penalty goals, a second-yellow red card), so it is **not held out** and its numbers are not accuracy claims. Its two penalty goals are both found from video.
Full grades, dev clips and known limits are in [`vision/README.md`](vision/README.md#accuracy-the-demo-numbers).
 
## What the AI does not see 
 
- Fouls, cards, offsides and substitutions come from the simulator (`SIM` on the card), not from video.
- One fixed full-pitch camera. Moving broadcast cameras are not supported.
- No ball height. Throw-ins, corners and free kicks are not detected as restarts.
- A substitute's track keeps the name of the player who went off.
## Run it yourself
 
```bash
pip install -r requirements.txt
cp .env.example .env        # Foundry endpoint, key, deployment (only for --backend foundry)
pytest                      # tests
 
# Offline, no Azure needed
python -m agents.run data/fake/sample_a      # template text -> data/generated/sample_a/overlays.json
cd web && npm install && npm run dev         # web player on the committed sample match
```
 
The full chain for one clip (render, vision, merge, agents, web) is in [`agents/README.md`](agents/README.md). In short:
 
```bash
C=test1
python -m vision.footage render $C                                   # simulate + render the clip
python -m vision data/renders/footage/$C/$C.mp4 --out runs/footage/$C/events.json
python scripts/merge_events.py runs/footage/$C/events.json data/renders/footage/$C/truth/events.json --out data/demo/$C/events.json
python -m agents.run data/demo/$C --backend foundry --out data/demo/$C
(cd web && MATCH=data/demo/$C npm run build)
```
 
Videos, renders and runs are git-ignored and regenerated by these scripts. Rendering a 10-minute clip takes about 35 min. The vision run takes about 40 min on an M-series Mac, and less on an NVIDIA GPU.
 
## Repository layout
 
| Folder | What lives there |
| --- | --- |
| `schemas/` | Shared data formats (JSON Schema). The contract between the stages. |
| `simulator/`, `renderer/`, `vision/`, `agents/`, `web/` | One folder per stage, each with its own README |
| `scripts/` | Schema validation, event merge, sample-data generation |
| `data/fake/` | Small committed sample matches for development |
 
Coding agents: read [`AGENTS.md`](AGENTS.md) first.
 
## Team
 
| Person | Worked on |
| --- | --- |
| Ozan Özak | Simulator, vision AI, agents, integration |
| Bora Yılmazer | Agents, renderer |
| Ege Töman | General design of the web player and player picker|
| Berat Yücal | Agents, web player|
 
