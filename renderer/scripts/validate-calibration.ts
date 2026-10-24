import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { readFile, writeFile } from 'node:fs/promises';
import { artifactDirectory } from './lib/paths';
const root = (await artifactDirectory()) + '/';
const names = ['calibration-full-pitch.mp4', 'calibration-broadcast.mp4', 'repeat/calibration-full-pitch.mp4'];
for (const name of names) {
  process.stdout.write(execFileSync(process.execPath, ['--import', 'tsx', 'scripts/validate-export.ts', '--video', root + name, '--metadata', 'fixtures/calibration/match_info.json', '--tracking', 'fixtures/calibration/tracking.jsonl'], { encoding: 'utf8' }));
}
const [fullPitch, broadcast, repeated] = await Promise.all(names.map(name => readFile(root + name + '.manifest.json', 'utf8').then(JSON.parse)));
assert.equal(fullPitch.render.camera, 'cv_full_pitch'); assert.equal(broadcast.render.camera, 'broadcast');
assert.deepEqual({ ...fullPitch, render: { ...fullPitch.render, camera: 'broadcast' } }, broadcast, 'comparison manifests may differ only in camera preset');
assert.deepEqual(fullPitch, repeated);
const [originalHash, repeatedHash] = names.filter(name => name !== 'calibration-broadcast.mp4').map(name => execFileSync('ffmpeg', ['-v', 'error', '-i', root + name, '-map', '0:v:0', '-f', 'framemd5', '-'], { encoding: 'utf8' }));
assert.equal(originalHash, repeatedHash, 'repeated full-pitch exports must decode to identical pixels');
await writeFile(root + 'calibration-export-checks.json', JSON.stringify({ framesPerVideo: fullPitch.frames.length, timingAndMotionMatch: true, cameraOnlyDifference: true, repeatedDecodedFramesIdentical: true }, null, 2));
console.log('Comparison passed: camera-only settings difference, identical input-frame mapping, and all decoded repeat frames have identical pixel hashes.');
