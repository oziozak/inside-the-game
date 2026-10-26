import type { MatchInfo, MatchEvent } from '../types';
import { finalScore, compareRows } from '../data/summary';

export function renderHero(info: MatchInfo, events: MatchEvent[]): void {
  const score = finalScore(events);
  document.querySelector('#hero-home-name')!.textContent = info.home.name;
  document.querySelector('#hero-away-name')!.textContent = info.away.name;
  document.querySelector('#hero-home-tab')!.textContent = info.home.short;
  document.querySelector('#hero-away-tab')!.textContent = info.away.short;
  (document.querySelector('#hero-home-tab') as HTMLElement).style.background = info.home.kit.shirt;
  (document.querySelector('#hero-away-tab') as HTMLElement).style.background = info.away.kit.shirt;
  document.querySelector('#hero-home-score')!.textContent = String(score.home);
  document.querySelector('#hero-away-score')!.textContent = String(score.away);
  document.querySelector('#hero-home-formation')!.textContent = info.home.formation ?? '—';
  document.querySelector('#hero-away-formation')!.textContent = info.away.formation ?? '—';
}

export function renderCompare(container: HTMLElement, events: MatchEvent[]): void {
  const rows = compareRows(events);
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
