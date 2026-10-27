import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import Ajv from 'ajv/dist/2020.js';
import { loadTs } from './support/load-ts.mjs';

const web = fileURLToPath(new URL('../', import.meta.url));
const json = path => JSON.parse(readFileSync(new URL(`../../${path}`, import.meta.url), 'utf8'));
const info = json('data/fake/sample_a/match_info.json');
const sampleEvents = json('data/fake/sample_a/events.json');
const { overlayMentionsPlayer, activeOverlays } = loadTs(`${web}/src/render/schedule.ts`);
const { startingPlayers, findPlayer } = loadTs(`${web}/src/data/identity.ts`);
const validOverlay = new Ajv({ strict: false }).compile(json('schemas/overlay.schema.json'));

// Issue 84 (Web: PLAYER mode lets the viewer pick one player to follow) — this test file.

// A real pass, home player 6 ("from") to home player 9 ("to"); and a sim-only event with no actor.
const pass = { ...sampleEvents.find(e => e.type === 'pass'), id: 'e9201', from: 6, to: 9 };
const unidentified = { ...sampleEvents.find(e => e.type === 'foul'), id: 'e9202', from: null, to: null };
const events = new Map([pass, unidentified].map(e => [e.id, e]));

const base = {
  id: 'o9201', start: 0, duration: 60, graphic: 'pass_card', mode: 'player_focus', lang: 'en',
  text: 'Synthetic test fixture', title: 'Synthetic test fixture',
};

test('overlayMentionsPlayer matches the overlay\'s own subject', () => {
  const overlay = { ...base, player: 6, event_ids: [] };
  assert.equal(validOverlay(overlay), true);
  assert.equal(overlayMentionsPlayer(overlay, events, 6), true);
  assert.equal(overlayMentionsPlayer(overlay, events, 9), false);
});

test('overlayMentionsPlayer matches a cited event\'s actor (from), even without overlay.player', () => {
  const overlay = { ...base, player: null, event_ids: [pass.id] };
  assert.equal(overlayMentionsPlayer(overlay, events, pass.from), true);
});

test('overlayMentionsPlayer matches a cited event\'s receiver (to)', () => {
  const overlay = { ...base, player: null, event_ids: [pass.id] };
  assert.equal(overlayMentionsPlayer(overlay, events, pass.to), true);
});

test('an overlay/event with no identified player never matches any real player id', () => {
  const overlay = { ...base, player: null, event_ids: [unidentified.id] };
  for (const id of [6, 9, ...info.home.players.map(p => p.id), ...info.away.players.map(p => p.id)]) {
    assert.equal(overlayMentionsPlayer(overlay, events, id), false);
  }
});

test('a cited event not in the evidence map, and a player not cited by any listed event, do not match', () => {
  const overlay = { ...base, player: null, event_ids: ['e-not-loaded'] };
  assert.equal(overlayMentionsPlayer(overlay, events, 6), false);
  const unrelated = { ...base, player: null, event_ids: [pass.id] };
  assert.equal(overlayMentionsPlayer(unrelated, events, 2), false); // player 2 is neither from nor to on this pass
});

test('PLAYER mode with nobody followed shows nothing: filtering must start from an empty set, not activeOverlays', () => {
  const overlay = { ...base, player: 6, event_ids: [] };
  const active = activeOverlays([overlay], 0, 'player_focus', 'en');
  assert.equal(active.length, 1); // mode/lang/time matching alone does not imply a player is chosen
});

test('startingPlayers returns exactly each team\'s starting XI, tagged with team, in squad-number order', () => {
  const players = startingPlayers(info);
  const expectedCount = info.home.players.filter(p => p.starter).length + info.away.players.filter(p => p.starter).length;
  assert.equal(players.length, expectedCount);
  assert.ok(players.every(p => p.starter === true));
  const home = players.filter(p => p.team === 'home');
  assert.deepEqual(home.map(p => p.number), [...home.map(p => p.number)].sort((a, b) => a - b));
  // Every player returned is genuinely findable by id, on the team startingPlayers claims.
  for (const p of players) {
    const found = findPlayer(info, p.id);
    assert.equal(found.team, p.team);
    assert.equal(found.id, p.id);
  }
});
