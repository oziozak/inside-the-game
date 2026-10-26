import type { PerspectiveCamera } from 'three';
import type { Match, MatchEvent, MatchInfo, Overlay, OverlayPosition } from '../types';
import { projectToCanvas } from './camera';
import { sample } from '../data/loadMatch';
import { COLOR, REF_WIDTH } from './theme';
import { clock } from './schedule';
import { overlayProvenance, provenanceText } from '../data/provenance';
import { overlayIdentity, type OverlayIdentity } from '../data/identity';

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

const KIND: Partial<Record<Overlay['graphic'], string>> = {
  pass_card: 'PASS', shot_card: 'SHOT', goal_banner: 'GOAL', insight_text: 'INSIGHT',
  player_tag: 'PLAYER', speed_badge: 'SPEED', distance_badge: 'DISTANCE',
};

const CELL_KEYS: [key: string, label: string, unit: string][] = [
  ['distance_m', 'DISTANCE', 'm'],
  ['goal_distance_m', 'RANGE', 'm'],
  ['speed_kmh', 'BALL SPEED', 'km/h'],
  ['difficulty', 'DIFFICULTY', '/10'],
  ['xg', 'XG', ''],
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

function cellValueUnits(overlay: Overlay): [string, string, string][] {
  const values = overlay.values ?? {};
  const known = CELL_KEYS.filter(([key]) => key in values).slice(0, 3);
  if (known.length) return known.map(([key, label, unit]) => [label, String(values[key]), unit]);
  return Object.entries(values).slice(0, 3).map(([key, v]) => [key.replace(/_/g, ' ').toUpperCase(), String(v), '']);
}

/** Pitch-position ruler: only when the cited event carries real start/end meters (pass-like events). */
function citedEventWithPositions(overlay: Overlay, events: Map<string, MatchEvent>): MatchEvent | undefined {
  const event = overlay.event_ids.map(id => events.get(id)).find(e => e?.start && e?.end);
  return event;
}

interface CardLayout { x: number; y: number; w: number; h: number }

function drawStandardCard(
  ctx: CanvasRenderingContext2D, overlay: Overlay, identity: OverlayIdentity, info: MatchInfo,
  events: Map<string, MatchEvent>, periods: { period: number; start: number; end: number }[] | undefined,
  x: number, y: number, align: 'left' | 'right' | 'center', s: number, reveal: number,
): CardLayout {
  const w = px(360, s);
  const team = identity.team;
  const tabColor = team ? info[team].kit.shirt : COLOR.mint;
  const tabLabel = team ? info[team].short : 'INFO';
  const kind = KIND[overlay.graphic] ?? overlay.graphic.replace(/_/g, ' ').toUpperCase();
  const cells = cellValueUnits(overlay);
  const ruler = overlay.graphic === 'pass_card' ? citedEventWithPositions(overlay, events) : undefined;

  const headH = px(32, s);
  const nameH = px(62, s);
  const cellsH = cells.length ? px(76, s) : 0;
  const rulerH = ruler ? px(58, s) : 0;
  const h = headH + nameH + cellsH + rulerH;
  const left = align === 'right' ? x - w : align === 'center' ? x - w / 2 : x;

  ctx.save();
  ctx.beginPath(); ctx.rect(left, y, w * reveal, h); ctx.clip();

  ctx.fillStyle = COLOR.card; ctx.fillRect(left, y, w, h);
  ctx.strokeStyle = 'rgba(237,240,234,0.22)'; ctx.lineWidth = Math.max(1, px(1, s)); ctx.strokeRect(left + 0.5, y + 0.5, w - 1, h - 1);

  // header: team tab · kind · timecode · source chevron
  teamTab(ctx, left, y, team || overlay.player == null ? px(56, s) : px(56, s), headH, tabColor, tabLabel, s);
  labText(ctx, kind, left + px(68, s), y + headH / 2 + px(4, s), s, COLOR.chalk);
  const tcText = clock(overlay.start, periods);
  ctx.font = `700 ${px(13, s)}px ${COLOR_FONT_MONO}`; ctx.fillStyle = COLOR.chalk; ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
  const sourceW = px(124, s);
  ctx.fillText(tcText, left + w - sourceW - px(12, s), y + headH / 2 + px(1, s));
  if (sourceW) {
    ctx.strokeStyle = COLOR.line; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(left + w - sourceW, y); ctx.lineTo(left + w - sourceW, y + headH); ctx.stroke();
    const source = overlayProvenance(overlay, events);
    const sourceX = left + w - sourceW + px(8, s), sourceTextW = sourceW - px(28, s);
    ctx.font = `600 ${px(9, s)}px ${COLOR_FONT_MONO}`; ctx.fillStyle = COLOR.chalk; ctx.textAlign = 'left';
    ctx.fillText(truncate(ctx, `SOURCE ${source.label}`, sourceTextW), sourceX, y + px(10, s));
    ctx.fillStyle = COLOR.dust;
    ctx.fillText(truncate(ctx, source.confidence ?? (source.label === 'SIM' ? 'SIMULATOR' : 'EVENT EVIDENCE'), sourceTextW), sourceX, y + px(23, s));
    ctx.fillStyle = COLOR.mint;
    const ax = left + w - px(16, s), ay = y + headH / 2;
    ctx.beginPath(); ctx.moveTo(ax, ay - px(5, s)); ctx.lineTo(ax + px(4, s), ay); ctx.lineTo(ax, ay + px(5, s)); ctx.fill();
  }

  // name / title
  ctx.fillStyle = COLOR.chalk; ctx.font = `800 ${px(34, s)}px ${COLOR_FONT_DISPLAY}`; ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
  const title = identity.description ? (team ? info[team].name : identity.description) : overlay.title ?? overlay.text;
  ctx.fillText(truncate(ctx, title, w - px(32, s)), left + px(16, s), y + headH + px(40, s));
  ctx.font = `500 ${px(14, s)}px ${COLOR_FONT_DISPLAY}`; ctx.fillStyle = 'rgba(237,240,234,0.75)';
  wrapText(ctx, identity.description ?? (overlay.title ? overlay.text : ''), w - px(32, s)).slice(0, 1).forEach(line => {
    ctx.fillText(truncate(ctx, line, w - px(32, s)), left + px(16, s), y + headH + px(58, s));
  });

  // data cells
  let cy = y + headH + nameH;
  if (cells.length) {
    const cw = w / cells.length;
    ctx.strokeStyle = COLOR.line; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(left, cy); ctx.lineTo(left + w, cy); ctx.stroke();
    cells.forEach(([label, value, unit], i) => {
      const cx = left + i * cw;
      ctx.fillStyle = COLOR.cell; ctx.fillRect(cx + (i ? 0.5 : 0), cy, cw - (i ? 0.5 : 0), cellsH);
      labText(ctx, label, cx + px(14, s), cy + px(22, s), s);
      const isDiff = label === 'DIFFICULTY';
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
    labText(ctx, 'PITCH POSITION', left + px(16, s), cy + px(20, s), s);
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

/** Dual-team row: momentum_bar and stat_compare both flank a shared body with home/away tabs. */
function drawDualCard(
  ctx: CanvasRenderingContext2D, overlay: Overlay, events: Map<string, MatchEvent>, info: MatchInfo, x: number, y: number, align: 'left' | 'right' | 'center', s: number, reveal: number,
): CardLayout {
  const w = px(420, s), h = px(76, s);
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
  teamTab(ctx, left, y, tabW, h, info.home.kit.shirt, info.home.short, s);
  teamTab(ctx, left + w - tabW, y, tabW, h, info.away.kit.shirt, info.away.short, s);

  const numW = px(64, s);
  ctx.fillStyle = COLOR.chalk; ctx.font = `700 ${px(32, s)}px ${COLOR_FONT_MONO}`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  if (homeVal != null) ctx.fillText(String(homeVal), left + tabW + numW / 2, y + h / 2);
  if (awayVal != null) ctx.fillText(String(awayVal), left + w - tabW - numW / 2, y + h / 2);

  const bodyX0 = left + tabW + numW, bodyX1 = left + w - tabW - numW, bodyW = bodyX1 - bodyX0;
  ctx.font = `500 ${px(10, s)}px ${COLOR_FONT_MONO}`;
  labText(ctx, truncate(ctx, overlay.title ?? overlay.graphic, bodyW - px(8, s)), bodyX0 + px(4, s), y + px(30, s), s);
  if (homeVal != null && awayVal != null) {
    const total = Number(homeVal) + Number(awayVal) || 1;
    const homeW = bodyW * (Number(homeVal) / total);
    ctx.fillStyle = info.home.kit.shirt; ctx.fillRect(bodyX0, y + px(42, s), homeW, px(8, s));
    ctx.fillStyle = info.away.kit.shirt; ctx.fillRect(bodyX0 + homeW, y + px(42, s), bodyW - homeW, px(8, s));
  }

  ctx.font = `500 ${px(9, s)}px ${COLOR_FONT_MONO}`; ctx.fillStyle = COLOR.dust; ctx.textAlign = 'left';
  ctx.fillText(truncate(ctx, `SOURCE ${provenanceText(overlayProvenance(overlay, events))}`, bodyW - px(8, s)), bodyX0 + px(4, s), y + px(67, s));

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

  for (const overlay of overlays) {
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
    const position = overlay.position === 'follow-player' && !point ? 'bottom-left' : overlay.position ?? 'bottom-left';
    const reveal = Math.min(1, Math.max(0, (t - overlay.start) / 0.35));
    const isDual = overlay.graphic === 'momentum_bar' || overlay.graphic === 'stat_compare';

    const playerInfo = identity.player ? roster.get(identity.player.id) : undefined;
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
      ctx.font = `500 ${px(8, s)}px ${COLOR_FONT_MONO}`; ctx.fillStyle = COLOR.dust;
      ctx.fillText(truncate(ctx, `SOURCE ${provenanceText(overlayProvenance(overlay, events))}`, w - numW - px(16, s)), left + numW + px(8, s), top + px(43, s));
      ctx.restore();
      regions.push({ overlay, x: left, y: top, w, h });
      continue;
    }

    const corner = CORNERS[position as Exclude<OverlayPosition, 'follow-player'>] ?? CORNERS['bottom-left'];
    const baseX = corner.align === 'center' ? canvasWidth / 2 : corner.x >= 0 ? px(corner.x, s) : canvasWidth + px(corner.x, s);
    const baseY = corner.y >= 0 ? px(corner.y, s) : canvasHeight + px(corner.y, s);
    const offset = stackCursor[position] ?? 0;

    if (isDual) {
      const h = px(76, s);
      const topY = corner.grow === 1 ? baseY + offset : baseY - offset - h;
      const layout = drawDualCard(ctx, overlay, events, match.info, baseX, topY, corner.align, s, reveal);
      stackCursor[position] = offset + layout.h + px(10, s);
      regions.push({ overlay, ...layout });
    } else {
      // Pre-measure height with a throwaway pass so top-anchored growth can be computed without double-drawing visuals.
      const probe = measureStandardCard(ctx, overlay, events, s);
      const topY = corner.grow === 1 ? baseY + offset : baseY - offset - probe.h;
      const layout = drawStandardCard(ctx, overlay, identity, match.info, events, periods, baseX, topY, corner.align, s, reveal);
      stackCursor[position] = offset + layout.h + px(10, s);
      regions.push({ overlay, ...layout });
    }
  }
  return regions;
}

function measureStandardCard(ctx: CanvasRenderingContext2D, overlay: Overlay, events: Map<string, MatchEvent>, s: number): { h: number } {
  const headH = px(32, s), nameH = px(62, s);
  const cells = cellValueUnits(overlay);
  const cellsH = cells.length ? px(76, s) : 0;
  const ruler = overlay.graphic === 'pass_card' ? citedEventWithPositions(overlay, events) : undefined;
  const rulerH = ruler ? px(58, s) : 0;
  return { h: headH + nameH + cellsH + rulerH };
}
