import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, rm, readFile } from 'node:fs/promises';
import { createWriteStream } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { pipeline } from 'node:stream/promises';
import { Readable } from 'node:stream';
import { loadInterval } from '../scripts/lib/interval';
import { parseMatch, sample, type Frame, type Match } from '../src/data/match';
import { cameraTarget } from '../src/camera/tracking';
import { exportTimes } from '../src/playback/timing';
let root: string, path: string, metadata: Match['info'];
const row = (i: number): Frame => ({ match_id: metadata.match_id, frame: i, t: i / 25,
  period: i < 67500 ? 1 : 2, ball: [50 + 20 * Math.sin(i / 90), 34, i % 7 / 10 + 0.11],
  players: [{ id: 8, team: 'home', pos: [45, 30] }],
});
before(async () => {
  root = await mkdtemp(join(tmpdir(), 'renderer-interval-')); path = join(root, 'full.jsonl');
  metadata = JSON.parse(await readFile(new URL('../../data/fake/sample_a/match_info.json', import.meta.url), 'utf8'));
  metadata.periods = [{ period: 1, start: 0, end: 2700 }, { period: 2, start: 2700, end: 5400 }];
  function* lines() { for (let i = 0; i < 135000; i++) yield JSON.stringify(row(i)) + '\n'; }
  await pipeline(Readable.from(lines()), createWriteStream(path));
});
after(async () => { if (root) await rm(root, { recursive: true, force: true }); });

test('90-minute input retains only a short context window with absolute frame IDs and timestamps', async () => {
  const interval = await loadInterval(metadata, path, { start: 2400, end: 2410 });
  assert.equal(interval.stats.totalFrames, 135000);
  assert.ok(interval.stats.retainedFrames < 280);
  assert.ok(interval.stats.payloadBytes < interval.stats.inputBytes / 100);
  const times = exportTimes(interval.start, interval.end);
  assert.equal(times.length, 250); assert.equal(times[0], 2400); assert.equal(times.at(-1), 2409.96);
  assert.equal(sample(interval.match, times[0]).frame, 60000);
  assert.equal(sample(interval.match, times.at(-1)!).frame, 60249);
  for (const frame of interval.match.frames) assert.deepEqual(frame, row(frame.frame));
});

test('window and pre-trimmed input agree for fractional starts, interpolation and full camera history', async () => {
  const options = { start: 2400.013, end: 2410.013 };
  const full = await loadInterval(metadata, path, options);
  const expected = parseMatch(metadata, Array.from({ length: 400 }, (_, i) => JSON.stringify(row(59950 + i))).join('\n'));
  const trimmedPath = join(root, 'trimmed.jsonl');
  await writeFile(trimmedPath, expected.frames.map(f => JSON.stringify(f)).join('\n'));
  const trimmed = await loadInterval(metadata, trimmedPath, options);
  assert.deepEqual(full.match, trimmed.match);
  assert.ok(full.match.frames[0].t < options.start - 0.8);
  for (const t of exportTimes(options.start, options.end)) {
    assert.deepEqual(sample(full.match, t), sample(expected, t));
    assert.deepEqual(cameraTarget(full.match, t), cameraTarget(expected, t));
  }
});

test('half-time context and sparse samples preserve hold and interpolation behavior', async () => {
  const frames = [row(67450), row(67470), row(67499), row(67500), row(67501), row(67600), row(67601)];
  // Long gaps straddle both selection boundaries; outside neighbors must not be dropped.
  const sparsePath = join(root, 'sparse.jsonl');
  await writeFile(sparsePath, frames.map(f => JSON.stringify(f)).join('\n'));
  const expected = parseMatch(metadata, frames.map(f => JSON.stringify(f)).join('\n'));
  for (const options of [{ start: 2699.98, end: 2700.1 }, { start: 2702, end: 2703 }]) {
    const { match } = await loadInterval(metadata, sparsePath, options);
    for (const t of exportTimes(options.start, options.end)) {
      assert.deepEqual(sample(match, t), sample(expected, t));
      assert.deepEqual(cameraTarget(match, t), cameraTarget(expected, t));
    }
  }
  const { match } = await loadInterval(metadata, sparsePath, { start: 2702, end: 2703 });
  assert.equal(sample(match, 2702).frame, 67501);
  assert.equal(match.frames.at(-1)!.frame, 67600);
});

