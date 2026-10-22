import { captureCanvas } from './lib/capture';
import assert from 'node:assert/strict';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { parseArgs } from 'node:util';
import { chromium } from 'playwright';
import { renderingServer } from './lib/server';
import { loadInterval } from './lib/interval';
import { sample, world } from '../src/data/match';
import { exportTimes } from '../src/playback/timing';
import type { CameraPreset } from '../src/scene/config';
const { values } = parseArgs({ options: {
  metadata: { type: 'string', default: '../data/generated/renderer-m007/match_info.json' },
  tracking: { type: 'string', default: '../data/generated/renderer-m007/tracking.jsonl' },
  start: { type: 'string', default: '2503' }, end: { type: 'string', default: '2513' },
} });
const metadata = JSON.parse(await readFile(values.metadata!, 'utf8'));
const start = Number(values.start), end = Number(values.end), times = exportTimes(start, end);
const interval = await loadInterval(metadata, values.tracking!, { start, end });
const reference = await loadInterval(metadata, values.tracking!, { start: Math.max(interval.stats.coverageStart, start - 1), end: Math.min(interval.stats.coverageEnd, end + 0.04) });
const trimmedFolder = '../data/generated/renderer-integration-trimmed/';
await mkdir(trimmedFolder, { recursive: true });
await writeFile(trimmedFolder + 'tracking.jsonl', reference.tracking);
await writeFile(trimmedFolder + 'match_info.json', JSON.stringify(metadata, null, 2));
const { server, closeServer } = await renderingServer();
let browser: Awaited<ReturnType<typeof chromium.launch>> | undefined;
try {
  await server.listen(); browser = await chromium.launch({ args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  const errors: string[] = [], requests: string[] = [];
  page.on('pageerror', err => errors.push(err.message)); page.on('request', req => requests.push(req.url()));
  await page.goto(`${server.resolvedUrls!.local[0]}?export=1`); await page.waitForFunction(() => !!window.broadcast);
  const results = [];
  for (const camera of ['cv_full_pitch', 'broadcast'] as CameraPreset[]) {
    await page.evaluate(({ metadata, tracking, camera }) => {
      window.broadcast.load(metadata, tracking); window.broadcast.resize(1920, 1080);
      window.broadcast.configure({ camera, cvVisibility: true, ballScale: 2, playerScale: 1 });
    }, { metadata, tracking: interval.tracking, camera });
    const states = await page.evaluate(times => times.map(t => { window.broadcast.setTime(t); return window.broadcast.inspect(); }), times);
    for (const [i, state] of states.entries()) {
      const source = sample(interval.match, times[i]);
      assert.equal(state.players.length, 22);
      assert.equal(state.players.filter(p => p.team === 'home').length, 11);
      assert.equal(state.players.filter(p => p.team === 'away').length, 11);
      assert.deepEqual(state.ball.position, world(source.ball));
      for (const p of state.players) {
        const input = source.players.find(q => q.id === p.id)!;
        assert.deepEqual(p.position, world(input.pos));
        const team = interval.match.info[input.team as 'home' | 'away'];
        const roster = team.players.find(r => r.id === p.id)!;
        assert.equal(p.shirtColor, roster.pos === 'GK' ? team.kit.goalkeeper ?? team.kit.shirt : team.kit.shirt);
        assert.equal(p.shortsColor, team.kit.shorts);
      }
    }
    const compareIndices = [0, Math.floor(states.length / 2), states.length - 1];
    const captures = [];
    for (const i of compareIndices) {
      await page.evaluate(t => window.broadcast.setTime(t), times[i]);
      assert.deepEqual(await page.evaluate(() => window.broadcast.inspect()), states[i]);
      captures.push(await captureCanvas(page));
    }
    // Wider pre-trimmed data must produce identical framing and pixels, including the first frame.
    await page.evaluate(({ metadata, tracking }) => { window.broadcast.load(metadata, tracking); window.broadcast.resize(1920, 1080); }, { metadata, tracking: reference.tracking });
    for (const [n, i] of compareIndices.entries()) {
      await page.evaluate(t => window.broadcast.setTime(t), times[i]);
      assert.deepEqual(await page.evaluate(() => window.broadcast.inspect()), states[i]);
      assert.deepEqual(await captureCanvas(page), captures[n]);
    }
    // Player identities must survive array reordering; this uses the same real samples.
    const reordered = interval.match.frames.map(f => JSON.stringify({ ...f, players: [...f.players].reverse() })).join('\n');
    await page.evaluate(({ metadata, tracking, t }) => { window.broadcast.load(metadata, tracking); window.broadcast.resize(1920, 1080); window.broadcast.setTime(t); }, { metadata, tracking: reordered, t: start });
    const reversed = await page.evaluate(() => window.broadcast.inspect());
    assert.deepEqual(reversed.players.sort((a, b) => a.id - b.id), [...states[0].players].sort((a, b) => a.id - b.id));
    assert.deepEqual(reversed.ball, states[0].ball);
    await mkdir('../data/renders', { recursive: true });
    await captureCanvas(page, { path: `../data/renders/simulator-${camera}-preview.png` });
    results.push({ camera, framesChecked: states.length, playersPerFrame: 22, goalkeepersChecked: 2, directSeekAndTrimmedPixelChecks: compareIndices.length, reorderedIdentities: true });
  }
  assert.deepEqual(errors, []); assert.ok(!requests.some(r => /events|overlays/.test(r)));
  const report = { start, end, input: interval.stats, maxBallHeight: Math.max(...times.map(t => sample(interval.match, t).ball[2])), results };
  assert.ok(report.maxBallHeight > 0.11, 'selected interval must contain aerial ball motion');
  await writeFile('../data/renders/simulator-integration.json', JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
} finally { try { await browser?.close(); } finally { await closeServer(); } }
