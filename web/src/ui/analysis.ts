import type { Insight, MatchEvent, MatchInfo, Report, ReportFact } from '../types';
import { eventSection } from './evidence';
import { overlayProvenance, provenanceText } from '../data/provenance';

/** Cited events listed in an insight's evidence before the rest are summarised as a count. */
export const MAX_EVENTS_SHOWN = 12;

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

/** The Match analysis panel: headline and insights in `lang`; clicking an insight calls `onPick`. */
export function renderAnalysis(panel: HTMLElement, report: Report, lang: string, info: MatchInfo,
                               onPick: (insight: Insight) => void, onClose: () => void): void {
  const insights = report.insights.filter(i => i.text[lang]);
  const body = !hasLanguage(report, lang)
    ? `<p class="analysis-empty">No match analysis in ${esc(lang.toUpperCase())} for this clip.</p>`
    : `${report.headline[lang] ? `<h3 class="analysis-headline">${esc(report.headline[lang])}</h3>` : ''}
       ${insights.length ? `<ol class="analysis-list">${insights.map(i => `
         <li><button class="insight${i.hedged ? ' hedged' : ''}" data-insight="${esc(i.id)}">
           <span class="insight-head">${teamTab(info, i.team)}<span class="lab">${TOPIC[i.topic]}</span>
             <span class="insight-coverage mono">${i.hedged ? 'HEDGED · ' : ''}${pct(i.coverage)} SEEN</span></span>
           <span class="insight-title">${esc(i.title[lang] ?? '')}</span>
           <span class="insight-text">${esc(i.text[lang])}</span>
         </button></li>`).join('')}</ol>`
         : '<p class="analysis-empty">Too little of the clip was seen for a tactical insight.</p>'}`;
  panel.innerHTML = `
    <div class="evidence-head">
      <h2>MATCH ANALYSIS</h2>
      <button id="analysis-close" class="evidence-close mono" aria-label="Close match analysis"><span>CLOSE</span></button>
    </div>
    <div class="analysis-body">${body}
      <p class="analysis-note mono">Written by the analyst agent from tactical facts computed by code; every number is from those facts. Click an insight for its evidence.</p>
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