test('coverage, invalid intervals, empty and malformed/out-of-order input produce useful errors', async () => {
  const small = join(root, 'small.jsonl');
  await writeFile(small, [row(100), row(101)].map(f => JSON.stringify(f)).join('\n'));
  for (const options of [{ start: 3, end: 4 }, { start: 4, end: 5 }, { start: 4.08, end: 4.09 }]) {
    await assert.rejects(loadInterval(metadata, small, options), /outside tracking coverage/);
  }
  await assert.rejects(loadInterval(metadata, small, { start: 4, end: NaN }), /finite interval/);
  await assert.rejects(loadInterval(metadata, small, { start: 5, end: 4 }), /finite interval/);
  await assert.rejects(loadInterval(metadata, small, { end: 1 }), /Expected start < end/);
  const tail = await loadInterval(metadata, small, { start: 4.05, end: 4.08 });
  assert.equal(sample(tail.match, 4.05).frame, 101);
  await writeFile(small, ''); await assert.rejects(loadInterval(metadata, small, { start: 0, end: 1 }), /empty/);
  await writeFile(small, JSON.stringify(row(0)) + '\n{');
  await assert.rejects(loadInterval(metadata, small, { start: 0, end: 0.01 }), /Invalid JSON on tracking line 2/);
  await writeFile(small, [row(10), row(9)].map(f => JSON.stringify(f)).join('\n'));
  await assert.rejects(loadInterval(metadata, small, { start: 0.4, end: 0.41 }), /increase strictly/);
});

test('streamed validation rejects corrupt schema records and identities beyond the retained window', async () => {
  const file = join(root, 'corrupt-after-window.jsonl');
  for (const bad of [
    { ...row(1000), ball: [1, 2] },
    { ...row(1000), match_id: 'wrong-match' },
    { ...row(1000), players: [{ id: 999, team: 'home', pos: [1, 2] }] },
    { ...row(1000), players: [row(1000).players[0], row(1000).players[0]] },
  ]) {
    await writeFile(file, [row(0), row(1), bad].map(f => JSON.stringify(f)).join('\n'));
    await assert.rejects(loadInterval(metadata, file, { start: 0, end: 0.04 }), /Tracking line 3|mismatch|Unknown player|Duplicate tracked/);
  }
});

test('a half-time boundary between sample timestamps retains the exact full-input cut behavior', async () => {
  const info = { ...metadata, periods: [{ period: 1, start: 0, end: 2700.005 }, { period: 2, start: 2700.015, end: 5400 }] };
  const frames = [67450, 67499, 67500, 67501, 67550].map(i => ({ ...row(i), period: (i / 25 < 2700.015 ? 1 : 2) as 1 | 2 }));
  const text = frames.map(f => JSON.stringify(f)).join('\n');
  const file = join(root, 'fractional-half.jsonl'); await writeFile(file, text);
  const expected = parseMatch(info, text);
  const { match } = await loadInterval(info, file, { start: 2699.99, end: 2700.12 });
  for (const t of [2699.99, 2700.01, 2700.015, 2700.02, 2700.04, 2700.08]) {
    assert.deepEqual(sample(match, t), sample(expected, t));
    assert.deepEqual(cameraTarget(match, t), cameraTarget(expected, t));
  }
  assert.equal(sample(match, 2700.02).frame, 67500, 'hold before first post-cut sample; do not blend the teleport');
});

test('calibration defaults, final sample, optional period and goal-area coordinates are preserved', async () => {
  const info = JSON.parse(await readFile(new URL('../fixtures/calibration/match_info.json', import.meta.url), 'utf8'));
  const file = new URL('../fixtures/calibration/tracking.jsonl', import.meta.url);
  const { match, start } = await loadInterval(info, file.pathname, { end: 12 });
  assert.equal(start, 0); assert.equal(match.frames.length, 300);
  assert.deepEqual(sample(match, 11.96).ball, [106, 34, 0.11]);
});
