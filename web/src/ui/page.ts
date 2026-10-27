import type { MatchInfo, MatchEvent } from '../types';
import { scoreAt, compareRows } from '../data/summary';
import { clock } from '../render/schedule';

export function renderHero(info: MatchInfo): void {
  document.querySelector('#hero-home-name')!.textContent = info.home.name;
  document.querySelector('#hero-away-name')!.textContent = info.away.name;
  document.querySelector('#hero-home-tab')!.textContent = info.home.short;
  document.querySelector('#hero-away-tab')!.textContent = info.away.short;
  (document.querySelector('#hero-home-tab') as HTMLElement).style.background = info.home.kit.shirt;
  (document.querySelector('#hero-away-tab') as HTMLElement).style.background = info.away.kit.shirt;
  document.querySelector('#hero-home-formation')!.textContent = info.home.formation ?? '—';
  document.querySelector('#hero-away-formation')!.textContent = info.away.formation ?? '—';
}

/** Recompute on either playback or seeking; never carry mutable score state between frames. */
export function renderSummary(info: MatchInfo, events: MatchEvent[], start: number, t: number, end: number): void {
  const score = scoreAt(events.filter(e => e.t < end), t, start, info.score_at_start);
  document.querySelector('#hero-home-score')!.textContent = score ? String(score.home) : '—';
  document.querySelector('#hero-away-score')!.textContent = score ? String(score.away) : '—';
  document.querySelector('#hero-clock')!.textContent = `MATCH ${clock(t, info.periods)}${score ? '' : ' · Score unavailable'}`;
  document.querySelector('#compare-scope')!.textContent = `${clock(start, info.periods)}–${clock(Math.min(t, end), info.periods)} · so far`;
  const container = document.querySelector<HTMLElement>('#compare-rows')!;
  const rows = compareRows(events, start, t, end);
  container.innerHTML = rows.map(row => {
    const total = row.home + row.away || 1;
    const homePct = (row.home / total) * 100;
    return `
      <div class="compare-row">
        <span class="num">${row.home}</span>
        <div class="compare-mid">
          <span class="lab">${row.label}</span>
          <div class="compare-bar">
            <span class="fill home" style="width:${homePct}%"></span>
            <span class="fill away" style="width:${100 - homePct}%"></span>
          </div>
        </div>
        <span class="num">${row.away}</span>
      </div>`;
  }).join('');
}

export function renderLineups(homeEl: HTMLElement, awayEl: HTMLElement, info: MatchInfo): void {
  const list = (team: 'home' | 'away', el: HTMLElement) => {
    const players = info[team].players.filter(p => p.starter).sort((a, b) => a.number - b.number);
    const label = team === 'home' ? info.home.short : info.away.short;
    el.innerHTML = `
      <div class="lineup-head">
        <span class="chip ${team}">${label}</span>
        <span>${info[team].name}</span>
      </div>
      <ul class="lineup-list">
        ${players.map(p => `
          <li>
            <span class="mono lineup-number">${p.number}</span>
            <span class="lineup-name">${p.name}</span>
            <span class="lab">${p.pos}</span>
          </li>`).join('')}
      </ul>`;
  };
  list('home', homeEl);
  list('away', awayEl);
}
