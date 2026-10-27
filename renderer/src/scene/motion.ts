import { sample, type Frame, type Match } from '../data/match';

export interface PlayerPose { heading: number; stride: number; speed: number }
/** Causal motion estimate: no accumulated pose, future samples, or mutable tracking. */
export function playerPoses(match: Match, frame: Frame): Map<number, PlayerPose> {
  const start = Math.max(match.frames[0].t, ...(match.info.periods ?? []).filter(p => p.start <= frame.t).map(p => p.start));
  const before = sample(match, Math.max(start, frame.t - 0.12));
  const dt = frame.t - before.t;
  const previous = new Map(before.players.map(p => [p.id, p]));
  return new Map(frame.players.map(player => {
    const old = previous.get(player.id);
    const dx = old ? player.pos[0] - old.pos[0] : 0;
    const dz = old ? old.pos[1] - player.pos[1] : 0;
    const measured = dt > 1e-6 && old?.team === player.team ? Math.hypot(dx, dz) / dt : 0;
    // Hold neutral through gaps, period cuts, and implausible relocation velocities.
    const speed = measured <= 12 && dt <= 0.16 ? measured : 0;
    const moving = speed > 0.15;
    return [player.id, {
      heading: moving ? Math.atan2(dx, dz) : 0,
      stride: moving ? Math.sin(frame.t * Math.PI * 4 + player.id * 0.7) * Math.min(0.32, speed * 0.065) : 0,
      speed,
    }];
  }));
}
