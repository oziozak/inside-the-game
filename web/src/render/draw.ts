import type { PerspectiveCamera } from 'three';
import type { Match, MatchEvent, MatchInfo, Overlay, OverlayPosition } from '../types';
import { projectToCanvas } from './camera';
import { sample } from '../data/loadMatch';
import { COLOR, REF_WIDTH } from './theme';
import { clock } from './schedule';
import { sourceChipText } from '../data/provenance';
import { overlayIdentity, type OverlayIdentity } from '../data/identity';
import { ui, trMaybe, type Key } from '../i18n';

export interface HitRegion { overlay: Overlay; x: number; y: number; w: number; h: number }

interface PlayerInfo { name: string; team: 'home' | 'away'; number: number; color: string }

export function buildRoster(info: MatchInfo): Map<number, PlayerInfo> {
  const roster = new Map<number, PlayerInfo>();
  for (const team of ['home', 'away'] as const) {
    for (const p of info[team].players) roster.set(p.id, { name: p.name, team, number: p.number, color: info[team].kit.shirt });
  }
  return roster;
}

const CORNERS: Record<Exclude<OverlayPosition, 'follow-player'>, { x: number; y: number; align: 'left' | 'right' | 'center'; grow: 1 | -1 }> = {
  'top-left': { x: 24, y: 24, align: 'left', grow: 1 },
  'top-right': { x: -24, y: 24, align: 'right', grow: 1 },
  'bottom-left': { x: 24, y: -24, align: 'left', grow: -1 },
  'bottom-right': { x: -24, y: -24, align: 'right', grow: -1 },
  'bottom-center': { x: 0, y: -24, align: 'center', grow: -1 },
};

const KIND = new Set<Overlay['graphic']>(['pass_card', 'shot_card', 'goal_banner', 'insight_text', 'player_tag', 'speed_badge', 'distance_badge', 'stat_compare', 'momentum_bar']);

/** The label key for a card: a card banner is named from the card event it cites (a second yellow is a red). */
function cardKindKey(overlay: Overlay, events: Map<string, MatchEvent>): Key | undefined {
  if (overlay.graphic === 'card_banner') {
    const cited = overlay.event_ids.map(id => events.get(id));
    if (cited.some(e => e?.type === 'red_card')) return 'kind.red_card';
    if (cited.some(e => e?.type === 'yellow_card')) return 'kind.yellow_card';
    return undefined;
  }
  return KIND.has(overlay.graphic) ? `kind.${overlay.graphic}` as Key : undefined;
}

/**
 * The header label viewers see, in the card's own language. An unknown graphic gets no label, never its internal
 * type name.
 */
export function cardKind(overlay: Overlay, events: Map<string, MatchEvent>): string {
  const key = cardKindKey(overlay, events);
  return key ? ui(overlay.lang, key) : '';
}

const CELL_KEYS: [key: string, unit: string][] = [
  ['distance_m', 'm'], ['goal_distance_m', 'm'], ['speed_kmh', 'km/h'], ['difficulty', '/10'], ['xg', ''],
];

function px(ref: number, scale: number): number { return ref * scale; }

function drawCornerMarks(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, s: number) {
  const len = px(12, s), off = px(6, s), lw = Math.max(1, px(2, s));
  ctx.strokeStyle = COLOR.mint; ctx.lineWidth = lw;
  const marks: [number, number, number, number][] = [
    [x - off, y - off, 1, 1], [x + w + off, y - off, -1, 1],
    [x - off, y + h + off, 1, -1], [x + w + off, y + h + off, -1, -1],
  ];
  for (const [cx, cy, dx, dy] of marks) {
    ctx.beginPath(); ctx.moveTo(cx, cy + len * dy); ctx.lineTo(cx, cy); ctx.lineTo(cx + len * dx, cy); ctx.stroke();
  }
}

function teamTab(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, color: string, label: string, s: number) {
  ctx.fillStyle = color; ctx.fillRect(x, y, w, h);
  ctx.fillStyle = '#ffffff'; ctx.font = `700 ${px(12, s)}px ${COLOR_FONT_MONO}`;
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillText(label, x + w / 2, y + h / 2 + px(1, s));
}

