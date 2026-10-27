import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import Ajv from 'ajv/dist/2020.js';
import { loadTs } from './support/load-ts.mjs';

const web = fileURLToPath(new URL('../', import.meta.url));
const json = path => JSON.parse(readFileSync(new URL(`../../${path}`, import.meta.url), 'utf8'));
const info = json('data/fake/sample_a/match_info.json');
const sample = json('data/fake/sample_a/events.json');
const example = json('schemas/examples/report.example.json');
const { renderAnalysis, renderInsightEvidence, coverageNote, hasLanguage, esc, MAX_EVENTS_SHOWN } = loadTs(`${web}/src/ui/analysis.ts`);
const validReport = new Ajv({ strict: false }).compile(json('schemas/report.schema.json'));

function panel() {
  const listeners = [];
  return {
    innerHTML: '', hidden: true, listeners,
    classList: { remove() { this.owner.hidden = false; }, add() { this.owner.hidden = true; }, contains() { return false; } },
    querySelector() { return { addEventListener: (_, f) => listeners.push(f) }; },
    querySelectorAll() { return []; },
  };
}
function fresh() { const p = panel(); p.classList.owner = p; return p; }

test('the example report is schema-valid and renders its headline and insights in the chosen language', () => {
  assert.equal(validReport(example), true);
  for (const lang of ['en', 'tr', 'es']) {
    const p = fresh();
    renderAnalysis(p, example, lang, info, () => {}, () => {});
    assert.equal(p.hidden, false);
    assert.ok(p.innerHTML.includes(esc(example.headline[lang])), lang);
    for (const i of example.insights) assert.ok(p.innerHTML.includes(esc(i.text[lang])), `${lang} ${i.id}`);
  }
});

test('a language the report lacks says so instead of falling back to another', () => {
  const p = fresh();
  assert.equal(hasLanguage(example, 'de'), false);
  renderAnalysis(p, example, 'de', info, () => {}, () => {});
  assert.match(p.innerHTML, /No clip analysis in DE/);
  assert.ok(!p.innerHTML.includes(esc(example.headline.en)));
});

