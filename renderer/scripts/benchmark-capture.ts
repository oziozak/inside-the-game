import { spawn } from 'node:child_process';
import { readFile, writeFile } from 'node:fs/promises';
import { cpus, platform, release, totalmem } from 'node:os';
import { parseArgs } from 'node:util';
import { chromium } from 'playwright';
import { exportTimes } from '../src/playback/timing';
import { captureCanvas } from './lib/capture';
import { loadInterval } from './lib/interval';
import { artifactDirectory, simulatorOptions } from './lib/paths';
import { renderingServer } from './lib/server';

// The unsynchronized variant exists only here; production always uses captureCanvas.
const { values } = parseArgs({ options: { ...simulatorOptions, runs: { type: 'string', default: '3' }, rich: { type: 'boolean', default: false }, 'synchronized-only': { type: 'boolean', default: false } } });
const runs = Number(values.runs);
if (!Number.isInteger(runs) || runs < 1) throw new Error('runs must be a positive integer');
const metadata = JSON.parse(await readFile(values.metadata!, 'utf8'));
const start = Number(values.start), end = Number(values.end);
const interval = await loadInterval(metadata, values.tracking!, { start, end });
const times = exportTimes(start, end), artifacts = await artifactDirectory();
const { server, closeServer } = await renderingServer();
let browser: Awaited<ReturnType<typeof chromium.launch>> | undefined;
try {
  await server.listen();
  browser = await chromium.launch({ args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  await page.goto(`${server.resolvedUrls!.local[0]}?export=1`);
  await page.waitForFunction(() => !!window.broadcast);
  await page.evaluate(({ metadata, tracking, rich }) => {
    window.broadcast.load(metadata, tracking); window.broadcast.resize(1920, 1080);
    window.broadcast.configure({ camera: 'broadcast', ballScale: 2, cvVisibility: true });
    window.broadcast.setRich(rich);
  }, { metadata, tracking: interval.tracking, rich: values.rich! });
  // Warm both paths before measuring, and alternate order to reduce thermal/order bias.
  await captureCanvas(page); await page.locator('canvas').screenshot();
  const results = [];
  for (let run = 0; run < runs; run++) {
    for (const synchronized of values['synchronized-only'] ? [true] : run % 2 ? [true, false] : [false, true]) {
      const encoder = spawn('ffmpeg', ['-v', 'error', '-f', 'image2pipe', '-vcodec', 'png', '-framerate', '25', '-i', 'pipe:0', '-an', '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p', '-f', 'null', '-'], { stdio: ['pipe', 'ignore', 'inherit'] });
      const completion = new Promise<{ code: number | null; error?: Error }>(resolve => {
        let error: Error | undefined;
        encoder.once('error', cause => { error = cause; });
        encoder.once('close', code => resolve({ code, error }));
      });
      let pipeError: Error | undefined;
      encoder.stdin.on('error', error => { pipeError = error; });
      const began = performance.now();
      let captureMs = 0, renderMs = 0;
      try {
        for (const t of times) {
          const renderStarted = performance.now();
          await page.evaluate(t => window.broadcast.setTime(t), t);
          renderMs += performance.now() - renderStarted;
          const captureStarted = performance.now();
          const png = synchronized ? await captureCanvas(page) : await page.locator('canvas').screenshot();
          captureMs += performance.now() - captureStarted;
          if (pipeError) throw pipeError;
          await new Promise<void>((resolve, reject) => encoder.stdin.write(png, error => error ? reject(error) : resolve()));
        }
        encoder.stdin.end();
        const result = await completion;
        if (result.error || result.code !== 0) throw result.error ?? new Error(`FFmpeg exit ${result.code}`);
        const elapsedMs = performance.now() - began;
        results.push({ run: run + 1, synchronized, frames: times.length, captureMs, renderMs, nodePeakRssBytes: process.resourceUsage().maxRSS * 1024, elapsedMs, fps: times.length * 1000 / elapsedMs });
        console.log(JSON.stringify(results.at(-1)));
      } finally {
        encoder.stdin.destroy();
        if (encoder.exitCode === null && encoder.signalCode === null) encoder.kill();
        await completion;
      }
    }
  }
  for (const t of [start, (start + end) / 2, end - 0.04]) {
    await page.evaluate(t => window.broadcast.setTime(t), t);
    await captureCanvas(page, { path: `${artifacts}/broadcast-${t}.png` });
  }
  const session = await page.context().newCDPSession(page);
  const browserHeap = await session.send('Runtime.getHeapUsage');
  await session.detach();
  const report = { browserHeap, environment: { cpu: cpus()[0]?.model, logicalCpus: cpus().length, memoryBytes: totalmem(), platform: platform(), release: release(), node: process.version, chromium: browser.version(), graphics: 'ANGLE SwiftShader' }, start, end, width: 1920, height: 1080, fps: 25, camera: 'broadcast', cvVisibility: true, playerScale: 1, ballScale: 2, rich: values.rich, renderStatistics: await page.evaluate(() => window.broadcast.statistics()), input: interval.stats, results };
  await writeFile(`${artifacts}/capture-benchmark.json`, JSON.stringify(report, null, 2));
} finally { try { await browser?.close(); } finally { await closeServer(); } }
