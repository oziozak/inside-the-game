import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import { parseArgs } from 'node:util';
import { chromium } from 'playwright';
import { PerspectiveCamera, Vector3 } from 'three';
import { captureCanvas } from './lib/capture';
import { loadInterval } from './lib/interval';
import { artifactDirectory, simulatorOptions } from './lib/paths';
import { renderingServer } from './lib/server';

const { values } = parseArgs({ options: { ...simulatorOptions, baseline: { type: 'boolean', default: false }, rich: { type: 'boolean', default: false }, 'clean-reference': { type: 'boolean', default: false } } });
const metadata = JSON.parse(await readFile(values.metadata!, 'utf8'));
const start = Number(values.start), end = Number(values.end);
const interval = await loadInterval(metadata, values.tracking!, { start, end });
const artifacts = await artifactDirectory();
const { server, closeServer } = await renderingServer();
let browser: Awaited<ReturnType<typeof chromium.launch>> | undefined;
try {
  await server.listen();
  browser = await chromium.launch({ args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  await page.goto(`${server.resolvedUrls!.local[0]}?export=1`); await page.waitForFunction(() => !!window.broadcast);
  await page.evaluate(({ metadata, tracking, rich, clean }) => {
    window.broadcast.load(metadata, tracking); window.broadcast.resize(1920, 1080);
    window.broadcast.configure({ camera: clean ? 'cv_full_pitch' : 'broadcast', cvVisibility: true, ballScale: 2 });
    window.broadcast.setRich(rich);
  }, { metadata, tracking: interval.tracking, rich: values.rich!, clean: values['clean-reference']! });
  const states = [];
  for (const t of [start, start + (end - start) / 2, end - 0.04]) {
    await page.evaluate(t => window.broadcast.setTime(t), t);
    states.push(await page.evaluate(() => window.broadcast.inspect()));
    await captureCanvas(page, { path: `${artifacts}/broadcast-${t}.png` });
  }
  assert.ok(states.every(state => state.players.length === 22));
  const projections = states.map(state => {
    const camera = new PerspectiveCamera(state.camera.fov, 16 / 9, 0.1, 400);
    camera.position.fromArray(state.camera.position); camera.quaternion.fromArray(state.camera.quaternion);
    camera.zoom = state.camera.zoom; camera.updateProjectionMatrix(); camera.updateMatrixWorld(true);
    const ball = new Vector3(...state.ball.position).project(camera);
    assert.ok(Math.abs(ball.x) < 1 && Math.abs(ball.y) < 1 && Math.abs(ball.z) < 1, 'active ball must be framed in the selected simulator views');
    const goalX = state.ball.position[0] < 0 ? -52.5 : 52.5;
    const goalVisible = [-3.66, 3.66].every(z => [0, 2.44].every(y => {
      const point = new Vector3(goalX, y, z).project(camera);
      return Math.abs(point.x) < 1 && Math.abs(point.y) < 1 && Math.abs(point.z) < 1;
    }));
    return { ball: ball.toArray(), nearestGoalVisible: goalVisible };
  });
  if (!values.baseline) {
    // Rich mode must be reversible, including pixels after restoring the clean materials/lights.
    const originalRich = values.rich!;
    await page.evaluate(t => window.broadcast.setTime(t), start);
    const originalPixels = await captureCanvas(page);
    const originalState = await page.evaluate(() => window.broadcast.inspect());
    await page.evaluate(rich => window.broadcast.setRich(rich), !originalRich);
    assert.deepEqual((await page.evaluate(() => window.broadcast.inspect())).players.map(p => p.position), originalState.players.map(p => p.position));
    await page.evaluate(rich => window.broadcast.setRich(rich), originalRich);
    assert.deepEqual(await page.evaluate(() => window.broadcast.inspect()), originalState);
    assert.deepEqual(await captureCanvas(page), originalPixels);
    // Number/motion controls are independent; compare anchors and return to the same pose/pixels.
    const t = start + (end - start) / 2;
    await page.evaluate(t => { window.broadcast.setTime(t); window.broadcast.configure({ jerseyNumbers: true }); }, t);
    const numbered = await page.evaluate(() => window.broadcast.inspect());
    assert.deepEqual(numbered.players.map(p => p.position), states[1].players.map(p => p.position));
    for (const player of numbered.players) {
      const roster = metadata[player.team].players.find((p: { id: number }) => p.id === player.id);
      assert.equal(player.jerseyNumber, roster.number); assert.equal(player.numberVisible, true);
    }
    const pixels = await captureCanvas(page);
    await page.evaluate(t => { window.broadcast.setTime(t); window.broadcast.configure({ animatePlayers: false, cvVisibility: false }); }, start);
    await page.evaluate(t => { window.broadcast.configure({ animatePlayers: true, cvVisibility: true }); window.broadcast.setTime(t); }, t);
    assert.deepEqual(await page.evaluate(() => window.broadcast.inspect()), numbered);
    assert.deepEqual(await captureCanvas(page), pixels);
    await page.evaluate(() => window.broadcast.setRich(true));
    await captureCanvas(page, { path: `${artifacts}/broadcast-rich-numbers.png` });
    // Exercise aspect changes without implying that distant shirt numbers are OCR-readable.
    await page.evaluate(() => window.broadcast.resize(640, 640));
    await captureCanvas(page, { path: `${artifacts}/broadcast-square.png` });
  }
  await writeFile(`${artifacts}/presentation.json`, JSON.stringify({ start, end, baseline: values.baseline, states, projections }, null, 2));
  console.log(`Saved ${states.length} genuine simulator views to ${artifacts}`);
} finally { try { await browser?.close(); } finally { await closeServer(); } }
