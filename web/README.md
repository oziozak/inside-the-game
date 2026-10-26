# Web player

**Owner:** Person 4

HTML video element + transparent canvas on top. On each animation frame, canvas draws the overlays whose `start <= t < start + duration` for the selected mode and language, where `t` is match time (seconds since kick-off). Vite + TypeScript, no framework.

## Run locally

```bash
cd web
npm install
npm run dev
```

`predev`/`prebuild` prepare the selected assets in ignored `public/sample/`. Set `MATCH` to a **repository-root-relative directory**, even though npm runs from `web/`:

```bash
MATCH=data/demo/test1 npm run dev
MATCH=data/demo/dev1 npm run build
npm test
```

These commands expect Ozan's prepared directories to exist; they do not create demo data. Absolute paths, paths outside the repository (including directory symlink escapes), and empty explicit selections are rejected. An invalid explicit `MATCH` never falls back to sample_a.

Each selected folder must contain exactly these required asset names (other files are not copied):

```text
data/demo/test1/
  match_info.json
  events.json                 # merged CV + simulator invisible events
  overlays.json               # generated against these merged event IDs
  match.mp4
  match.mp4.manifest.json      # original sidecar for this exact video
  tracking.jsonl              # optional; needed only for tags anchored over players
  ai_view.mp4                 # optional; synchronized full-pitch detection video
  ai_view.mp4.manifest.json   # optional original AI-feed sidecar, if available
```

