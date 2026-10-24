# Vision AI

**Owner:** Ozan

Video in, events out. Never reads simulator data at runtime.

1. Detect players and ball (YOLO)
2. Assign teams by shirt color
3. Track identities across frames
4. Map pixels to pitch meters (homography)
5. Possession = nearest player to the ball ([event rules](#event-rules-visionrulespy))
6. Rules turn possession changes into events (`source: cv`)
7. Lineup assignment names the tracks with roster ids from the team sheet ([lineup](#lineup-assignment-visionlineuppy))

Accuracy is measured afterward against the simulator's true events.

The first five sections are what you need to use the stage and quote its numbers. The rest, from
[Footage](#footage), is reference for changing it.

## Quick start: fresh checkout to `events.json` and a grade

**1. Setup** (once per machine):

```bash
pip install -r requirements.txt
git lfs install && git lfs pull       # the calibration clip; `file vision/fixtures/calibration/calibration.mp4` must say MP4
```

The YOLO weights (`data/models/yolo11s.pt`, 18 MB, ignored by git) download on the first run.

**2. Calibration clip** (committed, 12 s, about a minute on a laptop):

```bash
# video in, events out (the tracer)
python -m vision vision/fixtures/calibration/calibration.mp4 --out runs/calibration/events.json

# grade against the true events -> vision_report.json
python -m vision.grader --detected runs/calibration/events.json \
    --truth renderer/fixtures/calibration/ground_truth.events.json \
    --manifest vision/fixtures/calibration/calibration.mp4.manifest.json \
    --out runs/calibration/vision_report.json

# add the five types video cannot see -> the one events.json the agents read
python scripts/merge_events.py runs/calibration/events.json \
    renderer/fixtures/calibration/ground_truth.events.json --out runs/calibration/merged/events.json

python scripts/validate.py runs/calibration runs/calibration/merged
```

Expected: 3 events (1 pass, 1 shot, 1 goal), each graded P 1.000 / R 1.000; the merge adds nothing
(the clip has no fouls, cards, offsides or substitutions).

**3. A 22-player footage clip** (needs the renderer's export setup, see [Footage](#footage)):

```bash
python -m vision.footage render dev1                 # ~7 min: data/renders/footage/dev1/
python -m vision.grade_footage dev1                  # ~8 min: runs/footage/dev1/{events,vision_report}.json
python scripts/merge_events.py runs/footage/dev1/events.json \
    data/renders/footage/dev1/truth/events.json --out data/generated/dev1/events.json
```

`grade_footage` runs the tracer on the clip as a child process, then grades it. To run the tracer on its
own: `python -m vision data/renders/footage/dev1/dev1.mp4 --out runs/dev1/events.json`. Use `test1`
for the held-out grade (35 min to render, about 40 to grade on an M-series Mac).

## What it reads: the video and the team sheet, nothing else

At runtime the stage reads **only** the rendered video and its team sheet (`match_info.json`: clubs, kit
colors, rosters with shirt numbers and positions, periods, kickoff direction), used the way a
broadcaster uses a team sheet. Plus the detector weights. It never opens the simulator's `events.json`
or `tracking.jsonl`, and imports no simulator, grader, harness, baseline or footage code.

**Evidence: the guard test** (`tests/test_vision_pipeline.py`, runs in every `pytest`, needs the LFS
clip). `test_tracer_opens_only_the_video_and_team_sheet` copies the calibration clip into a folder laid
out like a footage clip, with the true events and tracking in `truth/` and beside the video, and runs
`python -m vision` in a child process that records every file opened or listed from Python (an audit
hook). It fails if the run opened anything in the clip folder other than the video and team sheet,
anything under a `truth/` folder, any events or tracking file, or anything from `simulator/`,
`scripts/`, `renderer/fixtures/`, `data/generated/`, `data/renders/` or `data/fake/`, or if it loaded
simulator, grader, harness, baseline or footage code. `test_guard_catches_a_read_of_simulator_data`
checks that the guard does catch a run that reads those files. OpenCV reads the video in native code,
which the hook does not see.

Simulator truth is read only offline, by the grading code (`grader.py`, `grade_footage.py`,
`baseline.py`, `harness.py`), and by `scripts/merge_events.py`, which lives outside `vision/`.

## What it guarantees

- **Schema-valid events:** `--out` is a JSON array matching `schemas/event.schema.json`, sorted by `t`,
  ids `e0001...`. Every event is **`source: cv`**. The tests validate the tracer's output.
- **`confidence` below 1:** each event's confidence is the rule's own certainty (0.9 pass, kickoff and
  goal; 0.8 shot; 0.7 possession change) times the mean ball-detection confidence, clamped to
  [0.01, 0.99]. 1.0 stays reserved for `source: sim`.
- **v1 event scope:** `kickoff`, `pass`, `possession_change`, `shot`, `goal`, with the fields
  `schemas/README.md` gives each type. `from`/`to` are roster ids of the right team from the team
  sheet, or `null` where a player could not be named; a track id never appears.
- **The five invisible types arrive via the merge:** `foul`, `yellow_card`, `red_card`, `offside` and
  `substitution` are never detected. `scripts/merge_events.py DETECTED TRUTH --out OUT` adds them from
  the simulator's events (`source: sim`, `confidence` 1.0), sorts by `t` and renumbers ids. It refuses
  detected files that are not all `source: cv`, that contain an invisible type, or that are from a
  different match.

## Accuracy: the demo numbers

All on v1 render settings: `cv_full_pitch` camera, CV visibility on, ball scale 2, player scale 1,
1920x1080, 25 fps, not rich (recorded in each `vision_report.json`'s `clip` block). Detector:
**pretrained yolo11s, no fine-tuning** (#21 closed: training seeds none). Clips are the first minutes of
seeded full matches (`footage_seeds.json`): dev1 seed 2007, dev2 2006, dev3 2005, **test1 seed 2101**
(Bosphorus FC v Thames United, red v blue, 10 min, `[0, 600)` s, held out: never used for tuning).

**Player detector recall** (`baseline.py`, IoU >= 0.5 with each projected player):

| Calibration | dev1 | dev2 | dev3 |
| --- | --- | --- | --- |
| 98.5 % | 98.6 % | 98.5 % | 96.0 % |

**Held-out test1** (`runs/footage/test1/vision_report.json`), precision / recall (matched / true, detected):

| Type | Grade |
| --- | --- |
| Kickoff | 1/1 found, right team |
| Pass | **P 0.963 / R 0.970** (131/135, 136) |
| Shot | 2/2 found, P 0.67 (3 detected) |
| Possession change | P 0.29 / R 0.50 (2/4, 7): a known label limit, see below |
| Goal | none in the clip |

Matched passes: success right 92 %, mean timing error 0.03 s.

**Player-id accuracy** (matched events naming the right `from`, and `to` where it is a player), before /
after the noise hardening (#19):

| Clip | Before #19 | After #19 |
| --- | --- | --- |
| dev1 | 0.69 | 0.94 |
| dev2 | 0.38 | 0.72 |
| dev3 | 0.43 | 0.75 |
| test1 | 0.46 | **TODO: test1 re-grade after #19** |

Dev-clip and seam-2 grades in detail: [Footage grades](#footage-grades-visiongrade_footagepy-offline-only),
[Seam-2 harness](#seam-2-harness-visionharnesspy-offline-only).

## Known limits

- **Camera:** `cv_full_pitch` only, one fixed full-pitch camera. The homography comes from the first
  frame's pitch markings; a moving or broadcast camera is not supported.
- **No ball height:** observations carry the ball's ground projection only. Rules use where a kick
  starts and stops, never mid-flight positions; a header's player is guessed from the nearest track.
- **Restarts and clearances:** no throw-ins, corners, goal kicks, clearances or free kicks from video.
  Restarts are not reported (kickoffs are); clearances come out as passes, the main source of false
  passes.
- **Possession-change labels** (#17, #31): grades are capped by how the simulator labels changes
  (interceptions only early in a pass's path, no change for won loose balls or after unseen fouls), so
  precision and recall sit around 0.5-0.6 even on clean observations ([details](#seam-2-harness-visionharnesspy-offline-only)).
- **Substitutions:** never named. A substitute's track takes the name of the player who went off, so
  player-id drops to about 0.5 after the first substitution (58'-82'). Footage clips end before any.
- **test1 has no goals:** goal detection is graded on the calibration clip and the seam-2 matches only.
  A second held-out clip with goals and the half-time kickoff is planned (test2, #35).
- **Second-half kickoff** is tested only on simulator observations (seam-2), not on rendered footage.

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
| training | `train1`-`train6`, 2 min each | reserved for fine-tuning the player detector; the other six pairings. Unused: pretrained recall sufficed (#21) |

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

## Tracer (`vision/pipeline.py`): video in, events out

The one command for the whole stage: the [video stage](#video-stage-visionvideopy-video-in-frame-observations-out) then the [event rules](#event-rules-visionrulespy), in one batch run.

```bash
python -m vision vision/fixtures/calibration/calibration.mp4 --out runs/calibration/events.json
python -m vision data/renders/footage/dev1/dev1.mp4 --out runs/dev1/events.json --observations runs/dev1/observations.jsonl
```

- **Reads:** the video, its team sheet (`match_info.json` next to the video, or `--match-info`) and the YOLO weights (`--weights`). Nothing else.
- **Writes:** `--out`, the detected events (`source: cv`, event schema, ids `e0001...`), and with `--observations` the frame observations in between.
- `--start` and `--frames` as in the video stage. No state is kept between runs and nothing is interactive, so it can run as a batch job (e.g. an Azure job) unchanged. `--help` lists all of this.

`tests/test_vision_pipeline.py` always runs it on the calibration clip and grades the output: one successful pass at 2 s, a shot at 8 s, a goal at 8.9 s, nothing else. The same run is the [guard](#what-it-reads-the-video-and-the-team-sheet-nothing-else).

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

With the video stage's default, dev2 is 98.5 % and dev3 96.0 % (same sampling as dev1). #21 (fine-tuning)
was closed on these numbers: the pretrained detector stays.

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

The event stage: frame observations and the team sheet in, detected events out. It imports nothing but `vision.observation` and `vision.lineup` (a test enforces this).

```bash
python -m vision.rules observations.jsonl --match-info match_info.json --out events.json
```

`EventRules.push(frame)` takes one frame at a time and returns the events it has decided, so a live wrapper can feed it later; `detect_events(frames, team_sheet)` runs a whole file, sorts by `t` and numbers the ids. Each kick is decided a short, fixed time after the ball lands: 0.16 s after a reception, 0.12 s after a touch, at most 1 s after it comes to rest with nobody taking it, 0.5 s after it reaches the goal line. A possession change is decided 0.5 s after the ball was won, or with the winner's next kick.

- **Possession:** the track nearest a visible ball, within 1.5 m, with the ball moving with it, for 4 frames. Observations have no ball height, so "the ball moves with the track" stands in for "the ball is at ground level": a ball flying past is not possessed. A track whose kit changes mid-possession has been swapped onto another player by the tracker: possession starts over. A second box on a named player (its [twin](#lineup-assignment-visionlineuppy)) stands for that player's track.
- **Hidden ball:** a ball behind a player (`ball_visible` false) is bridged, not guessed at: possession stays as it was until the ball is seen again. Ball speeds are measured only over frames since it was last hidden (across a gap it may have waited, then been kicked). A ball that comes back already flying was kicked when its first speed seen puts it back where it was last seen; that time is the kick's `t` and starts its `duration_s`. A tackle's 0.5 s counts from when the ball is seen again.
- **Kick:** possession ends and the ball travels at least 3 m at 4 m/s or more to where it next stops: where it comes to rest, the next possession, a touch (the ball suddenly turns or speeds up, e.g. a header or a one-touch shot), the goal line, or out of play. Rules use the two ends of that path and when the ball arrived, never mid-flight positions, because an airborne ball's ground projection is wrong. `distance_m`, `duration_s` and `speed_kmh` (the average ground speed) come from those ends.
- **Shot:** a kick within 45 m of a goal and not from a corner flag, whose line meets the goal line within 9.5 m of the goal's center, at 70 km/h or more (65 within 25 m of the goal, 50 for a ball redirected in flight, such as a header). Subtype: `off_target` when it goes out, `blocked` when an outfield opponent stops it short of the line, else from where its line meets the goal line.
- **Pass:** any other kick in open play; `success` when the next track in possession is on the kicker's team; `short`/`long` at 25 m. Restarts are not passes, and v1 does not report them (except kickoffs): the first kick after the ball went out or a goal, a kick from a ball still for 3 s (free kick), or from the center spot or a corner arc.
- **Kickoff:** the ball rests on the center spot (within 1 m) with every track in its own team's half (1 m of slack), then leaves it at 4 m/s or more. At a half start the broadcast cuts straight to the kickoff, so the ball on the spot in the period's first frame is enough. That also covers a simulator quirk: at the second-half kickoff its players are not always lined up yet. The kicker is, of the team of the track nearest the ball, the track within 1.5 m of the spot furthest behind the ball as it is played (a teammate can stand nearer, beside it); the team is the kicker's. `t` and `start` are where the ball last rested, `end`, `distance_m`, `speed_kmh` and `duration_s` come from the kick, and `success` is decided as for a pass.
- **Possession change:** the other team takes the ball in play, without a pass from the team that lost it:
  - off the holder, within 0.5 s of the holder's last touch and without a kick: `tackle` (`interception` when the winner is a goalkeeper);
  - by cutting out a pass in open play within 1 s of it being played (not a restart such as a corner), or by taking a blocked shot: `interception`. The pass is still reported, unsuccessful.

  The change stands once the winner keeps the ball for 0.5 s or plays it on (a short nudge to a teammate counts). When the other team takes the ball straight back, that is flicker (a player running past the ball), and neither change is reported; one still pending when play stops (out of play, end of input) is dropped too. A goalkeeper holding a shot is a save, not a possession change. `team` is the winner's; `t` and `start` are where the winner first had the ball.
- **Goal:** a shot reaches the goal line (within 0.5 m: observed ball positions are off by tenths of a meter) between the posts with no player within reach of the ball (that is a save), then comes to rest between the posts, within 0.8 m of the line or behind it (not wide of the goal: from a sharp angle, an off-target ball's ground projection can cross the mouth). The shot gets `success: true`, and the goal carries the running `score`.
- **Players:** `from` and `to` are roster ids from [lineup assignment](#lineup-assignment-visionlineuppy), taken when the track got the ball, per `schemas/README.md`: passer and receiver (pass, kickoff; `to` is `null` when it failed), winner and loser (possession change), the shooter (shot; the goal names the shot's). A shot redirected with no track within reach (a header: an airborne ball's ground projection lands meters from the player) names the shooting team's track nearest where it was struck, within 3.5 m. A track not named yet (before the first kickoff, or nobody missing to take over from) gives `null`; a track id never appears.
- **Confidence:** 0.9 (pass, goal, kickoff), 0.8 (shot) or 0.7 (possession change) times the mean ball confidence over the kick.

How the rules hold up on noisy observations: [noise variants](#noise-variants-harnessadd_noise).

### Lineup assignment (`vision/lineup.py`)

Names anonymous tracks with roster ids, from the team sheet only. Part of the event stage: `EventRules` calls it every frame and at each detected kickoff, and it imports nothing but `vision.observation`.

- **At each kickoff**, on the frame just before the ball is played (on a period's first frame players may not be lined up yet, #31), each team's tracks are matched to its starters at least total squared distance (Hungarian). The goalkeeper is the track in the keeper's kit. Outfield players are matched to where their position stands (`SLOT`: back line, then midfield, then attack, R positions on the right, L on the left; starters sharing a slot, like two center backs, spread right to left in team-sheet order), held in their own half. Both shapes are centered on their outfield centroid, so a team standing higher or deeper still matches. The kickoff taker is not in their slot: they get the starter left over.
- **In play**, each track's place in its team's shape (position relative to the outfield centroid, in its team's frame) is averaged over about 60 s. Every 2 s, and at each kickoff, named tracks with at least 4 s of shape swap names among themselves to fit the in-play slots best. One kickoff frame cannot tell apart players standing together: the taker, a striker and an attacking midfielder all wait on the halfway line. Their shapes in play can.
- **When a track is lost** (swapped, merged) and a new one appears, the new track takes the name of a missing player of its team (whose track is not in the frame), the one whose last-known position is nearest, if they could have run there since: within 3 m plus 8 m per second missing. A track nobody could have reached (a duplicate box, a false detection) stays unnamed. A keeper's track only takes the keeper's name. A starter missing from a kickoff's frame is last known at their slot there, and any track of the team may take their name.
- **When a track swaps players** (two players cross and the tracker follows the wrong one), the swap is visible if the kits differ: a named track whose team or keeper flag no longer fits its name gives the name up and is matched again like a new track, so the two tracks of a home-away swap trade names on the frame the kits flip. A swap between teammates is left to the in-play shape.
- **A second box on one player:** an unnamed track within 1 m of a named one of the same kit is its twin and answers to that name (`Lineup.player`), until it is named or moves away.
- **Substitutes** are never named: who comes on is invisible to video in v1. A substitute's track takes the name of the player who went off (see the grades below).

`tests/test_vision_rules.py` grades the players of matched events on the seam-2 clips (`PLAYER_ID_THRESHOLD`), checks every `from`/`to` is a roster id of the right team or `null` where the schema allows it, and breaks tracks mid-play (3 tracks every 20 s vanish for 10 frames and come back under new ids): the new tracks are named right on their first frame back, and the events name players as well as on clean tracks. `tests/test_vision_lineup.py` covers the matching, kit swaps, the reach limit and twins on hand-built frames.

Where names went wrong on the dev clips' saved observations (diagnosed against `truth/tracking.jsonl` by matching each observed track to the nearest true player every frame; #19). Per-frame naming accuracy is the share of tracked players named right:

| Clip | Tracker identity switches | Per-frame naming, before / after #19 | Event player-id, before / after #19 |
| --- | --- | --- | --- |
| dev1 | 16 (13 between the two teams) | 0.85 / 0.99 | 0.69 / 0.94 (35 events) |
| dev2 | 30 | 0.80 / 0.99 | 0.38 / 0.72 (18) |
| dev3 | 37 | 0.74 / 0.98 | 0.43 / 0.75 (24) |

The biggest cause was tracker swaps between a home and an away player who cross: the track's kit flips with the player it now follows, but it kept its name, so events named a player of the wrong team. Next were detections flickering in and out in crowds, where a returning or duplicate track took the name of a missing player across the pitch (fixed by the reach limit), and duplicate boxes on the player with the ball (twins). The initial kickoff assignment was wrong for about 6 of 22 players per clip until the in-play shape corrected it (now after 4 s rather than 10 s). What is left is mostly not naming: kicks by a track the rules could not see or picked wrong, and the first seconds after the kickoff.

### Seam-2 harness (`vision/harness.py`, offline only)

Builds clean frame observations from simulator tracking, so the rules can be built and graded in seconds without video. Roster ids become anonymous track ids, the goalkeeper flag comes from the team sheet, and the ball loses its height. It reads simulator data, so no other vision code may import it (a test enforces this).

```bash
python -m vision.harness data/generated/m007/tracking.jsonl data/generated/m007/match_info.json --out runs/m007/observations.jsonl
python -m vision.harness ... --noise swaps=0.3 --noise occlusion=0.05     # with noise (below)
```

`tests/test_vision_rules.py` grades the rules on the calibration fixture (one successful pass at 2 s, a shot at 8 s, a goal at 8.9 s, nothing else) and on the first 15 minutes of both halves of seeds 401-404, four pairings, cut together as the broadcast cuts the break (kickoff direction and the second-half switch included). Its `THRESHOLDS` hold the minimum precision and recall per type, and `SUBTYPE_THRESHOLDS` the minimum share of matched shots and possession changes with the true subtype. A separate test checks that a kickoff is found at both half starts and after every goal (7 goals in those clips), on the center spot, by the right team.

Grades on clean observations, whole 90-minute matches (both halves), four pairings per row. The rules were tuned on 201-204; 401-404 and 501-504 were also looked at while tuning, so these are dev grades, not held-out ones (re-measured after the noise hardening, #19: unchanged but for one point of whole-match players on 201-204):

| Seeds | Kickoff P / R | Pass P / R | Possession change P / R | Shot P / R | Shot subtype right | Goal P / R | Players right: before 1st sub / whole match |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 201-204 | 1.00 / 1.00 (17) | 0.95 / 0.99 | 0.60 / 0.60 | 0.96 / 0.85 | 98 / 99 | 0.89 / 0.89 (9 goals) | 0.95 / 0.81 |
| 401-404 | 1.00 / 1.00 (27) | 0.95 / 0.99 | 0.55 / 0.63 | 0.91 / 0.90 | 89 / 92 | 0.93 / 0.74 (19 goals) | 0.97 / 0.84 |
| 501-504 | 1.00 / 1.00 (24) | 0.95 / 0.99 | 0.52 / 0.69 | 0.96 / 0.80 | 80 / 82 | 0.93 / 0.81 (16 goals) | 0.96 / 0.83 |

What keeps clean grades below 1 is mostly the simulator, not the rules:
- **False passes:** almost all are clearances, physically the same kick as a long pass. v1 reports them as passes.
- **Missed shots:** many come from the simulator playing a shot (or a pass) from a player standing meters from the ball. Some shots blocked at close range never come to rest near a player, and a few headers measure under 50 km/h.
- **Goals:** in a penalty, the keeper stands within reach as the ball goes in, so it reads as a save. A few clearances go into the clearing team's own goal.
- **Possession changes** are capped by how the simulator labels them. It labels an interception only when a pass is cut out in the first 30 % of its path to the intended target, which video cannot see, so a pass cut out within 1 s is a guess either way. It labels no change when a cleared or loose ball is won by the other team, or when a restart follows a foul or offside (invisible to video) and the ball was never seen going out. A tackler who passes on at once (under 0.2 s) never has possession, so the tackle is missed. 473 of 491 matched changes (96 %) carry the true subtype.
- **Shot subtypes:** the few misses are blocked shots that then go out, which read as `off_target`.
- **Players** (matched events naming `from`, and `to` where it is a player, right) drop after the first substitution (58'-82') to about 0.5: a substitute's new track takes the name of the player who went off, and later kickoffs name it as that starter. Footage clips end before any substitution. Before it, the misses are the first kickoff of each half's clip (named from one frame) and the simulator playing a ball from a player meters from it.

### Noise variants (`harness.add_noise`)

`add_noise(frames, variant, level, seed)` makes clean harness observations look like a real video stage's, one variant at a time (`NOISE` in `harness.py`; `--noise VARIANT=LEVEL` on the command line, repeatable):

| Variant | Level | What it does |
| --- | --- | --- |
| `position` | offset per axis, m | each track (and the ball, at half) carries an offset that drifts slowly, plus per-frame jitter of a twelfth of it. 0.3 is about the dev footage: 0.37 m mean error, 0.05 m change from frame to frame (footage: 0.28 m, 0.04 m) |
| `dropped` | share of player detections missing | players vanish for 1-5 frames at a time and come back under the same track id |
| `swaps` | chance per encounter | two players coming within 1 m swap tracks; team and keeper flags stay with the players, as the video stage reads them from kit |
| `merged` | chance per encounter | two players within 1 m are boxed as one (one track at their midpoint, the other gone) for as long as they stay that close; the hidden one comes back under a new track id |
| `occlusion` | chance per frame near a player | the ball hides behind the player for 1-12 frames: `ball_visible` false, no position. 0.05 is about the dev footage (ball visible 89-92 %) |
| `confidence` | lowest confidence | every detection's confidence uniform in [level, 1] |

`tests/test_vision_noise.py` runs each variant at three levels on the seam-2 clips (seeds 401-404, four pairings, first 15 minutes of both halves) and checks, pooled over the clips, precision and recall per type and player-id accuracy against floors: the grades below minus a margin (one event for kickoffs and goals, 0.03 for passes and players, 0.05 for the rest). Precision floors also catch a variant making the rules invent events, such as kicks while the ball is hidden. It also checks that event confidence falls with detection confidence and stays in (0, 1).

Grades (2026-10-24), precision / recall, then player-id accuracy:

| Variant, level | Kickoff | Pass | Possession change | Shot | Goal (7) | Players |
| --- | --- | --- | --- | --- | --- | --- |
| clean | 1.00 / 1.00 | 0.96 / 0.98 | 0.54 / 0.58 | 0.91 / 0.91 | 1.00 / 1.00 | 0.97 |
| position 0.15 / 0.3 / 0.5 | 1.00 / 1.00 at all | 0.96 / 0.98, 0.95 / 0.98, 0.94 / 0.91 | 0.55 / 0.59, 0.55 / 0.61, 0.56 / 0.54 | 0.91 / 0.89, 0.94 / 0.89, 0.86 / 0.89 | 1.00 / 1.00, 1.00 / 1.00, 0.78 / 1.00 | 0.96, 0.95, 0.89 |
| dropped 0.05 / 0.1 / 0.2 | 1.00 / 1.00 at all | 0.96 / 0.95, 0.95 / 0.93, 0.96 / 0.86 | 0.55 / 0.53, 0.46 / 0.41, 0.49 / 0.38 | 0.89-0.94 / 0.91 | 1.00 / 1.00, 1.00 / 1.00, 0.88 / 1.00 | 0.96, 0.94, 0.92 |
| swaps 0.1 / 0.3 / 0.6 | 1.00 / 1.00 at all | 0.96 / 0.98 at all | 0.53 / 0.57, 0.54 / 0.56, 0.51 / 0.51 | 0.91 / 0.91 at all | 1.00 / 1.00 at all | 0.95, 0.94, 0.95 |
| merged 0.1 / 0.3 / 0.6 | 1.00 / 1.00 at all | 0.96 / 0.98 at all | 0.53-0.55 / 0.57-0.59 | 0.89-0.91 / 0.91 | 1.00 / 1.00 at all | 0.97, 0.96, 0.96 |
| occlusion 0.02 / 0.05 / 0.1 | 1.00 / 1.00, 1.00 / 1.00, 1.00 / 0.93 | 0.96 / 0.97, 0.95 / 0.93, 0.96 / 0.88 | 0.50 / 0.52, 0.50 / 0.44, 0.54 / 0.37 | 0.91 / 0.91, 0.91 / 0.89, 0.83 / 0.69 | 1.00 / 1.00, 1.00 / 1.00, 0.86 / 0.86 | 0.96, 0.93, 0.89 |
| confidence 0.8 / 0.5 / 0.2 | as clean | as clean | as clean | as clean | as clean | 0.97; mean event confidence 0.79, 0.66, 0.53 |

What gave way before #19's hardening, and what is left:
- **Swaps and merged boxes** cost names, not events; the lineup fixes above hold player-id at 0.94-0.97.
- **Ball occlusion** used to end every possession after 3 hidden frames, miss kickoffs and penalties played behind a player (the speed was measured across the wait), and run the tackle window out while the ball was hidden; now bridged (see [hidden ball](#event-rules-visionrulespy)). At 0.1 (the ball hidden about 40 % of the time it is at a player's feet) shots and possession changes still drop: a kick or tackle made out of sight is often not recoverable.
- **Position noise** used to cost most goals at 0.3 m: the ball never came within 0.1 m of the goal line. Beyond 0.5 m (twice the footage's) possession starts to fail, because ball and feet drift apart past the 1.5 m reach.
- **Dropped detections** cost possession changes: a tackler who flickers out of the frame never holds the ball for 4 frames.

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

`tests/test_vision_footage.py` runs the same on every dev and test clip when `$VISION_FOOTAGE` points at the rendered clips, and skips otherwise. Its `THRESHOLDS` hold each clip's minimum precision and recall per type: the first measured grade minus a cross-hardware margin (the dev clips were graded on MPS, test1 on CUDA): 0.03 for passes, one match fewer for types with fewer than 5 true events. Floors are only ever raised. Kickoffs get no margin: every clip's kickoff must be found, for the right team, because kickoffs anchor lineup assignment. Player-id accuracy is reported but not asserted yet.

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

Matched events in test1: pass success right 92 %, pass subtype 85 %, shot and possession-change subtype 100 %, mean timing error 0.03 s, distance error 0.8 m, speed error 7 km/h. The dev clips were graded on an M-series Mac (MPS), test1 on an RTX 5070 (CUDA); a second dev run on the Mac gave byte-identical events.

These grades were measured before lineup assignment (#18), so `from`/`to` were `null` and player-id accuracy 0. Re-running the merged event rules on the dev clips' saved observations (the video stage is unchanged) gives the same detections and grades as above, and player-id accuracy 0.69 / 0.38 / 0.43 (dev1 / dev2 / dev3), against about 0.96 on clean seam-2 observations. With the noise hardening (#19), the same saved observations give player-id accuracy 0.94 / 0.72 / 0.75 ([where names went wrong](#lineup-assignment-visionlineuppy)) and slightly more detections: dev2 passes 16/17 (18 detected), possession changes 0/2 (1); dev3 passes 20/25 (23); dev1 unchanged. Every floor in `THRESHOLDS`, and the kickoff check, still holds on these re-run detections; the floors are still the first grades. test1 went from player-id 0.46 before #19 to **TODO: test1 re-grade after #19**.
