import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { parseArgs } from 'node:util';
import { parseMatch, sample } from '../src/data/match';
import { exportTimes, FPS } from '../src/playback/timing';
const { values } = parseArgs({ options: {
  video: { type: 'string' },
  metadata: { type: 'string', default: '../data/fake/sample_a/match_info.json' },
  tracking: { type: 'string', default: '../data/fake/sample_a/tracking.jsonl' },
} });
if (!values.video) throw new Error('Usage: npm run validate:export -- --video path/to/export.mp4 [--metadata ... --tracking ...]');
const manifest = JSON.parse(await readFile(`${values.video}.manifest.json`, 'utf8'));
const match = parseMatch(JSON.parse(await readFile(values.metadata!, 'utf8')), await readFile(values.tracking!, 'utf8'));
const times = exportTimes(manifest.start, manifest.end);
// Decode/count frames and inspect actual presentation timestamps, not just container metadata.
const probe = JSON.parse(execFileSync('ffprobe', ['-v', 'error', '-select_streams', 'v:0', '-count_frames', '-show_frames', '-show_entries', 'stream=codec_name,width,height,r_frame_rate,nb_read_frames:frame=best_effort_timestamp_time', '-of', 'json', values.video], { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 }));
const stream = probe.streams[0];
assert.equal(stream.codec_name, 'h264'); assert.equal(stream.r_frame_rate, `${FPS}/1`);
assert.equal(stream.width, manifest.width); assert.equal(stream.height, manifest.height);
assert.equal(manifest.match_id, match.info.match_id); assert.equal(manifest.fps, FPS);
assert.equal(Number(stream.nb_read_frames), times.length);
assert.equal(probe.frames.length, times.length); assert.equal(manifest.frames.length, times.length);
for (const [i, time] of times.entries()) {
  const entry = manifest.frames[i];
  assert.equal(entry.output_frame, i); assert.ok(Math.abs(entry.t - time) < 1e-8, `manifest time at ${i}`);
  assert.equal(entry.input_frame, sample(match, time).frame);
  assert.ok(Math.abs(Number(probe.frames[i].best_effort_timestamp_time) - i / FPS) < 1e-6, `video PTS at ${i}`);
}
console.log(`Validated ${times.length} decoded H.264 frames at ${FPS} FPS, video PTS, manifest timestamps, and tracking frame correspondence.`);
