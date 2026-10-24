import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFile, writeFile } from 'node:fs/promises';
import { artifactDirectory, SIMULATOR_SOURCE, SIMULATOR_TRIMMED } from './lib/paths';
const renders = (await artifactDirectory()) + '/';
const source = SIMULATOR_SOURCE;
const trimmed = SIMULATOR_TRIMMED;
const cases = [
  { name: 'simulator-full-pitch.mp4', input: source },
  { name: 'simulator-broadcast.mp4', input: source },
  { name: 'simulator-broadcast-trimmed.mp4', input: trimmed },
];
for (const { name, input } of cases) {
  process.stdout.write(execFileSync(process.execPath, ['--import', 'tsx', 'scripts/validate-export.ts', '--video', renders + name, '--metadata', input + 'match_info.json', '--tracking', input + 'tracking.jsonl'], { encoding: 'utf8' }));
}
const [fullPitch, broadcast, trimmedBroadcast] = await Promise.all(cases.map(({ name }) => readFile(renders + name + '.manifest.json', 'utf8').then(JSON.parse)));
assert.equal(fullPitch.render.camera, 'cv_full_pitch'); assert.equal(broadcast.render.camera, 'broadcast');
assert.deepEqual({ ...fullPitch, render: { ...fullPitch.render, camera: 'broadcast' } }, broadcast, 'comparison manifests may differ only in camera preset');
assert.deepEqual(broadcast, trimmedBroadcast);
const [sourceHash, trimmedHash] = cases.filter(c => c.name !== 'simulator-full-pitch.mp4').map(({ name }) => execFileSync('ffmpeg', ['-v', 'error', '-i', renders + name, '-map', '0:v:0', '-f', 'framemd5', '-'], { encoding: 'utf8' }));
assert.equal(sourceHash, trimmedHash, 'full-file and pre-trimmed broadcast exports must decode to identical pixels');
const report = { frames: fullPitch.frames.length, start: fullPitch.start, end: fullPitch.end,
  firstFrame: fullPitch.frames[0], lastFrame: fullPitch.frames.at(-1),
  cameraOnlyDifference: true, absoluteInputReferencesValid: true, allTrimmedDecodedFramesIdentical: true };
await writeFile(renders + 'simulator-export-checks.json', JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
