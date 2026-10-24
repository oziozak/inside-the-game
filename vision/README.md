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

## Tracer (`vision/pipeline.py`): video in, events out

The one command for the whole stage: the [video stage](#video-stage-visionvideopy-video-in-frame-observations-out) then the [event rules](#event-rules-visionrulespy), in one batch run.

```bash
python -m vision vision/fixtures/calibration/calibration.mp4 --out runs/calibration/events.json
python -m vision data/renders/footage/dev1/dev1.mp4 --out runs/dev1/events.json --observations runs/dev1/observations.jsonl
```

- **Reads:** the video, its team sheet (`match_info.json` next to the video, or `--match-info`) and the YOLO weights (`--weights`). Nothing else.
- **Writes:** `--out`, the detected events (`source: cv`, event schema, ids `e0001...`), and with `--observations` the frame observations in between.
- `--start` and `--frames` as in the video stage. No state is kept between runs and nothing is interactive, so it can run as a batch job (e.g. an Azure job) unchanged. `--help` lists all of this.

`tests/test_vision_pipeline.py` always runs it on the calibration clip and grades the output: one successful pass at 2 s, a shot at 8 s, a goal at 8.9 s, nothing else. The same run is the **guard**: the clip is copied into a folder laid out like a footage clip, with the true events and tracking in `truth/` and beside the video, and the command runs in a child process that records every file opened or listed from Python (an audit hook). The test fails if it opened anything in the clip folder other than the video and team sheet, anything under a `truth/` folder, any events or tracking file, or anything from `simulator/`, `scripts/`, `renderer/fixtures/`, `data/generated/`, `data/renders/` or `data/fake/`, or if it loaded simulator, grader, harness, baseline or footage code. OpenCV reads the video in native code, which the hook does not see. A second test checks that the guard catches a run that does read those files.

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

## Event rules (`vision/rules.py`)

The event stage: frame observations and the team sheet in, detected events out. It imports nothing but `vision.observation` (a test enforces this).

```bash
python -m vision.rules observations.jsonl --match-info match_info.json --out events.json
```

`EventRules.push(frame)` takes one frame at a time and returns the events it has decided, so a live wrapper can feed it later; `detect_events(frames, team_sheet)` runs a whole file, sorts by `t` and numbers the ids. Each kick is decided a short, fixed time after the ball lands: 0.16 s after a reception, 0.12 s after a touch, at most 1 s after it comes to rest with nobody taking it, 0.5 s after it reaches the goal line. A possession change is decided 0.5 s after the ball was won, or with the winner's next kick.

- **Possession:** the track nearest a visible ball, within 1.5 m, with the ball moving with it, for 4 frames. Observations have no ball height, so "the ball moves with the track" stands in for "the ball is at ground level": a ball flying past is not possessed.
- **Kick:** possession ends and the ball travels at least 3 m at 4 m/s or more to where it next stops: where it comes to rest, the next possession, a touch (the ball suddenly turns or speeds up, e.g. a header or a one-touch shot), the goal line, or out of play. Rules use the two ends of that path and when the ball arrived, never mid-flight positions, because an airborne ball's ground projection is wrong. `distance_m`, `duration_s` and `speed_kmh` (the average ground speed) come from those ends.
- **Shot:** a kick within 45 m of a goal and not from a corner flag, whose line meets the goal line within 9.5 m of the goal's center, at 70 km/h or more (65 within 25 m of the goal, 50 for a ball redirected in flight, such as a header). Subtype: `off_target` when it goes out, `blocked` when an outfield opponent stops it short of the line, else from where its line meets the goal line.
- **Pass:** any other kick in open play; `success` when the next track in possession is on the kicker's team; `short`/`long` at 25 m. Restarts are not passes, and v1 does not report them (except kickoffs): the first kick after the ball went out or a goal, a kick from a ball still for 3 s (free kick), or from the center spot or a corner arc.
- **Kickoff:** the ball rests on the center spot (within 1 m) with every track in its own team's half (1 m of slack), then leaves it at 4 m/s or more. At a half start the broadcast cuts straight to the kickoff, so the ball on the spot in the period's first frame is enough. That also covers a simulator quirk: at the second-half kickoff its players are not always lined up yet. The team is the track nearest the ball, `t` and `start` are where the ball last rested, `end`, `distance_m`, `speed_kmh` and `duration_s` come from the kick, and `success` is decided as for a pass.
- **Possession change:** the other team takes the ball in play, without a pass from the team that lost it:
  - off the holder, within 0.5 s of the holder's last touch and without a kick: `tackle` (`interception` when the winner is a goalkeeper);
  - by cutting out a pass in open play within 1 s of it being played (not a restart such as a corner), or by taking a blocked shot: `interception`. The pass is still reported, unsuccessful.

  The change stands once the winner keeps the ball for 0.5 s or plays it on (a short nudge to a teammate counts). When the other team takes the ball straight back, that is flicker (a player running past the ball), and neither change is reported; one still pending when play stops (out of play, end of input) is dropped too. A goalkeeper holding a shot is a save, not a possession change. `team` is the winner's; `t` and `start` are where the winner first had the ball.
- **Goal:** a shot reaches the goal line between the posts with no player within reach of the ball (that is a save), then comes to rest between the posts, on the line or behind it (not wide of the goal: from a sharp angle, an off-target ball's ground projection can cross the mouth). The shot gets `success: true`, and the goal carries the running `score`.
- **Players:** `from` and `to` are `null` on every event. Tracks are anonymous until lineup assignment names them, and a track id in `from` would read as a roster player id.
- **Confidence:** 0.9 (pass, goal, kickoff), 0.8 (shot) or 0.7 (possession change) times the mean ball confidence over the kick.

Not yet: lineup assignment (#18), noisy observations (#19).

### Seam-2 harness (`vision/harness.py`, offline only)

Builds clean frame observations from simulator tracking, so the rules can be built and graded in seconds without video. Roster ids become anonymous track ids, the goalkeeper flag comes from the team sheet, and the ball loses its height. It reads simulator data, so no other vision code may import it (a test enforces this).

```bash
python -m vision.harness data/generated/m007/tracking.jsonl data/generated/m007/match_info.json --out runs/m007/observations.jsonl
```

`tests/test_vision_rules.py` grades the rules on the calibration fixture (one successful pass at 2 s, a shot at 8 s, a goal at 8.9 s, nothing else) and on the first 15 minutes of both halves of seeds 401-404, four pairings, cut together as the broadcast cuts the break (kickoff direction and the second-half switch included). Its `THRESHOLDS` hold the minimum precision and recall per type, and `SUBTYPE_THRESHOLDS` the minimum share of matched shots and possession changes with the true subtype. A separate test checks that a kickoff is found at both half starts and after every goal (7 goals in those clips), on the center spot, by the right team.

Grades on clean observations, whole 90-minute matches (both halves), four pairings per row. The rules were tuned on 201-204; 401-404 and 501-504 were also looked at while tuning, so these are dev grades, not held-out ones:

| Seeds | Kickoff P / R | Pass P / R | Possession change P / R | Shot P / R | Shot subtype right | Goal P / R |
| --- | --- | --- | --- | --- | --- | --- |
| 201-204 | 1.00 / 1.00 (17) | 0.95 / 0.99 | 0.60 / 0.60 | 0.96 / 0.85 | 98 / 99 | 0.89 / 0.89 (9 goals) |
| 401-404 | 1.00 / 1.00 (27) | 0.95 / 0.99 | 0.55 / 0.63 | 0.91 / 0.90 | 89 / 92 | 0.93 / 0.74 (19 goals) |
| 501-504 | 1.00 / 1.00 (24) | 0.95 / 0.99 | 0.52 / 0.69 | 0.96 / 0.80 | 80 / 82 | 0.93 / 0.81 (16 goals) |

What keeps clean grades below 1 is mostly the simulator, not the rules:
- **False passes:** almost all are clearances, physically the same kick as a long pass. v1 reports them as passes.
- **Missed shots:** many come from the simulator playing a shot (or a pass) from a player standing meters from the ball. Some shots blocked at close range never come to rest near a player, and a few headers measure under 50 km/h.
- **Goals:** in a penalty, the keeper stands within reach as the ball goes in, so it reads as a save. A few clearances go into the clearing team's own goal.
- **Possession changes** are capped by how the simulator labels them. It labels an interception only when a pass is cut out in the first 30 % of its path to the intended target, which video cannot see, so a pass cut out within 1 s is a guess either way. It labels no change when a cleared or loose ball is won by the other team, or when a restart follows a foul or offside (invisible to video) and the ball was never seen going out. A tackler who passes on at once (under 0.2 s) never has possession, so the tackle is missed. 473 of 491 matched changes (96 %) carry the true subtype.
- **Shot subtypes:** the few misses are blocked shots that then go out, which read as `off_target`.

## Grader (`vision/grader.py`, offline only)

Scores detected events against true events and writes `vision_report.json`. It is the only vision code allowed to read simulator events, and nothing on the runtime path imports it (a test enforces this).

```bash
python -m vision.grader --detected runs/m007/events.json --truth data/generated/m007/events.json \
    --manifest data/renders/m007.mp4.manifest.json --seed 7 --training-seeds 1 2 3 \
    --out runs/m007/vision_report.json
```

- A detected event matches a true event of the same type within ±0.5 s and 5 m of its start point. Matching is one-to-one, closest first (pairs ranked by time gap / 0.5 s + distance / 5 m).
- `per_type`: detected, true and matched counts, plus precision, recall and F1 (`null` when undefined, e.g. no detections).
- `matched`: player-id accuracy (`from` right, and `to` too for types where `to` is a player; shots and goals score `from` only), pass-success accuracy, `subtype_accuracy` for pass, possession change and shot (over matched pairs whose true event has a subtype; a missing detected subtype counts as wrong; detected goals and kickoffs carry none), and mean absolute timing, distance and speed error.
- `unmatched_detections` and `missed`: id, type, `t` and start of each.
- `clip`: render settings from the export manifest's `render` block (plus width, height, rich), the clip window, and the seeds. `--render KEY=VALUE`, `--seed` and `--training-seeds` add to or override them.
- By default only the v1 detected types are graded (`kickoff, pass, possession_change, shot, goal`); `--types all` or a comma list changes that.

## Footage grades (`vision/grade_footage.py`, offline only)

The tracer on the 22-player footage clips, graded. For each clip in the seed record it runs `python -m vision` as a child process on the clip's video (so the run reads only the video and team sheet), grades the detected events against `truth/events.json` and writes `vision_report.json`. The report's `clip` block records the render settings (export manifest), the clip's name, role, seed and pairing (seed record), the detector weights and the seeds they were trained on (none: pretrained yolo11s, #21).

```bash
python -m vision.grade_footage --role dev              # or dev1 test1, or --all (dev + test)
python -m vision.grade_footage --role dev --reuse      # re-grade saved detections, no tracer run
```

Clips are read from `--footage`, else `$VISION_FOOTAGE`, else `data/renders/footage`. Output in `runs/footage/<name>/` (ignored by git): `events.json`, `observations.jsonl`, `vision_report.json`. The tracer runs at about 6 frames/s on an M-series Mac: 8 minutes per dev clip, about 40 for the test clip (`caffeinate -i` keeps the Mac awake).

`tests/test_vision_footage.py` runs the same on every dev and test clip when `$VISION_FOOTAGE` points at the rendered clips, and skips otherwise. Its `THRESHOLDS` hold each clip's minimum precision and recall per type: the first measured grade minus a cross-hardware margin (the dev clips were graded on MPS, test1 on CUDA): 0.03 for passes, one match fewer for types with fewer than 5 true events. Floors are only ever raised. Player-id accuracy is reported (0 until lineup assignment, #18, names players) but not asserted.

```bash
VISION_FOOTAGE=data/renders/footage pytest tests/test_vision_footage.py -k dev    # or -k test1
```

**Dev clips are for tuning; `test1` is the held-out grade and is never used to tune the rules or the detector.**

First grades (2026-10-24, pretrained yolo11s, v1 render settings), precision / recall (matched / true, detected):

| Clip | Kickoff | Pass | Possession change | Shot | Goal |
| --- | --- | --- | --- | --- | --- |
| dev1 (red v blue) | 1.00 / 1.00 (1/1, 1) | 0.97 / 0.91 (31/34, 32) | 1.00 / 1.00 (3/3, 3) | - / 0.00 (0/1, 0) | none |
| dev2 (orange v white) | 1.00 / 1.00 (1/1, 1) | 0.88 / 0.82 (14/17, 16) | 0.00 / 0.00 (0/2, 2) | 1.00 / 0.50 (1/2, 1) | none |
| dev3 (green v orange) | 1.00 / 1.00 (1/1, 1) | 0.86 / 0.76 (19/25, 22) | 0.33 / 0.50 (1/2, 3) | 0.67 / 1.00 (2/2, 3) | none |
| **dev, all three** | 1.00 / 1.00 (3/3, 3) | **0.91 / 0.84** (64/76, 70) | 0.50 / 0.57 (4/7, 8) | 0.75 / 0.60 (3/5, 4) | none |
| **test1 (held out, 10 min, red v blue)** | 1.00 / 1.00 (1/1, 1) | **0.96 / 0.97** (131/135, 136) | 0.29 / 0.50 (2/4, 7) | 0.67 / 1.00 (2/2, 3) | none |

Matched events in test1: pass success right 92 %, pass subtype 85 %, shot and possession-change subtype 100 %, mean timing error 0.03 s, distance error 0.8 m, speed error 7 km/h. Player-id accuracy is 0 (no lineup assignment yet). The dev clips were graded on an M-series Mac (MPS), test1 on an RTX 5070 (CUDA); a second dev run on the Mac gave byte-identical events.
