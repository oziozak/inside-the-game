import { readFile, writeFile } from 'node:fs/promises';
import { parseArgs } from 'node:util';
import { loadInterval } from './lib/interval';
import { parseMatch } from '../src/data/match';
const { values } = parseArgs({ options: {
  mode: { type: 'string', default: 'interval' },
  metadata: { type: 'string', default: '../data/generated/renderer-m007/match_info.json' },
  tracking: { type: 'string', default: '../data/generated/renderer-m007/tracking.jsonl' },
  start: { type: 'string', default: '2503' }, end: { type: 'string', default: '2513' },
  out: { type: 'string' },
} });
const metadata = JSON.parse(await readFile(values.metadata!, 'utf8'));
const began = performance.now();
let frames: number, total: number, bytes: number, inputBytes: number;
if (values.mode === 'whole') {
  // Baseline is the old Node read/parse path only; deliberately does not send the whole file to Chromium.
  const tracking = await readFile(values.tracking!, 'utf8');
  const match = parseMatch(metadata, tracking);
  frames = total = match.frames.length; bytes = Buffer.byteLength(tracking); inputBytes = bytes;
} else if (values.mode === 'interval') {
  const interval = await loadInterval(metadata, values.tracking!, { start: Number(values.start), end: Number(values.end) });
  frames = interval.stats.retainedFrames; total = interval.stats.totalFrames;
  bytes = interval.stats.payloadBytes; inputBytes = interval.stats.inputBytes;
} else throw new Error('mode must be whole or interval');
const report = { mode: values.mode, totalFrames: total, retainedFrames: frames, inputBytes, browserPayloadBytes: bytes, loadingMs: performance.now() - began, nodePeakRssBytes: process.resourceUsage().maxRSS * 1024 };
if (values.out) await writeFile(values.out, JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
