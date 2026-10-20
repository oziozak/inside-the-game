# Simulator

**Owner:** Ozan

Python match engine. Generates a fictional match and writes:
- `match_info.json`
- `events.json` (true events, `source: sim`)
- `tracking.jsonl` (positions of all players and the ball, 25 fps)

Two layers: an **event layer** (weighted dice decide what happens) and a **movement layer** (players shift with the ball around their formation positions).
