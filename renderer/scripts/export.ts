import { parseArgs } from 'node:util';
import { readFile, mkdir, writeFile, access } from 'node:fs/promises';
import { resolve, dirname } from 'node:path';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { chromium } from 'playwright';
import { createServer } from 'vite';
import { parseMatch, sample } from '../src/data/match';
import { exportTimes, FPS } from '../src/playback/timing';
import { renderConfig, type CameraPreset } from '../src/scene/config';

const { values } = parseArgs({ options: {
  metadata: { type: 'string', default: '../data/fake/sample_a/match_info.json' },
  tracking: { type: 'string', default: '../data/fake/sample_a/tracking.jsonl' },
  out: { type: 'string', default: '../data/renders/sample_a.mp4' },
  start: { type: 'string' }, end: { type: 'string', default: '10' },
  width: { type: 'string', default: '1920' }, height: { type: 'string', default: '1080' },
  rich: { type: 'boolean', default: false },
  cv_visibility: { type: 'boolean', default: false },
  camera: { type: 'string', default: 'cv_full_pitch' },
  'player-scale': { type: 'string', default: '1' }, 'ball-scale': { type: 'string', default: '1' },
} });
const config = renderConfig({ cvVisibility: values.cv_visibility!, camera: values.camera as CameraPreset, playerScale: Number(values['player-scale']), ballScale: Number(values['ball-scale']) });
const metadata = JSON.parse(await readFile(resolve(values.metadata!), 'utf8'));
const tracking = await readFile(resolve(values.tracking!), 'utf8');
const match = parseMatch(metadata, tracking);
const start = Number(values.start ?? match.frames[0].t), end = Number(values.end);
const times = exportTimes(start, end), width = Number(values.width), height = Number(values.height);
if (![width, height].every(n => Number.isInteger(n) && n >= 64 && n <= 7680 && n % 2 === 0)) throw new Error('Dimensions must be even integers from 64 to 7680');
// Last sample is valid for one frame duration. Never silently freeze beyond the input.
if (start < match.frames[0].t || end > match.frames.at(-1)!.t + 1 / FPS + 1e-8) throw new Error('Export interval lies outside tracking coverage');
const output = resolve(values.out!);
await mkdir(dirname(output), { recursive: true });
for (const path of [output, `${output}.manifest.json`]) {
  try { await access(path); } catch { continue; }
  throw new Error(`Output already exists: ${path}. Choose another --out.`);
}
const server = await createServer({ server: { host: '127.0.0.1', port: 0 }, logLevel: 'error' });
let browser: Awaited<ReturnType<typeof chromium.launch>> | undefined;
let encoder: ReturnType<typeof spawn> | undefined;
try {
  await server.listen();
  const url = server.resolvedUrls!.local[0];
  browser = await chromium.launch({ headless: true, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });
  await page.goto(`${url}?export=1`);
  await page.waitForFunction(() => !!window.broadcast);
  await page.evaluate(({ metadata, tracking, width, height, rich, config }) => {
    window.broadcast.load(metadata, tracking); window.broadcast.resize(width, height); window.broadcast.setRich(rich);
    window.broadcast.configure(config);
  }, { metadata, tracking, width, height, rich: values.rich!, config });
  encoder = spawn('ffmpeg', ['-hide_banner', '-loglevel', 'error', '-n', '-f', 'image2pipe', '-vcodec', 'png', '-framerate', String(FPS), '-i', 'pipe:0', '-an', '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', output], { stdio: ['pipe', 'inherit', 'inherit'] });
  const finished = new Promise<void>((ok, fail) => { encoder!.on('error', fail); encoder!.on('close', code => code === 0 ? ok() : fail(new Error(`FFmpeg exit ${code}`))); });
  // Attach handlers immediately so early encoder exits cannot become unhandled rejections.
  finished.catch(() => {});
  let pipeError: Error | undefined;
  encoder.stdin!.on('error', err => { pipeError = err; });
  const mapping = [];
  for (const [index, time] of times.entries()) {
    const state = await page.evaluate(t => window.broadcast.setTime(t), time);
    if (Math.abs(state.t - time) > 1e-8) throw new Error(`Unexpected time clamp at output ${index}`);
    const source = sample(match, time);
    if (state.inputFrame !== source.frame || Math.abs(state.inputTime - source.t) > 1e-8) throw new Error(`Input synchronization mismatch at output ${index}`);
    const image = await page.locator('canvas').screenshot({ type: 'png' });
    if (pipeError || encoder.exitCode !== null) throw pipeError ?? new Error('Encoder exited early');
    if (!encoder.stdin!.write(image)) await once(encoder.stdin!, 'drain');
    mapping.push({ output_frame: index, t: time, input_frame: source.frame });
    if (index % 100 === 0) console.log(`Rendered ${index + 1}/${times.length}`);
  }
  encoder.stdin!.end(); await finished;
  await writeFile(`${output}.manifest.json`, JSON.stringify({ match_id: match.info.match_id, fps: FPS, width, height, start, end, rich: values.rich, render: config, frames: mapping }, null, 2));
  console.log(`Wrote ${output} (${times.length} frames) and timing manifest`);
} finally {
  if (encoder && encoder.exitCode === null) encoder.kill();
  await browser?.close(); await server.close();
}
