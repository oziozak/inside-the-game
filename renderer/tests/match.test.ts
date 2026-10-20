import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parseMatch, sample, world } from '../src/data/match';
import { exportTimes, clock } from '../src/playback/timing';
const metadata = JSON.parse(readFileSync(new URL('../../data/fake/sample_a/match_info.json', import.meta.url), 'utf8'));
const tracking = readFileSync(new URL('../../data/fake/sample_a/tracking.jsonl', import.meta.url), 'utf8');
const match = parseMatch(metadata, tracking);
test('25 FPS export preserves every sample timestamp and frame identity', () => {
  const times = exportTimes(0, 60);
  assert.equal(times.length, 1500);
  for (const [i, t] of times.entries()) { assert.ok(Math.abs(t - match.frames[i].t) < 1e-9); assert.equal(sample(match, t).frame, i); }
  assert.deepEqual(exportTimes(3.12, 3.24), [3.12, 3.16, 3.2]);
  for (const [i, t] of exportTimes(2.4, 12.4).entries()) {
    assert.equal(sample(match, t), match.frames[60 + i], 'aligned nonzero interval returns the exact source frame');
  }
});
test('interpolation uses IDs even when input order changes, respects ball height, clamps endpoints', () => {
  const a = structuredClone(match.frames[0]), b = structuredClone(match.frames[1]);
  b.players.reverse(); b.players.find(p => p.id === a.players[0].id)!.pos = [10, 20];
  const short = { info: metadata, frames: [a, b] };
  const mid = sample(short, 0.02);
  assert.deepEqual(mid.players[0].pos, a.players[0].pos.map((x, i) => (x + [10, 20][i]) / 2));
  assert.equal(mid.ball[2], 0.12);
  assert.equal(sample(short, -1), a); assert.equal(sample(short, 100), b);
  assert.deepEqual(world([0, 0, 3]), [-52.5, 3, 34]);
});
test('half-time cuts and missing samples are held, not blended', () => {
  const a = match.frames[0], b = { ...match.frames[1], t: 1, frame: 25 };
  assert.equal(sample({ info: metadata, frames: [a, b] }, 0.5), a);
  const info = { ...metadata, periods: [{ period: 2, start: 0.04, end: 300 }] };
  assert.equal(sample({ info, frames: match.frames.slice(0, 2) }, 0.02), a);
  assert.equal(clock(304.17, metadata.periods), '45:00');
});
test('reject malformed data, cross-match IDs, duplicate identities and unordered frames', () => {
  assert.throws(() => parseMatch({}, tracking), /Match info/);
  assert.throws(() => parseMatch(metadata, ''), /empty/);
  assert.throws(() => parseMatch(metadata, '{'), /Invalid JSON/);
  assert.throws(() => parseMatch(metadata, JSON.stringify({ ...match.frames[0], match_id: 'other' })), /mismatch/);
  assert.throws(() => parseMatch(metadata, [match.frames[1], match.frames[0]].map(x => JSON.stringify(x)).join('\n')), /increase/);
  assert.throws(() => parseMatch(metadata, JSON.stringify({ ...match.frames[0], players: [match.frames[0].players[0], match.frames[0].players[0]] })), /Duplicate/);
  assert.throws(() => exportTimes(2, 1));
});
