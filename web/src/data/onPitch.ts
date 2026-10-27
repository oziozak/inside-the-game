import type { MatchEvent, MatchInfo } from '../types';
import { findPlayer, type PlayerRef, type Side } from './identity';
import { matchMinute } from '../render/schedule';

/** A player on the pitch: `on` (broadcast minute) and `replaced` are set for a substitute who came on. */
export interface OnPitchPlayer { player: PlayerRef; booked: boolean; on?: number; replaced?: PlayerRef }

/** A player who left: substituted (with who replaced them) or sent off. */
export interface OffPlayer { player: PlayerRef; minute: number; reason: 'substituted' | 'sent_off'; replacedBy?: PlayerRef }

export interface TeamOnPitch { on: OnPitchPlayer[]; off: OffPlayer[]; booked: PlayerRef[] }

/**
 * Who is on the pitch at match time t: the team sheet's XI (squad-number order) plus every substitution,
 * yellow and red card with `t <=` the given time. Recomputed from the events on every call, so seeking back
 * restores the earlier state. A substitute takes the slot of the player they replace. Events naming players
 * who are not in the team sheet, or a substitution whose outgoing player is not on, change nothing.
 */
export function onPitchAt(info: MatchInfo, events: MatchEvent[], t: number): Record<Side, TeamOnPitch> {
  const teams = {} as Record<Side, TeamOnPitch>;
  for (const side of ['home', 'away'] as const) {
    const xi = info[side].players.filter(p => p.starter).sort((a, b) => a.number - b.number);
    teams[side] = { on: xi.map(p => ({ player: { ...p, team: side }, booked: false })), off: [], booked: [] };
  }
  const relevant = events
    .filter(e => e.t <= t && (e.type === 'substitution' || e.type === 'yellow_card' || e.type === 'red_card'))
    .map((event, index) => ({ event, index }))
    .sort((a, b) => a.event.t - b.event.t || a.index - b.index);
  for (const { event } of relevant) {
    const minute = matchMinute(event.t, info.periods);
    if (event.type === 'substitution') {
      const incoming = findPlayer(info, event.from), outgoing = findPlayer(info, event.to);
      if (!incoming || !outgoing || incoming.team !== outgoing.team) continue;
      const team = teams[outgoing.team];
      const slot = team.on.findIndex(p => p.player.id === outgoing.id);
      if (slot < 0 || team.on.some(p => p.player.id === incoming.id)) continue;
      team.on[slot] = { player: incoming, booked: team.booked.some(p => p.id === incoming.id), on: minute, replaced: outgoing };
      team.off.push({ player: outgoing, minute, reason: 'substituted', replacedBy: incoming });
      continue;
    }
    const player = findPlayer(info, event.from);
    if (!player) continue;
    const team = teams[player.team];
    if (event.type === 'yellow_card') {
      if (!team.booked.some(p => p.id === player.id)) team.booked.push(player);
      const entry = team.on.find(p => p.player.id === player.id);
      if (entry) entry.booked = true;
    } else {
      const slot = team.on.findIndex(p => p.player.id === player.id);
      if (slot < 0) continue;
      team.on.splice(slot, 1);
      team.off.push({ player, minute, reason: 'sent_off' });
    }
  }
  return teams;
}
