import { PerspectiveCamera, Vector3 } from 'three';
import { sample } from '../data/loadMatch';
import type { Match } from '../types';

/**
 * Pixel-parity with the renderer's export camera (renderer/src/camera/presets.ts, tracking.ts),
 * ported here so follow-player overlays land on the player visible in the broadcast video.
 */
export function world([x, y, height = 0]: number[]): [number, number, number] { return [x - 52.5, height, 34 - y]; }

export function applyCamera(camera: PerspectiveCamera, preset: 'cv_full_pitch' | 'broadcast', ball: Vector3, aspect: number): void {
  camera.aspect = aspect;
  camera.zoom = 1;
  if (preset === 'broadcast') {
    const x = Math.max(-38, Math.min(38, ball.x));
    const z = Math.max(-18, Math.min(18, ball.z));
    camera.fov = 40; camera.position.set(x, 38, z + 48); camera.lookAt(x, 0, z);
    camera.updateProjectionMatrix(); camera.updateMatrixWorld(true);
    return;
  }
  camera.fov = 43; camera.position.set(0, 75, 83); camera.lookAt(0, 0, 0);
  camera.updateProjectionMatrix(); camera.updateMatrixWorld(true);
  let extent = 1;
  for (const x of [-57, 57]) for (const z of [-38, 38]) for (const y of [0, 10]) {
    const point = new Vector3(x, y, z).project(camera);
    extent = Math.max(extent, Math.abs(point.x) * 1.03, Math.abs(point.y) * 1.03);
  }
  camera.zoom = 1 / extent; camera.updateProjectionMatrix();
}

/** Fixed 0.8 s causal triangular filter over tracking, evaluated from absolute match time. */
export function cameraTarget(match: Match, t: number): Vector3 {
  const periods = match.info.periods ?? [];
  const start = Math.max(match.frames[0].t, ...periods.filter(p => p.start <= t).map(p => p.start));
  const target = new Vector3();
  let total = 0;
  for (let i = 0; i <= 20; i++) {
    const weight = 21 - i;
    const ball = sample(match, Math.max(start, t - i / 25)).ball;
    target.addScaledVector(new Vector3(...world(ball)), weight); total += weight;
  }
  target.divideScalar(total); target.y = 0;
  return target;
}

/** Projects a pitch-meter position (ground, or ball with height) to canvas pixels for the given camera pose. */
export function projectToCanvas(camera: PerspectiveCamera, positionMeters: number[], canvasWidth: number, canvasHeight: number): { x: number; y: number } {
  const [x, y, z] = world(positionMeters);
  const ndc = new Vector3(x, y, z).project(camera);
  return { x: (ndc.x + 1) / 2 * canvasWidth, y: (1 - ndc.y) / 2 * canvasHeight };
}

/** Matches the renderer's live render path (src/main.ts), which always passes the filtered target into applyCamera. */
export function buildCamera(preset: 'cv_full_pitch' | 'broadcast', match: Match, t: number, aspect: number): PerspectiveCamera {
  const camera = new PerspectiveCamera();
  applyCamera(camera, preset, cameraTarget(match, t), aspect);
  return camera;
}
