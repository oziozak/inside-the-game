# 3D broadcast renderer

Transforms shared `match_info.json` + `tracking.jsonl` into a Three.js broadcast view and deterministic 25 FPS H.264 footage. No events, overlays, AI services, or simulator internals are read. Fictional teams use the metadata's kit colors, including goalkeepers.

## Run locally

Requires Node 22.12+ (or a newer supported Node), npm, and a WebGL 2 browser.

```bash
cd renderer
npm ci
npm run dev
```

Open the URL printed by Vite (normally http://127.0.0.1:5173). The first 60 seconds of `sample_a` load automatically. `predev` and `prebuild` copy **only** metadata and tracking into ignored `public/sample/` for serving; source data is never edited. Other inputs can be selected with the two file pickers and **Load files**. Files are validated before replacing the current match. They remain in the browser; there is no upload API.

Play/pause, seek and speed controls use the input timestamps. The debug clock can be hidden (also `?clock=0`). Stadium tiers and shadows are optional; the clean default keeps the pitch and objects easy to see. Player geometry is intentionally simple, without real likenesses or branding.

### CV visibility and camera settings

The Camera, CV visibility, Player scale and Ball scale controls are presentation settings independent of tracking. Defaults are `cv_full_pitch`, player scale `1`, ball scale `1`; both scales accept finite values from `0.25` to `5`. For easier detection, try player scale `1.5` and ball scale `3`. These are uniform geometry multipliers, not pitch-coordinate multipliers. Player models scale about their tracked foot anchor; the ball scales about its tracked center, including height. Enlarged balls can intersect the grass at low heights: the renderer deliberately preserves the tracked center rather than lifting it. No outlines, labels or tracking annotations are added.

| Preset | Behavior |
| --- | --- |
| `cv_full_pitch` | Fixed elevated view, 43° base vertical field of view, position `(0,75,83)` in Three.js coordinates. Aspect-aware zoom fits the pitch, goals and run-off with headroom. Camera pose never follows the action. Recommended for CV calibration. |
| `broadcast` | Closer 40° view, 38 m high and 48 m behind its target. Smoothly follows the filtered ball ground position, clamped to ±38 m along the centered pitch length and ±18 m across its width. Some players and pitch edges can be offscreen. |

The full-pitch preset uses only the aspect ratio. The broadcast target uses a fixed 0.8-second causal triangular filter over tracking samples evaluated from absolute simulation time, with about 0.27 seconds of lag on constant-velocity motion. The filter restarts at the current period boundary. Seeking evaluates the same history window directly; no wall-clock delta, accumulated camera state or randomness is used. Camera poses live in `src/camera/presets.ts`, temporal filtering in `src/camera/tracking.ts`; visibility defaults, scale validation and ball radius live in `src/scene/config.ts`. Base player dimensions remain in `src/scene/broadcast.ts`: about 1.88 m tall, torso 0.58×0.65×0.32 m, head radius 0.19 m. Base ball radius is 0.11 m. At `1.5`/`3`, player height is about 2.82 m and ball radius 0.33 m; these deliberate visual exaggerations affect image measurements and should be recorded when comparing CV evaluations.

## Export video

Install FFmpeg with `libx264` and make `ffmpeg` / `ffprobe` available on PATH. Install Playwright's matching browser once:

```bash
cd renderer
npx playwright install chromium
npm run export -- --start 0 --end 10 --out ../data/renders/sample_a-10s.mp4
```

Export with explicit CV visibility settings (use a fresh output filename):

```bash
npm run export -- --start 0 --end 10 --camera cv_full_pitch \
  --player-scale 1.5 --ball-scale 3 --out ../data/renders/cv-visibility.mp4
npm run validate:export -- --video ../data/renders/cv-visibility.mp4
```

Use `--camera broadcast` for the closer preset. Each export manifest records the selected camera and scales under `render`, so they can be reproduced. These settings never change metadata or tracking files. `--cv_visibility` enables the high-contrast ball treatment described below.

For genuine simulator output, use the current simulator CLI from the repository root:

```bash
python -m simulator --home bosphorus --away thames --seed 7 --out data/generated/renderer-m007
cd renderer
npm run export -- \
  --metadata ../data/generated/renderer-m007/match_info.json \
  --tracking ../data/generated/renderer-m007/tracking.jsonl \
  --start 2503 --end 2513 --camera cv_full_pitch --cv_visibility --ball-scale 2 \
  --out ../data/renders/simulator-full-pitch.mp4
npm run export -- \
  --metadata ../data/generated/renderer-m007/match_info.json \
  --tracking ../data/generated/renderer-m007/tracking.jsonl \
  --start 2503 --end 2513 --camera broadcast --cv_visibility --ball-scale 2 \
  --out ../data/renders/simulator-broadcast.mp4
```

Paths resolve against the current directory, so run npm commands in `renderer/`. The simulator's `--out` is required and both inputs come from that directory. Output parents are created; existing video or manifest paths are refused. Videos, previews, metrics and manifests belong under ignored `data/renders/`. `--rich` enables stadium/shadows; clean exports default to no stadium/shadows. Output contains the canvas only, with no clock, controls, event labels, or annotations. The sample-data export commands above remain supported.

Defaults: 1920×1080, 25 FPS, H.264, yuv420p, CRF 18. Width and height must be even. `--start` defaults to the first tracking timestamp; `--end` defaults to 10 seconds and must be supplied for later intervals. Intervals are half-open `[start,end)`: output frame `i` is rendered at `start + i / 25`. For an exact whole-frame interval, output duration equals `end-start`; otherwise it rounds up to the next frame. The final input sample covers one 40 ms output frame. Out-of-coverage requests fail instead of silently extending the match.

Export streams a tracking window on Node (details below), then starts a loopback-only Vite server and headless Chromium with software WebGL, explicitly applies each timestamp, captures the canvas PNG, then pipes images to FFmpeg with backpressure. It never uses real-time playback or MediaRecorder. A sibling `.mp4.manifest.json` lists output index, requested time and preceding input frame index. This is an export sidecar, not a change to the shared tracking schema. Sparse input uses the last sample until a new sample arrives; the manifest records that preceding sample. There are no temporary image sequences to clean up. An interrupted export can leave a partial video; use a new output path when retrying.

```bash
ffprobe -v error -count_frames -select_streams v:0 \
  -show_entries stream=codec_name,width,height,r_frame_rate,nb_read_frames,pix_fmt \
  -of json ../data/renders/sample_a-10s.mp4
# Expected: h264, 1920, 1080, 25/1, 250 frames, yuv420p
```

Timing and scene state are deterministic. The browser test also checks byte-identical captures when returning to the same timestamp. For pixel reproducibility across machines, keep the lockfile, Chromium, OS, and graphics stack fixed; different graphics drivers can rasterize differently. This does not affect the timestamp mapping. Export speed is machine-dependent and may be slower than real time.

`npm run validate:export -- --video PATH` uses FFprobe to decode/count actual video frames, verifies H.264/resolution/25 FPS, checks every frame's presentation timestamp against `i/25`, then checks the manifest's match ID, frame count, timestamps and source frame indices against tracking. For custom input, pass the same `--metadata` and `--tracking` paths used for export. A nonzero aligned interval, for example `--start 2.4 --end 3.4`, must have 25 frames mapping to input IDs 60–84 for `sample_a`. Arbitrary subframe starts retain the existing interpolation behavior; align to source sample times for exact one-to-one sample correspondence. Nanosecond-level roundoff at sample boundaries snaps to the exact source frame. Sparse inputs retain the documented hold behavior.



### Streaming interval extraction and absolute time

`scripts/lib/interval.ts` scans UTF-8 JSONL incrementally with a 64 KiB file stream and `readline`. It never reads the complete file into one string. Every nonblank line is schema-validated with the same `frameParser` used by browser playback, including match/roster IDs and global timestamp/frame ordering. The scan continues to EOF to establish actual coverage, input counts, and malformed data outside the requested interval. Disk/validation work is therefore O(total input frames); retained memory is O(selected frames).

For `[start,end)`, retain `[start - 1 second, end + 1/25 second]`, plus the nearest sample before and the first sample after those boundaries, when available. The causal broadcast filter queries back 0.8 seconds, so one second gives margin. Outside neighbors are essential: a sparse gap may exceed either fixed margin and the existing sampler must still see its true predecessor/successor. The original metadata (including all half-time boundaries), JSONL sample contents, timestamps, frame numbers, player IDs, optional `period`, and goal-area coordinates are preserved. No re-timing, renumbering, clamping or simulator regeneration is performed.

The browser parses only this retained window. At export time `t`, sampling/interpolation and camera filtering still use absolute `t`; the history margin ensures the trimmed window's first sample cannot affect requested camera queries. Existing sparse-gap and half-time hold behavior is unchanged. Requests are checked against actual file coverage `[first.t,last.t+0.04)`, not the metadata's nominal full-time value. The last sample is held for its one-frame interval, including fractional output times after its timestamp. Invalid or out-of-coverage requests fail with their requested/available interval before launching Chromium.

The same loader is used by `validate:export`, so validation does not load the entire match either. It still checks the actual decoded MP4 count and presentation timestamps against the unchanged manifest's **original** input-frame references. An additional `.mp4.metrics.json` sidecar records input/retained frames and bytes, scan time, browser load time, capture-plus-encoding FPS and Node peak RSS. The metrics sidecar is renderer-specific and is not a shared schema change.

This is **interval buffering**, not a bounded-memory full-match exporter. A whole-match selection still retains the whole match; Node keeps parsed frames and a window string, Playwright serializes that string, and Chromium parses another copy. Large windows can still exhaust memory. Prefer short sequential export intervals with fresh output paths. Interactive file-picker playback still loads the entire selected file; use interval export for large simulator feeds. Automatic chunk concatenation, seeking indexes and rolling browser windows are outside this change. The video validator also buffers FFprobe's decoded-frame metadata (currently capped at 64 MiB).

### Full-match integration and measurements

Seed 7 (`bosphorus` versus `thames`, default 45-minute halves) produced 135,303 samples and 144,283,869 bytes of tracking, covering `[0,5412.12)`. The selected `[2503,2513)` interval includes a shot at 2508.72 s. Event truth was inspected **offline only** to choose the interval; no rendering or export code loads events. The browser receives 279 frames (2501.96–2513.08) and 297,154 JSONL bytes. Both comparison videos are 1920×1080, H.264/yuv420p, 25 FPS and 250 decoded frames, with the same player scale 1, ball scale 2 and CV materials. Only their camera differs.

All 250 frames in each camera were checked for 11 home players, 11 away players, exact transformed player/ball coordinates, metadata shirt/shorts colors and both goalkeeper kits. The ball reaches 1.55 m high in the selected interval. Direct seeking and wider-trimmed loading produced the same state and screenshots at the beginning, middle and end. Reversed player-array order preserved IDs and positions. Actors remain present even when cropped by the broadcast view; no label or event request is made. The exports were visually inspected.

Fresh-process input-only comparisons on this machine (single measurements, cached local disk, Node RSS excludes Chromium/FFmpeg):

| Measurement | Previous full-string read/parse | Streaming interval |
| --- | --- | --- |
| Input samples | 135,303 | 135,303 scanned |
| Retained samples | 135,303 | 279 |
| JSONL bytes for browser transfer | 144,283,869 (baseline size; not sent) | 297,154 |
| Read/validate time | 803 ms | 705 ms |
| Peak Node RSS during input benchmark | 678.1 MiB | 101.0 MiB |

The old browser crash was not deliberately reproduced: the baseline measures the previous **Node input** path only. These measurements do not establish total application memory or an exact Chromium memory reduction. A complete optimized export also includes Vite/Playwright and image buffers: full-pitch Node peak RSS was 343.2 MiB and broadcast 338.2 MiB, still excluding child processes. Browser window loads took about 680 ms. Measured capture plus H.264 encoding was 11.41 FPS full-pitch and 11.47 FPS broadcast; performance depends on machine load and these are observations, not targets.

Reproduce input measurements in separate processes (the output folder must exist):

```bash
npm run benchmark:input -- --mode interval --out ../data/renders/simulator-input-window.json
npm run benchmark:input -- --mode whole --out ../data/renders/simulator-input-whole.json
```

Both default to the seed-7 paths/interval above; `--metadata`, `--tracking`, `--start`, and `--end` can select others. `whole` intentionally allocates the entire input in Node and is for controlled benchmarking only.

### Integration validation commands

```bash
npm test
npm run build
npm run test:browser
npm run test:calibration
npm run test:simulator
npm run validate:export -- --video ../data/renders/simulator-full-pitch.mp4 \
  --metadata ../data/generated/renderer-m007/match_info.json \
  --tracking ../data/generated/renderer-m007/tracking.jsonl
npm run validate:export -- --video ../data/renders/simulator-broadcast.mp4 \
  --metadata ../data/generated/renderer-m007/match_info.json \
  --tracking ../data/generated/renderer-m007/tracking.jsonl
```

`test:simulator` requires genuine simulator output to exist; it never generates a replacement simulator. Optional metadata/tracking/start/end flags match the exporter defaults above. It uses two bounded context windows, writes `data/renders/simulator-integration.json` and previews, and saves a wider pre-trimmed reference under `data/generated/renderer-integration-trimmed/`. This is extracted from the **same** full tracking file. Do not use the simulator's `--start` flag to create an equivalence reference: its movement layer starts that window at formation positions, so it may be a different trajectory.

For an actual encoded-video equivalence check, after `test:simulator` and both exports above:

```bash
npm run export -- \
  --metadata ../data/generated/renderer-integration-trimmed/match_info.json \
  --tracking ../data/generated/renderer-integration-trimmed/tracking.jsonl \
  --start 2503 --end 2513 --camera broadcast --cv_visibility --ball-scale 2 \
  --out ../data/renders/simulator-broadcast-trimmed.mp4
npm run validate:simulator
npm run validate:calibration
cd ..
python scripts/validate.py
python scripts/validate.py renderer/fixtures/calibration
```

`validate:simulator` checks the seed-7 comparison and trimmed regression filenames above, confirms matching manifests and camera-only settings differences, and uses FFmpeg `framemd5` to compare every decoded broadcast frame. All 250 decoded frames matched exactly. The manifest's first output frame is input frame 62575 at 2503.0 s; the last is input frame 62824 at 2512.96 s. The result is in `data/renders/simulator-export-checks.json`. All 135,303 simulator tracking lines are also schema/identity/order validated by the streaming reader on every full-source export, while the repository's Python validator checks its default sample/example paths separately.

The unit suite includes a streamed 135,000-frame input, fractional starts, retained history, full-versus-pre-trimmed sampling/camera equivalence, long sparse gaps, half-time cuts between sample timestamps, coverage failures, original frame IDs and calibration/goal-area preservation. Existing calibration validation still passes. The final reliability investigation, capture synchronization and concurrent-test limitations are documented below. Scene-state determinism is checked separately from screenshot and decoded-video equality.

### Final reliability review

The historical failure was the strict broadcast-repeat assertion in `scripts/smoke.ts` (originally line 56), after seeking `2.4 → 12 → 2.4` seconds. It was **not** reproduced in three isolated and six concurrent diagnostic runs or twelve additional unmodified concurrent smoke runs with calibration load. Diagnostics compared scene transforms, native canvas hashes, screenshot bytes, canvas bounds/scroll and actual server ports: they agreed, and HTTP ports were distinct. This is evidence against a demonstrated scene-state bug, not proof that the historical failure cannot recur.

A separate concurrent export later lost `window.broadcast` mid-run, consistent with a page reload or development-server invalidation. A synthetic watcher-event probe did not reproduce navigation within the normal timeout, so the exact historical cause remains unproven. Resource contention can expose missing synchronization, and Vite automation previously shared live-reload/dependency-cache resources. The review addresses these mechanisms without claiming a definitive explanation for the original PNG mismatch:

- `scripts/lib/capture.ts` calls WebGL `finish()` and waits across two animation-frame callbacks before capture. Screenshots still use Playwright and byte-for-byte assertions. There are no pixel tolerances, retries, fixed-delay sleeps or increased timeouts. Scene time never advances in export mode.
- `scripts/lib/server.ts` disables file watching/HMR for automation and provides a private temporary Vite cache per invocation. Cleanup closes the server and removes its own cache even on failure. Normal `npm run dev` behavior is unchanged.
- Sample preparation publishes each copied file with an atomic rename, avoiding partial reads when a build and browser test overlap. This does not make concurrent regeneration of an entire metadata/tracking pair atomic; inputs should remain immutable during a run.
- Repeat tests use separate artifact directories. On a broadcast-repeat failure, the test saves both screenshots plus scene/layout JSON, then rethrows the original strict assertion.

Repeat the strict test without automatic retries:

```bash
npm run test:browser:repeat -- --runs 5 --concurrency 1
npm run test:browser:repeat -- --runs 12 --concurrency 3 --load
```

Final isolated-cache results: **5/5 isolated and 12/12 concurrent browser runs passed**, with **4/4 concurrent calibration-load runs passed**. The ordinary browser, simulator and calibration commands also passed while fresh exports and a build were running. Logs and summaries are under ignored `runs/browser-repeat-*/`. The final reports for this review are `runs/browser-repeat-4j9TPc/results.json` and `runs/browser-repeat-oepdGD/results.json`. Observed stability in this matrix does not guarantee bit-identical pixels on other OS/browser/graphics stacks.

The code review also changed encoder writes to await their callbacks (reporting premature pipe closure), waits for FFmpeg to be reaped, guarantees server cleanup even if browser closure fails, releases rich-mode shadow targets on match replacement, preserves real access errors when checking output paths, and verifies complete comparison manifests rather than only their frame lists/settings. Corrupt schema records and player/match identities **outside** the retained interval are regression-tested. The unit suite now has **17 passing tests**.

An injected FFmpeg executable exiting with code 7 produced exporter exit 1 promptly, with no success manifest; the browser/server and process closed. Fresh videos under `data/renders/final-review-isolated/` passed all count/PTS/input-reference checks. The optimized full-match export still retained 279 of 135,303 frames (297,154 bytes), and all 250 decoded full-source versus pre-trimmed broadcast frames remained identical.

The earlier 11.4 FPS measurements above predate the explicit capture barrier. Final review exports under concurrent stress measured approximately **7.6–7.8 FPS** with browser window load around 0.8–0.9 s. Synchronization adds overhead; retain it for correctness rather than weakening the test for throughput. Node-only RSS and whole-window memory limitations above still apply. Docker/Azure and non-renderer source were not changed.

### Ball contrast and apparent size

Normal mode keeps the 0.11 m physical radius and shaded white surface, now with six dark surface patches. **CV visibility** (UI checkbox, CLI `--cv_visibility`, API `{ cvVisibility: true }`) uses an unlit yellow surface (`#fff052`) with dark patches. This separates it from both grass and white pitch lines and avoids darkening with changing lighting. Depth testing, player occlusion and goal nets remain enabled; no labels, outlines, trails, boxes or event cues are drawn, and the ball is never moved to avoid occlusion.

CV mode estimates projected sphere diameter from camera depth, vertical focal length, and output height. It asks for 5 pixels but caps automatic enlargement at 2× base radius (0.22 m). The explicit `ballScale` remains a lower bound; it can exceed that automatic cap if deliberately set by the user. The estimate is an unoccluded diameter, not a guaranteed count of visible segmented pixels: grass clips enlarged low balls, players can occlude them, and H.264/antialiasing reduce detail. `window.broadcast.inspect().ball` reports effective scale, projected diameter and whether a ray to the ball center intersects a player. The ray test does not certify the whole silhouette is clear or measure goal-net occlusion.

Adaptive scaling can choose different geometry under different cameras. For a camera-only comparison, set `--ball-scale 2` in **both** exports, as below. This fixes the same 0.22 m radius in both views while leaving players at their realistic base scale of 1. At low heights it intersects the grass because its tracked center is preserved. To evaluate physical-size footage, omit `--cv_visibility` and use `--ball-scale 1`.

## Calibration footage for the vision team

The isolated fixture in [`fixtures/calibration/`](fixtures/calibration/README.md) has 300 frames over 12 seconds: A holds (0–2), passes (2–4), B receives (4–5), carries (5–8), then shoots (8–9). The ball rests inside the goal until 12 seconds. It uses the unchanged shared metadata/tracking schemas. Ground truth lives separately in `ground_truth.events.json` using the shared event schema; it is never loaded into the renderer. No simulator or vision code is involved. Regenerate deterministically:

```bash
cd renderer
npm run generate:calibration
npm run build
npm test
npm run test:browser
npm run test:calibration
```

Open `npm run dev`, choose `fixtures/calibration/match_info.json` and `tracking.jsonl` in the existing file controls, then choose a camera and enable CV visibility. To generate the 1920×1080, 25 FPS H.264 comparison (existing output files are refused):

```bash
npm run export -- --metadata fixtures/calibration/match_info.json \
  --tracking fixtures/calibration/tracking.jsonl --start 0 --end 12 \
  --camera cv_full_pitch --cv_visibility --ball-scale 2 \
  --out ../data/renders/calibration-full-pitch.mp4
npm run export -- --metadata fixtures/calibration/match_info.json \
  --tracking fixtures/calibration/tracking.jsonl --start 0 --end 12 \
  --camera broadcast --cv_visibility --ball-scale 2 \
  --out ../data/renders/calibration-broadcast.mp4
```

Both exports consume byte-identical tracking and use identical ball/player geometry, materials, interval and encoding; only camera presentation differs. Use the full-pitch video for stable homography and the closer broadcast video for moving-camera tracking. Frame `i` corresponds to `i/25` simulation seconds. Event labels are for offline scoring only; send only the videos to the vision model. The goal extends to x=107, and the fixture intentionally stops the ball at x=106, within the net rather than outside the coordinate convention.

Validate either video with its actual fixture inputs:

```bash
npm run validate:export -- --video ../data/renders/calibration-full-pitch.mp4 \
  --metadata fixtures/calibration/match_info.json --tracking fixtures/calibration/tracking.jsonl
npm run validate:export -- --video ../data/renders/calibration-broadcast.mp4 \
  --metadata fixtures/calibration/match_info.json --tracking fixtures/calibration/tracking.jsonl
```

For an actual repeated-export comparison, export a second full-pitch video under the ignored `repeat/` folder, then run the pair/repeat validator:

```bash
npm run export -- --metadata fixtures/calibration/match_info.json \
  --tracking fixtures/calibration/tracking.jsonl --start 0 --end 12 \
  --camera cv_full_pitch --cv_visibility --ball-scale 2 \
  --out ../data/renders/repeat/calibration-full-pitch.mp4
npm run validate:calibration
```

`test:calibration` checks actual world coordinates for all 300 rendered frames in each view, compares direct seek with sequential rendering, tests repeat screenshots at seven times per view, and records projected ball diameter and center-ray occlusion in `data/renders/calibration-checks.json`. It saves one preview per view. `validate:calibration` decodes all three exported videos, verifies their counts/timestamps/input mapping, confirms camera-only manifest differences, and compares all decoded full-pitch repeat-frame hashes with FFmpeg `framemd5`. Results go in `data/renders/calibration-export-checks.json`. Cross-machine bitwise reproducibility still requires the same browser/OS/graphics stack; scene coordinates and timing are tested independently.

Known limitations: this is an uncluttered two-player baseline, not a representative full match; it intentionally avoids player occlusion and has no keeper, tackles or complex animation. There is no motion blur or shutter integration. The simple trajectory stops at the net without simulating net physics. The broadcast camera has deliberate lag and may crop distant players. Enlarged yellow footage helps controlled detection testing but differs from regulation-size white-ball footage; record the manifest settings with every evaluation. The five-pixel target is best-effort, not a detection guarantee.

## Integration API and coordinates

`parseMatch(metadata, jsonl)` validates the repository's actual Draft 2020-12 schemas with Ajv, then checks match IDs, strictly increasing frame numbers/timestamps, unique player IDs, and roster/team consistency. This renderer supports the project's 25 FPS, 105×68 m configuration; it explicitly rejects other dimensions/rates. Referees are supported without team roster entries. Frames may contain a changing subset of players; actors are keyed by ID and disappear when absent.

Tracking coordinates map to Three.js as `(x - 52.5, height, 34 - y)`. No coordinate clamping, team flipping, or event-based inference is applied. Linear interpolation preserves the provided sample positions and ball heights exactly at their timestamps. Player correspondence uses IDs, never array order. Gaps over 1.5 sample intervals and second-half cuts hold the preceding sample rather than interpolate a teleport.

For automation, load `/?export=1`, wait for `window.broadcast`, then call:

```js
window.broadcast.load(metadataObject, trackingJsonlText);
window.broadcast.resize(1920, 1080);
window.broadcast.setRich(false);
window.broadcast.configure({ camera: 'cv_full_pitch', playerScale: 1.5, ballScale: 3 });
window.broadcast.setTime(2.4); // synchronous render; returns t, inputFrame, inputTime, playerIds
window.broadcast.inspect(); // actual world anchors, geometry scales and camera state; never drawn
```

Export mode never starts playback or automatically fetches the sample. Capture `canvas#pitch` after `setTime`. `src/data/` owns contracts, parsing and sampling; `src/playback/` owns export timing and clock formatting; `src/scene/` owns geometry, camera, lighting and actors; `src/main.ts` owns controls and the automation API. Interactive input files are loaded into memory; the Node export and export validator use the bounded interval loader described above.

## Checks

```bash
cd renderer
npm run build
npm test
npm run test:browser
cd ..
python scripts/validate.py
```

`npm test` verifies all 1,500 sample timestamps, nonzero interval boundaries, interpolation by ID, ball height, coordinate transforms, half-time cuts, gaps, invalid data, visibility settings and both camera presets. Full-pitch coverage is checked at 16:9, 4:3, square and portrait aspect ratios. The browser check exercises sample loading, motion, same-time pixel reproducibility, play/pause, seek, speed selection, clock hiding, rich mode, scaling without anchor movement, stable CV framing, deterministic broadcast seeking, clean export mode and absence of event/overlay requests. It saves `data/renders/renderer-preview.png`. Run `npm run build` before browser checks on a fresh checkout to prepare sample assets. Browser checks/export require permission to bind a localhost port and launch Chromium in restricted environments.

Implementation status: functional renderer, deterministic export, configurable presentation, and deployment files are implemented. Build, unit tests, browser checks, schema validation, a 1080p video export, and the production server have been exercised locally. Docker image build remains unverified because the local daemon was unavailable. Azure has not been deployed.

## Production and Docker

```bash
cd renderer
npm run build
PORT=8080 HOST=127.0.0.1 npm start
# http://127.0.0.1:8080 and /healthz
```

`PORT` (default 8080) and `HOST` (default 0.0.0.0) configure the production static server. `/healthz` returns `{"status":"ok"}`. The server serves only the built directory and supports GET/HEAD. The production app uses local file inputs for custom matches, so no credentials or storage account are needed.

From the **repository root**, after starting Docker:

```bash
docker build -f renderer/Dockerfile -t inside-game-renderer:local .
docker run --rm -p 8080:8080 -e PORT=8080 inside-game-renderer:local
curl --fail http://127.0.0.1:8080/healthz
```

The Dockerfile uses the repo root as context because schemas and sample data live outside `renderer/`. Its sibling `Dockerfile.dockerignore` excludes secrets, dependencies, and generated outputs. The multi-stage runtime runs as a non-root user and contains just Node, the built site, and its dependency-free server. The hosted container serves the renderer UI; batch video generation stays in the local Playwright/FFmpeg workflow. It does not pretend to provide an Azure render-job queue or GPU service.

## Azure Container Apps (run only after explicit deployment approval)

These commands create billable resources. They are instructions only and have not been executed. Requires Azure CLI, permission to create resources and role assignments, and an approved subscription. Choose a globally unique ACR name and an available region. From the repository root:

```bash
az login
az account set --subscription '<approved-subscription-id>'
az extension add --name containerapp --upgrade
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.OperationalInsights

RG=inside-game-renderer
LOCATION=westeurope
ACR='<globally-unique-lowercase-registry-name>'
az group create --name "$RG" --location "$LOCATION"
az acr create --resource-group "$RG" --name "$ACR" --sku Basic
az acr build --registry "$ACR" --image renderer:v1 --file renderer/Dockerfile .
az containerapp env create --name inside-game-env --resource-group "$RG" --location "$LOCATION"

az identity create --name renderer-pull --resource-group "$RG"
PULL_ID=$(az identity show --name renderer-pull --resource-group "$RG" --query id -o tsv)
PULL_PRINCIPAL=$(az identity show --name renderer-pull --resource-group "$RG" --query principalId -o tsv)
ACR_ID=$(az acr show --name "$ACR" --query id -o tsv)
ACR_HOST=$(az acr show --name "$ACR" --query loginServer -o tsv)
az role assignment create --assignee-object-id "$PULL_PRINCIPAL" \
  --assignee-principal-type ServicePrincipal --role AcrPull --scope "$ACR_ID"

az containerapp create --name inside-game-renderer --resource-group "$RG" \
  --environment inside-game-env --image "$ACR_HOST/renderer:v1" \
  --user-assigned "$PULL_ID" --registry-identity "$PULL_ID" --registry-server "$ACR_HOST" \
  --ingress external --target-port 8080 --cpu 0.5 --memory 1Gi \
  --min-replicas 0 --max-replicas 1 --env-vars PORT=8080 HOST=0.0.0.0
az containerapp show --name inside-game-renderer --resource-group "$RG" \
  --query properties.configuration.ingress.fqdn -o tsv
```

Allow role-assignment propagation before app creation if the registry initially denies image pulls. Open the returned hostname over HTTPS and check `/healthz`. In Container Apps, configure HTTP readiness/liveness probes at `/healthz`, port 8080, if explicit HTTP probes are desired; Docker HEALTHCHECK alone does not configure Azure's probes. Local file choices stay in the viewer's browser. ACR image pulls use managed identity rather than registry passwords.

References: [Container Apps CLI](https://learn.microsoft.com/en-us/cli/azure/containerapp?view=azure-cli-latest), [ingress](https://learn.microsoft.com/en-us/azure/container-apps/ingress), [managed identity image pulls](https://learn.microsoft.com/en-us/azure/container-apps/managed-identity-image-pull), [Three.js renderer](https://threejs.org/docs/pages/WebGLRenderer), [Playwright capture](https://playwright.dev/docs/screenshots).