const COLOR_FONT_MONO = "'Martian Mono', ui-monospace, Menlo, Consolas, monospace";
const COLOR_FONT_DISPLAY = "'Archivo', 'Arial Narrow', Arial, sans-serif";

function labText(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, s: number, color: string = COLOR.dust) {
  ctx.fillStyle = color; ctx.font = `500 ${px(10, s)}px ${COLOR_FONT_MONO}`;
  ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  ctx.fillText(text.toUpperCase(), x, y);
}

/** Data cells for a standard card. `minute` is left out: the header already shows the clock, and two times read as a clash. */
function cellValueUnits(overlay: Overlay): [key: string, label: string, value: string, unit: string][] {
  const values = overlay.values ?? {};
  const known = CELL_KEYS.filter(([key]) => key in values).slice(0, 3);
  if (known.length) return known.map(([key, unit]) => [key, ui(overlay.lang, `cell.${key}` as Key), String(values[key]), unit]);
  return Object.entries(values).filter(([key]) => key !== 'minute').slice(0, 3)
    .map(([key, v]) => [key, trMaybe(overlay.lang, `cell.${key}`, key.replace(/_/g, ' ').toUpperCase()), String(v), '']);
}

const CHIP_FONT = (s: number) => `700 ${px(9, s)}px ${COLOR_FONT_MONO}`;

/** Width of a source chip (0 without one); set `ctx.font` is clobbered. */
function chipWidth(ctx: CanvasRenderingContext2D, text: string | undefined, s: number): number {
  if (!text) return 0;
  ctx.font = CHIP_FONT(s);
  return ctx.measureText(text).width + px(12, s);
}

/** A small outlined source chip ("AI · 73%" / "SIM"), its left edge at x and vertically centered on cy. */
function drawChip(ctx: CanvasRenderingContext2D, text: string, x: number, cy: number, s: number): number {
  const w = chipWidth(ctx, text, s), h = px(16, s);
  ctx.strokeStyle = COLOR.lineHi; ctx.lineWidth = 1; ctx.strokeRect(x + 0.5, cy - h / 2 + 0.5, w - 1, h - 1);
  ctx.fillStyle = text.startsWith('AI') ? COLOR.mint : COLOR.dust; ctx.font = CHIP_FONT(s);
  ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
  ctx.fillText(text, x + px(6, s), cy + px(1, s));
  return w;
}

/** Pitch-position ruler: only when the cited event carries real start/end meters (pass-like events). */
function citedEventWithPositions(overlay: Overlay, events: Map<string, MatchEvent>): MatchEvent | undefined {
  const event = overlay.event_ids.map(id => events.get(id)).find(e => e?.start && e?.end);
  return event;
}

interface CardLayout { x: number; y: number; w: number; h: number }

/** Text fitted into a box: font size (reference px), the lines to draw, and the baseline-to-baseline step (reference px). */
export interface TextBlock { size: number; lines: string[]; lineHeight: number }

/** Every measurement a standard card needs before drawing, so stacking and drawing agree on its height. */
export interface StandardCardLayout {
  w: number; h: number; headH: number; nameH: number; cellsH: number; rulerH: number;
  title: TextBlock; body: TextBlock; cells: [key: string, label: string, value: string, unit: string][]; ruler?: MatchEvent;
}

/** A title may shrink to this fraction of its size before it wraps. */
const TITLE_MIN_SCALE = 0.75;
const TITLE_SIZE = 34, BODY_SIZE = 14, BODY_MIN = 12;
const TITLE_TOP = 6, BODY_LINE = 18, NAME_BOTTOM = 8;
const titleFont = (size: number, s: number) => `800 ${px(size, s)}px ${COLOR_FONT_DISPLAY}`;
const bodyFont = (size: number, s: number) => `500 ${px(size, s)}px ${COLOR_FONT_DISPLAY}`;

/**
 * Lay out a card's title (one line, shrinking to 75%; else up to 2 lines) and body (up to 3 lines),
 * and size the card from the actual line counts.
 */
