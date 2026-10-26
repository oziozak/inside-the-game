import type { Mode, Overlay } from '../types';

/** Overlays visible at match time t for the selected mode/language, highest priority first. */
export function activeOverlays(overlays: Overlay[], t: number, mode: Mode, lang: string): Overlay[] {
  return overlays
    .filter(o => o.mode === mode && o.lang === lang && t >= o.start && t < o.start + o.duration)
    .sort((a, b) => (b.priority ?? 0) - (a.priority ?? 0));
}

/** Language availability is explicit; gaps in the timeline never trigger another language. */
export function languageNotice(overlays: Overlay[], lang: string, mode: Mode): string {
  const name = ({ en: 'English', tr: 'Turkish', es: 'Spanish' } as Record<string, string>)[lang] ?? lang;
  if (!overlays.some(o => o.lang === lang)) return `${name} overlays are not available for this match.`;
  if (!overlays.some(o => o.lang === lang && o.mode === mode)) return `${name} overlays are not available for this mode.`;
  return '';
}

/** Match clock using the shared second-half convention (continuous clock, break cut). Ported from renderer/src/playback/timing.ts. */
export function clock(t: number, periods?: { period: number; start: number }[]): string {
  const second = periods?.find(p => p.period === 2);
  const seconds = Math.floor(second && t >= second.start ? 2700 + t - second.start : t);
  return `${Math.floor(seconds / 60).toString().padStart(2, '0')}:${(seconds % 60).toString().padStart(2, '0')}`;
}
