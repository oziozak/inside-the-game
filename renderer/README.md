# 3D broadcast renderer

Three.js playback and deterministic 25 FPS H.264 export from shared `match_info.json` and `tracking.jsonl`. The renderer reads no events, overlays or ground truth. Teams, kit colors, goalkeeper colors and optional shirt numbers come from metadata.

## Installation and local execution

Requires Node 22.12+, npm, a WebGL 2 browser, and FFmpeg/FFprobe with libx264 for exports.

```bash
cd renderer
npm ci
npx playwright install chromium
npm run dev
```

Open Vite's printed URL. The first 60 seconds of `sample_a` load automatically. Build/dev preparation copies only metadata and tracking into ignored `public/sample/`. Use the file pickers to load another match; files stay in the browser. Invalid data leaves the existing match intact. Playback supports seeking and speed selection. The clock and rich presentation are optional.

## Cameras and CV configuration

| Setting | Behavior |
| --- | --- |
| `cv_full_pitch` (default) | Fixed 43° elevated view at `(0,75,83)`, with aspect-aware zoom fitting pitch, goals and run-off. Suitable for calibration. |
| `broadcast` | 38° elevated sideline view, 34 m high and 44 m behind the filtered target; a slight infield bias near either goal reduces off-pitch margins. Distant players can be cropped. |
| Player / ball scale | Uniform geometry scales from 0.25 to 5, default 1. Anchors and ball center/height never move. |
| CV visibility | Unlit yellow ball with dark patches; best-effort 5 px diameter, automatic enlargement capped at 2×. Explicit ball scale remains a lower bound. |
| Shirt numbers | Off by default; metadata-derived decals on shirt backs, independent of CV visibility. CLI `--jersey-numbers`. |
| Player motion | Off by default for clean CV compatibility. Enable with the Player motion checkbox or CLI `--rich --animate-players`; `--no-animation` remains supported. |
| Rich presentation | Off by default; CLI `--rich` adds four-sided stands, instanced crowd/seating, floodlight structures, generic boards, matte mowing colors, stylized players and soft contact shadows. |

Broadcast filtering uses 0.8 seconds of causal history and resets at period boundaries. Pose and camera state depend on absolute simulation time, with no accumulated playback state or randomness. Player roots stay at tracked foot anchors; only limb geometry rotates. Stationary/missing/gapped/relocated motion samples use neutral poses. The ball's physical radius is 0.11 m; players are about 1.88 m tall. Scaling changes apparent dimensions and must be recorded for CV comparisons. Enlarged low balls can intersect grass because their centers remain exact.

Clean CV presentation is `setRich(false)` with `cv_full_pitch`; it retains the existing pitch, player models, lighting and camera. Rich mode uses separate lightweight player bodies (shirts, shorts, socks, boots, head/hair) under the same tracked roots. Walking/running cycles blend by tracked speed without clock-dependent phase jumps. Crowd cards and bench sections are instanced and static. Generic boards contain no real sponsors. Whole-pitch shadow maps and fine grass noise were omitted after measured export regressions; procedural soft contact shadows keep players grounded. No kicking/event inference is added.

Numbers use contrasting white/dark text on shirt surfaces, never floating player IDs. They are often only a few pixels tall, can face away, and are **not established as OCR-readable**. Leave them off for annotation-free CV footage. Clean exports contain no clock, controls or event cues. Occlusion/depth testing remain enabled; the CV diameter target does not guarantee visible segmented pixels.

## Video export

Run npm commands from `renderer/`. Output paths must be fresh; existing videos/manifests/metrics are refused.

```bash
npm run export -- --start 0 --end 10 --out ../data/renders/sample-a.mp4
npm run export -- --start 0 --end 10 --camera cv_full_pitch \
  --cv_visibility --player-scale 1.5 --ball-scale 3 --out ../data/renders/sample-cv.mp4
npm run validate:export -- --video ../data/renders/sample-cv.mp4
```

Defaults: 1920×1080, 25 FPS, H.264/libx264, CRF 18, yuv420p. Width/height must be even (64–7680). `--start` defaults to the first sample; `--end` defaults to 10 seconds. Select later intervals explicitly. Frames use `[start,end)`, at `start + i/25`; fractional durations round up to a whole frame. Align starts to tracking timestamps for one-to-one source correspondence. Sparse gaps and period cuts hold the preceding sample rather than blending teleports.

