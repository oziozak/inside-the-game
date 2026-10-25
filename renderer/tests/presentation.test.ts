import assert from 'node:assert/strict';
import { test } from 'node:test';
import { PerspectiveCamera, Vector3 } from 'three';
import { applyCamera } from '../src/camera/presets';
import { DEFAULT_CONFIG, renderConfig } from '../src/scene/config';
test('visibility configuration validates finite, positive bounded scales', () => {
  assert.deepEqual(renderConfig(), DEFAULT_CONFIG);
  assert.deepEqual(renderConfig({ ballScale: 3, playerScale: 1.5 }), { ...DEFAULT_CONFIG, ballScale: 3, playerScale: 1.5 });
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
  assert.equal(camera.position.x, 20); assert.equal(camera.position.y, 34);
  applyCamera(camera, 'broadcast', new Vector3(-40, 0.11, 30));
  applyCamera(camera, 'cv_full_pitch', ball);
  applyCamera(camera, 'broadcast', ball);
  assert.deepEqual(camera.matrixWorld.toArray(), matrix);
  const projected = ball.clone().project(camera);
  assert.ok(Math.abs(projected.x) < 1 && Math.abs(projected.y) < 1);
});
test('broadcast reduces near-touchline apron while framing balls across the pitch', () => {
  const camera = new PerspectiveCamera(40, 16 / 9, 0.1, 400);
  const target = new Vector3(0, 0, 18);
  camera.position.set(0, 38, 66); camera.lookAt(target); camera.updateMatrixWorld(true);
  const nearLine = new Vector3(0, 0, 34);
  const before = nearLine.clone().project(camera).y;
  applyCamera(camera, 'broadcast', target);
  assert.ok(nearLine.clone().project(camera).y < before, 'near line shifts down, reducing ground below it');
  for (const x of [-52.5, -38, 0, 38, 52.5]) for (const z of [-34, -18, 0, 18, 34]) {
    const ball = new Vector3(x, 0.11, z);
    applyCamera(camera, 'broadcast', ball);
    const point = ball.project(camera);
    assert.ok(Math.abs(point.x) < 1 && Math.abs(point.y) < 1 && Math.abs(point.z) < 1);
  }
});
test('broadcast pans continuously at clamps and frames both nearby goals without zoom steps', () => {
  const camera = new PerspectiveCamera(43, 16 / 9, 0.1, 400);
  for (const x of [-52.5, -35, 0, 35, 52.5]) for (const z of [-18, 0, 18]) {
    applyCamera(camera, 'broadcast', new Vector3(x - 0.001, 0.11, z - 0.001));
    const position = camera.position.clone(), rotation = camera.quaternion.clone();
    applyCamera(camera, 'broadcast', new Vector3(x + 0.001, 0.11, z + 0.001));
    assert.ok(position.distanceTo(camera.position) < 0.003);
    assert.ok(Math.abs(rotation.dot(camera.quaternion)) > 0.99999);
    assert.equal(camera.fov, 38); assert.equal(camera.zoom, 1);
  }
  for (const side of [-1, 1]) {
    applyCamera(camera, 'broadcast', new Vector3(side * 48, 0.11, 0));
    for (const y of [0, 2.44]) for (const z of [-3.66, 3.66]) {
      const point = new Vector3(side * 52.5, y, z).project(camera);
      assert.ok(Math.abs(point.x) < 1 && Math.abs(point.y) < 1 && Math.abs(point.z) < 1);
    }
  }
});
