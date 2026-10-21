import { test } from 'node:test';
import assert from 'node:assert/strict';
import { PerspectiveCamera, Vector3 } from 'three';
import { applyCamera } from '../src/camera/presets';
import { DEFAULT_CONFIG, renderConfig } from '../src/scene/config';
test('visibility configuration validates finite, positive bounded scales', () => {
  assert.deepEqual(renderConfig(), DEFAULT_CONFIG);
  assert.deepEqual(renderConfig({ ballScale: 3, playerScale: 1.5 }), { camera: 'cv_full_pitch', ballScale: 3, playerScale: 1.5, cvVisibility: false });
  for (const value of [0, -1, NaN, Infinity, 6]) assert.throws(() => renderConfig({ ballScale: value }));
  assert.throws(() => renderConfig({ camera: 'other' as never }));
});
test('CV camera is fixed and fits pitch plus run-off at common aspect ratios', () => {
  for (const aspect of [16 / 9, 4 / 3, 1, 9 / 16]) {
    const camera = new PerspectiveCamera(43, aspect, 0.1, 400);
    applyCamera(camera, 'cv_full_pitch', new Vector3(-45, 0, 10));
    const matrix = camera.matrixWorld.toArray(), projection = camera.projectionMatrix.toArray();
    applyCamera(camera, 'cv_full_pitch', new Vector3(45, 5, -30));
    assert.deepEqual(camera.matrixWorld.toArray(), matrix); assert.deepEqual(camera.projectionMatrix.toArray(), projection);
    for (const x of [-57, 57]) for (const z of [-38, 38]) for (const y of [0, 10]) {
      const p = new Vector3(x, y, z).project(camera);
      assert.ok(Math.abs(p.x) < 1 && Math.abs(p.y) < 1 && Math.abs(p.z) < 1);
    }
  }
});
test('broadcast camera is closer, follows current ball, and has no seek history', () => {
  const camera = new PerspectiveCamera(43, 16 / 9, 0.1, 400), ball = new Vector3(20, 0.11, -10);
  applyCamera(camera, 'broadcast', ball);
  const matrix = camera.matrixWorld.toArray();
  assert.equal(camera.position.x, 20); assert.equal(camera.position.y, 38);
  applyCamera(camera, 'broadcast', new Vector3(-40, 0.11, 30));
  applyCamera(camera, 'cv_full_pitch', ball);
  applyCamera(camera, 'broadcast', ball);
  assert.deepEqual(camera.matrixWorld.toArray(), matrix);
  const projected = ball.clone().project(camera);
  assert.ok(Math.abs(projected.x) < 1 && Math.abs(projected.y) < 1);
});
