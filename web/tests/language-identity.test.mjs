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
const { activeOverlays, languageNotice } = loadTs(`${web}/src/render/schedule.ts`);
const { findPlayer, overlayIdentity } = loadTs(`${web}/src/data/identity.ts`);
const { renderEvidence } = loadTs(`${web}/src/ui/evidence.ts`);
const { buildRoster, drawOverlays } = loadTs(`${web}/src/render/draw.ts`);
const { buildCamera } = loadTs(`${web}/src/render/camera.ts`);
const ajv = new Ajv({ strict: false });
const validEvent = ajv.compile(json('schemas/event.schema.json'));
const validOverlay = ajv.compile(json('schemas/overlay.schema.json'));

// Explicitly synthetic UI fixtures. No text or CV attribution here is an agent/detector result.
const pass = { ...sample.find(e => e.type === 'pass'), id: 'e9101', source: 'cv', confidence: 0.76, from: null, to: null, distance_m: 28 };
const shot = { ...sample.find(e => e.type === 'shot'), id: 'e9102', source: 'cv', from: null, to: null };
const foul = { ...sample.find(e => e.type === 'foul'), id: 'e9103', source: 'sim', from: null, to: null };
const events = new Map([pass, shot, foul].map(e => [e.id, e]));
const base = { id: 'o9101', start: 0, duration: 60, graphic: 'pass_card', event_ids: [pass.id], player: null, position: 'follow-player', title: 'Synthetic test only', text: 'Synthetic test only', mode: 'analyst', lang: 'en' };

function context() {
  const text = [];
  const target = { font: '', fillText(value) { text.push(value); }, measureText(value) { return { width: value.length * Number(/([\d.]+)px/.exec(this.font)?.[1] ?? 10) * 0.6 }; } };
  return { text, ctx: new Proxy(target, { get: (o, k) => o[k] ?? (() => {}) }) };
}

test('EN/TR/ES filtering stays exact across timestamps and modes; Spanish fixtures are schema-valid', () => {
  const overlays = ['en', 'tr', 'es'].flatMap(lang => ['analyst', 'casual', 'player_focus'].map(mode => ({ ...base, lang, mode, text: lang === 'es' ? 'Prueba sintética: pase' : 'Synthetic test fixture' })));
  for (const o of overlays) assert.equal(validOverlay(o), true);
  for (const lang of ['en', 'tr', 'es']) for (const t of [0, 20, 5]) for (const mode of ['analyst', 'casual', 'player_focus']) {
    const active = activeOverlays(overlays, t, mode, lang);
    assert.equal(active.length, 1);
    assert.equal(active[0].lang, lang);
    assert.equal(active[0].mode, mode);
    assert.equal(languageNotice(overlays, lang, mode), '');
  }
});

test('missing Spanish never falls back to English, and missing modes are distinguished from timeline gaps', () => {
  assert.deepEqual(activeOverlays([base], 1, 'analyst', 'es'), []);
  assert.match(languageNotice([base], 'es', 'analyst'), /Spanish.*match/);
  const es = { ...base, lang: 'es', start: 10, duration: 5 };
  assert.match(languageNotice([es], 'es', 'casual'), /Spanish.*mode/);
  assert.equal(languageNotice([es], 'es', 'analyst'), '');
  assert.deepEqual(activeOverlays([es], 0, 'analyst', 'es'), []);
});

test('schema-valid null/missing player actions resolve to their cited team and deterministic description', () => {
  for (const e of [pass, shot, foul]) assert.equal(validEvent(e), true);
  assert.equal(findPlayer(info, null), undefined);
  assert.equal(findPlayer(info, 9999), undefined);
  const identity = overlayIdentity(base, events, info);
  assert.equal(identity.player, undefined);
  assert.equal(identity.team, 'home');
  assert.equal(identity.description, 'Bosphorus FC pass, 28 m');
  assert.equal(overlayIdentity({ ...base, lang: 'es' }, events, info).description, 'Bosphorus FC pase, 28 m');
  const missing = { ...pass }; delete missing.from;
  assert.equal(validEvent(missing), true);
  assert.equal(overlayIdentity({ ...base, player: 8 }, new Map([[pass.id, missing]]), info).player, undefined);
});