Each MP4 has `.manifest.json` (settings, requested times, original input frame IDs) and `.metrics.json` (scan/load/render time and Node-only peak RSS). `validate:export` decodes the video with FFprobe and checks every frame's count, PTS and input reference. For custom inputs, supply the same `--metadata` and `--tracking` to export and validation.

The exporter streams and validates the entire JSONL source, retaining only the selected interval plus one second of history and outside interpolation neighbors. Scan work is O(total frames), retained memory O(selected frames). A whole-match selection still buffers a whole match; prefer short intervals. Interactive file loading also buffers the whole file. The validator buffers FFprobe frame metadata (64 MiB cap). Interrupted exports may leave a partial MP4; retry at a new path.

## Genuine simulator integration

Generate genuine tracking using the simulator's existing CLI from the repository root:

```bash
python -m simulator --home bosphorus --away thames --seed 7 --out data/generated/renderer-m007
cd renderer
npm run test:simulator
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

`test:simulator` checks every output timestamp for 22 actors, exact anchors/ball height, kits and metadata numbers, plus reordered IDs and deterministic seeking. It extracts a wider reference into ignored `data/generated/renderer-integration-trimmed/`. To verify encoded equivalence, export that reference with identical settings and `--out ../data/renders/simulator-broadcast-trimmed.mp4`, then run `npm run validate:simulator`. Do not regenerate the reference with the simulator's `--start` flag: it can create different movement trajectories.

## Calibration and validation

The separate [calibration fixture](fixtures/calibration/README.md) contains 300 samples over 12 seconds with a controlled pass/carry/shot. Its ground-truth events are for offline scoring only and never reach the renderer. `npm run generate:calibration` regenerates it deterministically.

```bash
npm test
npm run build
npm run test:browser
npm run test:calibration
npm run test:simulator
npm run test:presentation
npm run test:server
cd ..
python scripts/validate.py
python scripts/validate.py renderer/fixtures/calibration
```

For calibration export, use `--metadata fixtures/calibration/match_info.json --tracking fixtures/calibration/tracking.jsonl --start 0 --end 12 --cv_visibility --ball-scale 2`. Export each preset to `calibration-full-pitch.mp4` / `calibration-broadcast.mp4`, repeat full-pitch to `repeat/calibration-full-pitch.mp4`, then run `npm run validate:calibration`. It validates timing/manifests and every decoded repeated frame with FFmpeg `framemd5`.

Browser checks require localhost binding and Chromium. Artifacts default to ignored `data/renders/`; `RENDERER_TEST_ARTIFACT_DIR` overrides the root for browser checks, comparison validators and benchmarks. Video filenames in comparison validators follow the conventions above. Keep input pairs immutable during runs. Repeat strict screenshot checks with `npm run test:browser:repeat -- --runs 5 --concurrency 1`, or `--runs 12 --concurrency 3 --load` for contention testing. No retries or pixel tolerances are applied.

`npm run benchmark:capture -- --end 2505 --runs 3 --rich --synchronized-only` measures synchronized rich capture; omit `--synchronized-only` to compare both capture variants sequentially on the same seed-7 interval/settings, alternates order, and saves environment/timing JSON. It records CPU render submission, capture/encode time, Node RSS, browser heap and render counters. The unsynchronized variant is benchmark-only; production always waits for WebGL completion and a paint boundary. Run benchmarks alone. `benchmark:input -- --mode interval` / `--mode whole` compares Node input memory only, excluding Chromium/FFmpeg.

## Integration API and limitations

Load `/?export=1` and wait for `window.broadcast`:

```js
window.broadcast.load(metadataObject, trackingJsonlText);
window.broadcast.resize(1920, 1080);
window.broadcast.setRich(false);
window.broadcast.configure({ camera: 'broadcast', cvVisibility: true,
  playerScale: 1, ballScale: 2, jerseyNumbers: false, animatePlayers: true });
