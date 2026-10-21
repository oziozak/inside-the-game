import { Vector3 } from 'three';
import { sample, world, type Match } from '../data/match';

/** Fixed 0.8 s causal triangular filter evaluated from absolute simulation time, never render history. */
export function cameraTarget(match: Match, t: number): Vector3 {
  const start = Math.max(match.frames[0].t, ...((match.info.periods ?? []).filter(p => p.start <= t).map(p => p.start)));
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
