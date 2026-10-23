# Vision AI

**Owner:** Ozan

Video in, events out. Never reads simulator data at runtime.

1. Detect players and ball (YOLO)
2. Assign teams by shirt color
3. Track identities across frames
4. Map pixels to pitch meters (homography)
5. Possession = nearest player to the ball ([event rules](#event-rules-visionrulespy))
6. Rules turn possession changes into events (`source: cv`)

Accuracy is measured afterward against the simulator's true events.

## Footage

All footage the vision work uses comes from one script and the seed record
[`footage_seeds.json`](footage_seeds.json). No vision code is involved.

```bash
python -m vision.footage check                 # seed record valid, roles disjoint
python -m vision.footage list                  # clips with role, seed, pairing, kits
python -m vision.footage render dev1           # one clip (skipped if already rendered)
python -m vision.footage render --role dev     # or --all; --force rebuilds
```

| Role | Clips | Purpose |
| --- | --- | --- |
| dev | `dev1`-`dev3`, 2 min each | develop the pipeline; red v blue, orange v white (away kit), green v orange |
| test | `test1`, 10 min | held-out grade; its seed is never used for dev or training |
| training | `train1`-`train6`, 2 min each | fine-tune the player detector; the other six pairings |

Dev, test and training seeds are disjoint. `check` (and `pytest`) fails if a
seed is used by two clips, if a role has no clip, or if the dev clips show
fewer than three kit combinations or no white away kit.

Each clip is **the first `minutes` of a full 90-minute match** (seeded, `full`
profile), from the kickoff, so `[0, minutes * 60)` seconds. The simulator plays
the whole match but writes tracking only for the clip, and `truth/events.json`
holds only the true events before the clip's end, so the grader needs no
clip-end logic. Clips stay inside the first half, which keeps
substitutions (58'-82') out of them. Short simulated halves are not used
because the simulator squeezes its full substitution plan into them, which
adds minutes of dead time.

Render settings are fixed for v1: `cv_full_pitch` camera, CV visibility on,
ball scale 2, player scale 1, 1920x1080 at 25 fps. `render` checks that the
export manifest recorded exactly these.

Output, all ignored by git, in `data/renders/footage/<name>/`. The top level
holds what the vision stage may read, plus render records. `truth/` holds the
simulator's truth, which the vision stage never reads:

| File | Use |
| --- | --- |
| `<name>.mp4` | the video: the vision stage's input |
| `match_info.json` | team sheet: the only other file the vision stage may read |
| `<name>.mp4.manifest.json`, `.metrics.json` | renderer export manifest (camera, scales, CV visibility, frame-to-tracking map) and timing |
| `clip.json` | seed record entry + render settings; written last, after `validate:export` passed |
| `truth/events.json` | true events (`source: sim`) with `t` before the clip's end, original ids: grading only |
| `truth/events.full.json` | true events of the whole simulated match, for reference |
| `truth/tracking.jsonl` | simulator tracking for the clip: training-label projection and grading only |

Rendering needs the renderer's export setup (`cd renderer && npm ci && npx
playwright install chromium`, plus `ffmpeg`/`ffprobe` with libx264 on PATH).
Export runs at roughly 7-8 frames/s: about 7 minutes per 2-minute clip, 35
minutes for the test clip. The simulator output is byte-identical for the
same seed; video pixels are reproducible on the same browser/OS/graphics stack
(see `renderer/README.md`).
The vision AI never sees fouls, cards, offsides or substitutions. `scripts/merge_events.py` (outside
this folder) adds those from the simulator (`source: sim`) to the detected events, sorts by `t` and
renumbers ids, giving the one `events.json` the agents read:

```bash
python scripts/merge_events.py DETECTED_EVENTS TRUE_EVENTS --out data/generated/<match>/events.json
```
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

## Event rules (`vision/rules.py`)

The event stage: frame observations and the team sheet in, detected events out. It imports nothing but `vision.observation` (a test enforces this).

```bash
python -m vision.rules observations.jsonl --match-info match_info.json --out events.json
```

`EventRules.push(frame)` takes one frame at a time and returns the events it has decided, so a live wrapper can feed it later; `detect_events(frames, team_sheet)` runs a whole file, sorts by `t` and numbers the ids. Each kick is decided a short, fixed time after the ball lands: 0.16 s after a reception, 0.12 s after a touch, at most 1 s after it comes to rest with nobody taking it, 0.5 s after it reaches the goal line.

- **Possession:** the track nearest a visible ball, within 1.5 m, with the ball moving with it, for 4 frames. Observations have no ball height, so "the ball moves with the track" stands in for "the ball is at ground level": a ball flying past is not possessed.
- **Kick:** possession ends and the ball travels at least 3 m at 4 m/s or more to where it next stops: where it comes to rest, the next possession, a touch (the ball suddenly turns or speeds up, e.g. a header or a one-touch shot), the goal line, or out of play. Rules use the two ends of that path and when the ball arrived, never mid-flight positions, because an airborne ball's ground projection is wrong. `distance_m`, `duration_s` and `speed_kmh` (the average ground speed) come from those ends.
- **Shot:** a kick within 45 m of a goal and not from a corner flag, whose line meets the goal line within 9.5 m of the goal's center, at 70 km/h or more (65 within 25 m of the goal, 50 for a ball redirected in flight, such as a header). Subtype: `off_target` when it goes out, `blocked` when an outfield opponent stops it short of the line, else from where its line meets the goal line.
- **Pass:** any other kick in open play; `success` when the next track in possession is on the kicker's team; `short`/`long` at 25 m. Restarts are not passes, and v1 does not report them: the first kick after the ball went out or a goal, a kick from a ball still for 3 s (free kick), or from the center spot or a corner arc.
- **Goal:** a shot reaches the goal line between the posts with no player within reach of the ball (that is a save), then comes to rest between the posts, on the line or behind it (not wide of the goal: from a sharp angle, an off-target ball's ground projection can cross the mouth). The shot gets `success: true`, and the goal carries the running `score`.
- **Players:** `from` and `to` are `null` on every event. Tracks are anonymous until lineup assignment names them, and a track id in `from` would read as a roster player id.
- **Confidence:** 0.9 (pass, goal) or 0.8 (shot) times the mean ball confidence over the kick.

Not yet: kickoffs, possession changes and lineup assignment (#17, #18), noisy observations (#19).

### Seam-2 harness (`vision/harness.py`, offline only)

Builds clean frame observations from simulator tracking, so the rules can be built and graded in seconds without video. Roster ids become anonymous track ids, the goalkeeper flag comes from the team sheet, and the ball loses its height. It reads simulator data, so no other vision code may import it (a test enforces this).

```bash
python -m vision.harness data/generated/m007/tracking.jsonl data/generated/m007/match_info.json --out runs/m007/observations.jsonl
```

`tests/test_vision_rules.py` grades the rules on the calibration fixture (one successful pass at 2 s, a shot at 8 s, a goal at 8.9 s, nothing else) and on the first 15 minutes of seeds 401-404, four pairings. Its `THRESHOLDS` hold the minimum precision and recall per type.

Grades on clean observations, first halves (45 min) of full matches, four pairings per row. The rules were tuned on 201-204; 401-404 and 501-504 were also looked at while tuning, so these are dev grades, not held-out ones:

| Seeds | Pass P / R | Shot P / R | Goal P / R |
| --- | --- | --- | --- |
| 201-204 | 0.95 / 0.99 | 0.98 / 0.83 | 1.00 / 1.00 (5 goals) |
| 401-404 | 0.96 / 0.98 | 0.91 / 0.91 | 0.91 / 0.77 (13 goals) |
| 501-504 | 0.96 / 0.99 | 0.94 / 0.80 | 0.86 / 1.00 (6 goals) |

What keeps clean grades below 1 is mostly the simulator, not the rules:
- **False passes:** almost all are clearances, physically the same kick as a long pass. v1 reports them as passes.
- **Missed shots:** many come from the simulator playing a shot (or a pass) from a player standing meters from the ball. Some shots blocked at close range never come to rest near a player, and a few headers measure under 50 km/h.
- **Goals:** in a penalty, the keeper stands within reach as the ball goes in, so it reads as a save. A few clearances go into the clearing team's own goal.

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
