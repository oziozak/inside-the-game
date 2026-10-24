import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import { chromium } from 'playwright';
import { captureCanvas } from './lib/capture';
import { artifactDirectory } from './lib/paths';
import { renderingServer } from './lib/server';
const artifactDir = await artifactDirectory();
const { server, closeServer } = await renderingServer();
let browser: Awaited<ReturnType<typeof chromium.launch>> | undefined;
try {
  await server.listen();
  browser = await chromium.launch({ args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 }, deviceScaleFactor: 1 });
  const errors: string[] = []; const requests: string[] = [];
  page.on('pageerror', e => errors.push(e.message)); page.on('request', req => requests.push(req.url()));
  await page.goto(server.resolvedUrls!.local[0]);
  await page.waitForFunction(() => !document.querySelector<HTMLButtonElement>('#play')!.disabled);
  assert.match(await page.locator('#status').innerText(), /1500 tracking frames/);
  const metadata = JSON.parse(await readFile('../data/fake/sample_a/match_info.json', 'utf8'));
  assert.equal(await page.locator('#home-name').innerText(), metadata.home.name);
  assert.equal(await page.locator('#away-name').innerText(), metadata.away.name);
  const a = await page.evaluate(() => window.broadcast.setTime(2.4));
  assert.equal(a.inputFrame, 60); assert.equal(a.playerIds.length, 22);
  const image1 = await captureCanvas(page);
  await page.evaluate(() => window.broadcast.setTime(12));
  const image2 = await captureCanvas(page); assert.notDeepEqual(image1, image2);
  await page.evaluate(() => window.broadcast.setTime(2.4));
  assert.deepEqual(await captureCanvas(page), image1, 'same absolute time must reproduce pixels');
  await page.locator('#play').click(); await page.waitForTimeout(180); await page.locator('#play').click();
  assert.ok(Number(await page.locator('#seek').inputValue()) > 2.4);
  await page.locator('#speed').selectOption('2');
  await page.locator('#seek').fill('4'); await page.locator('#seek').dispatchEvent('input');
  assert.equal(await page.locator('#seek').inputValue(), '4');
  await page.locator('#debug').uncheck(); assert.equal(await page.locator('#clock').isVisible(), false);
  await page.locator('#rich').check();
  await page.screenshot({ path: `${artifactDir}/renderer-preview.png` });
  await page.locator('#rich').uncheck();
  await page.evaluate(() => window.broadcast.setTime(2.4));
  const before = await page.evaluate(() => window.broadcast.inspect());
  await page.locator('#player-scale').fill('1.5'); await page.locator('#player-scale').dispatchEvent('change');
  await page.locator('#ball-scale').fill('3'); await page.locator('#ball-scale').dispatchEvent('change');
  const scaled = await page.evaluate(() => window.broadcast.inspect());
  assert.deepEqual(scaled.players.map(p => p.position), before.players.map(p => p.position));
  assert.deepEqual(scaled.ball.position, before.ball.position);
  assert.ok(scaled.players.every(p => p.scale.every(v => v === 1.5)));
  assert.deepEqual(scaled.ball.scale, [3, 3, 3]);
  assert.notDeepEqual(await captureCanvas(page), image1);
  await page.evaluate(() => window.broadcast.setTime(12));
  assert.deepEqual((await page.evaluate(() => window.broadcast.inspect())).camera, scaled.camera);
  await page.locator('#camera').selectOption('broadcast');
  await page.evaluate(() => window.broadcast.setTime(2.4));
  const closer = await page.evaluate(() => window.broadcast.inspect());
  assert.notDeepEqual(closer.camera.position, scaled.camera.position);
  assert.deepEqual(closer.ball.position, scaled.ball.position);
  const broadcastState = await page.evaluate(() => window.broadcast.inspect());
  const broadcastLayout = await page.locator('canvas').boundingBox();
  const broadcastImage = await captureCanvas(page);
  await page.evaluate(() => window.broadcast.setTime(12));
  await page.evaluate(() => window.broadcast.setTime(2.4));
  const repeatState = await page.evaluate(() => window.broadcast.inspect());
  const repeatImage = await captureCanvas(page);
  try {
    assert.deepEqual(repeatState, broadcastState, 'broadcast scene state must repeat exactly');
    assert.deepEqual(repeatImage, broadcastImage, 'broadcast screenshot must repeat byte-for-byte');
  } catch (error) {
    await Promise.all([
      writeFile(`${artifactDir}/broadcast-before.png`, broadcastImage),
      writeFile(`${artifactDir}/broadcast-after.png`, repeatImage),
      writeFile(`${artifactDir}/broadcast-repeat.json`, JSON.stringify({
        before: { state: broadcastState, layout: broadcastLayout },
        after: { state: repeatState, layout: await page.locator('canvas').boundingBox() },
        serverUrl: server.resolvedUrls!.local[0],
      }, null, 2)),
    ]);
    throw error;
  }
  const renamed = structuredClone(metadata);
  renamed.home.name = 'Bosphorus Reserves'; renamed.away.name = 'Thames Reserves';
  await page.locator('#metadata').setInputFiles({ name: 'match_info.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(renamed)) });
  await page.locator('#tracking').setInputFiles('../data/fake/sample_a/tracking.jsonl');
  await page.locator('#load').click();
  await page.waitForFunction(() => document.querySelector('#home-name')?.textContent === 'Bosphorus Reserves');
  assert.equal(await page.locator('#away-name').innerText(), renamed.away.name);
  await page.goto(`${server.resolvedUrls!.local[0]}?export=1`);
  await page.waitForFunction(() => !!window.broadcast);
  assert.equal(await page.locator('#clock').isVisible(), false);
  assert.equal(await page.locator('#controls').isVisible(), false);
  assert.deepEqual(errors, []); assert.ok(!requests.some(url => /events|overlays/.test(url)));
  console.log('Browser passed: metadata team names on initial load and file reload, playback, both camera presets, geometry scaling without coordinate changes, reproducible pixels, clean export mode; no event requests.');
} finally { try { await browser?.close(); } finally { await closeServer(); } }
