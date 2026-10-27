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
  assert.match(p.innerHTML, /No match analysis in DE/);
  assert.ok(!p.innerHTML.includes(esc(example.headline.en)));
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
