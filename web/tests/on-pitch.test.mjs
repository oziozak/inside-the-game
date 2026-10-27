import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { loadTs } from './support/load-ts.mjs';

const web = fileURLToPath(new URL('../', import.meta.url));
const json = path => JSON.parse(readFileSync(new URL(`../../${path}`, import.meta.url), 'utf8'));
const info = json('data/fake/sample_a/match_info.json');
const { onPitchAt } = loadTs(`${web}/src/data/onPitch.ts`);

// Synthetic unit fixtures on sample_a's team sheet (periods 0-303.39, 304.39-605.04); not simulator output.
const ev = (id, t, type, from, to = null, extra = {}) => ({ id, match_id: info.match_id, t, type, from, to, source: 'sim', confidence: 1, ...extra });
const sub = ev('e9201', 400, 'substitution', 14, 6, { team: 'home' });            // #14 on for #6, 2nd half
const yellow1 = ev('e9202', 100, 'yellow_card', 110, null, { team: 'away' });
const yellow2 = ev('e9203', 200, 'yellow_card', 110, null, { team: 'away' });
const red = ev('e9204', 200, 'red_card', 110, null, { team: 'away', subtype: 'second_yellow' });
const ids = players => players.map(p => p.player.id);
const xi = side => info[side].players.filter(p => p.starter).map(p => p.id).sort((a, b) => a - b);

test('a clip with no substitution or card events shows the team sheet XI', () => {
  const pass = ev('e9200', 50, 'pass', 9, 10, { team: 'home' });
  for (const t of [0, 300, 9999]) {
    const teams = onPitchAt(info, [pass], t);
    for (const side of ['home', 'away']) {
      assert.deepEqual(ids(teams[side].on), xi(side));
      assert.deepEqual(teams[side].off, []);
      assert.deepEqual(teams[side].booked, []);
    }
  }
});

test('a substitution swaps the players at its time, not before; the sub takes the outgoing slot', () => {
  const before = onPitchAt(info, [sub], 399.99).home;
  assert.ok(ids(before.on).includes(6) && !ids(before.on).includes(14));
  const at = onPitchAt(info, [sub], 400).home;
  const slot = xi('home').indexOf(6);
  assert.equal(at.on[slot].player.id, 14);
  assert.equal(at.on[slot].on, 47);                  // 400 s is 95.6 s into the 2nd half: 47'
  assert.equal(at.on[slot].replaced.id, 6);
  assert.equal(at.on.length, 11);
  assert.deepEqual(at.off.map(o => [o.player.id, o.minute, o.reason, o.replacedBy.id]), [[6, 47, 'substituted', 14]]);
});

test('seeking back before a substitution restores the XI (no stored state)', () => {
  onPitchAt(info, [sub], 500);
  const back = onPitchAt(info, [sub], 10).home;
  assert.deepEqual(ids(back.on), xi('home'));
  assert.deepEqual(back.off, []);
});

test('a second yellow then red removes the player: 10 on the pitch, sent off with the minute', () => {
  const events = [yellow1, yellow2, red];
  const first = onPitchAt(info, events, 150).away;
  assert.equal(first.on.length, 11);
  assert.ok(first.on.find(p => p.player.id === 110).booked);
  assert.deepEqual(first.booked.map(p => p.id), [110]);
  const after = onPitchAt(info, events, 200).away;
  assert.equal(after.on.length, 10);
  assert.ok(!ids(after.on).includes(110));
  assert.deepEqual(after.off.map(o => [o.player.id, o.minute, o.reason]), [[110, 4, 'sent_off']]);
  assert.equal(onPitchAt(info, events, 200).home.on.length, 11);
});

test('events after t change nothing; unknown players and impossible substitutions are ignored', () => {
  const later = [ev('e9205', 600, 'red_card', 9, null, { team: 'home' }), { ...sub, t: 590 }];
  assert.deepEqual(onPitchAt(info, later, 500), onPitchAt(info, [], 500));
  const odd = [ev('e9206', 10, 'red_card', 999), ev('e9207', 20, 'substitution', 17, 999), ev('e9208', 30, 'substitution', 114, 6)];
  assert.deepEqual(onPitchAt(info, odd, 100), onPitchAt(info, [], 100));
});

test('event order in the file does not matter; a yellow before coming on carries over to the sub', () => {
  const events = [sub, ev('e9209', 350, 'yellow_card', 14, null, { team: 'home' })];
  assert.deepEqual(onPitchAt(info, events, 500), onPitchAt(info, [...events].reverse(), 500));
  assert.ok(onPitchAt(info, events, 500).home.on.find(p => p.player.id === 14).booked);
});

const { renderLineupCard, renderOnPitchPanel, renderLineups, clipStartLabel } = loadTs(`${web}/src/ui/lineups.ts`);
const element = () => ({ innerHTML: '', hidden: true, classList: { remove() {} }, querySelector() { return null; } });

test('the lineup card shows the clip start minute and score, both XIs and anyone already off', () => {
  const midMatch = { ...info, score_at_start: { home: 3, away: 0 } };
  assert.equal(clipStartLabel(midMatch, [], 240), "5' · 3–0");
  const card = element();
  renderLineupCard(card, midMatch, [yellow1, yellow2, red], 240, () => {});
  assert.equal(card.hidden, false);
  assert.match(card.innerHTML.replaceAll('&#39;', "'"), /5' · 3–0/);
  for (const side of ['home', 'away']) assert.match(card.innerHTML, new RegExp(info[side].formation));
  assert.match(card.innerHTML, /SENT OFF 4'/);
  assert.match(card.innerHTML, /4-4-2 · 10|· 10</);
  assert.match(card.innerHTML, /SKIP/);
});

test('the ON THE PITCH panel and the Lineups section follow onPitchAt at the current time', () => {
  const panel = element();
  renderOnPitchPanel(panel, info, [sub, yellow1, yellow2, red], 500, () => {});
  assert.match(panel.innerHTML, /ON THE PITCH · 49'/);
  assert.match(panel.innerHTML, /10 PLAYERS/);
  assert.match(panel.innerHTML, /SENT OFF 4'/);
  assert.match(panel.innerHTML, /ON 47'/);
  assert.match(panel.innerHTML, /OFF 47' · 14 /);
  assert.doesNotMatch(panel.innerHTML, /SIM|source/i);
  renderOnPitchPanel(panel, info, [sub, yellow1, yellow2, red], 50, () => {});
  assert.doesNotMatch(panel.innerHTML, /10 PLAYERS|OFF/);
  const home = element(), away = element();
  renderLineups(home, away, info, [sub], 500);
  assert.match(home.innerHTML, /data-player-id="14"/);
  assert.doesNotMatch(home.innerHTML, /data-player-id="6"/);
});
