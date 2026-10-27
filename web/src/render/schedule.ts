import type { MatchEvent, Mode, Overlay } from '../types';
import { ui, trMaybe } from '../i18n';

/** Overlays visible at match time t for the selected mode/language, highest priority first. */
export function activeOverlays(overlays: Overlay[], t: number, mode: Mode, lang: string): Overlay[] {
  return overlays
    .filter(o => o.mode === mode && o.lang === lang && t >= o.start && t < o.start + o.duration)
    .sort((a, b) => (b.priority ?? 0) - (a.priority ?? 0));
}

/**
 * True when a player_focus overlay is "about" the given player: it's the overlay's own subject,
 * or a cited event's actor (`from`) or receiver (`to`). An overlay/event with no identified player
 * (null or omitted `player`/`from`/`to`) never matches any real id — it is excluded for everyone.
 */
export function overlayMentionsPlayer(overlay: Overlay, events: Map<string, MatchEvent>, playerId: number): boolean {
  if (!Number.isInteger(playerId) || playerId <= 0) return false;  // a missing id must not equal a missing player
  if (overlay.player === playerId) return true;
  return overlay.event_ids.some(id => {
    const event = events.get(id);
    return !!event && (event.from === playerId || event.to === playerId);
  });
}

/**
 * The followed player's PLAYER-mode cards in `lang` (#96): how many start before the clip's `end`, and how many of
 * those start after t. A count only, never when: the timeline still shows nothing ahead of playback.
 */
export function playerMoments(overlays: Overlay[], events: Map<string, MatchEvent>, playerId: number, lang: string,
                              t: number, end = Infinity): { total: number; ahead: number } {
  const mine = overlays.filter(o => o.mode === 'player_focus' && o.lang === lang && o.start < end && overlayMentionsPlayer(o, events, playerId));
  return { total: mine.length, ahead: mine.filter(o => o.start > t).length };
}

/** The line under the FOLLOWING chip: why the pitch can be quiet, and what is still to come; or that nothing is. */
export function playerHint(moments: { total: number; ahead: number }, name: string, lang: string): string {
  if (!moments.total) return ui(lang, 'player.none', { name });
  const ahead = moments.ahead === 1 ? ui(lang, 'player.ahead1') : moments.ahead ? ui(lang, 'player.aheadN', { n: moments.ahead }) : '';
  return [ui(lang, 'player.hint'), ahead].filter(Boolean).join(' ');
}

/** Language availability is explicit; gaps in the timeline never trigger another language. The notice is in `uiLang`. */
export function languageNotice(overlays: Overlay[], lang: string, mode: Mode, uiLang = 'en'): string {
  const language = trMaybe(uiLang, `language.${lang}`, lang);
  if (!overlays.some(o => o.lang === lang)) return ui(uiLang, 'notice.match', { language });
  if (!overlays.some(o => o.lang === lang && o.mode === mode)) return ui(uiLang, 'notice.mode', { language });
  return '';
}

/** Match clock using the shared second-half convention (continuous clock, break cut). Ported from renderer/src/playback/timing.ts. */
export function clock(t: number, periods?: { period: number; start: number }[]): string {
  const second = periods?.find(p => p.period === 2);
  const seconds = Math.floor(second && t >= second.start ? 2700 + t - second.start : t);
  return `${Math.floor(seconds / 60).toString().padStart(2, '0')}:${(seconds % 60).toString().padStart(2, '0')}`;
}

/** Broadcast minute of match time t: 1-based (18:12 is the 19th minute), the second half counting on from 46'. */
export function matchMinute(t: number, periods?: { period: number; start: number }[]): number {
  const second = periods?.find(p => p.period === 2);
  return second && t >= second.start ? 45 + Math.floor((t - second.start) / 60) + 1 : Math.floor(t / 60) + 1;
}
