import { Mesh, MeshBasicMaterial, MeshStandardMaterial, PerspectiveCamera, SphereGeometry, Vector3 } from 'three';
import { BALL_RADIUS_M, type RenderConfig } from './config';

/** Realistic base geometry with dark surface panels (no overlay, outline or depth override). */
export function createBall(): Mesh {
  const ball = new Mesh(new SphereGeometry(BALL_RADIUS_M, 24, 16), new MeshStandardMaterial({ color: '#ffffff', roughness: 0.8 }));
  for (const axis of [new Vector3(1, 0, 0), new Vector3(-1, 0, 0), new Vector3(0, 1, 0), new Vector3(0, -1, 0), new Vector3(0, 0, 1), new Vector3(0, 0, -1)]) {
    const panel = new Mesh(new SphereGeometry(BALL_RADIUS_M + 0.0005, 12, 6, 0, Math.PI * 2, 0, 0.4), new MeshBasicMaterial({ color: '#111827' }));
    panel.quaternion.setFromUnitVectors(new Vector3(0, 1, 0), axis); ball.add(panel);
  }
  ball.castShadow = true;
  return ball;
}

/** Unoccluded projected diameter estimate; scene occlusion and grass clipping remain physically enabled. */
export function projectedDiameter(camera: PerspectiveCamera, position: Vector3, height: number, radius = BALL_RADIUS_M): number {
  const depth = -position.clone().applyMatrix4(camera.matrixWorldInverse).z;
  return depth > 0 ? radius * height * camera.projectionMatrix.elements[5] / depth : 0;
}

/** CV mode asks for 5px at the current resolution, but caps automatic enlargement at 2× radius. */
export function ballScale(config: RenderConfig, baseDiameter: number): number {
  return config.cvVisibility ? Math.max(config.ballScale, Math.min(2, 5 / Math.max(baseDiameter, 1e-6))) : config.ballScale;
}
