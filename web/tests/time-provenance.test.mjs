import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import Ajv from 'ajv/dist/2020.js';
import { loadTs } from './support/load-ts.mjs';

const web = fileURLToPath(new URL('../', import.meta.url));
const json = path => JSON.parse(readFileSync(new URL(`../../${path}`, import.meta.url), 'utf8'));
const events = json('data/fake/sample_a/events.json');
const info = json('data/fake/sample_a/match_info.json');
const { scoreAt, compareRows } = loadTs(`${web}/src/data/summary.ts`);
const { confidencePercent, overlayProvenance } = loadTs(`${web}/src/data/provenance.ts`);
const { renderEvidence } = loadTs(`${web}/src/ui/evidence.ts`);
const { renderSummary } = loadTs(`${web}/src/ui/page.ts`);
const { clock } = loadTs(`${web}/src/render/schedule.ts`);
const validate = new Ajv({ strict: false }).compile(json('schemas/event.schema.json'));

// Synthetic unit fixtures, derived from committed sample events; these are not detector outputs.
const cv = { ...events.find(e => e.type === 'pass'), id: 'e9001', source: 'cv', confidence: 0.76 };
const sim = { ...events.find(e => e.type === 'foul'), id: 'e9002', source: 'sim', confidence: 1 };
const overlay = ids => ({ id: 'o9001', event_ids: ids, start: 10, duration: 5, graphic: 'pass_card', text: 'Synthetic unit fixture', mode: 'analyst', lang: 'en' });
const map = new Map([[cv.id, cv], [sim.id, sim]]);

test('sample_a score follows the goal timestamp and reverses safely on seeking', () => {
  const goal = events.find(e => e.type === 'goal');
  assert.equal(goal.t, 43.73);
  assert.deepEqual(scoreAt(events, 0), { home: 0, away: 0 });
  assert.deepEqual(scoreAt(events, goal.t - 0.001), { home: 0, away: 0 });
  assert.deepEqual(scoreAt(events, goal.t), { home: 1, away: 0 });
  assert.deepEqual(scoreAt(events, 50), { home: 1, away: 0 });
  assert.deepEqual(scoreAt(events, 1), { home: 0, away: 0 });
});

test('nonzero clips retain prior score context but count only this clip so far', () => {
  assert.deepEqual(scoreAt(events, 50, 50), { home: 1, away: 0 });
  assert.equal(compareRows(events, 50, 50, 60).find(r => r.label === 'GOALS').home, 0);
  for (const t of [0, 20, 44, 59.96]) {
    const rows = compareRows(events, 0, t, 60);
    assert.equal(rows.find(r => r.label === 'SHOTS').home, events.filter(e => e.type === 'shot' && e.team === 'home' && e.t <= t && e.t < 60).length);
  }
  const atEnd = compareRows(events, 0, 60, 60);
  const withBoundary = [...events, { ...cv, t: 60 }];
  assert.deepEqual(compareRows(withBoundary, 0, 60, 60), atEnd);
});

test('empty clips and missing opening context never invent a score', () => {
  assert.deepEqual(scoreAt([], 0), { home: 0, away: 0 });
  assert.equal(scoreAt([], 50, 50), undefined);
  assert.ok(compareRows([], 50, 51, 60).every(r => r.home === 0 && r.away === 0));
  assert.deepEqual(scoreAt([cv, { ...cv, type: 'shot', success: true }], 10), { home: 0, away: 0 });
});

test('explicit score snapshots restore missing history without counting goals twice', () => {
  const goal = { ...events.find(e => e.type === 'goal'), t: 100, score: { home: 3, away: 2 } };
  const later = { ...goal, id: 'e9003', t: 105, team: 'away', score: undefined };
  assert.equal(validate(goal), true);
  assert.equal(scoreAt([later, goal], 99, 90), undefined);
  assert.deepEqual(scoreAt([later, goal], 100, 90), { home: 3, away: 2 });
  assert.deepEqual(scoreAt([later, goal], 106, 90), { home: 3, away: 3 });
});

test('a clip cut from mid-match starts from match_info.score_at_start (#83)', () => {
  const opening = { home: 3, away: 0 };
  const goal = { ...events.find(e => e.type === 'goal'), t: 2614, score: { home: 4, away: 0 } };
  const unsnapshotted = { ...goal, id: 'e9004', t: 2700, team: 'away', score: undefined };
  assert.deepEqual(scoreAt([], 2400, 2400, opening), { home: 3, away: 0 });
  assert.deepEqual(scoreAt([goal, unsnapshotted], 2614, 2400, opening), { home: 4, away: 0 });
  assert.deepEqual(scoreAt([goal, unsnapshotted], 2701, 2400, opening), { home: 4, away: 1 });
  assert.deepEqual(scoreAt([goal, unsnapshotted], 2500, 2400, opening), { home: 3, away: 0 });
  // An event before the clip (a full-match events.json) does not undo the opening score.
  assert.deepEqual(scoreAt(events, 2400, 2400, opening), { home: 3, away: 0 });
});

test('halftime clock boundaries preserve score and context when seeking across halves', () => {
  const second = info.periods.find(p => p.period === 2).start;
  assert.equal(clock(second, info.periods), '45:00');
  assert.deepEqual(scoreAt(events, second), { home: 1, away: 0 });
  assert.deepEqual(scoreAt(events, second + 0.04, second), { home: 1, away: 0 });
  assert.deepEqual(scoreAt(events, 0), { home: 0, away: 0 });
});

