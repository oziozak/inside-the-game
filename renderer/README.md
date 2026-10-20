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

For other simulator output:

```bash
npm run export -- \
  --metadata ../data/fake/sample_a/match_info.json \
  --tracking ../data/generated/sample_a/tracking.jsonl \
  --start 12 --end 22 --width 1920 --height 1080 \
  --out ../data/renders/interval-12-22.mp4
```

Use the actual location of metadata (the full-tracking generator currently leaves metadata in `data/fake/sample_a/`). Paths resolve against the current directory, so run commands in `renderer/`. Output parents are created; existing video or manifest paths are refused. Generated videos, previews, and manifests belong under ignored `data/renders/`. `--rich` enables stadium/shadows; clean exports default to no stadium/shadows. Output contains the canvas only, with no clock, controls, event labels, or annotations.

Defaults: 1920×1080, 25 FPS, H.264, yuv420p, CRF 18. Width and height must be even. `--start` defaults to the first tracking timestamp; `--end` defaults to 10 seconds and must be supplied for later intervals. Intervals are half-open `[start,end)`: output frame `i` is rendered at `start + i / 25`. For an exact whole-frame interval, output duration equals `end-start`; otherwise it rounds up to the next frame. The final input sample covers one 40 ms output frame. Out-of-coverage requests fail instead of silently extending the match.

Export starts a loopback-only Vite server and headless Chromium with software WebGL, explicitly applies each timestamp, captures the canvas PNG, then pipes images to FFmpeg with backpressure. It never uses real-time playback or MediaRecorder. A sibling `.mp4.manifest.json` lists output index, requested time and preceding input frame index. This is an export sidecar, not a change to the shared tracking schema. Sparse input uses the last sample until a new sample arrives; the manifest records that preceding sample. There are no temporary image sequences to clean up. An interrupted export can leave a partial video; use a new output path when retrying.

```bash
ffprobe -v error -count_frames -select_streams v:0 \
  -show_entries stream=codec_name,width,height,r_frame_rate,nb_read_frames,pix_fmt \
  -of json ../data/renders/sample_a-10s.mp4
# Expected: h264, 1920, 1080, 25/1, 250 frames, yuv420p
```

Timing and scene state are deterministic. The browser test also checks byte-identical captures when returning to the same timestamp. For pixel reproducibility across machines, keep the lockfile, Chromium, OS, and graphics stack fixed; different graphics drivers can rasterize differently. This does not affect the timestamp mapping. Export speed is machine-dependent and may be slower than real time.

`npm run validate:export -- --video PATH` uses FFprobe to decode/count actual video frames, verifies H.264/resolution/25 FPS, checks every frame's presentation timestamp against `i/25`, then checks the manifest's match ID, frame count, timestamps and source frame indices against tracking. For custom input, pass the same `--metadata` and `--tracking` paths used for export. A nonzero aligned interval, for example `--start 2.4 --end 3.4`, must have 25 frames mapping to input IDs 60–84 for `sample_a`. Arbitrary subframe starts retain the existing interpolation behavior; align to source sample times for exact one-to-one sample correspondence. Nanosecond-level roundoff at sample boundaries snaps to the exact source frame. Sparse inputs retain the documented hold behavior.


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

Export mode never starts playback or automatically fetches the sample. Capture `canvas#pitch` after `setTime`. `src/data/` owns contracts, parsing and sampling; `src/playback/` owns export timing and clock formatting; `src/scene/` owns geometry, camera, lighting and actors; `src/main.ts` owns controls and the automation API. Inputs are currently loaded into memory; very long tracking feeds will need windowed loading if browser memory becomes a constraint.

## Checks

```bash
cd renderer
npm run build
npm test
npm run test:browser
cd ..
.venv/bin/python scripts/validate.py
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
