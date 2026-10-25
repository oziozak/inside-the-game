import { spawn } from 'node:child_process';
import { readFile, mkdir, writeFile, access } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { parseArgs } from 'node:util';
import { chromium } from 'playwright';
import { sample } from '../src/data/match';
import { exportTimes, FPS } from '../src/playback/timing';
import { renderConfig, type CameraPreset } from '../src/scene/config';
import { captureCanvas } from './lib/capture';
import { loadInterval } from './lib/interval';
import { renderingServer } from './lib/server';

const { values } = parseArgs({ options: {
  metadata: { type: 'string', default: '../data/fake/sample_a/match_info.json' },
  tracking: { type: 'string', default: '../data/fake/sample_a/tracking.jsonl' },
  out: { type: 'string', default: '../data/renders/sample_a.mp4' },
  start: { type: 'string' }, end: { type: 'string', default: '10' },
  width: { type: 'string', default: '1920' }, height: { type: 'string', default: '1080' },
  rich: { type: 'boolean', default: false },
  cv_visibility: { type: 'boolean', default: false },
  'jersey-numbers': { type: 'boolean', default: false },
  'animate-players': { type: 'boolean', default: false },
  'no-animation': { type: 'boolean', default: false },
  camera: { type: 'string', default: 'cv_full_pitch' },
  'player-scale': { type: 'string', default: '1' }, 'ball-scale': { type: 'string', default: '1' },
} });
const config = renderConfig({ jerseyNumbers: values['jersey-numbers']!, animatePlayers: values['animate-players']! && !values['no-animation'], cvVisibility: values.cv_visibility!, camera: values.camera as CameraPreset, playerScale: Number(values['player-scale']), ballScale: Number(values['ball-scale']) });
const metadata = JSON.parse(await readFile(resolve(values.metadata!), 'utf8'));
const interval = await loadInterval(metadata, resolve(values.tracking!), { start: values.start === undefined ? undefined : Number(values.start), end: Number(values.end) });
const { match, tracking, start, end } = interval;
console.log(`Tracking window: ${interval.stats.retainedFrames}/${interval.stats.totalFrames} frames, ${interval.stats.payloadBytes} bytes transferred (input ${interval.stats.inputBytes} bytes), loaded in ${interval.stats.loadingMs.toFixed(0)} ms`);
const times = exportTimes(start, end), width = Number(values.width), height = Number(values.height);
if (![width, height].every(n => Number.isInteger(n) && n >= 64 && n <= 7680 && n % 2 === 0)) throw new Error('Dimensions must be even integers from 64 to 7680');
const output = resolve(values.out!);
await mkdir(dirname(output), { recursive: true });
for (const path of [output, `${output}.manifest.json`, `${output}.metrics.json`]) {
  try { await access(path); } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') continue;
    throw error;
  }
  throw new Error(`Output already exists: ${path}. Choose another --out.`);
}
const { server, closeServer } = await renderingServer();
let browser: Awaited<ReturnType<typeof chromium.launch>> | undefined;
let encoder: ReturnType<typeof spawn> | undefined;
let encoderClosed: Promise<{ code: number | null; error?: Error }> | undefined;
try {
  await server.listen();
  const url = server.resolvedUrls!.local[0];
  browser = await chromium.launch({ headless: true, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });
  await page.goto(`${url}?export=1`);
  await page.waitForFunction(() => !!window.broadcast);
  const browserLoadStarted = performance.now();
  await page.evaluate(({ metadata, tracking, width, height, rich, config }) => {
    window.broadcast.load(metadata, tracking); window.broadcast.resize(width, height); window.broadcast.setRich(rich);
    window.broadcast.configure(config);
  }, { metadata, tracking, width, height, rich: values.rich!, config });
  const browserLoadMs = performance.now() - browserLoadStarted;
  const renderStarted = performance.now();
  encoder = spawn('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-n', '-f', 'image2pipe', '-vcodec', 'png', '-framerate', String(FPS), '-i', 'pipe:0', '-an', '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', output], { stdio: ['pipe', 'inherit', 'inherit'] });
  encoderClosed = new Promise(resolve => {
    let error: Error | undefined;
    encoder!.once('error', cause => { error = cause; });
    encoder!.once('close', code => resolve({ code, error }));
  });
  let pipeError: Error | undefined;
  encoder.stdin!.on('error', err => { pipeError = err; });
  const mapping = [];
  for (const [index, time] of times.entries()) {
    const state = await page.evaluate(t => window.broadcast.setTime(t), time);
    if (Math.abs(state.t - Math.min(time, match.frames.at(-1)!.t)) > 1e-8) throw new Error(`Unexpected time clamp at output ${index}`);
    const source = sample(match, time);
    if (state.inputFrame !== source.frame || Math.abs(state.inputTime - source.t) > 1e-8) throw new Error(`Input synchronization mismatch at output ${index}`);
    const image = await captureCanvas(page, { type: 'png' });
    if (pipeError || encoder.exitCode !== null) throw pipeError ?? new Error('Encoder exited early');
    await new Promise<void>((resolve, reject) => {
      encoder!.stdin!.write(image, error => error ? reject(error) : resolve());
    });
    mapping.push({ output_frame: index, t: time, input_frame: source.frame });
    if (index % 100 === 0) console.log(`Rendered ${index + 1}/${times.length}`);
  }
  encoder.stdin!.end();
  const completion = await encoderClosed;
  if (completion.error) throw completion.error;
  if (completion.code !== 0) throw new Error(`FFmpeg exit ${completion.code}`);
  const exportMs = performance.now() - renderStarted;
  const metrics = { input: interval.stats, browserLoadMs, exportMs, framesPerSecond: times.length * 1000 / exportMs, nodePeakRssBytes: process.resourceUsage().maxRSS * 1024 };
  await writeFile(`${output}.metrics.json`, JSON.stringify(metrics, null, 2));
  console.log(`Capture + encode: ${metrics.framesPerSecond.toFixed(2)} FPS; browser window load: ${browserLoadMs.toFixed(0)} ms; Node peak RSS: ${(metrics.nodePeakRssBytes / 1024 ** 2).toFixed(1)} MiB (excludes Chromium/FFmpeg)`);
  await writeFile(`${output}.manifest.json`, JSON.stringify({ match_id: match.info.match_id, fps: FPS, width, height, start, end, rich: values.rich, render: config, frames: mapping }, null, 2));
  console.log(`Wrote ${output} (${times.length} frames) and timing manifest`);
} finally {
  try {
    encoder?.stdin?.destroy();
    if (encoder && encoder.exitCode === null && encoder.signalCode === null) encoder.kill();
    await encoderClosed;
  } finally {
    try { await browser?.close(); } finally { await closeServer(); }
  }
}