test('CV, SIM, and mixed provenance comes from schema-valid cited events', () => {
  assert.equal(validate(cv), true); assert.equal(validate(sim), true);
  assert.deepEqual(overlayProvenance(overlay([cv.id]), map), { label: 'CV', confidence: 'CV 76%' });
  assert.deepEqual(overlayProvenance(overlay([sim.id]), map), { label: 'SIM' });
  assert.deepEqual(overlayProvenance(overlay([cv.id, sim.id]), map), { label: 'CV+SIM', confidence: 'CV 76%' });
  assert.equal(overlayProvenance(overlay(['e9999']), map).label, '?');
});

test('missing confidence is schema-valid; invalid confidence stays rejected by the schema and unavailable in display', () => {
  const missing = { ...cv }; delete missing.confidence;
  assert.equal(validate(missing), true);
  assert.equal(overlayProvenance(overlay([cv.id]), new Map([[cv.id, missing]])).confidence, 'CV n/a');
  for (const confidence of [-0.1, 1.1, '0.8', null]) {
    assert.equal(validate({ ...cv, confidence }), false);
    assert.equal(confidencePercent(confidence), undefined);
  }
  assert.equal(confidencePercent(NaN), undefined);
  assert.equal(confidencePercent(0), '0%');
});

test('multiple CV references show their confidence range and flag unavailable values', () => {
  const cv2 = { ...cv, id: 'e9003', confidence: 0.9 };
  const local = new Map([...map, [cv2.id, cv2]]);
  const cited = overlay([cv.id, cv2.id, sim.id, cv.id]);
  assert.deepEqual(overlayProvenance(cited, local), { label: 'CV+SIM', confidence: 'CV 76–90%' });
  local.set(cv2.id, { ...cv2, confidence: undefined });
  assert.equal(overlayProvenance(cited, local).confidence, 'CV 76% · ?');
});

test('evidence retains individual event sources and never displays SIM confidence', () => {
  const panel = { innerHTML: '', classList: { remove() {} }, querySelector() { return null; } };
  const cited = overlay([cv.id, sim.id]);
  const original = structuredClone(cited);
  renderEvidence(panel, cited, map, info);
  assert.match(panel.innerHTML, /CV\+SIM/);
  assert.match(panel.innerHTML, /CV · Detected from video/);
  assert.match(panel.innerHTML, /CV confidence: 76%/);
  assert.match(panel.innerHTML, /SIM · Simulator/);
  assert.doesNotMatch(panel.innerHTML, /100%/);
  assert.deepEqual(cited, original);
  renderEvidence(panel, overlay([sim.id]), map, info);
  assert.doesNotMatch(panel.innerHTML, /confidence/i);
});

test('hero and clip-stat UI recompute at nonzero offsets and exclude source-end events', t => {
  const elements = new Map();
  const previous = globalThis.document;
  globalThis.document = { querySelector(id) { if (!elements.has(id)) elements.set(id, { textContent: '', innerHTML: '' }); return elements.get(id); } };
  t.after(() => { globalThis.document = previous; });
  renderSummary(info, events, 40, 40, 50);
  assert.equal(elements.get('#hero-home-score').textContent, '0');
  renderSummary(info, events, 40, 44, 50);
  assert.equal(elements.get('#hero-home-score').textContent, '1');
  assert.match(elements.get('#hero-clock').textContent, /00:44/);
  assert.match(elements.get('#compare-scope').textContent, /00:40–00:44/);
  renderSummary(info, events, 40, 40, 50);
  assert.equal(elements.get('#hero-home-score').textContent, '0');
  renderSummary(info, events, 0, 43.73, 43.73);
  assert.equal(elements.get('#hero-home-score').textContent, '0');
  renderSummary({ ...info, score_at_start: { home: 2, away: 1 } }, [], 2400, 2401, 3000);
  assert.equal(elements.get('#hero-home-score').textContent, '2');
  assert.equal(elements.get('#hero-away-score').textContent, '1');
  assert.doesNotMatch(elements.get('#hero-clock').textContent, /unavailable/);
});

test('standard, dual-team and player-following cards all render cited provenance', () => {
  const { drawOverlays, buildRoster } = loadTs(`${web}/src/render/draw.ts`);
  const { buildCamera } = loadTs(`${web}/src/render/camera.ts`);
  const first = JSON.parse(readFileSync(new URL('../../data/fake/sample_a/tracking.jsonl', import.meta.url), 'utf8').split('\n')[0]);
  const match = { info, frames: [first] };
  const camera = buildCamera('cv_full_pitch', match, 10, 16 / 9);
  for (const graphic of ['pass_card', 'stat_compare', 'player_tag']) {
    const drawn = [];
    const target = { font: '', fillText(text) { drawn.push(text); }, measureText(text) { return { width: text.length * Number(/([\d.]+)px/.exec(this.font)?.[1] ?? 10) * 0.6 }; } };
    const ctx = new Proxy(target, { get: (object, name) => object[name] ?? (() => {}) });
    const o = { ...overlay([cv.id, sim.id]), start: 0, duration: 20, graphic, player: cv.from,
      position: graphic === 'player_tag' ? 'follow-player' : 'bottom-left', title: 'Long fixture title '.repeat(40), values: { shots_home: 1, shots_away: 0 } };
    const regions = drawOverlays(ctx, 1920, 1080, [o], buildRoster(info), map, match, 10, camera);
    assert.equal(regions.length, 1, graphic);
    assert.ok(drawn.some(text => text.includes('SOURCE CV+SIM')), graphic);
    assert.ok(drawn.some(text => text.includes('76%')), graphic);
    assert.ok(drawn.every(text => !text.includes('undefined')), graphic);
  }
});
