import type { MatchEvent, Overlay } from '../types';

/** Confidence is optional in the schema. Invalid values never become an invented percentage. */
export function confidencePercent(value: unknown): string | undefined {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 1
    ? `${Math.round(value * 100)}%` : undefined;
}

export interface Provenance { label: string; confidence?: string }

/** Sources come exclusively from cited events; ranges describe CV values, never SIM confidence. */
export function overlayProvenance(overlay: Overlay, events: Map<string, MatchEvent>): Provenance {
  const cited = [...new Set(overlay.event_ids)].map(id => events.get(id));
  const cv = cited.filter((e): e is MatchEvent => e?.source === 'cv');
  const sim = cited.some(e => e?.source === 'sim');
  const unknown = cited.some(e => !e || (e.source !== 'cv' && e.source !== 'sim'));
  const sources = [cv.length ? 'CV' : '', sim ? 'SIM' : '', unknown ? '?' : ''].filter(Boolean);
  const label = sources.length ? sources.join('+') : 'UNKNOWN';
  if (!cv.length) return { label };
  const values = cv.map(e => e.confidence).filter((c): c is number => confidencePercent(c) !== undefined);
  if (!values.length) return { label, confidence: 'CV n/a' };
  const low = confidencePercent(Math.min(...values))!, high = confidencePercent(Math.max(...values))!;
  const range = low === high ? low : `${low.replace('%', '')}–${high}`;
  return { label, confidence: `CV ${range}${values.length < cv.length ? ' · ?' : ''}` };
}

export function provenanceText(provenance: Provenance): string {
  return [provenance.label, provenance.confidence].filter(Boolean).join(' · ');
}
