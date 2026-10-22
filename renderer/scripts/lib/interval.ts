import { createReadStream } from 'node:fs';
import { stat } from 'node:fs/promises';
import { createInterface } from 'node:readline';
import { frameParser, type Frame, type Match } from '../../src/data/match';
import { FPS } from '../../src/playback/timing';

// Covers the 0.8 s causal camera window with margin. The nearest outside samples
// are also retained: a fixed time margin alone is insufficient for sparse inputs.
export const HISTORY_SECONDS = 1;
export interface IntervalStats {
  totalFrames: number; inputBytes: number; retainedFrames: number; payloadBytes: number;
  coverageStart: number; coverageEnd: number; retainedStart: number; retainedEnd: number;
  loadingMs: number;
}
export interface Interval {
  match: Match; tracking: string; start: number; end: number; stats: IntervalStats;
}

/** Scan/validate JSONL once with bounded retention, keeping original lines, IDs and timestamps. */
export async function loadInterval(metadata: unknown, path: string, options: { start?: number; end: number }): Promise<Interval> {
  const began = performance.now();
  let start = options.start;
  const end = options.end;
  if (!Number.isFinite(end) || end <= 0 || (start !== undefined && (!Number.isFinite(start) || start < 0 || start >= end))) {
    throw new Error('Expected a finite interval with 0 <= start < end');
  }
  const parser = frameParser(metadata);
  const inputBytes = (await stat(path)).size;
  const stream = createReadStream(path, { encoding: 'utf8', highWaterMark: 64 * 1024 });
  const lines = createInterface({ input: stream, crlfDelay: Infinity });
  let totalFrames = 0, lineNumber = 0;
  let first: Frame | undefined, last: Frame | undefined;
  let before: { frame: Frame; text: string } | undefined;
  let enteredWindow = false, hasSuccessor = false;
  const frames: Frame[] = [], retainedLines: string[] = [];
  const keep = (frame: Frame, text: string) => { frames.push(frame); retainedLines.push(text); };
  try {
    for await (const text of lines) {
      const line = lineNumber++;
      if (!text.trim()) continue;
      const frame = parser.parse(text, line);
      totalFrames++; first ??= frame; last = frame; start ??= frame.t;
      if (frame.t < start - HISTORY_SECONDS) { before = { frame, text }; continue; }
      if (!enteredWindow) {
        if (before) keep(before.frame, before.text);
        before = undefined; enteredWindow = true;
      }
      if (frame.t <= end + 1 / FPS) keep(frame, text);
      else if (!hasSuccessor) { keep(frame, text); hasSuccessor = true; }
      // Continue scanning to establish actual coverage, total count, and ordering integrity.
    }
  } finally { lines.close(); stream.destroy(); }
  if (!first || !last || start === undefined) throw new Error('Tracking is empty');
  if (start >= end) throw new Error(`Expected start < end; first tracking time is ${first.t}, requested end is ${end}`);
  const coverageEnd = last.t + 1 / FPS;
  if (start < first.t || end > coverageEnd + 1e-8 || start >= coverageEnd) {
    throw new Error(`Requested interval [${start}, ${end}) lies outside tracking coverage [${first.t}, ${coverageEnd})`);
  }
  const tracking = retainedLines.join('\n') + '\n';
  return { start, end, match: { info: parser.info, frames }, tracking, stats: {
    totalFrames, inputBytes, retainedFrames: frames.length, payloadBytes: Buffer.byteLength(tracking),
    coverageStart: first.t, coverageEnd, retainedStart: frames[0].t, retainedEnd: frames.at(-1)!.t,
    loadingMs: performance.now() - began,
  } };
}
