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
  report.json                 # optional; the analyst's post-match report (Clip analysis panel)
```

### Several clips in one build (clip picker)

`MATCH` may list several folders, separated by commas. Each is prepared and validated exactly as a single folder, then published in its own subfolder named after the folder (`public/sample/hl1/`), with `public/sample/clips.json` listing them in order. The page then shows a **CLIP** picker under the score; choosing a clip reloads the page on `?clip=<id>`, so a link can open a specific clip. With no or an unknown `?clip=`, the first clip in the list plays. One bad folder fails the whole build and publishes nothing.

```bash
MATCH=data/demo/test2,data/demo/showcase,data/demo/hl1,data/demo/hl2 npm run build
```

- Folder names are the clip ids: lowercase letters, digits, `-` or `_`, unique across the list.
- The picker label is the first line of an optional `title.txt` in the folder (e.g. `Highlight: red card, 51'`), else the folder name.
- A single folder (no comma) keeps the layout above, with no `clips.json` and no picker.
- Switching clips starts the new clip fresh: ANALYST mode and nobody followed in PLAYER mode, since the rosters may differ.

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
- `src/render/draw.ts` — canvas drawing for the card grammar (team tab, kind label, timecode, source chip, data cells, pitch ruler, corner print marks, wipe-in reveal) and follow-player tags; returns click-hit regions per overlay. Card text is never cut silently: a title shrinks to 75% of its size to fit one line, then wraps to 2 lines at that size; body text wraps to 3 lines; each card's height comes from its measured lines (`standardCardLayout` / `dualCardLayout`), so stacked cards and the stats row move down instead of overlapping. An ellipsis appears only if text still does not fit at the smallest size.
- `src/data/onPitch.ts` — `onPitchAt(info, events, t)`: who is on the pitch at `t` (see "Lineups" below).
- `src/ui/lineups.ts` — the pre-clip lineup card, the ON THE PITCH panel and the bottom Lineups section, all drawn from `onPitchAt`.
- `src/ui/evidence.ts` — the "source events" side panel: one section per cited `MatchEvent` (id, type, timecode, from/to player chips, start/end pitch position) plus a derived-values section from the overlay's own `values`, opened by clicking a card.
- `src/main.ts` — wires video/canvas/controls together; `video.currentTime` + the export manifest's `start` gives match time `t`; also builds the scrub bar's event ticks (goals, cards, shots) and minute-ruler labels once the video's duration is known.

## Design

The visual language (floodlight-black ground, team tabs in fixed club colors, mint as the one UI-only accent, Archivo condensed + Martian Mono type) was designed in a separate Claude Design canvas and ported in by hand — there's no shared design-token pipeline between that canvas and this app, so a future revision has to be re-ported the same way. The card grammar is applied generically across all 7 overlay graphics rather than hand-building bespoke layouts for each (no goal-mouth placement diagram for `shot_card`, no dedicated score-banner art for `goal_banner`); `momentum_bar` and `stat_compare` share one dual-team-tab renderer keyed off whichever `_home`/`_away` value pair is present.

## Modes, language, live

Mode (`analyst` / `casual` / `player_focus`) and language (`EN` / `TR` / `ES`) are segmented button groups — switching either just changes which overlays pass the filter in `schedule.ts`, no reload. Language remains selected across seeking, pause/play and mode changes. ES uses only supplied `lang: "es"` overlays; there is no English fallback or automatic agent-text translation. If that language is absent from the match or selected mode, a visible status explains why there are no cards. A normal gap between scheduled cards does not show an unavailable-language warning. Changing language or mode closes old evidence so it does not appear to belong to the new selection. "Live" disables the seek bar and keeps the video playing, simulating a broadcast feed with no scrubbing into the future.

The hero always displays a small "Synthetic match" disclosure alongside its clock. Team formations remain visible.

The page's own words (navigation, console, head-to-head stats, lineups, the analysis and evidence panels, the labels drawn on cards, event types, the *How it works* section) come from one EN/TR/ES table, `src/i18n.ts` (#95). Static markup carries `data-i18n` / `data-i18n-aria` keys; switching language re-words it live, without a reload. Cards are labelled in their own `lang`. Player and team names, and agent-written text, are never translated by the page; the analysis report's fact labels are code-written in English and stay English.

