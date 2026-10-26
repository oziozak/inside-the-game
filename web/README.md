# Web player

**Owner:** Person 4

HTML video element + transparent canvas on top. On each animation frame, canvas draws the overlays whose `start <= t < start + duration` for the selected mode and language, where `t` is match time (seconds since kick-off). Vite + TypeScript, no framework.

## Run locally

```bash
cd web
npm install
npm run dev
```

`predev`/`prebuild` copy dev data into ignored `public/sample/`: `data/fake/sample_a/{match_info,tracking,events}` plus director output from `data/generated/sample_a/overlays.json` (the schema-example `data/fake/sample_a/overlays.json` is a stale stand-in — see `../docs` team notes). If `data/renders/sample_a-60s.mp4` + its `.manifest.json` sidecar exist, they're copied in too and used as the video source; otherwise fetching `sample/match.mp4` 404s and the player shows the fetch error.

To (re)produce the dev clip:

```bash
cd renderer
npm ci && npx playwright install chromium   # once
npm run export -- --start 0 --end 60 --camera broadcast --out ../data/renders/sample_a-60s.mp4
```

## How it fits together

- `src/data/loadMatch.ts` — fetches and schema-validates (`ajv`, against `../schemas/*.schema.json` directly) match info, tracking, events, overlays; same frame-ordering/roster invariants the renderer enforces.
- `src/render/camera.ts` — the renderer's camera math (`renderer/src/camera/{presets,tracking}.ts`) ported here, not imported, to keep the two Vite projects independent. Used to project a tracked player's pitch position to canvas pixels so `follow-player` overlays land on the player actually visible in the broadcast video. Must be re-synced by hand if the renderer's camera changes.
- `src/render/theme.ts` — the design system's palette/font tokens as plain values, for canvas drawing. Mirrored as CSS custom properties in `style.css` for the DOM chrome — **keep both in sync by hand**, there's no single source of truth between them.
- `src/render/schedule.ts` — which overlays are active at time `t` for the chosen mode/language; the shared match-clock formatter.
- `src/render/draw.ts` — canvas drawing for the card grammar (team tab, kind label, timecode, source chevron, data cells, pitch ruler, corner print marks, wipe-in reveal) and follow-player tags; returns click-hit regions per overlay.
- `src/ui/evidence.ts` — the "source events" side panel: one section per cited `MatchEvent` (id, type, timecode, from/to player chips, start/end pitch position) plus a derived-values section from the overlay's own `values`, opened by clicking a card.
- `src/main.ts` — wires video/canvas/controls together; `video.currentTime` + the export manifest's `start` gives match time `t`; also builds the scrub bar's event ticks (goals, cards, shots) and minute-ruler labels once the video's duration is known.

## Design

The visual language (floodlight-black ground, team tabs in fixed club colors, mint as the one UI-only accent, Archivo condensed + Martian Mono type) was designed in a separate Claude Design canvas and ported in by hand — there's no shared design-token pipeline between that canvas and this app, so a future revision has to be re-ported the same way. The card grammar is applied generically across all 7 overlay graphics rather than hand-building bespoke layouts for each (no goal-mouth placement diagram for `shot_card`, no dedicated score-banner art for `goal_banner`); `momentum_bar` and `stat_compare` share one dual-team-tab renderer keyed off whichever `_home`/`_away` value pair is present.

## Modes, language, live

Mode (`analyst` / `casual` / `player_focus`) and language are segmented button groups — switching either just changes which overlays pass the filter in `schedule.ts`, no reload. "Live" disables the seek bar and keeps the video playing, simulating a broadcast feed with no scrubbing into the future.

## Known gaps

- Director currently emits 7 of the 10 graphic types; `player_tag`, `speed_badge`, `distance_badge` have no sample data to test against yet.
- Card layout is a simple stack per corner; no collision/priority culling when many overlays land on the same corner at once.
- Bespoke per-type art from the design (goal-mouth shot placement, score banner, head-to-head stat rows) isn't built — see "Design" above.
- No deploy step yet (plan: Azure Static Web Apps).