test('shot identity comes from the shot rather than its setup or a simulator citation', () => {
  const awayShot = { ...shot, team: 'away' };
  const local = new Map([...events, [shot.id, awayShot]]);
  const identity = overlayIdentity({ ...base, graphic: 'shot_card', event_ids: [pass.id, shot.id, foul.id] }, local, info);
  assert.equal(identity.player, undefined);
  assert.equal(identity.team, 'away');
  assert.match(identity.description, /^Thames United shot/);
});

test('unavailable follow-player anchors become stable bottom-left cards with a CV/SIM source chip', () => {
  const first = JSON.parse(readFileSync(new URL('../../data/fake/sample_a/tracking.jsonl', import.meta.url), 'utf8').split('\n')[0]);
  const match = { info, frames: [first] };
  const camera = buildCamera('cv_full_pitch', match, 10, 16 / 9);
  for (const e of [pass, shot]) for (const player of [null, undefined, 9999]) {
    const o = { ...base, graphic: e.type === 'shot' ? 'shot_card' : 'pass_card', player, event_ids: [e.id, foul.id] };
    const { ctx, text } = context();
    const draw = t => drawOverlays(ctx, 1280, 720, [o], buildRoster(info), events, match, t, camera);
    const regions = draw(10);
    assert.equal(regions.length, 1);
    assert.equal(regions[0].x, 24);
    assert.deepEqual(draw(12).map(r => [r.x, r.y, r.w, r.h]), regions.map(r => [r.x, r.y, r.w, r.h]));
    assert.ok(text.some(v => /^AI · \d+% \+ SIM$/.test(v)));
    assert.ok(text.some(v => v.includes(info.home.name)));
    assert.ok(text.every(v => !v.includes('undefined')));
  }
  const known = { ...pass, from: 8 };
  const { ctx } = context();
  assert.equal(drawOverlays(ctx, 1280, 720, [base], buildRoster(info), new Map([[pass.id, known]]), match, 10, camera)[0].x, 24);
  const emptyMatch = { info, frames: [{ ...first, players: [] }] };
  assert.equal(drawOverlays(ctx, 1280, 720, [{ ...base, player: 8 }], buildRoster(info), new Map([[pass.id, known]]), emptyMatch, 10, camera)[0].x, 24);
});

test('card and evidence identities use arbitrary metadata names without false player chips', () => {
  const alternate = structuredClone(info);
  const home = json('simulator/teams/caldera.json'), away = json('simulator/teams/saltmarsh.json');
  Object.assign(alternate.home, { name: home.name, short: home.short, kit: home.kit });
  Object.assign(alternate.away, { name: away.name, short: away.short, kit: away.kit });
  const o = { ...base, event_ids: [pass.id, foul.id] };
  const panel = { innerHTML: '', classList: { remove() {} }, querySelector() { return null; } };
  renderEvidence(panel, o, events, alternate);
  assert.match(panel.innerHTML, /Caldera SC/);
  assert.match(panel.innerHTML, /CV\+SIM/);
  assert.match(panel.innerHTML, /CV confidence: 76%/);
  assert.doesNotMatch(panel.innerHTML, /class="chip|undefined|100%/);
  const { ctx, text } = context();
  for (const overlay of [o, { ...o, graphic: 'stat_compare' }]) {
    drawOverlays(ctx, 1280, 720, [overlay], buildRoster(alternate), events, { info: alternate, frames: [] }, 10);
  }
  assert.ok(text.includes(home.short)); assert.ok(text.includes(away.short));
  assert.ok(!text.includes('BOS') && !text.includes('THU'));
  const recipient = alternate.away.players[0];
  renderEvidence(panel, { ...base, event_ids: [foul.id] }, new Map([[foul.id, { ...foul, to: recipient.id }]]), alternate);
  assert.ok(panel.innerHTML.includes(recipient.name));
  assert.doesNotMatch(panel.innerHTML, />FROM</);
});
