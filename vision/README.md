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

Each clip is a **whole short match**: the simulator plays two halves of
`minutes / 2` (seeded, `full` profile), and the renderer exports the whole
match. The true events and the `match_info.json` periods therefore cover
exactly the video, including the half-time cut and the second kickoff.

Render settings are fixed for v1: `cv_full_pitch` camera, CV visibility on,
ball scale 2, player scale 1, 1920x1080 at 25 fps. `render` checks that the
export manifest recorded exactly these.

Output, all ignored by git, in `data/renders/footage/<name>/`:

| File | Use |
| --- | --- |
| `<name>.mp4` | the video: the vision stage's input |
| `<name>.mp4.manifest.json`, `.metrics.json` | renderer export manifest (camera, scales, CV visibility, frame-to-tracking map) and timing |
| `match_info.json` | team sheet: the only other file the vision stage may read |
| `events.json` | true events (`source: sim`): grading only |
| `tracking.jsonl` | simulator tracking: training-label projection and grading only |
| `clip.json` | seed record entry + render settings; written last, after `validate:export` passed |

Rendering needs the renderer's export setup (`cd renderer && npm ci && npx
playwright install chromium`, plus `ffmpeg`/`ffprobe` with libx264 on PATH).
Export runs at roughly 7-8 frames/s: about 7 minutes per 2-minute clip, 35
minutes for the test clip. The simulator output is byte-identical for the
same seed; video pixels are reproducible on the same browser/OS/graphics stack
(see `renderer/README.md`).