export function standardCardLayout(
  ctx: CanvasRenderingContext2D, overlay: Overlay, identity: OverlayIdentity, info: MatchInfo,
  events: Map<string, MatchEvent>, s: number,
): StandardCardLayout {
  const w = px(360, s), textW = w - px(32, s);
  const team = identity.team;
  const titleText = identity.description ? (team ? info[team].name : identity.description) : overlay.title ?? overlay.text;
  const bodyText = identity.description ?? (overlay.title ? overlay.text : '');
  const titleFit = fitTitle(ctx, titleText, textW, size => titleFont(size, s), TITLE_SIZE);
  const bodyFit = fitText(ctx, bodyText, textW, size => bodyFont(size, s), BODY_SIZE, BODY_MIN, 3);
  const title = { size: titleFit.size, lines: titleFit.lines, lineHeight: titleFit.size * 1.05 };
  const body = { size: bodyFit.size, lines: bodyFit.lines, lineHeight: BODY_LINE * bodyFit.size / BODY_SIZE };
  const cells = cellValueUnits(overlay);
  const ruler = overlay.graphic === 'pass_card' ? citedEventWithPositions(overlay, events) : undefined;

  const headH = px(32, s);
  const textBottom = TITLE_TOP + title.size + (title.lines.length - 1) * title.lineHeight + body.lines.length * body.lineHeight;
  const nameH = px(textBottom + NAME_BOTTOM, s);
  const cellsH = cells.length ? px(76, s) : 0;
  const rulerH = ruler ? px(58, s) : 0;
  return { w, h: headH + nameH + cellsH + rulerH, headH, nameH, cellsH, rulerH, title, body, cells, ruler };
}

