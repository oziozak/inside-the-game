import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { calibration } from '../scripts/calibration';
import { parseMatch, sample } from '../src/data/match';
import { cameraTarget } from '../src/camera/tracking';
import { ballScale } from '../src/scene/ball';
import { renderConfig } from '../src/scene/config';
const info = JSON.parse(readFileSync(new URL('../../data/fake/sample_a/match_info.json', import.meta.url), 'utf8'));
const { metadata, frames, events } = calibration(info);
const match = parseMatch(metadata, frames.map(f => JSON.stringify(f)).join('\n'));
test('calibration is reproducible, schema-valid, 300 frames, with controlled pass/carry/shot timing', () => {
  assert.deepEqual(calibration(info), { metadata, frames, events });
  assert.equal(frames.length, 300);
  assert.deepEqual(sample(match, 0).ball, sample(match, 1.96).ball);
  assert.deepEqual(sample(match, 4).ball, [72.75, 29.25, 0.11]);
  assert.deepEqual(sample(match, 8).ball, [87.75, 33.25, 0.11]);
  assert.deepEqual(sample(match, 9).ball, [106, 34, 0.11]);
  assert.deepEqual(events.map(e => e.type), ['pass', 'shot', 'goal']);
  for (const [i, f] of frames.entries()) {
    assert.equal(f.frame, i); assert.equal(f.t, i / 25);
    assert.ok(f.ball[0] >= 0 && f.ball[0] <= 107 && f.ball[1] >= 0 && f.ball[1] <= 68 && f.ball[2] >= 0.11);
    if (f.ball[0] > 105) assert.ok(f.ball[1] > 30.34 && f.ball[1] < 37.66 && f.ball[2] < 2.44, 'beyond goal line only inside goal mouth');
    if (i) {
      const prev = frames[i - 1];
      assert.ok(Math.hypot(...f.ball.map((x, k) => x - prev.ball[k])) * 25 < 22, 'ball speed bounded');
      assert.ok(Math.hypot(...f.players[1].pos.map((x, k) => x - prev.players[1].pos[k])) * 25 < 6, 'player speed bounded');
    }
  }
});
test('camera smoothing is absolute-time deterministic and continuous around release/receive/shot', () => {
  for (const t of [0, 2, 4, 5, 8, 9, 11.96]) {
    const direct = cameraTarget(match, t).toArray();
    cameraTarget(match, 11); cameraTarget(match, 1);
    assert.deepEqual(cameraTarget(match, t).toArray(), direct);
    if (t > 0) assert.ok(cameraTarget(match, t + 0.001).distanceTo(cameraTarget(match, t - 0.001)) < 0.05);
  }
  assert.ok(cameraTarget(match, 8.4).x < frames[210].ball[0] - 52.5, 'causal camera lags the shot instead of snapping');
});
test('CV ball visibility is capped, resolution-aware, and optional', () => {
  const cv = renderConfig({ cvVisibility: true });
  assert.equal(ballScale(cv, 1), 2); assert.equal(ballScale(cv, 4), 1.25);
  assert.equal(ballScale(cv, 10), 1);
  assert.equal(ballScale(renderConfig(), 1), 1);
  assert.equal(ballScale(renderConfig({ cvVisibility: true, ballScale: 3 }), 1), 3, 'explicit user scale remains supported');
});