window.broadcast.setTime(2503); // synchronous render; t, inputFrame, inputTime, playerIds
window.broadcast.inspect(); // scene state only; never drawn into footage
```

Metadata/tracking use the shared schemas unchanged. IDs identify actors independent of array order. Coordinates map to `(x - 52.5, height, 34 - y)` without clamping or team flipping. Supported input is 25 FPS on a 105×68 m pitch. Export mode neither advances automatically nor fetches sample data.

Timing and scene states are deterministic; bitwise pixels across different OS/browser/graphics stacks are not guaranteed. Preserve the lockfile and browser stack for pixel comparisons. Rendering can be slower than real time. Broadcast framing has causal lag and cannot guarantee every player/goal remains visible. Motion is illustrative, not biomechanical or possession-aware, with neutral facing when stationary. Crowd cards are static cutouts, contact shadows do not model full light occlusion, and rich-mode colors intentionally differ from the clean CV materials. Calibration is a two-player baseline with no keeper/tackles, motion blur, or net physics. UI file loading and long export selections retain their memory limitations above.

## Production and Docker

```bash
npm run build
PORT=8080 HOST=127.0.0.1 npm start
# From another terminal: curl --fail http://127.0.0.1:8080/healthz
```

`PORT` defaults to 8080 and `HOST` to 0.0.0.0. The dependency-free server serves only `dist/`, supports GET/HEAD and exposes `/healthz`. `test:server` checks the production app, assets, health endpoint and configured port with local Chromium.

From the repository root with Docker running:

```bash
docker build -f renderer/Dockerfile -t inside-game-renderer:local .
docker run --rm -p 8080:8080 -e PORT=8080 inside-game-renderer:local
curl --fail http://127.0.0.1:8080/healthz
```

The multi-stage image runs as non-root and contains Node, built assets and the server. Its build context is the repository root; `Dockerfile.dockerignore` excludes `.env` files, dependencies and generated outputs. Do not place credentials in frontend code or public assets. Container execution requires a working Docker daemon; Azure deployment requires explicit approval. This deploys the renderer UI; Playwright/FFmpeg batch export remains local.

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
az acr config authentication-as-arm show --registry "$ACR"
az acr build --registry "$ACR" --image renderer:phase3 --file renderer/Dockerfile .
az containerapp env create --name inside-game-env --resource-group "$RG" --location "$LOCATION"

az identity create --name renderer-pull --resource-group "$RG"
PULL_ID=$(az identity show --name renderer-pull --resource-group "$RG" --query id -o tsv)
PULL_PRINCIPAL=$(az identity show --name renderer-pull --resource-group "$RG" --query principalId -o tsv)
ACR_ID=$(az acr show --name "$ACR" --query id -o tsv)
ACR_HOST=$(az acr show --name "$ACR" --query loginServer -o tsv)
az role assignment create --assignee-object-id "$PULL_PRINCIPAL" \
  --assignee-principal-type ServicePrincipal --role AcrPull --scope "$ACR_ID"

az containerapp create --name inside-game-renderer --resource-group "$RG" \
  --environment inside-game-env --image "$ACR_HOST/renderer:phase3" \
  --user-assigned "$PULL_ID" --registry-identity "$PULL_ID" --registry-server "$ACR_HOST" \
  --ingress external --target-port 8080 --cpu 0.5 --memory 1Gi \
  --min-replicas 0 --max-replicas 1 --env-vars PORT=8080 HOST=0.0.0.0
az containerapp show --name inside-game-renderer --resource-group "$RG" \
  --query properties.configuration.ingress.fqdn -o tsv
```

Managed-identity pulls require ARM audience tokens to be enabled on ACR; if the check reports disabled, enable them with `az acr config authentication-as-arm update --registry "$ACR" --status enabled` after deployment approval.

Allow role-assignment propagation before app creation if the registry initially denies image pulls. Open the returned hostname over HTTPS and check `/healthz`. In Container Apps, configure HTTP readiness/liveness probes at `/healthz`, port 8080, if explicit HTTP probes are desired; Docker HEALTHCHECK alone does not configure Azure's probes. Local file choices stay in the viewer's browser. ACR image pulls use managed identity rather than registry passwords.

References: [Container Apps CLI](https://learn.microsoft.com/en-us/cli/azure/containerapp?view=azure-cli-latest), [health probes](https://learn.microsoft.com/en-us/azure/container-apps/health-probes), [managed identity image pulls](https://learn.microsoft.com/en-us/azure/container-apps/managed-identity-image-pull), [Three.js renderer](https://threejs.org/docs/pages/WebGLRenderer), [Playwright capture](https://playwright.dev/docs/screenshots).