function drawStandardCard(
  ctx: CanvasRenderingContext2D, overlay: Overlay, identity: OverlayIdentity, info: MatchInfo,
  events: Map<string, MatchEvent>, periods: { period: number; start: number; end: number }[] | undefined,
  layout: StandardCardLayout, x: number, y: number, align: 'left' | 'right' | 'center', s: number, reveal: number,
): CardLayout {
  const { w, h, headH, nameH, cellsH, title, body, cells, ruler } = layout;
  const team = identity.team;
  const tabColor = team ? info[team].kit.shirt : COLOR.mint;
  const tabLabel = team ? info[team].short : ui(overlay.lang, 'cell.info');
  const kindKey = cardKindKey(overlay, events);
  const kind = kindKey ? ui(overlay.lang, kindKey) : '';
  const left = align === 'right' ? x - w : align === 'center' ? x - w / 2 : x;

  ctx.save();
  ctx.beginPath(); ctx.rect(left, y, w * reveal, h); ctx.clip();

  ctx.fillStyle = COLOR.card; ctx.fillRect(left, y, w, h);
  ctx.strokeStyle = 'rgba(237,240,234,0.22)'; ctx.lineWidth = Math.max(1, px(1, s)); ctx.strokeRect(left + 0.5, y + 0.5, w - 1, h - 1);

  // header: team tab · card glyph · kind · timecode · source chip
  teamTab(ctx, left, y, px(56, s), headH, tabColor, tabLabel, s);
  let kindX = left + px(68, s);
  if (kindKey === 'kind.red_card' || kindKey === 'kind.yellow_card') {
    ctx.fillStyle = kindKey === 'kind.red_card' ? COLOR.redCard : COLOR.yellow;
    ctx.fillRect(kindX, y + headH / 2 - px(7, s), px(10, s), px(14, s));
    kindX += px(18, s);
  }
  if (kind) labText(ctx, kind, kindX, y + headH / 2 + px(4, s), s, COLOR.chalk);
  const chip = sourceChipText(overlay, events);
  const chipW = chipWidth(ctx, chip, s);
  if (chip) drawChip(ctx, chip, left + w - chipW - px(10, s), y + headH / 2, s);
  ctx.font = `700 ${px(13, s)}px ${COLOR_FONT_MONO}`; ctx.fillStyle = COLOR.chalk; ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
  ctx.fillText(clock(overlay.start, periods), left + w - chipW - px(chip ? 20 : 12, s), y + headH / 2 + px(1, s));

  // name / title, then body, each line on its own baseline
  ctx.fillStyle = COLOR.chalk; ctx.font = titleFont(title.size, s); ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  let baseline = TITLE_TOP + title.size;
  title.lines.forEach((line, i) => {
    if (i) baseline += title.lineHeight;
    ctx.fillText(line, left + px(16, s), y + headH + px(baseline, s));
  });
  ctx.font = bodyFont(body.size, s); ctx.fillStyle = 'rgba(237,240,234,0.75)';
  body.lines.forEach(line => {
    baseline += body.lineHeight;
    ctx.fillText(line, left + px(16, s), y + headH + px(baseline, s));
  });

  // data cells
  let cy = y + headH + nameH;
  if (cells.length) {
    const cw = w / cells.length;
    ctx.strokeStyle = COLOR.line; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(left, cy); ctx.lineTo(left + w, cy); ctx.stroke();
    cells.forEach(([key, label, value, unit], i) => {
      const cx = left + i * cw;
      ctx.fillStyle = COLOR.cell; ctx.fillRect(cx + (i ? 0.5 : 0), cy, cw - (i ? 0.5 : 0), cellsH);
      labText(ctx, label, cx + px(14, s), cy + px(22, s), s);
      const isDiff = key === 'difficulty';
      ctx.fillStyle = isDiff ? COLOR.mint : COLOR.chalk;
      ctx.font = `700 ${px(36, s)}px ${COLOR_FONT_MONO}`; ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
      ctx.fillText(value, cx + px(14, s), cy + px(58, s));
      if (unit) {
        const vw = ctx.measureText(value).width;
        ctx.font = `600 ${px(11, s)}px ${COLOR_FONT_MONO}`; ctx.fillStyle = COLOR.dust;
        ctx.fillText(unit, cx + px(14, s) + vw + px(4, s), cy + px(58, s));
      }
    });
    cy += cellsH;
  }

  // pitch ruler
  if (ruler?.start && ruler?.end) {
    ctx.strokeStyle = COLOR.line; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(left, cy); ctx.lineTo(left + w, cy); ctx.stroke();
    labText(ctx, ui(overlay.lang, 'cell.pitch'), left + px(16, s), cy + px(20, s), s);
    ctx.font = `600 ${px(11, s)}px ${COLOR_FONT_MONO}`; ctx.fillStyle = COLOR.chalk; ctx.textAlign = 'right';
    ctx.fillText(`${Math.round(ruler.start[0])} → ${Math.round(ruler.end[0])} m`, left + w - px(16, s), cy + px(20, s));
    const trackY = cy + px(44, s), trackX0 = left + px(16, s), trackX1 = left + w - px(16, s), trackW = trackX1 - trackX0;
    const p0 = ruler.start[0] / 105, p1 = ruler.end[0] / 105;
    ctx.strokeStyle = COLOR.lineHi; ctx.lineWidth = Math.max(1, px(2, s));
    ctx.beginPath(); ctx.moveTo(trackX0, trackY); ctx.lineTo(trackX1, trackY); ctx.stroke();
    ctx.fillStyle = COLOR.mint; ctx.fillRect(trackX0 + trackW * Math.min(p0, p1), trackY - px(3, s), trackW * Math.abs(p1 - p0), px(6, s));
    ctx.fillStyle = COLOR.chalk;
    ctx.fillRect(trackX0 + trackW * p0 - px(1, s), trackY - px(8, s), px(2, s), px(16, s));
    ctx.fillRect(trackX0 + trackW * p1 - px(1, s), trackY - px(8, s), px(2, s), px(16, s));
  }

  drawCornerMarks(ctx, left, y, w, h, s);
  ctx.restore();
  return { x: left, y, w, h };
}

/** Dual-team card layout: the team row (fixed height) plus a body strip sized to the wrapped text. */
interface DualCardLayout { w: number; h: number; rowH: number; title: TextBlock; body: TextBlock }

const DUAL_TITLE_SIZE = 10, DUAL_TITLE_BASELINE = 30;
const labelFont = (size: number, s: number) => `500 ${px(size, s)}px ${COLOR_FONT_MONO}`;

