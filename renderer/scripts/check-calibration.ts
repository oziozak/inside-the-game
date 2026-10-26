import { captureCanvas } from './lib/capture';
import assert from 'node:assert/strict';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { chromium } from 'playwright';
import { renderingServer } from './lib/server';
import { parseMatch, world } from '../src/data/match';
import type { CameraPreset } from '../src/scene/config';
const metadata = JSON.parse(await readFile('fixtures/calibration/match_info.json', 'utf8'));
const tracking = await readFile('fixtures/calibration/tracking.jsonl', 'utf8');
const match = parseMatch(metadata, tracking);
const artifactDir = process.env.RENDERER_TEST_ARTIFACT_DIR ?? '../data/renders';
const { server, closeServer } = await renderingServer();
let browser: Awaited<ReturnType<typeof chromium.launch>> | undefined;
try {
  await server.listen(); browser = await chromium.launch({ args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const reports = [];
  for (const camera of ['cv_full_pitch', 'broadcast'] as CameraPreset[]) {
    const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
    const requests: string[] = [], errors: string[] = [];
    page.on('request', req => requests.push(req.url())); page.on('pageerror', err => errors.push(err.message));
    await page.goto(`${server.resolvedUrls!.local[0]}?export=1`); await page.waitForFunction(() => !!window.broadcast);
    await page.evaluate(({ metadata, tracking, camera }) => {
      window.broadcast.load(metadata, tracking); window.broadcast.resize(1920, 1080);
      window.broadcast.configure({ camera, cvVisibility: true, ballScale: 2, playerScale: 1 });
    }, { metadata, tracking, camera });
    const sequential = await page.evaluate(() => Array.from({ length: 300 }, (_, i) => {
      window.broadcast.setTime(i / 25); return window.broadcast.inspect();
    }));
    for (const [i, state] of sequential.entries()) {
      assert.deepEqual(state.ball.position, world(match.frames[i].ball));
      for (const player of state.players) assert.deepEqual(player.position, world(match.frames[i].players.find(p => p.id === player.id)!.pos));
    }
    let repeatPixels = 0;
    for (const i of [0, 50, 100, 150, 200, 225, 299]) {
      await page.evaluate(t => window.broadcast.setTime(t), i / 25);
      assert.deepEqual(await page.evaluate(() => window.broadcast.inspect()), sequential[i], `${camera}: direct seek equals sequential frame ${i}`);
      const pixels = await captureCanvas(page);
      await page.evaluate(() => window.broadcast.setTime(1));
      await page.evaluate(t => window.broadcast.setTime(t), i / 25);
      assert.deepEqual(await captureCanvas(page), pixels);
      repeatPixels++;
    }
    if (camera === 'cv_full_pitch') assert.ok(sequential.every(s => JSON.stringify(s.camera) === JSON.stringify(sequential[0].camera)));
    assert.deepEqual(errors, []); assert.ok(!requests.some(r => /ground_truth|events|overlays/.test(r)));
    assert.equal(await page.locator('#clock').isVisible(), false);
    await mkdir(artifactDir, { recursive: true });
    await page.evaluate(() => window.broadcast.setTime(3));
    await captureCanvas(page, { path: `${artifactDir}/calibration-${camera}-preview.png` });
    reports.push({ camera, frames: sequential.length, coordinateChecks: 'all frames match tracking', directSeekChecks: repeatPixels, repeatedPixelChecks: repeatPixels, minProjectedBallDiameterPx: Math.min(...sequential.map(s => s.ball.projectedDiameterPx)), maxProjectedBallDiameterPx: Math.max(...sequential.map(s => s.ball.projectedDiameterPx)), playerOccludedCenterFrames: sequential.filter(s => s.ball.centerOccludedByPlayer).length });
    await page.close();
  }
  await writeFile(`${artifactDir}/calibration-checks.json`, JSON.stringify(reports, null, 2));
  console.log(JSON.stringify(reports, null, 2));
} finally { try { await browser?.close(); } finally { await closeServer(); } }
