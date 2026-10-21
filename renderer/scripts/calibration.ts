import type { Frame, MatchInfo } from '../src/data/match';
import { FPS } from '../src/playback/timing';

export const CALIBRATION_DURATION = 12;
/** Isolated analytic choreography; no simulator dependency, randomness, or hidden renderer labels. */
export function calibration(info: MatchInfo) {
  const metadata = structuredClone(info);
  metadata.match_id = 'renderer_calibration_v1';
  metadata.periods = [{ period: 1, start: 0, end: CALIBRATION_DURATION }];
  const frames: Frame[] = Array.from({ length: CALIBRATION_DURATION * FPS }, (_, frame) => {
    const t = frame / FPS;
    const carry = Math.max(0, Math.min(1, (t - 5) / 3));
    let ball = [55.75, 24.25, 0.11];
    if (t >= 2 && t < 4) {
      const u = (t - 2) / 2;
      ball = [55.75 + 17 * u, 24.25 + 5 * u, 0.11 + 0.18 * Math.sin(Math.PI * u)];
    } else if (t >= 4 && t < 8) ball = [72.75 + 15 * carry, 29.25 + 4 * carry, 0.11];
    else if (t >= 8 && t < 9) {
      const u = t - 8;
      ball = [87.75 + 18.25 * u, 33.25 + 0.75 * u, 0.11 + 3.2 * u * (1 - u)];
    } else if (t >= 9) ball = [106, 34, 0.11];
    return { match_id: metadata.match_id, frame, t, ball, players: [
      { id: 8, team: 'home', pos: [55, 25] },
      { id: 10, team: 'home', pos: [72 + 15 * carry, 30 + 4 * carry] },
    ] };
  });
  // Shared event format used solely as separate evaluation truth, never a renderer input.
  const passDistance = Math.hypot(17, 5), shotDistance = Math.hypot(18.25, 0.75);
  const events = [
    { id: 'e0001', match_id: metadata.match_id, t: 2, period: 1, type: 'pass', subtype: 'short', team: 'home', from: 8, to: 10, start: [55.75, 24.25], end: [72.75, 29.25], duration_s: 2, distance_m: passDistance, speed_kmh: passDistance / 2 * 3.6, success: true, source: 'sim', confidence: 1 },
    { id: 'e0002', match_id: metadata.match_id, t: 8, period: 1, type: 'shot', subtype: 'on_target', team: 'home', from: 10, to: null, start: [87.75, 33.25], end: [106, 34], duration_s: 1, distance_m: shotDistance, speed_kmh: shotDistance * 3.6, success: true, source: 'sim', confidence: 1 },
    { id: 'e0003', match_id: metadata.match_id, t: 8 + 17.25 / 18.25, period: 1, type: 'goal', subtype: 'open_play', team: 'home', from: 10, to: null, start: [105, 33.25 + 0.75 * 17.25 / 18.25], score: { home: 1, away: 0 }, source: 'sim', confidence: 1 },
  ];
  return { metadata, frames, events };
}
