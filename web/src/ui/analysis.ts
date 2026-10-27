import type { Insight, MatchEvent, MatchInfo, Report, ReportFact } from '../types';
import { eventSection } from './evidence';
import { overlayProvenance, provenanceText } from '../data/provenance';
import { matchMinute } from '../render/schedule';
import { ui } from '../i18n';

/** Cited events listed in an insight's evidence before the rest are summarised as a count. */
export const MAX_EVENTS_SHOWN = 12;
/** Under this many seconds a clip with no insight is too short for a tactical read, not badly seen (#83). */
export const SHORT_CLIP_S = 300;

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
export function coverageNote(insight: Insight, report: Report, lang = 'en'): string {
  const seen = ui(lang, 'insight.basedOn', { pct: pct(insight.coverage) });
  return insight.hedged ? ui(lang, 'insight.belowHedged', { seen, pct: pct(report.coverage_min) }) : seen;
}

/** Whether the report has text in this language (no fallback to another language, as for the cards). */
export function hasLanguage(report: Report, lang: string): boolean {
  return Boolean(report.headline[lang]) || report.insights.some(i => i.text[lang]);
}

/** Why a report has no insight: a short highlight is too short for a tactical read; a long clip was badly seen. */
function emptyNote(report: Report, lang: string): string {
  return ui(lang, report.end - report.start < SHORT_CLIP_S ? 'analysis.short' : 'analysis.unseen');
}

/**
 * The Clip analysis panel: headline and insights in `lang`; clicking an insight calls `onPick`. The report covers the
 * whole clip, so its window line says the final score is shown (#95): opened mid-clip, the headline may be ahead of play.
 */
export function renderAnalysis(panel: HTMLElement, report: Report, lang: string, info: MatchInfo,
                               onPick: (insight: Insight) => void, onClose: () => void): void {
  const insights = report.insights.filter(i => i.text[lang]);
  const body = !report.insights.length ? `<p class="analysis-empty">${emptyNote(report, lang)}</p>`
    : !hasLanguage(report, lang)
    ? `<p class="analysis-empty">${ui(lang, 'analysis.noLanguage', { lang: esc(lang.toUpperCase()) })}</p>`
    : `${report.headline[lang] ? `<h3 class="analysis-headline">${esc(report.headline[lang])}</h3>` : ''}
       ${insights.length ? `<ol class="analysis-list">${insights.map(i => `
         <li><button class="insight${i.hedged ? ' hedged' : ''}" data-insight="${esc(i.id)}">
           <span class="insight-head">${teamTab(info, i.team)}<span class="lab">${ui(lang, `topic.${i.topic}`)}</span>
             <span class="insight-coverage mono">${i.hedged ? `${ui(lang, 'analysis.hedged')} · ` : ''}${ui(lang, 'analysis.seen', { pct: pct(i.coverage) })}</span></span>
           <span class="insight-title">${esc(i.title[lang] ?? '')}</span>
           <span class="insight-text">${esc(i.text[lang])}</span>
         </button></li>`).join('')}</ol>`
         : `<p class="analysis-empty">${ui(lang, 'analysis.noInsight', { lang: esc(lang.toUpperCase()) })}</p>`}`;
  panel.innerHTML = `
    <div class="evidence-head">
      <h2>${ui(lang, 'analysis.title')}</h2>
      <button id="analysis-close" class="evidence-close mono" aria-label="${ui(lang, 'analysis.close')}"><span>${ui(lang, 'panel.close')}</span></button>
    </div>
    <div class="analysis-body">
      <p class="analysis-window mono">${ui(lang, 'analysis.window', { from: matchMinute(report.start, info.periods), to: matchMinute(report.end, info.periods) })}</p>
      <p class="analysis-window mono">${ui(lang, 'analysis.fullClip')}</p>${body}
      <p class="analysis-note mono">${ui(lang, 'analysis.note')}</p>
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

function factRow(fact: ReportFact, lang: string): string {
  const seen = fact.n_frames !== undefined ? ui(lang, 'fact.frames', { n: fact.n_frames })
    : fact.n_events !== undefined ? ui(lang, 'fact.events', { n: fact.n_events }) : '';
  return `<div class="fact-row">
    <span class="lab" lang="en">${esc(fact.label)}</span>
    <span class="num">${esc(fact.value ?? 'n/a')}</span>
    <span class="fact-meta mono">${ui(lang, 'fact.seen', { pct: pct(fact.coverage) })}${seen ? ` · ${seen}` : ''} · ${esc(fact.ref)}</span>
  </div>`;
}

/** An insight's evidence: its coverage, the facts with their values, and the events it cites. */
export function renderInsightEvidence(panel: HTMLElement, insight: Insight, report: Report,
                                      events: Map<string, MatchEvent>, info: MatchInfo, lang = 'en'): void {
  const cited = insight.event_ids.map(id => events.get(id)).filter((e): e is MatchEvent => !!e);
  const shown = cited.slice(0, MAX_EVENTS_SHOWN);
  const more = cited.length - shown.length;
  panel.innerHTML = `
    <div class="evidence-head">
      <h2>${ui(lang, 'insight.title')}</h2>
      <button id="evidence-close" class="evidence-close mono" aria-label="${ui(lang, 'panel.closeAria')}"><span>${ui(lang, 'panel.close')}</span></button>
    </div>
    <div class="evidence-provenance${insight.hedged ? ' hedged' : ''}">${esc(coverageNote(insight, report, lang))}</div>
    <div class="evt-derived"><div class="lab" style="margin-bottom:8px">${ui(lang, 'insight.facts')}</div>${insight.facts.map(f => factRow(f, lang)).join('')}</div>
    ${cited.length ? `<div class="evidence-provenance">${cited.length === 1 ? ui(lang, 'insight.cited1') : ui(lang, 'insight.citedN', { n: cited.length })} · ${esc(provenanceText(overlayProvenance(insight, events)))}</div>` : `<div class="evidence-provenance">${ui(lang, 'insight.frameFacts')}</div>`}
    ${shown.map(e => eventSection(e, info, lang)).join('')}
    ${more > 0 ? `<div class="evidence-provenance">${more === 1 ? ui(lang, 'insight.more1') : ui(lang, 'insight.moreN', { n: more })}</div>` : ''}`;
  panel.classList.remove('hidden');
  panel.querySelector('#evidence-close')?.addEventListener('click', () => panel.classList.add('hidden'));
}