test('the panel is the clip\'s analysis: its window in match minutes, from what the AI saw (#83)', () => {
  const p = fresh();
  renderAnalysis(p, example, 'en', info, () => {}, () => {});   // the dev1 clip, 0:00-2:00
  assert.match(p.innerHTML, /<h2>CLIP ANALYSIS<\/h2>/);
  assert.doesNotMatch(p.innerHTML, /MATCH ANALYSIS/i);
  assert.match(p.innerHTML, /CLIP 1'–2' · WHAT THE AI SAW/);
  assert.match(p.innerHTML, /aria-label="Close clip analysis"/);
  assert.match(p.innerHTML, /this clip only, from the vision AI's tracking and events/);
  const second = info.periods.find(q => q.period === 2).start;   // sample_a: 2 x 5 minutes
  const late = { ...example, start: second + 60, end: second + 179.96 };
  renderAnalysis(p, late, 'en', info, () => {}, () => {});
  assert.match(p.innerHTML, /CLIP 47'–48'/);
});

test('a clip with no insight says why: too short under 5 minutes, else too little seen (#83)', () => {
  const empty = { ...example, headline: {}, insights: [] };
  for (const lang of ['en', 'tr']) {
    const p = fresh();
    renderAnalysis(p, empty, lang, info, () => {}, () => {});
    assert.match(p.innerHTML, /This clip is too short for a tactical read\./, lang);
    assert.doesNotMatch(p.innerHTML, /No clip analysis in|too little/i, lang);
  }
  const p = fresh();
  renderAnalysis(p, { ...empty, end: 600 }, 'en', info, () => {}, () => {});
  assert.match(p.innerHTML, /Too little of the clip was seen for a tactical insight\./);
  // Insights in other languages only: not "too short", which would be untrue.
  const enOnly = { ...example, insights: example.insights.map(i => ({ ...i, text: { en: i.text.en } })) };
  renderAnalysis(p, enOnly, 'tr', info, () => {}, () => {});
  assert.match(p.innerHTML, /No insight in TR\./);
  assert.doesNotMatch(p.innerHTML, /too short/);
});

test('agent text is escaped before it reaches the page', () => {
  const report = structuredClone(example);
  report.headline.en = '<img src=x onerror=alert(1)>';
  report.insights[0].text.en = '<script>x</script>';
  const p = fresh();
  renderAnalysis(p, report, 'en', info, () => {}, () => {});
  assert.doesNotMatch(p.innerHTML, /<img|<script/);
});

test('a hedged insight is marked, and its evidence says its coverage was below the threshold', () => {
  const report = structuredClone(example);
  Object.assign(report.insights[0], { coverage: 0.4, hedged: true });
  const p = fresh();
  renderAnalysis(p, report, 'en', info, () => {}, () => {});
  assert.match(p.innerHTML, /HEDGED · 40% SEEN/);
  assert.equal(coverageNote(report.insights[0], report), 'Based on 40% of the clip, below 60%: hedged');
  assert.equal(coverageNote(example.insights[0], example), `Based on ${Math.round(example.insights[0].coverage * 100)}% of the clip`);
  const evidence = fresh();
  renderInsightEvidence(evidence, report.insights[0], report, new Map(), info);
  assert.match(evidence.innerHTML, /below 60%: hedged/);
});

test('insight evidence lists every fact with its value and coverage, and the cited events (capped)', () => {
  const pass = sample.find(e => e.type === 'pass');
  const ids = Array.from({ length: MAX_EVENTS_SHOWN + 3 }, (_, n) => `e9${String(n).padStart(3, '0')}`);
  const events = new Map(ids.map(id => [id, { ...pass, id, source: 'cv', confidence: 0.8 }]));
  const insight = { ...example.insights[0], event_ids: ids };
  const p = fresh();
  renderInsightEvidence(p, insight, example, events, info);
  for (const f of insight.facts) {
    assert.ok(p.innerHTML.includes(esc(f.label)));
    assert.ok(p.innerHTML.includes(esc(f.ref)));
    assert.ok(p.innerHTML.includes(`${Math.round(f.coverage * 100)}% seen`));
  }
  assert.match(p.innerHTML, /15 cited events · CV · CV 80%/);
  assert.equal((p.innerHTML.match(/class="evt"/g) ?? []).length, MAX_EVENTS_SHOWN);
  assert.match(p.innerHTML, /and 3 more cited events/);
});

test('an insight with no events (frame facts) says where its evidence is', () => {
  const insight = example.insights.find(i => !i.event_ids.length);
  const p = fresh();
  renderInsightEvidence(p, insight, example, new Map(), info);
  assert.match(p.innerHTML, /Frame facts: no single event/);
  assert.match(p.innerHTML, /frames/);
});

/** Declarations of `selector`'s rule in style.css, inside `@media (max-width: 720px)` when `phone`. */
function css(selector, phone = false) {
  const style = readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');
  const media = style.lastIndexOf('@media (max-width: 720px) {\n  .analysis');
  const scope = phone ? style.slice(media) : style.slice(0, media);
  const body = new RegExp(`(?:^|\\n)\\s*${selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')} \\{([^}]*)\\}`).exec(scope)?.[1];
  assert.ok(body, `${selector} rule${phone ? ' (phone)' : ''}`);
  return Object.fromEntries(body.split(';').map(d => d.split(':').map(s => s.trim())).filter(([k, v]) => k && v));
}

test('the analysis panel keeps CLOSE outside its scrolling body, which has room below the last insight', () => {
  const p = fresh();
  renderAnalysis(p, example, 'en', info, () => {}, () => {});
  const head = p.innerHTML.indexOf('class="evidence-head"'), close = p.innerHTML.indexOf('id="analysis-close"'), body = p.innerHTML.indexOf('class="analysis-body"');
  assert.ok(head < close && close < body, 'CLOSE is in the header, before the body');
  assert.equal(css('.analysis').overflow, 'hidden');
  const scroller = css('.analysis-body');
  assert.equal(scroller['overflow-y'], 'auto');
  assert.equal(scroller['min-height'], '0');
  assert.ok(Number.parseInt(scroller.padding.split(' ')[2]) >= 32, 'bottom padding');
  assert.equal(css('.analysis-body', true).padding.split(' ')[2], scroller.padding.split(' ')[2]);
});

test('the panel cannot be pushed past the viewport\'s left edge, and is a full-screen sheet on a phone', () => {
  assert.equal(css('.player-section').width, '100%');  // a shrink-to-fit section centred in <main> overflows on both sides
  assert.equal(css('.analysis', true).position, 'fixed');
  assert.equal(css('.stage:has(> .analysis:not(.hidden)) > .evidence', true).position, 'fixed');
});
