import type { Insight, MatchEvent, MatchInfo, Report, ReportFact } from '../types';
import { eventSection } from './evidence';
import { overlayProvenance, provenanceText } from '../data/provenance';

/** Cited events listed in an insight's evidence before the rest are summarised as a count. */
export const MAX_EVENTS_SHOWN = 12;
/** Under this many seconds a clip with no insight is too short for a tactical read, not badly seen (#83). */
export const SHORT_CLIP_S = 300;

const TOPIC: Record<Insight['topic'], string> = {
  shape: 'SHAPE', defensive_line: 'LINE HEIGHT', compactness: 'COMPACTNESS', width: 'WIDTH', flanks: 'FLANKS',
  pressing: 'PRESSING', directness: 'DIRECTNESS', progression: 'PROGRESSION', change: 'CHANGE',
};

/** Report text is agent-written: always escaped before it reaches innerHTML. */
export function esc(value: unknown): string {
  return String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));
}

function pct(share: number | null | undefined): string {
  return typeof share === 'number' && Number.isFinite(share) ? `${Math.round(share * 100)}%` : 'n/a';
}

function teamTab(info: MatchInfo, team: Insight['team']): string {
  if (team === 'both') return `<span class="chip both">${esc(info.home.short)}·${esc(info.away.short)}</span>`;
  return `<span class="chip ${team}" style="background:${esc(info[team].kit.shirt)}">${esc(info[team].short)}</span>`;
}

/** What the insight's coverage means, in the words the evidence shows. */
export function coverageNote(insight: Insight, report: Report): string {
  const seen = `Based on ${pct(insight.coverage)} of the clip`;
  return insight.hedged ? `${seen}, below ${pct(report.coverage_min)}: hedged` : seen;
}

/** Whether the report has text in this language (no fallback to another language, as for the cards). */
export function hasLanguage(report: Report, lang: string): boolean {
  return Boolean(report.headline[lang]) || report.insights.some(i => i.text[lang]);
}

/** Broadcast minute of match time t: 1-based, the second half counting on from 46'. */
function minute(t: number, info: MatchInfo): number {
  const second = info.periods?.find(p => p.period === 2);
  return second && t >= second.start ? 45 + Math.floor((t - second.start) / 60) + 1 : Math.floor(t / 60) + 1;
}

/** Why a report has no insight: a short highlight is too short for a tactical read; a long clip was badly seen. */
function emptyNote(report: Report): string {
  return report.end - report.start < SHORT_CLIP_S
    ? 'This clip is too short for a tactical read.' : 'Too little of the clip was seen for a tactical insight.';
}

/** The Clip analysis panel: headline and insights in `lang`; clicking an insight calls `onPick`. */
export function renderAnalysis(panel: HTMLElement, report: Report, lang: string, info: MatchInfo,
                               onPick: (insight: Insight) => void, onClose: () => void): void {
  const insights = report.insights.filter(i => i.text[lang]);
  const body = !report.insights.length ? `<p class="analysis-empty">${emptyNote(report)}</p>`
    : !hasLanguage(report, lang)
    ? `<p class="analysis-empty">No clip analysis in ${esc(lang.toUpperCase())}.</p>`
    : `${report.headline[lang] ? `<h3 class="analysis-headline">${esc(report.headline[lang])}</h3>` : ''}
       ${insights.length ? `<ol class="analysis-list">${insights.map(i => `
         <li><button class="insight${i.hedged ? ' hedged' : ''}" data-insight="${esc(i.id)}">
           <span class="insight-head">${teamTab(info, i.team)}<span class="lab">${TOPIC[i.topic]}</span>
             <span class="insight-coverage mono">${i.hedged ? 'HEDGED · ' : ''}${pct(i.coverage)} SEEN</span></span>
           <span class="insight-title">${esc(i.title[lang] ?? '')}</span>
           <span class="insight-text">${esc(i.text[lang])}</span>
         </button></li>`).join('')}</ol>`
         : `<p class="analysis-empty">No insight in ${esc(lang.toUpperCase())}.</p>`}`;
  panel.innerHTML = `
    <div class="evidence-head">
      <h2>CLIP ANALYSIS</h2>
      <button id="analysis-close" class="evidence-close mono" aria-label="Close clip analysis"><span>CLOSE</span></button>
    </div>
    <div class="analysis-body">
      <p class="analysis-window mono">CLIP ${minute(report.start, info)}'–${minute(report.end, info)}' · WHAT THE AI SAW</p>${body}
      <p class="analysis-note mono">Covers this clip only, from the vision AI's tracking and events. Written by the analyst agent from tactical facts computed by code; every number is from those facts. Click an insight for its evidence.</p>
    </div>`;
  panel.classList.remove('hidden');
  panel.querySelector('#analysis-close')?.addEventListener('click', onClose);
  panel.querySelectorAll<HTMLElement>('[data-insight]').forEach(button => {
    button.addEventListener('click', () => {
      const insight = report.insights.find(i => i.id === button.dataset.insight);
      if (insight) onPick(insight);
    });
  });
}

function factRow(fact: ReportFact): string {
  const seen = fact.n_frames !== undefined ? `${fact.n_frames} frames` : fact.n_events !== undefined ? `${fact.n_events} events` : '';
  return `<div class="fact-row">
    <span class="lab">${esc(fact.label)}</span>
    <span class="num">${esc(fact.value ?? 'n/a')}</span>
    <span class="fact-meta mono">${pct(fact.coverage)} seen${seen ? ` · ${seen}` : ''} · ${esc(fact.ref)}</span>
  </div>`;
}

/** An insight's evidence: its coverage, the facts with their values, and the events it cites. */
export function renderInsightEvidence(panel: HTMLElement, insight: Insight, report: Report,
                                      events: Map<string, MatchEvent>, info: MatchInfo): void {
  const cited = insight.event_ids.map(id => events.get(id)).filter((e): e is MatchEvent => !!e);
  const shown = cited.slice(0, MAX_EVENTS_SHOWN);
  const more = cited.length - shown.length;
  panel.innerHTML = `
    <div class="evidence-head">
      <h2>INSIGHT EVIDENCE</h2>
      <button id="evidence-close" class="evidence-close mono" aria-label="Close"><span>CLOSE</span></button>
    </div>
    <div class="evidence-provenance${insight.hedged ? ' hedged' : ''}">${esc(coverageNote(insight, report))}</div>
    <div class="evt-derived"><div class="lab" style="margin-bottom:8px">FACTS (CODE)</div>${insight.facts.map(factRow).join('')}</div>
    ${cited.length ? `<div class="evidence-provenance">${cited.length} cited event${cited.length === 1 ? '' : 's'} · ${esc(provenanceText(overlayProvenance(insight, events)))}</div>` : '<div class="evidence-provenance">Frame facts: no single event; see the frames counted above.</div>'}
    ${shown.map(e => eventSection(e, info)).join('')}
    ${more > 0 ? `<div class="evidence-provenance">and ${more} more cited event${more === 1 ? '' : 's'}</div>` : ''}`;
  panel.classList.remove('hidden');
  panel.querySelector('#evidence-close')?.addEventListener('click', () => panel.classList.add('hidden'));
}