When a cited pass/shot has no identified actor (null, omitted, or out-of-roster ID), the card uses the event's team name/abbreviation and a deterministic description such as "Bosphorus FC pass, 28 m". The small action labels are localized UI text (`pass`/`pas`/`pase`, `shot`/`şut`/`tiro`), not fabricated agent explanations. Actual team names, abbreviations and kits come from match metadata. Follow-player graphics fall back to bottom-left cards if the actor, tracking sample or visible anchor is unavailable; valid projected tags still work. Evidence shows the known team and only genuinely identified player chips, preserving each event's CV/SIM attribution and confidence. Short clips do not need halftime/fulltime recap events. Without an identified team either, the fallback stays generic rather than inventing a club or player.

## Playback time, scores and evidence

The hero clock uses original match time: `manifest.start + video.currentTime`. Score is recomputed on playback and backward/forward seeking from goal events and explicit `score` snapshots at or before that time. It never treats a successful pass or shot as a goal. Include kickoff-to-current event history (including the initial kickoff), or a known score snapshot, in a later-starting bundle to preserve the opening score; if neither is available, the hero displays `—` and "Score unavailable" until an explicit snapshot arrives. No future snapshot is used to fill that gap.

"This clip" statistics cover the clip start through the current playback timestamp, excluding the export's end boundary and all future events. They are labelled "so far" and count the supplied event feed, not assumed complete match truth. Score can therefore include a pre-clip goal while this clip's goal count remains zero. Event ticks and opened evidence also respect playback time.

Every card, including dual-team cards and projected tags, carries a small source chip (#88): `AI · 73%` when its cited events were detected from video (the lowest cited CV confidence; `AI` if none is available), `SIM` for simulator events, `AI · 73% + SIM` when mixed. The full provenance lives in the evidence panel (click a card): the overlay's `CV`, `SIM` or `CV+SIM` label, the CV confidence range rather than an invented aggregate (missing confidence is `n/a`; a `?` marks unresolved evidence or partially unavailable CV confidence), and each event's individual source and CV confidence.

Card headers never show an internal graphic name. A `card_banner` is labeled from the card it cites, **RED CARD** (a second yellow too) or **YELLOW CARD**, with a small card glyph; `stat_compare` is **STATS** and `momentum_bar` **MOMENTUM**; a graphic with no label gets none. The header clock is the card's only time: a `minute` value is not repeated as a data cell (it stays in the evidence panel's derived values). The schema permits omitted confidence; out-of-range or nonnumeric values remain schema errors when loading a bundle, while display helpers safely handle them as unavailable. Source labels do not certify detector accuracy: synthetic test fixtures with `source: cv` are used only for verification, not as reported vision results.

## Lineups: the card before the clip and ON THE PITCH (#88)

`onPitchAt(info, events, t)` (`src/data/onPitch.ts`, pure, tested in `tests/on-pitch.test.mjs`) returns, per team, the players on the pitch, those off (with the minute and `substituted` / `sent_off`, and who replaced them) and the booked ones. It starts from the team sheet's XI and applies every `substitution` (`from` comes on, `to` goes off; the substitute takes their slot), `yellow_card` and `red_card` with `t <=` the given time. Nothing is stored: each call recomputes from the events, so seeking back restores the earlier state. Minutes use the broadcast convention (18:12 is 19'; the second half counts on from 46').

- **Lineup card.** On page load (and so after switching clip, which reloads), a card over the paused video shows both XIs with shirt numbers, names, positions, team colors and formations, and the clip's start minute with the score then (`41' · 3–0`, from `score_at_start`). Anyone already off at the clip start is listed as such. It closes on play, on SKIP, or after 6 s, and never shows while the video plays. It lives inside the video stage, so it never covers the console or scrub bar; at 375 px it fills the stage in a smaller type.
- **LINEUPS button / ON THE PITCH panel.** Opens a left-side panel (evidence stays on the right; it replaces the clip analysis if open) with each team at the current time: the XI with a yellow marker for a booking and `ON 63'` for a substitute, the player count (`10 PLAYERS` in red after a sending-off), and an OFF list (`SENT OFF 37'`, `OFF 63' · 14 A. Name ON`). It updates live while playing and when seeking back. Substitutions and cards come from the simulator (`source: sim`, merged by `scripts/merge_events.py`); the panel does not tag them, the evidence panel keeps the source.
- **Lineups section** (bottom of the page) shows the same state at the current time; names still pick a player to follow in PLAYER mode.

