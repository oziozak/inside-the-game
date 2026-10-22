# Vision AI

**Owner:** Ozan

Video in, events out. Never reads simulator data at runtime.

1. Detect players and ball (YOLO)
2. Assign teams by shirt color
3. Track identities across frames
4. Map pixels to pitch meters (homography)
5. Possession = nearest player to the ball
6. Rules turn possession changes into events (`source: cv`)

Accuracy is measured afterward against the simulator's true events.

## Inputs (runtime)

Only the rendered video and the team sheet (`match_info.json`), used as a broadcaster would use one. The runtime code never opens simulator `events.json` or `tracking.jsonl`.

## Frame observations (`vision/observation.py`)

The contract between the video stage (pixels → observations) and the event stage (observations → detected events). One record per video frame, stored as JSON Lines and described by [`frame_observation.schema.json`](frame_observation.schema.json):

```json
{"frame": 50, "t": 2.0, "period": 1,
 "ball": {"pos": [55.8, 24.3], "confidence": 0.93}, "ball_visible": true,
 "players": [{"track_id": 3, "team": "home", "goalkeeper": false, "pos": [55.0, 25.0], "confidence": 0.88}]}
```

- `ball.pos` is the ball's ground projection in meters; height is not recovered. When `ball_visible` is false, `ball` may hold a predicted position or be `null`.
- `track_id` is an anonymous track, not a roster player id. Mapping tracks to players (lineup assignment) is the event stage's job.
- Player `pos` is the foot point in meters.

Use `write_observations` / `read_observations` for files. To check one: `python -m vision.observation FILE.jsonl` (exit 1 on errors). Beyond the schema, it checks that a visible ball has a position, track ids are unique per frame, and frames and times strictly increase.

## Grader (`vision/grader.py`, offline only)

Scores detected events against true events and writes `vision_report.json`. It is the only vision code allowed to read simulator events, and nothing on the runtime path imports it (a test enforces this).

```bash
python -m vision.grader --detected runs/m007/events.json --truth data/generated/m007/events.json \
    --manifest data/renders/m007.mp4.manifest.json --seed 7 --training-seeds 1 2 3 \
    --out runs/m007/vision_report.json
```

- A detected event matches a true event of the same type within ±0.5 s and 5 m of its start point. Matching is one-to-one, closest first (pairs ranked by time gap / 0.5 s + distance / 5 m).
- `per_type`: detected, true and matched counts, plus precision, recall and F1 (`null` when undefined, e.g. no detections).
- `matched`: player-id accuracy (`from` right, and `to` too for types where `to` is a player; shots and goals score `from` only), pass-success accuracy, and mean absolute timing, distance and speed error.
- `unmatched_detections` and `missed`: id, type, `t` and start of each.
- `clip`: render settings from the export manifest's `render` block (plus width, height, rich), the clip window, and the seeds. `--render KEY=VALUE`, `--seed` and `--training-seeds` add to or override them.
- By default only the v1 detected types are graded (`kickoff, pass, possession_change, shot, goal`); `--types all` or a comma list changes that.
