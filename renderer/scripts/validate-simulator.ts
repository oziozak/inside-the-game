import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
const renders = '../data/renders/';
const source = '../data/generated/renderer-m007/';
const trimmed = '../data/generated/renderer-integration-trimmed/';
const names = ['simulator-full-pitch.mp4', 'simulator-broadcast.mp4', 'simulator-broadcast-trimmed.mp4'];
for (const [i, name] of names.entries()) {
  const input = i === 2 ? trimmed : source;
  process.stdout.write(execFileSync(process.execPath, ['--import', 'tsx', 'scripts/validate-export.ts', '--video', renders + name, '--metadata', input + 'match_info.json', '--tracking', input + 'tracking.jsonl'], { encoding: 'utf8' }));
}
const manifests = await Promise.all(names.map(name => readFile(renders + name + '.manifest.json', 'utf8').then(JSON.parse)));
assert.equal(manifests[0].render.camera, 'cv_full_pitch'); assert.equal(manifests[1].render.camera, 'broadcast');
assert.deepEqual(manifests[0].frames, manifests[1].frames);
assert.deepEqual({ ...manifests[0], render: { ...manifests[0].render, camera: 'broadcast' } }, manifests[1], 'the complete comparison manifests may differ only in camera preset');
assert.deepEqual(manifests[1], manifests[2]);
const hashes = names.slice(1).map(name => execFileSync('ffmpeg', ['-v', 'error', '-i', renders + name, '-map', '0:v:0', '-f', 'framemd5', '-'], { encoding: 'utf8' }));
assert.equal(hashes[0], hashes[1], 'full-file and pre-trimmed broadcast exports must decode to identical pixels');
const report = { frames: manifests[0].frames.length, start: manifests[0].start, end: manifests[0].end,
  firstFrame: manifests[0].frames[0], lastFrame: manifests[0].frames.at(-1),
  cameraOnlyDifference: true, absoluteInputReferencesValid: true, allTrimmedDecodedFramesIdentical: true };
await writeFile(renders + 'simulator-export-checks.json', JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
