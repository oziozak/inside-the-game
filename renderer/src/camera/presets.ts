import { PerspectiveCamera, Vector3 } from 'three';
import type { CameraPreset } from '../scene/config';

/** Camera is a pure function of preset, aspect and current ball position, with no smoothing history. */
export function applyCamera(camera: PerspectiveCamera, preset: CameraPreset, ball: Vector3): void {
  camera.zoom = 1;
  if (preset === 'broadcast') {
    const x = Math.max(-35, Math.min(35, ball.x));
    const z = Math.max(-18, Math.min(18, ball.z));
    // Slight infield bias near either goal reduces apron while keeping the goal/ball framed.
    camera.fov = 38; camera.position.set(x, 34, z + 44); camera.lookAt(x * 0.8, 0, z - 2);
    camera.updateProjectionMatrix(); camera.updateMatrixWorld(true);
    return;
  }
  camera.fov = 43; camera.position.set(0, 75, 83); camera.lookAt(0, 0, 0);
  camera.updateProjectionMatrix(); camera.updateMatrixWorld(true);
  // Fit the fixed camera to the pitch plus run-off/goals at any output aspect ratio.
  let extent = 1;
  for (const x of [-57, 57]) for (const z of [-38, 38]) for (const y of [0, 10]) {
    const point = new Vector3(x, y, z).project(camera);
    extent = Math.max(extent, Math.abs(point.x) * 1.03, Math.abs(point.y) * 1.03);
  }
  camera.zoom = 1 / extent; camera.updateProjectionMatrix();
}
