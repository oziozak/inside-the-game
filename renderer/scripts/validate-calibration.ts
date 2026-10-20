import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
const root = '../data/renders/';
const names = ['calibration-full-pitch.mp4', 'calibration-broadcast.mp4', 'repeat/calibration-full-pitch.mp4'];
for (const name of names) {
  process.stdout.write(execFileSync(process.execPath, ['--import', 'tsx', 'scripts/validate-export.ts', '--video', root + name, '--metadata', 'fixtures/calibration/match_info.json', '--tracking', 'fixtures/calibration/tracking.jsonl'], { encoding: 'utf8' }));
}
const manifests = await Promise.all(names.map(name => readFile(root + name + '.manifest.json', 'utf8').then(JSON.parse)));
assert.equal(manifests[0].render.camera, 'cv_full_pitch'); assert.equal(manifests[1].render.camera, 'broadcast');
assert.deepEqual({ ...manifests[0].render, camera: undefined }, { ...manifests[1].render, camera: undefined });
assert.deepEqual(manifests[0].frames, manifests[1].frames);
assert.deepEqual(manifests[0], manifests[2]);
const hashes = names.filter((_, i) => i !== 1).map(name => execFileSync('ffmpeg', ['-v', 'error', '-i', root + name, '-map', '0:v:0', '-f', 'framemd5', '-'], { encoding: 'utf8' }));
assert.equal(hashes[0], hashes[1], 'repeated full-pitch exports must decode to identical pixels');
await writeFile(root + 'calibration-export-checks.json', JSON.stringify({ framesPerVideo: manifests[0].frames.length, timingAndMotionMatch: true, cameraOnlyDifference: true, repeatedDecodedFramesIdentical: true }, null, 2));
console.log('Comparison passed: camera-only settings difference, identical input-frame mapping, and all 300 decoded repeat frames have identical pixel hashes.');
