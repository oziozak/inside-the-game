import type { MatchEvent, MatchInfo } from '../types';
import type { Side } from '../data/identity';
import { onPitchAt, type OffPlayer, type OnPitchPlayer, type TeamOnPitch } from '../data/onPitch';
import { scoreAt } from '../data/summary';
import { matchMinute } from '../render/schedule';

const esc = (value: unknown) => String(value).replace(/[&<>"']/g, c => `&#${c.charCodeAt(0)};`);

function teamHead(info: MatchInfo, side: Side, team: TeamOnPitch): string {
  const short = team.on.length < 11;
  return `<div class="lineup-head">
    <span class="chip ${side}" style="background:${info[side].kit.shirt}">${esc(info[side].short)}</span>
    <span>${esc(info[side].name)}</span>
    ${info[side].formation ? `<span class="lab">${esc(info[side].formation)}</span>` : ''}
    <span class="lab lineup-count${short ? ' short' : ''}">${team.on.length} PLAYERS</span>
  </div>`;
}

/** Name plus its marks: a yellow card, and "on 63'" for a substitute. */
function onRow(p: OnPitchPlayer): string {
  return `<span class="mono lineup-number">${p.player.number}</span>
    <span class="lineup-name">${esc(p.player.name)}${p.booked ? '<span class="card-mark yellow" title="Booked" aria-label="booked"></span>' : ''}</span>
    ${p.on != null ? `<span class="lab lineup-on" title="Replaced ${esc(p.replaced?.name ?? '')}">ON ${p.on}'</span>` : ''}
    <span class="lab">${esc(p.player.pos)}</span>`;
}

function offRow(o: OffPlayer): string {
  const why = o.reason === 'sent_off'
    ? `<span class="card-mark red" aria-hidden="true"></span><span class="lab lineup-off-why">SENT OFF ${o.minute}'</span>`
    : `<span class="lab lineup-off-why">OFF ${o.minute}' · ${o.replacedBy!.number} ${esc(o.replacedBy!.name)} ON</span>`;
  return `<li class="lineup-off"><span class="mono lineup-number">${o.player.number}</span>
    <span class="lineup-name">${esc(o.player.name)}</span>${why}</li>`;
}

/**
 * One team's players at a moment: who is on (pickable buttons carrying `data-player-id` when `pickable`),
 * then an "Off" list with the minute and reason.
 */
export function teamSheetHtml(info: MatchInfo, side: Side, team: TeamOnPitch, pickable: boolean): string {
  const rows = team.on.map(p => pickable
    ? `<li><button type="button" class="lineup-pick" data-player-id="${p.player.id}">${onRow(p)}</button></li>`
    : `<li><span class="lineup-pick">${onRow(p)}</span></li>`).join('');
  const off = team.off.length
    ? `<div class="lab lineup-off-head">OFF</div><ul class="lineup-list">${team.off.map(offRow).join('')}</ul>` : '';
  return `${teamHead(info, side, team)}<ul class="lineup-list">${rows}</ul>${off}`;
}

/** The bottom Lineups section: who is on the pitch at t (the XI before any change); names pick a player to follow. */
export function renderLineups(homeEl: HTMLElement, awayEl: HTMLElement, info: MatchInfo, events: MatchEvent[], t: number): void {
  const teams = onPitchAt(info, events, t);
  homeEl.innerHTML = teamSheetHtml(info, 'home', teams.home, true);
  awayEl.innerHTML = teamSheetHtml(info, 'away', teams.away, true);
}

/** The ON THE PITCH side panel at match time t, recomputed from the events on every call. */
export function renderOnPitchPanel(panel: HTMLElement, info: MatchInfo, events: MatchEvent[], t: number, onClose: () => void): void {
  const teams = onPitchAt(info, events, t);
  const scrolled = panel.querySelector<HTMLElement>('.onpitch-body')?.scrollTop ?? 0;  // a live update keeps the reader's place
  panel.innerHTML = `
    <div class="evidence-head">
      <h2>ON THE PITCH · ${matchMinute(t, info.periods)}'</h2>
      <button id="onpitch-close" class="evidence-close mono" aria-label="Close lineups"><span>CLOSE</span></button>
    </div>
    <div class="onpitch-body">
      <div class="lineup">${teamSheetHtml(info, 'home', teams.home, false)}</div>
      <div class="lineup">${teamSheetHtml(info, 'away', teams.away, false)}</div>
    </div>`;
  panel.classList.remove('hidden');
  const body = panel.querySelector<HTMLElement>('.onpitch-body');
  if (body) body.scrollTop = scrolled;
  panel.querySelector('#onpitch-close')?.addEventListener('click', onClose);
}

/** "41' · 3–0": the clip's start minute and the score then (score_at_start for a mid-match clip). */
export function clipStartLabel(info: MatchInfo, events: MatchEvent[], start: number): string {
  const score = scoreAt(events, start, start, info.score_at_start);
  return `${matchMinute(start, info.periods)}'${score ? ` · ${score.home}–${score.away}` : ''}`;
}

/** The pre-clip lineup card drawn over the paused video: both XIs at the clip start, formations and the score. */
export function renderLineupCard(card: HTMLElement, info: MatchInfo, events: MatchEvent[], start: number, onSkip: () => void): void {
  const teams = onPitchAt(info, events, start);
  const column = (side: Side) => {
    const team = teams[side];
    const rows = team.on.map(p => `<li><span class="mono lineup-number">${p.player.number}</span>
      <span class="lineup-name">${esc(p.player.name)}${p.booked ? '<span class="card-mark yellow" aria-label="booked"></span>' : ''}${p.on != null ? ` <span class="lineup-on">ON ${p.on}'</span>` : ''}</span>
      <span class="lineup-pos">${esc(p.player.pos)}</span></li>`).join('');
    const off = team.off.map(o => `<li class="lineup-off"><span class="mono lineup-number">${o.player.number}</span>
      <span class="lineup-name">${esc(o.player.name)}</span>
      <span class="lineup-pos">${o.reason === 'sent_off' ? `<span class="card-mark red" aria-hidden="true"></span>SENT OFF ${o.minute}'` : `OFF ${o.minute}'`}</span></li>`).join('');
    return `<div class="lc-team ${side}">
      <div class="lc-team-head" style="border-color:${info[side].kit.shirt}">
        <span class="chip ${side}" style="background:${info[side].kit.shirt}">${esc(info[side].short)}</span>
        <span class="lc-team-name">${esc(info[side].name)}</span>
        <span class="lc-formation">${esc(info[side].formation ?? '')}${team.on.length < 11 ? ` · ${team.on.length}` : ''}</span>
      </div>
      <ol class="lc-list">${rows}${off}</ol>
    </div>`;
  };
  card.innerHTML = `
    <div class="lc-head">
      <span class="lab">LINEUPS</span>
      <span class="lc-score num">${esc(clipStartLabel(info, events, start))}</span>
      <button type="button" id="lineup-card-skip" class="lc-skip mono">SKIP</button>
    </div>
    <div class="lc-teams">${column('home')}${column('away')}</div>`;
  card.hidden = false;
  card.querySelector('#lineup-card-skip')?.addEventListener('click', onSkip);
}
