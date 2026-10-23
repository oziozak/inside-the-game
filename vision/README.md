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

## Video stage (`vision/video.py`): video in, frame observations out

```bash
python -m vision.video vision/fixtures/calibration/calibration.mp4 --out runs/calibration/observations.jsonl
python -m vision.video data/renders/footage/dev1/dev1.mp4 --out runs/dev1/observations.jsonl
```

Reads only the video and the team sheet (`match_info.json` next to the video, or `--match-info`).
`--start` gives the match time of the first frame (default 0: footage clips start at the kickoff).

| Part | How | Module |
| --- | --- | --- |
| Pixel -> meter | One homography per video from the pitch markings of the first frame: touchlines, goal lines and halfway line, refined by least squares, six intersections. Near touchline (image bottom) is y = 0, left goal line x = 0 | `pitch.py` |
| Players | YOLO person class on the pitch region, upscaled (players are ~16 px tall at 1080p). Weights `data/models/<name>.pt` (ignored by git, downloaded on first use); `--weights` takes a fine-tuned model | `detect.py` |
| Ball | Color threshold on the CV-visibility yellow (`#fff052`). Blobs larger than a ball at that spot (0.44 m at ball scale 2, sized through the homography) or in the body of a detected player are rejected, so a yellow keeper shirt is not the ball; a ball at a player's feet is kept. Ground point = bottom of the blob | `detect.py` |
| Team, goalkeeper | Torso color matched to the team sheet's four kit colors (shirt and keeper per team), grass around the box left out; majority of the track's last 25 readings | `detect.py` |
| Tracking | ByteTrack (Ultralytics) for players, and for the ball candidates to keep following the same ball | `video.py` |

Each frame reports per-detection `confidence` and `ball_visible`; an unseen ball is `null`.

### Calibration clip (Git LFS)

`vision/fixtures/calibration/` holds the renderer's 12 s calibration fixture rendered with the v1 settings
(`cv_full_pitch`, CV visibility, ball scale 2, 1920x1080, 25 fps), its export manifest and team sheet. The
mp4 is the one video committed to git, through **Git LFS** (AGENTS.md rule 8 exception); run
`git lfs install && git lfs pull` if it is a text pointer. `tests/test_vision_video.py` always runs the video
stage on it and compares the observations with `renderer/fixtures/calibration/tracking.jsonl`. To re-render:

```bash
cd renderer && npm run export -- --metadata fixtures/calibration/match_info.json \
  --tracking fixtures/calibration/tracking.jsonl --start 0 --end 12 --camera cv_full_pitch \
  --cv_visibility --ball-scale 2 --player-scale 1 --out ../vision/fixtures/calibration/calibration.mp4
```

### Player detector recall (`vision/baseline.py`, offline only)

```bash
python -m vision.baseline VIDEO TRACKING [--weights PATH] [--upscale K] [--conf C] [--step N] [--native]
```

Projects each tracked player (1.88 m x 0.6 m upright box) through the renderer's `cv_full_pitch` camera and
counts it found when a detection has IoU >= 0.5 with it. It reads simulator tracking, so it is grading code;
the video stage never imports it (a test enforces this).

Day-1 baseline, pretrained COCO weights, no fine-tuning (2026-10-23; calibration: all 300 frames,
dev1: every 10th of 3000 frames):

| Detector | Calibration clip (2 players) | dev1 (22 players) |
| --- | --- | --- |
| yolo11n, whole frame at its native 640 px, conf 0.25 | **0.0 %** | **0.0 %** |
| yolo11n, pitch region x2, conf 0.03 | 83 % | 65 % |
| yolo11n, pitch region x4, conf 0.03 | 95 % | 96 % |
| **yolo11s, pitch region x2, conf 0.03 (the video stage's default)** | **98.5 %** | **98.6 %** |

Pretrained YOLO only works here at low confidence and with the frame upscaled. On the calibration clip its
two players score 0.05-0.2 (players in a full match about 0.7). Results swing with the scale (yolo11s at x3:
45 % on the calibration clip), so re-measure after changing any setting.

What the video stage observes (frame observations vs. tracking, ball "on the ground" = below 0.3 m):

| Clip | Players observed within 1 m | Foot error mean / p95 | Team / keeper right | Ball visible | Ball ground error mean / p95 | Tracks |
| --- | --- | --- | --- | --- | --- | --- |
| calibration | 97.7 % / 98.3 % (A / B) | 0.20 m / 0.28 m | 100 % / 100 % | 100 % | 0.15 m / 0.21 m | 2 |
| dev1 (red v blue, yellow away keeper) | 99.9 % | 0.27 m / 0.37 m | 99.8 % / 100 % | 92 % | 0.12 m / 0.24 m | 57 |

On dev1 no ball on the ground is ever placed more than 2 m from the truth (the yellow keeper is never taken
for it); the larger errors are balls in the air, whose ground projection is off by design. The video stage runs
at about 6 frames/s on an M-series Mac (MPS).

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
