import type { MatchEvent, MatchInfo, Overlay } from '../types';

export type Side = 'home' | 'away';
export type PlayerRef = MatchInfo['home']['players'][number] & { team: Side };

/** Null, missing and out-of-roster IDs identify nobody; never substitute another player. */
export function findPlayer(info: MatchInfo, id: number | null | undefined): PlayerRef | undefined {
  if (id == null) return undefined;
  for (const team of ['home', 'away'] as const) {
    const player = info[team].players.find(p => p.id === id);
    if (player) return { ...player, team };
  }
  return undefined;
}

export interface OverlayIdentity {
  player?: PlayerRef;
  team?: Side;
  description?: string;
}

/** Use the cited action, including a shot after its setup pass, for team and actor fallback. */
export function overlayIdentity(overlay: Overlay, events: Map<string, MatchEvent>, info: MatchInfo): OverlayIdentity {
  const cited = overlay.event_ids.map(id => events.get(id)).filter((e): e is MatchEvent => !!e);
  const action = overlay.graphic === 'pass_card' ? 'pass' : overlay.graphic === 'shot_card' ? 'shot' : undefined;
  const event = cited.find(e => e.type === action) ?? cited[0];
  // An explicitly unidentified cited actor must not acquire a stale overlay player ID.
  const actor = event ? findPlayer(info, event.from) : findPlayer(info, overlay.player);
  const player = actor ? findPlayer(info, overlay.player ?? actor.id) : undefined;
  const team = player?.team ?? (event?.team === 'home' || event?.team === 'away' ? event.team : undefined);
  let description;
  if (!player && event && (event.type === 'pass' || event.type === 'shot')) {
    // These are deterministic UI labels, not generated or translated agent explanations.
    const words = ({ en: { pass: 'pass', shot: 'shot', team: 'Team' }, tr: { pass: 'pas', shot: 'şut', team: 'Takım' }, es: { pass: 'pase', shot: 'tiro', team: 'Equipo' } } as const);
    const labels = words[overlay.lang as keyof typeof words] ?? words.en;
    const distance = typeof event.distance_m === 'number' && Number.isFinite(event.distance_m) && event.distance_m >= 0
      ? `, ${Math.round(event.distance_m)} m` : '';
    description = `${team ? info[team].name : labels.team} ${labels[event.type]}${distance}`;
  }
  return { player, team, description };
}