/** Lay out a dual card: title in the label slot (one line, shrinking to 75%; else 2 lines), text below the row in up to 3 lines. */
function dualCardLayout(ctx: CanvasRenderingContext2D, overlay: Overlay, s: number): DualCardLayout {
  const w = px(420, s), rowH = px(76, s);
  const labelW = w - px(2 * 56 + 2 * 64 + 8, s), textW = w - px(32, s);
  const titleText = (overlay.title ?? (KIND.has(overlay.graphic) ? ui(overlay.lang, `kind.${overlay.graphic}` as Key) : '')).toUpperCase();
  const titleFit = fitTitle(ctx, titleText, labelW, size => labelFont(size, s), DUAL_TITLE_SIZE);
  // Without a title the label shows the graphic's label (STATS / MOMENTUM), so the text always goes in the body.
  const bodyFit = fitText(ctx, overlay.text, textW, size => bodyFont(size, s), BODY_SIZE, BODY_MIN, 3);
  const title = { size: titleFit.size, lines: titleFit.lines, lineHeight: titleFit.size * 1.2 };
  const body = { size: bodyFit.size, lines: bodyFit.lines, lineHeight: BODY_LINE * bodyFit.size / BODY_SIZE };
  const bodyH = body.lines.length ? px(body.lines.length * body.lineHeight + NAME_BOTTOM, s) : 0;
  return { w, h: rowH + bodyH, rowH, title, body };
}

/** Dual-team row: momentum_bar and stat_compare both flank a shared body with home/away tabs. */
function drawDualCard(
  ctx: CanvasRenderingContext2D, overlay: Overlay, events: Map<string, MatchEvent>, info: MatchInfo,
  layout: DualCardLayout, x: number, y: number, align: 'left' | 'right' | 'center', s: number, reveal: number,
): CardLayout {
  const { w, h, rowH, title, body } = layout;
  const left = align === 'right' ? x - w : align === 'center' ? x - w / 2 : x;
  const values = overlay.values ?? {};
  const homeKey = Object.keys(values).find(k => k.endsWith('_home'));
  const awayKey = Object.keys(values).find(k => k.endsWith('_away'));
  const homeVal = homeKey ? values[homeKey] : undefined;
  const awayVal = awayKey ? values[awayKey] : undefined;

  ctx.save();
  ctx.beginPath(); ctx.rect(left, y, w * reveal, h); ctx.clip();
  ctx.fillStyle = COLOR.card; ctx.fillRect(left, y, w, h);
  ctx.strokeStyle = 'rgba(237,240,234,0.22)'; ctx.strokeRect(left + 0.5, y + 0.5, w - 1, h - 1);

  const tabW = px(56, s);
  teamTab(ctx, left, y, tabW, rowH, info.home.kit.shirt, info.home.short, s);
  teamTab(ctx, left + w - tabW, y, tabW, rowH, info.away.kit.shirt, info.away.short, s);

  const numW = px(64, s);
  ctx.fillStyle = COLOR.chalk; ctx.font = `700 ${px(32, s)}px ${COLOR_FONT_MONO}`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  if (homeVal != null) ctx.fillText(String(homeVal), left + tabW + numW / 2, y + rowH / 2);
  if (awayVal != null) ctx.fillText(String(awayVal), left + w - tabW - numW / 2, y + rowH / 2);

  const bodyX0 = left + tabW + numW, bodyX1 = left + w - tabW - numW, bodyW = bodyX1 - bodyX0;
  // title lines end on the label baseline, so a second line grows upward, clear of the bar
  ctx.fillStyle = COLOR.dust; ctx.font = labelFont(title.size, s); ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  title.lines.forEach((line, i) => {
    ctx.fillText(line, bodyX0 + px(4, s), y + px(DUAL_TITLE_BASELINE - (title.lines.length - 1 - i) * title.lineHeight, s));
  });
  if (homeVal != null && awayVal != null) {
    const total = Number(homeVal) + Number(awayVal) || 1;
    const homeW = bodyW * (Number(homeVal) / total);
    ctx.fillStyle = info.home.kit.shirt; ctx.fillRect(bodyX0, y + px(42, s), homeW, px(8, s));
    ctx.fillStyle = info.away.kit.shirt; ctx.fillRect(bodyX0 + homeW, y + px(42, s), bodyW - homeW, px(8, s));
  }

  const chip = sourceChipText(overlay, events);
  if (chip) drawChip(ctx, chip, bodyX0 + px(4, s), y + px(63, s), s);

  if (body.lines.length) {
    ctx.strokeStyle = COLOR.line; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(left, y + rowH); ctx.lineTo(left + w, y + rowH); ctx.stroke();
    ctx.font = bodyFont(body.size, s); ctx.fillStyle = 'rgba(237,240,234,0.75)';
    body.lines.forEach((line, i) => ctx.fillText(line, left + px(16, s), y + rowH + px((i + 1) * body.lineHeight, s)));
  }

  drawCornerMarks(ctx, left, y, w, h, s);
  ctx.restore();
  return { x: left, y, w, h };
}