Known limit: a demo folder's `events.json` holds only the clip window's events, so a red card or substitution **before** the clip starts is not in it and the card and panel show that player as on. Footage clips end by 58', so substitutions before a clip don't occur; a red card before a mid-match clip could. Feeding `truth/events.full.json` (simulator data, display only, tagged SIM) would need a separate decision.

## Known gaps

- Director currently emits 7 of the 10 graphic types; `player_tag`, `speed_badge`, `distance_badge` have no sample data to test against yet.
- Bespoke per-type art from the design (goal-mouth shot placement, score banner, head-to-head stat rows) isn't built — see "Design" above.
- No deploy step yet (plan: Azure Static Web Apps).

## Clip analysis (optional report.json)

When the bundle has `report.json` (`python -m agents.analyst`, see `agents/README.md`), preparation copies it and
checks that its `match_id` is the metadata's and that every insight cites events in `events.json`; the browser
validates it against `schemas/report.schema.json`. Without it, nothing changes and no button appears.

The panel (`src/ui/analysis.ts`) is titled CLIP ANALYSIS (#83): the analyst reads only this clip, from what the
vision AI saw, so it gives the clip's window in match minutes (`CLIP 41'–50' · WHAT THE AI SAW`, from the report's
`start` and `end`) and says so in its note. The report covers the whole clip, so a second line says `FULL-CLIP REPORT · FINAL SCORE SHOWN` (#95): opened mid-clip, its headline can carry the final score. It opens when the video ends and from the ANALYSIS button at any time: the headline
and 3-5 insights in the selected language (no fallback to another; it says when the language is missing), each
with its team, topic and how much of the clip it rests on. Hedged insights (coverage below the report's
`coverage_min`) are marked. Clicking an insight opens its evidence: the coverage note, every cited fact with its
value, coverage, frames or events and `tactics.json` path, and the cited events (first 12, then a count) with
their CV/SIM provenance. Agent text is escaped. Changing language re-renders an open panel. A report with no
insight says why: "This clip is too short for a tactical read." under 5 minutes (a highlight falls under the
analyst's sample thresholds), else "Too little of the clip was seen for a tactical insight."

The scoreboard starts from `match_info.score_at_start` when the clip was cut from mid-match (#83), then counts
the clip's goals; without it a clip from kick-off starts at 0-0 and a later one shows "—" until a goal's score.

## Optional AI VIEW feed

An explicit MATCH bundle may also contain `ai_view.mp4` and optionally its original `ai_view.mp4.manifest.json`. Preparation copies only these additional named files and creates a small `feeds.json` availability descriptor. One-feed bundles need no new tools; two-feed preparation requires `ffprobe` on PATH. It probes both video streams and rejects corrupt media, different frame rates, duration differences greater than half a frame, or disagreement with the broadcast manifest duration/FPS. An AI sidecar, when present, must also match the broadcast match ID, source start/end and FPS. No AI sidecar is invented. Matching media metadata cannot establish image content or kickoff alignment: the bundle producer must supply the same match and source interval, preferably with both original sidecars. Supply the full-pitch feed without cropping if using projected browser player tags.

Broadcast remains the default. AI VIEW is exposed only after both feeds load synchronized browser metadata. It preserves clip position, play/pause, speed and audio settings, including repeated switches and seeking. A failed AI feed removes the toggle and returns to broadcast. The page explains: "The AI watches the full-pitch feed." Detection boxes must already be in the supplied AI video; browser cards are a separate presentation layer, not vision input. Overlay scheduling still uses the broadcast manifest's source start, and tracked tags use full-pitch projection only while AI VIEW is selected.

Fixed cards are limited to two per effective position (including bottom-center), highest priority first. Equal priorities retain input order. Follow-player fallbacks compete in bottom-left; genuinely anchored player tags remain independent. Retained cards keep their evidence and provenance.
