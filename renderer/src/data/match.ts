import Ajv2020 from 'ajv/dist/2020.js';
import metadataSchema from '../../../schemas/match_info.schema.json';
import trackingSchema from '../../../schemas/tracking.schema.json';

export interface Player { id: number; team: 'home' | 'away' | 'referee'; pos: number[]; confidence?: number }
export interface Frame { match_id: string; frame: number; t: number; ball: number[]; players: Player[] }
export interface Team {
  name: string; short: string; kit: { shirt: string; shorts: string; goalkeeper?: string };
  players: { id: number; number: number; name: string; pos: string; starter: boolean }[];
}
export interface MatchInfo {
  match_id: string; fps: number; pitch: number[]; origin: 'bottom-left'; home: Team; away: Team;
  periods?: { period: number; start: number; end: number }[];
}
export interface Match { info: MatchInfo; frames: Frame[] }
const ajv = new Ajv2020({ strict: false, allErrors: true });
const validateInfo = ajv.compile(metadataSchema);
const validateFrame = ajv.compile(trackingSchema);

/** Validate the shared schemas plus renderer-specific identity and ordering invariants. */
export function parseMatch(metadata: unknown, jsonl: string): Match {
  if (!validateInfo(metadata)) throw new Error(`Match info: ${ajv.errorsText(validateInfo.errors)}`);
  const info = metadata as unknown as MatchInfo;
  if (info.fps !== 25 || info.pitch[0] !== 105 || info.pitch[1] !== 68) {
    throw new Error('Renderer requires 25 FPS and a 105 × 68 meter pitch');
  }
  const roster = new Map<number, string>();
  for (const team of ['home', 'away'] as const) for (const p of info[team].players) {
    if (roster.has(p.id)) throw new Error(`Duplicate roster ID ${p.id}`);
    roster.set(p.id, team);
  }
  const frames: Frame[] = [];
  for (const [line, text] of jsonl.split(/\r?\n/).entries()) {
    if (!text.trim()) continue;
    let frame: Frame;
    try { frame = JSON.parse(text); } catch { throw new Error(`Invalid JSON on tracking line ${line + 1}`); }
    if (!validateFrame(frame)) throw new Error(`Tracking line ${line + 1}: ${ajv.errorsText(validateFrame.errors)}`);
    const prev = frames.at(-1);
    if (frame.match_id !== info.match_id) throw new Error(`Match ID mismatch on line ${line + 1}`);
    if (prev && (frame.t <= prev.t || frame.frame <= prev.frame)) throw new Error('Tracking must increase strictly in t and frame');
    const ids = new Set<number>();
    for (const p of frame.players) {
      if (ids.has(p.id)) throw new Error(`Duplicate tracked player ${p.id}`);
      ids.add(p.id);
      if (p.team !== 'referee' && roster.get(p.id) !== p.team) throw new Error(`Unknown player or team mismatch: ${p.id}`);
    }
    frames.push(frame);
  }
  if (!frames.length) throw new Error('Tracking is empty');
  return { info, frames };
}

/** Shared pitch coordinates (x,y,height) -> Three.js (x,up,z); preserve handedness. */
export function world([x, y, height = 0]: number[]): [number, number, number] { return [x - 52.5, height, 34 - y]; }

/** Binary search and identity-based interpolation; hold across gaps and half-time cuts. */
export function sample(match: Match, t: number): Frame {
  if (!Number.isFinite(t)) throw new Error('Time must be finite');
  const { frames, info } = match;
  if (t <= frames[0].t) return frames[0];
  if (t >= frames.at(-1)!.t) return frames.at(-1)!;
  let lo = 0, hi = frames.length - 1;
  while (lo + 1 < hi) { const m = (lo + hi) >>> 1; if (frames[m].t <= t) lo = m; else hi = m; }
  const a = frames[lo], b = frames[hi];
  // Decimal tracking times and start + i/25 may differ by floating-point roundoff.
  // Snap only within a nanosecond so an aligned export retains the exact source identity.
  if (Math.abs(t - a.t) < 1e-9) return a;
  if (Math.abs(t - b.t) < 1e-9) return b;
  const cut = info.periods?.some(p => p.period === 2 && p.start > a.t && p.start <= b.t);
  if (cut || b.t - a.t > 1.5 / info.fps) return a;
  const u = (t - a.t) / (b.t - a.t);
  const mix = (v: number[], w: number[]) => v.map((x, i) => x + (w[i] - x) * u);
  const next = new Map(b.players.map(p => [p.id, p]));
  return { ...a, t, ball: mix(a.ball, b.ball), players: a.players.map(p => {
    const q = next.get(p.id); return q && q.team === p.team ? { ...p, pos: mix(p.pos, q.pos) } : p;
  }) };
}