function truncate(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string {
  if (ctx.measureText(text).width <= maxWidth) return text;
  let out = text;
  while (out.length > 1 && ctx.measureText(out + '…').width > maxWidth) out = out.slice(0, -1);
  return out + '…';
}

/**
 * Largest font size in [base, min] (1 px steps) at which `text` wraps into at most `maxLines` lines that each fit `maxWidth`.
 * If none does, use `min` and, as a last resort, keep `maxLines` lines with the overflow ellipsized on the last one.
 */
function fitText(
  ctx: CanvasRenderingContext2D, text: string, maxWidth: number, font: (size: number) => string, base: number, min: number, maxLines: number,
): { size: number; lines: string[]; fits: boolean } {
  for (let size = base; size > min - 1; size--) {
    ctx.font = font(Math.max(size, min));
    const lines = wrapText(ctx, text, maxWidth);
    if (lines.length <= maxLines && lines.every(line => ctx.measureText(line).width <= maxWidth)) return { size: Math.max(size, min), lines, fits: true };
  }
  ctx.font = font(min);
  const lines = wrapText(ctx, text, maxWidth);
  const kept = lines.length > maxLines ? [...lines.slice(0, maxLines - 1), lines.slice(maxLines - 1).join(' ')] : lines;
  return { size: min, lines: kept.map(line => truncate(ctx, line, maxWidth)), fits: false };
}

/**
 * A title: one line at the largest size down to TITLE_MIN_SCALE of `base`; else up to 2 lines at that shrunk size,
 * so a longer title is never drawn larger than a shorter one.
 */
function fitTitle(ctx: CanvasRenderingContext2D, text: string, maxWidth: number, font: (size: number) => string, base: number) {
  const min = base * TITLE_MIN_SCALE;
  const oneLine = fitText(ctx, text, maxWidth, font, base, min, 1);
  return oneLine.fits ? oneLine : fitText(ctx, text, maxWidth, font, min, min, 2);
}

function wrapText(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string[] {
  if (!text) return [];
  const words = text.split(' ');
  const lines: string[] = [];
  let line = '';
  for (const word of words) {
    const test = line ? `${line} ${word}` : word;
    if (ctx.measureText(test).width > maxWidth && line) { lines.push(line); line = word; }
    else line = test;
  }
  if (line) lines.push(line);
  return lines;
}

export function drawOverlays(
  ctx: CanvasRenderingContext2D, canvasWidth: number, canvasHeight: number,
  overlays: Overlay[], roster: Map<number, PlayerInfo>, events: Map<string, MatchEvent>,
  match: Match, t: number, camera?: PerspectiveCamera,
): HitRegion[] {
  ctx.clearRect(0, 0, canvasWidth, canvasHeight);
  const s = canvasWidth / REF_WIDTH;
  const regions: HitRegion[] = [];
  const stackCursor: Record<string, number> = {};
  const periods = match.info.periods;

  const fixedCounts: Record<string, number> = {};
  // Stable input order breaks equal-priority ties. Resolve anchors before counting.
  const ordered = overlays.map((overlay, index) => ({ overlay, index }))
    .sort((a, b) => (b.overlay.priority ?? 0) - (a.overlay.priority ?? 0) || a.index - b.index);
  for (const { overlay } of ordered) {
    const identity = overlayIdentity(overlay, events, match.info);
    let point: { x: number; y: number } | undefined;
    if (overlay.position === 'follow-player' && overlay.player != null && identity.player && camera && match.frames.length) {
      const tracked = sample(match, t).players.find(p => p.id === identity.player!.id);
      if (tracked) {
        const projected = projectToCanvas(camera, tracked.pos, canvasWidth, canvasHeight);
        if (Number.isFinite(projected.x) && Number.isFinite(projected.y)
            && projected.x >= 0 && projected.x <= canvasWidth && projected.y >= 0 && projected.y <= canvasHeight) point = projected;
      }
    }
    // Missing actors, frames or visible anchors all use the same stable fixed-card fallback.
    const playerInfo = identity.player ? roster.get(identity.player.id) : undefined;
    const position = overlay.position === 'follow-player' && (!point || !playerInfo) ? 'bottom-left' : overlay.position ?? 'bottom-left';
    const reveal = Math.min(1, Math.max(0, (t - overlay.start) / 0.35));
    const isDual = overlay.graphic === 'momentum_bar' || overlay.graphic === 'stat_compare';

    if (position === 'follow-player' && point && playerInfo) {
      const info = playerInfo;
      const w = px(180, s), h = px(52, s), numW = px(28, s);
      const left = point.x - w / 2, top = point.y - px(100, s);
      ctx.save();
      ctx.strokeStyle = COLOR.mint; ctx.lineWidth = Math.max(1, px(2, s));
      ctx.beginPath(); ctx.moveTo(point.x, point.y); ctx.lineTo(point.x, top + h + px(26, s)); ctx.stroke();
      ctx.fillStyle = COLOR.ink; ctx.fillRect(left, top, w, h);
      ctx.strokeStyle = 'rgba(237,240,234,0.35)'; ctx.lineWidth = 1; ctx.strokeRect(left + 0.5, top + 0.5, w - 1, h - 1);
      ctx.fillStyle = COLOR.mint; ctx.fillRect(left, top, w, Math.max(1, px(2, s)));
      ctx.fillStyle = info.color; ctx.fillRect(left, top, numW, h);
      ctx.fillStyle = '#fff'; ctx.font = `700 ${px(13, s)}px ${COLOR_FONT_MONO}`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText(String(info.number), left + numW / 2, top + h / 2 + px(1, s));
      ctx.fillStyle = COLOR.chalk; ctx.font = `800 ${px(16, s)}px ${COLOR_FONT_DISPLAY}`; ctx.textAlign = 'left';
      ctx.fillText(truncate(ctx, info.name.split(' ').pop() ?? info.name, w - numW - px(20, s)), left + numW + px(10, s), top + px(23, s));
      const chip = sourceChipText(overlay, events);
      if (chip) drawChip(ctx, chip, left + numW + px(10, s), top + px(39, s), s);
      ctx.restore();
      regions.push({ overlay, x: left, y: top, w, h });
      continue;
    }

    if ((fixedCounts[position] ?? 0) >= 2) continue;
    fixedCounts[position] = (fixedCounts[position] ?? 0) + 1;

    const corner = CORNERS[position as Exclude<OverlayPosition, 'follow-player'>] ?? CORNERS['bottom-left'];
    const baseX = corner.align === 'center' ? canvasWidth / 2 : corner.x >= 0 ? px(corner.x, s) : canvasWidth + px(corner.x, s);
    const baseY = corner.y >= 0 ? px(corner.y, s) : canvasHeight + px(corner.y, s);
    const offset = stackCursor[position] ?? 0;

    if (isDual) {
      const measured = dualCardLayout(ctx, overlay, s);
      const topY = corner.grow === 1 ? baseY + offset : baseY - offset - measured.h;
      const layout = drawDualCard(ctx, overlay, events, match.info, measured, baseX, topY, corner.align, s, reveal);
      stackCursor[position] = offset + layout.h + px(10, s);
      regions.push({ overlay, ...layout });
    } else {
      // Measure first so bottom-anchored cards grow upward by their real height.
      const measured = standardCardLayout(ctx, overlay, identity, match.info, events, s);
      const topY = corner.grow === 1 ? baseY + offset : baseY - offset - measured.h;
      const layout = drawStandardCard(ctx, overlay, identity, match.info, events, periods, measured, baseX, topY, corner.align, s, reveal);
      stackCursor[position] = offset + layout.h + px(10, s);
      regions.push({ overlay, ...layout });
    }
  }
  return regions;
}

