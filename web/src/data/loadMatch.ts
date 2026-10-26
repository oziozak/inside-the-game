import Ajv2020 from 'ajv/dist/2020.js';
import matchInfoSchema from '../../../schemas/match_info.schema.json';
import trackingSchema from '../../../schemas/tracking.schema.json';
import eventSchema from '../../../schemas/event.schema.json';
import overlaySchema from '../../../schemas/overlay.schema.json';
import type { Match, MatchInfo, Frame, MatchEvent, Overlay, ExportManifest } from '../types';

const ajv = new Ajv2020({ strict: false, allErrors: true });
const validateInfo = ajv.compile(matchInfoSchema);
const validateFrame = ajv.compile(trackingSchema);
const validateEvent = ajv.compile(eventSchema);
const validateOverlay = ajv.compile(overlaySchema);

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) throw new Error(`Failed to fetch ${path}: ${response.status}`);
  return response.json() as Promise<T>;
}

/** Parses JSON Lines tracking into strictly increasing frames; same invariants the renderer enforces. */
function parseTracking(info: MatchInfo, text: string): Frame[] {
  const roster = new Map<number, 'home' | 'away'>();
  for (const team of ['home', 'away'] as const) for (const p of info[team].players) roster.set(p.id, team);
  const frames: Frame[] = [];
  let prev: Frame | undefined;
  for (const [line, raw] of text.split(/\r?\n/).entries()) {
    if (!raw.trim()) continue;
    const frame = JSON.parse(raw) as Frame;
    if (!validateFrame(frame)) throw new Error(`Tracking line ${line + 1}: ${ajv.errorsText(validateFrame.errors)}`);
    if (frame.match_id !== info.match_id) throw new Error(`Tracking line ${line + 1}: match_id does not match metadata`);
    if (prev && (frame.t <= prev.t || frame.frame <= prev.frame)) throw new Error('Tracking must increase strictly in t and frame');
    for (const p of frame.players) {
      if (p.team !== 'referee' && roster.get(p.id) !== p.team) throw new Error(`Unknown player or team mismatch: ${p.id}`);
    }
    frames.push(frame);
    prev = frame;
  }
  if (!frames.length) throw new Error('Tracking is empty');
  return frames;
}

export async function loadMatch(baseUrl: string): Promise<Match> {
  const info = await fetchJson<MatchInfo>(`${baseUrl}/match_info.json`);
  if (!validateInfo(info)) throw new Error(`Match info: ${ajv.errorsText(validateInfo.errors)}`);
  // This Accept header prevents Vite's HTML fallback from hiding an absent optional file.
  const tracking = await fetch(`${baseUrl}/tracking.jsonl`, { headers: { Accept: 'application/x-ndjson' } });
  if (!tracking.ok && tracking.status !== 404) throw new Error(`Failed to fetch tracking: ${tracking.status}`);
  const frames = tracking.status === 404 ? [] : parseTracking(info, await tracking.text());
  return { info, frames };
}

export async function loadEvents(baseUrl: string): Promise<MatchEvent[]> {
  const events = await fetchJson<MatchEvent[]>(`${baseUrl}/events.json`);
  for (const event of events) if (!validateEvent(event)) throw new Error(`Event ${event.id}: ${ajv.errorsText(validateEvent.errors)}`);
  return events;
}

export async function loadOverlays(baseUrl: string): Promise<Overlay[]> {
  const overlays = await fetchJson<Overlay[]>(`${baseUrl}/overlays.json`);
  for (const overlay of overlays) if (!validateOverlay(overlay)) throw new Error(`Overlay ${overlay.id}: ${ajv.errorsText(validateOverlay.errors)}`);
  return overlays;
}

export async function loadManifest(videoUrl: string): Promise<ExportManifest | undefined> {
  const response = await fetch(`${videoUrl}.manifest.json`);
  if (!response.ok) return undefined;
  return response.json() as Promise<ExportManifest>;
}

/** Binary search and identity-based interpolation; hold across gaps and half-time cuts. Ported from renderer/src/data/match.ts for parity. */
export function sample(match: Match, t: number): Frame {
  const { frames, info } = match;
  if (!frames.length) throw new Error('Player projection requires optional tracking.jsonl');
  if (t <= frames[0].t) return frames[0];
  if (t >= frames.at(-1)!.t) return frames.at(-1)!;
  let lo = 0, hi = frames.length - 1;
  while (lo + 1 < hi) { const m = (lo + hi) >>> 1; if (frames[m].t <= t) lo = m; else hi = m; }
  const a = frames[lo], b = frames[hi];
  if (Math.abs(t - a.t) < 1e-9) return a;
  if (Math.abs(t - b.t) < 1e-9) return b;
  const cut = info.periods?.some(p => p.period === 2 && p.start > a.t && p.start <= b.t);
  if (cut || b.t - a.t > 1.5 / info.fps) return a;
  const u = (t - a.t) / (b.t - a.t);
  const mix = (v: number[], w: number[]) => v.map((x, i) => x + (w[i] - x) * u);
  return { ...a, t, ball: mix(a.ball, b.ball), players: a.players.map(p => {
    const other = b.players.find(q => q.id === p.id);
    return other ? { ...p, pos: mix(p.pos, other.pos) } : p;
  }) };
}
