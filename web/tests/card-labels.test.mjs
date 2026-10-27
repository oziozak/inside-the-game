import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { loadTs } from './support/load-ts.mjs';

const web = fileURLToPath(new URL('../', import.meta.url));
const json = path => JSON.parse(readFileSync(new URL(`../../${path}`, import.meta.url), 'utf8'));
const info = json('data/fake/sample_a/match_info.json');
const { buildRoster, drawOverlays, cardKind } = loadTs(`${web}/src/render/draw.ts`);
const { sourceChipText } = loadTs(`${web}/src/data/provenance.ts`);
const { renderEvidence } = loadTs(`${web}/src/ui/evidence.ts`);
const { clock } = loadTs(`${web}/src/render/schedule.ts`);

// Synthetic unit fixtures shaped like hl2's red-card graphic (#88 part 4); not agent or detector output.
const red = { id: 'e9101', match_id: info.match_id, t: 1091.78, period: 1, type: 'red_card', subtype: 'second_yellow', team: 'home', from: 10, to: null, source: 'sim', confidence: 1 };
const yellow = { ...red, id: 'e9102', type: 'yellow_card', subtype: undefined };
const goal = { id: 'e9103', match_id: info.match_id, t: 1980, period: 1, type: 'goal', team: 'home', from: 9, to: null, source: 'cv', confidence: 0.73 };
const events = new Map([red, yellow, goal].map(e => [e.id, e]));
const base = { id: 'o9101', start: 1092, duration: 6, player: 10, position: 'top-right', mode: 'analyst', lang: 'en', text: 'Second yellow' };
const banner = (event, extra = {}) => ({ ...base, graphic: 'card_banner', event_ids: [event.id], title: 'E. Demir sent off', values: { minute: 19 }, ...extra });

function draw(overlays) {
  const drawn = [];
  const target = { font: '', fillText(text) { drawn.push(text); }, measureText(text) { return { width: text.length * Number(/([\d.]+)px/.exec(this.font)?.[1] ?? 10) * 0.6 }; } };
  const ctx = new Proxy(target, { get: (o, k) => o[k] ?? (() => {}) });
  drawOverlays(ctx, 1280, 720, overlays, buildRoster(info), events, { info, frames: [] }, 1093);
  return drawn;
}

test('a card banner is labeled from the card it cites: RED CARD (second yellow too) or YELLOW CARD', () => {
  assert.equal(cardKind(banner(red), events), 'RED CARD');
  assert.equal(cardKind(banner(yellow), events), 'YELLOW CARD');
  assert.ok(draw([banner(red)]).includes('RED CARD'));
  assert.ok(draw([banner(yellow)]).includes('YELLOW CARD'));
});

test('stat_compare and momentum_bar get STATS / MOMENTUM; an unknown graphic gets no label', () => {
  assert.equal(cardKind({ ...base, graphic: 'stat_compare', event_ids: [] }, events), 'STATS');
  assert.equal(cardKind({ ...base, graphic: 'momentum_bar', event_ids: [] }, events), 'MOMENTUM');
  assert.equal(cardKind({ ...base, graphic: 'mystery_widget', event_ids: [] }, events), '');
  assert.equal(cardKind({ ...base, graphic: 'card_banner', event_ids: [goal.id] }, events), '');
});

test('no card draws a raw graphic type name', () => {
  const graphics = ['pass_card', 'shot_card', 'goal_banner', 'card_banner', 'stat_compare', 'momentum_bar', 'insight_text', 'mystery_widget'];
  for (const graphic of graphics) {
    const drawn = draw([{ ...base, graphic, event_ids: [red.id], title: undefined, values: { shots_home: 2, shots_away: 1 } }]);
    for (const text of drawn) assert.doesNotMatch(text, /_|CARD BANNER|STAT COMPARE|MOMENTUM BAR|MYSTERY/i, `${graphic}: "${text}"`);
  }
});

test('card and goal banners show one time: the header clock, no MINUTE cell', () => {
  const goalBanner = { ...base, id: 'o9102', graphic: 'goal_banner', position: 'bottom-center', event_ids: [goal.id], title: 'Bosphorus FC strike again', values: { score_home: 2, score_away: 0, minute: 33 } };
  const drawn = draw([banner(red), goalBanner]);
  assert.ok(drawn.includes(clock(base.start, info.periods)));
  assert.ok(!drawn.some(text => /^MINUTE$/i.test(text)), 'MINUTE cell drawn');
  assert.ok(!drawn.includes('19') && !drawn.includes('33'));
  assert.ok(drawn.includes('SCORE HOME') && drawn.includes('2'));
});

test('cards draw a small source chip (AI · 73% / SIM) and no SOURCE block', () => {
  assert.equal(sourceChipText({ event_ids: [goal.id] }, events), 'AI · 73%');
  assert.equal(sourceChipText({ event_ids: [red.id] }, events), 'SIM');
  assert.equal(sourceChipText({ event_ids: ['e0000'] }, events), undefined);
  const drawn = draw([banner(red), { ...base, id: 'o9103', graphic: 'goal_banner', position: 'bottom-center', event_ids: [goal.id], values: {} }]);
  assert.ok(drawn.includes('SIM') && drawn.includes('AI · 73%'));
  assert.ok(drawn.every(text => !/SOURCE|SIMULATOR|EVENT EVIDENCE/.test(text)));
});

test('the evidence panel still shows the full source', () => {
  const panel = { innerHTML: '', classList: { remove() {} }, querySelector() { return null; } };
  renderEvidence(panel, banner(red), events, info);
  assert.match(panel.innerHTML, /SIM · Simulator/);
  renderEvidence(panel, { ...base, graphic: 'goal_banner', event_ids: [goal.id] }, events, info);
  assert.match(panel.innerHTML, /CV · Detected from video/);
  assert.match(panel.innerHTML, /CV confidence: 73%/);
});