Metadata, events, video and sidecar must describe the same match and source interval. Preparation checks metadata/manifest/event match IDs and overlay evidence references. It copies the video and sidecar from the same selected folder together; the producer must supply the correct original sidecar (a video's match identity cannot be inferred from its filename). Keep source files unchanged while preparation runs. Browser schema validation still applies to JSON/tracking. When tracking is supplied, its frame match IDs must match the metadata.

The five-file bundle supports video playback, timed cards, language/mode switching, and evidence. Without tracking, `follow-player` overlays appear as ordinary bottom-left cards; no player positions are invented. With tracking, existing projected tags are retained. Include tracking for the video's interval plus camera history if precise projected placement is needed. Changing `MATCH` requires restarting `npm run dev` (or rebuilding); it is a preparation-time selection, not an in-page picker. Run dev/build preparation sequentially: one checkout has one shared `public/sample/` bundle.

Preparation clears the old generated bundle, copies only the five required files, optional tracking and optional AI-feed assets into staging, validates them, then publishes the complete directory. Missing required assets stop dev/build with file paths in the error; failures leave no previous match available for accidental reuse. Unrelated videos, detector weights, `truth/`, and other files are never copied.

With `MATCH` **unset**, the existing sample_a sources remain:

- `data/fake/sample_a/{match_info.json,tracking.jsonl,events.json}`
- `data/generated/sample_a/overlays.json` (director output, not the stale example overlays)
- `data/renders/sample_a-60s.mp4` and `sample_a-60s.mp4.manifest.json`

All are required. Generate missing director output from the repository root with `python -m agents.run data/fake/sample_a`. Default sample_a uses its existing simulator events for development; an explicit prepared folder supplies its own merged events.

To (re)produce the dev clip:

```bash
cd renderer
npm ci && npx playwright install chromium   # once
npm run export -- --start 0 --end 60 --camera broadcast --out ../data/renders/sample_a-60s.mp4
```

## How it fits together

- `src/data/loadMatch.ts` — fetches and schema-validates (`ajv`, against `../schemas/*.schema.json` directly) match info, optional tracking, events, overlays; supplied tracking must satisfy frame-ordering/roster invariants. A missing tracking file disables projection, while malformed tracking is an error.
- `src/render/camera.ts` — the renderer's camera math (`renderer/src/camera/{presets,tracking}.ts`) ported here, not imported, to keep the two Vite projects independent. Used to project a tracked player's pitch position to canvas pixels so `follow-player` overlays land on the player actually visible in the broadcast video. Must be re-synced by hand if the renderer's camera changes.
- `src/render/theme.ts` — the design system's palette/font tokens as plain values, for canvas drawing. Mirrored as CSS custom properties in `style.css` for the DOM chrome — **keep both in sync by hand**, there's no single source of truth between them.
- `src/render/schedule.ts` — which overlays are active at time `t` for the chosen mode/language; the shared match-clock formatter.
- `src/render/draw.ts` — canvas drawing for the card grammar (team tab, kind label, timecode, source chevron, data cells, pitch ruler, corner print marks, wipe-in reveal) and follow-player tags; returns click-hit regions per overlay. Card text is never cut silently: a title shrinks to 75% of its size to fit one line, then wraps to 2 lines; body text wraps to 3 lines; each card's height comes from its measured lines (`standardCardLayout` / `dualCardLayout`), so stacked cards and the stats row move down instead of overlapping. An ellipsis appears only if text still does not fit at the smallest size.
- `src/ui/evidence.ts` — the "source events" side panel: one section per cited `MatchEvent` (id, type, timecode, from/to player chips, start/end pitch position) plus a derived-values section from the overlay's own `values`, opened by clicking a card.
- `src/main.ts` — wires video/canvas/controls together; `video.currentTime` + the export manifest's `start` gives match time `t`; also builds the scrub bar's event ticks (goals, cards, shots) and minute-ruler labels once the video's duration is known.

## Design

The visual language (floodlight-black ground, team tabs in fixed club colors, mint as the one UI-only accent, Archivo condensed + Martian Mono type) was designed in a separate Claude Design canvas and ported in by hand — there's no shared design-token pipeline between that canvas and this app, so a future revision has to be re-ported the same way. The card grammar is applied generically across all 7 overlay graphics rather than hand-building bespoke layouts for each (no goal-mouth placement diagram for `shot_card`, no dedicated score-banner art for `goal_banner`); `momentum_bar` and `stat_compare` share one dual-team-tab renderer keyed off whichever `_home`/`_away` value pair is present.

## Modes, language, live

Mode (`analyst` / `casual` / `player_focus`) and language (`EN` / `TR` / `ES`) are segmented button groups — switching either just changes which overlays pass the filter in `schedule.ts`, no reload. Language remains selected across seeking, pause/play and mode changes. ES uses only supplied `lang: "es"` overlays; there is no English fallback or automatic agent-text translation. If that language is absent from the match or selected mode, a visible status explains why there are no cards. A normal gap between scheduled cards does not show an unavailable-language warning. Changing language or mode closes old evidence so it does not appear to belong to the new selection. "Live" disables the seek bar and keeps the video playing, simulating a broadcast feed with no scrubbing into the future.

The hero always displays a small "Synthetic match" disclosure alongside its clock. Team formations remain visible.

When a cited pass/shot has no identified actor (null, omitted, or out-of-roster ID), the card uses the event's team name/abbreviation and a deterministic description such as "Bosphorus FC pass, 28 m". The small action labels are localized UI text (`pass`/`pas`/`pase`, `shot`/`şut`/`tiro`), not fabricated agent explanations. Actual team names, abbreviations and kits come from match metadata. Follow-player graphics fall back to bottom-left cards if the actor, tracking sample or visible anchor is unavailable; valid projected tags still work. Evidence shows the known team and only genuinely identified player chips, preserving each event's CV/SIM attribution and confidence. Short clips do not need halftime/fulltime recap events. Without an identified team either, the fallback stays generic rather than inventing a club or player.

## Playback time, scores and evidence

The hero clock uses original match time: `manifest.start + video.currentTime`. Score is recomputed on playback and backward/forward seeking from goal events and explicit `score` snapshots at or before that time. It never treats a successful pass or shot as a goal. Include kickoff-to-current event history (including the initial kickoff), or a known score snapshot, in a later-starting bundle to preserve the opening score; if neither is available, the hero displays `—` and "Score unavailable" until an explicit snapshot arrives. No future snapshot is used to fill that gap.

"This clip" statistics cover the clip start through the current playback timestamp, excluding the export's end boundary and all future events. They are labelled "so far" and count the supplied event feed, not assumed complete match truth. Score can therefore include a pre-clip goal while this clip's goal count remains zero. Event ticks and opened evidence also respect playback time.

Every card, including dual-team cards and projected tags, labels its cited events as `CV`, `SIM`, or `CV+SIM`. Only CV citations show confidence; multiple CV confidences use their range rather than an invented aggregate. Missing confidence is `n/a`; a `?` marks unresolved evidence or partially unavailable CV confidence. The evidence panel shows each event's individual source and CV confidence. The schema permits omitted confidence; out-of-range or nonnumeric values remain schema errors when loading a bundle, while display helpers safely handle them as unavailable. Source labels do not certify detector accuracy: synthetic test fixtures with `source: cv` are used only for verification, not as reported vision results.

## Known gaps

- Director currently emits 7 of the 10 graphic types; `player_tag`, `speed_badge`, `distance_badge` have no sample data to test against yet.
- Bespoke per-type art from the design (goal-mouth shot placement, score banner, head-to-head stat rows) isn't built — see "Design" above.
- No deploy step yet (plan: Azure Static Web Apps).

## Optional AI VIEW feed

An explicit MATCH bundle may also contain `ai_view.mp4` and optionally its original `ai_view.mp4.manifest.json`. Preparation copies only these additional named files and creates a small `feeds.json` availability descriptor. One-feed bundles need no new tools; two-feed preparation requires `ffprobe` on PATH. It probes both video streams and rejects corrupt media, different frame rates, duration differences greater than half a frame, or disagreement with the broadcast manifest duration/FPS. An AI sidecar, when present, must also match the broadcast match ID, source start/end and FPS. No AI sidecar is invented. Matching media metadata cannot establish image content or kickoff alignment: the bundle producer must supply the same match and source interval, preferably with both original sidecars. Supply the full-pitch feed without cropping if using projected browser player tags.

Broadcast remains the default. AI VIEW is exposed only after both feeds load synchronized browser metadata. It preserves clip position, play/pause, speed and audio settings, including repeated switches and seeking. A failed AI feed removes the toggle and returns to broadcast. The page explains: "The AI watches the full-pitch feed." Detection boxes must already be in the supplied AI video; browser cards are a separate presentation layer, not vision input. Overlay scheduling still uses the broadcast manifest's source start, and tracked tags use full-pitch projection only while AI VIEW is selected.

Fixed cards are limited to two per effective position (including bottom-center), highest priority first. Equal priorities retain input order. Follow-player fallbacks compete in bottom-left; genuinely anchored player tags remain independent. Retained cards keep their evidence and provenance.
