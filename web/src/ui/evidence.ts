import type { MatchEvent, MatchInfo, Overlay } from '../types';
import { clock } from '../render/schedule';
import { confidencePercent, overlayProvenance, provenanceText } from '../data/provenance';

interface PlayerRef { name: string; number: number; team: 'home' | 'away' }

function findPlayer(info: MatchInfo, id: number | null | undefined): PlayerRef | undefined {
  if (id == null) return undefined;
  for (const team of ['home', 'away'] as const) {
    const player = info[team].players.find(p => p.id === id);
    if (player) return { name: player.name, number: player.number, team };
  }
  return undefined;
}

function chip(info: MatchInfo, id: number | null | undefined): string {
  const p = findPlayer(info, id);
  if (!p) return '<span class="lab">—</span>';
  const teamLabel = p.team === 'home' ? info.home.short : info.away.short;
  return `<span style="display:flex;align-items:center;gap:8px">
    <span class="chip ${p.team}">${teamLabel}</span>
    <span class="mono" style="font-size:12px">${p.number} ${p.name}</span>
  </span>`;
}

function eventTimecode(event: MatchEvent, periods: MatchInfo['periods']): string {
  const base = clock(event.t, periods);
  const frac = Math.floor((event.t % 1) * 100).toString().padStart(2, '0');
  return `${base}.${frac}`;
}

function eventSection(event: MatchEvent, info: MatchInfo): string {
  const kind = event.subtype ? `${event.type} · ${event.subtype}` : event.type;
  const rows: string[] = [];
  const source = event.source === 'cv' ? 'CV · Detected from video' : event.source === 'sim' ? 'SIM · Simulator' : 'Unknown source';
  const confidence = event.source === 'cv' ? confidencePercent(event.confidence) ?? 'Not available' : undefined;
  if (event.from != null) rows.push(`<div class="evt-field"><span class="lab">FROM</span>${chip(info, event.from)}</div>`);
  if (event.to != null) rows.push(`<div class="evt-field"><span class="lab">TO</span>${chip(info, event.to)}</div>`);
  if (event.start) rows.push(`<div class="evt-field"><span class="lab">START</span><span class="mono" style="font-size:12px">${event.start[0].toFixed(1)}, ${event.start[1].toFixed(1)} <span style="color:var(--dust)">m</span></span></div>`);
  if (event.end) rows.push(`<div class="evt-field"><span class="lab">END</span><span class="mono" style="font-size:12px">${event.end[0].toFixed(1)}, ${event.end[1].toFixed(1)} <span style="color:var(--dust)">m</span></span></div>`);
  return `
    <div class="evt">
      <div class="evt-row-head">
        <span class="evt-id">${event.id.toUpperCase()}</span>
        <span class="evt-type">${kind.toUpperCase()}</span>
      </div>
      <div class="evt-source">${source}</div>
      ${confidence ? `<div class="evt-confidence">CV confidence: ${confidence}</div>` : ''}
      <div class="evt-time">${eventTimecode(event, info.periods)}</div>
      ${rows.join('')}
    </div>`;
}

const UNIT: Record<string, string> = { distance_m: 'm', speed_kmh: 'km/h', goal_distance_m: 'm', duration_s: 's', difficulty: '/10' };

function derivedSection(overlay: Overlay): string {
  const values = overlay.values ?? {};
  const rows = Object.entries(values).map(([key, v]) => {
    const unit = UNIT[key] ?? '';
    const mint = key === 'difficulty' ? ' mint' : '';
    return `<div class="row"><span class="lab">${key.replace(/_/g, ' ')}</span><span class="num${mint}">${v}${unit ? ` <span class="mono" style="font-size:11px;font-weight:400;color:var(--dust)">${unit}</span>` : ''}</span></div>`;
  });
  if (!rows.length) return '';
  return `<div class="evt-derived"><div class="lab" style="margin-bottom:8px">DERIVED</div>${rows.join('')}</div>`;
}

export function renderEvidence(panel: HTMLElement, overlay: Overlay, events: Map<string, MatchEvent>, info: MatchInfo): void {
  const cited = overlay.event_ids.map(id => events.get(id)).filter((e): e is MatchEvent => !!e);
  panel.innerHTML = `
    <div class="evidence-head">
      <h2>SOURCE EVENTS</h2>
      <button id="evidence-close" class="evidence-close mono" aria-label="Close">
        <span>CLOSE</span>
      </button>
    </div>
    <div class="evidence-provenance">${provenanceText(overlayProvenance(overlay, events))}</div>
    ${cited.map(e => eventSection(e, info)).join('')}
    ${derivedSection(overlay)}`;
  panel.classList.remove('hidden');
  panel.querySelector('#evidence-close')?.addEventListener('click', () => panel.classList.add('hidden'));
}
