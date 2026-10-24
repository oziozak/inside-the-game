import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { calibration } from '../scripts/calibration';
import { parseMatch, sample } from '../src/data/match';
import { renderConfig } from '../src/scene/config';
import { playerPoses } from '../src/scene/motion';

const info = JSON.parse(readFileSync(new URL('../../data/fake/sample_a/match_info.json', import.meta.url), 'utf8'));
const { metadata, frames } = calibration(info);
const match = parseMatch(metadata, frames.map(f => JSON.stringify(f)).join('\n'));

test('motion faces tracked velocity, stays timestamp deterministic, and leaves anchors untouched', () => {
  const frame = sample(match, 6), original = structuredClone(frame);
  const pose = playerPoses(match, frame), moving = frame.players[1];
  const before = sample(match, 5.88).players.find(p => p.id === moving.id)!;
  assert.ok(pose.get(moving.id)!.speed > 0.15);
  assert.equal(pose.get(moving.id)!.heading, Math.atan2(moving.pos[0] - before.pos[0], before.pos[1] - moving.pos[1]));
  assert.ok(Math.abs(pose.get(moving.id)!.stride) <= 0.32);
  playerPoses(match, sample(match, 9)); playerPoses(match, sample(match, 1));
  assert.deepEqual(playerPoses(match, frame), pose);
  assert.deepEqual(frame, original);
  assert.equal(playerPoses(match, sample(match, 1)).get(frames[0].players[0].id)!.stride, 0);
});

test('motion holds neutral across period starts, sparse gaps, missing IDs and relocations', () => {
  const id = frames[0].players[0].id;
  const a = { ...frames[0], t: 0, frame: 0 };
  const b = { ...frames[1], t: 1, frame: 25, players: frames[1].players.map(p => ({ ...p, pos: [p.pos[0] + 30, p.pos[1]] })) };
  const sparse = { info: match.info, frames: [a, b] };
  assert.equal(playerPoses(sparse, b).get(id)!.speed, 0);
  const relocated = { ...b, t: 0.04, frame: 1 };
  assert.equal(playerPoses({ info: match.info, frames: [a, relocated] }, relocated).get(id)!.speed, 0);
  const cut = { ...match, info: { ...match.info, periods: [{ period: 1, start: 0, end: 5.96 }, { period: 2, start: 6, end: 12 }] } };
  assert.ok([...playerPoses(cut, sample(cut, 6)).values()].every(p => p.speed === 0));
  const missing = { ...match, frames: match.frames.map(f => f.t < 6 ? { ...f, players: [] } : f) };
  assert.ok([...playerPoses(missing, sample(missing, 6)).values()].every(p => p.speed === 0));
});

test('shirt numbers and motion are independently configurable from CV materials', () => {
  assert.equal(renderConfig().animatePlayers, false, 'clean CV must default to static players');
  assert.equal(renderConfig({ animatePlayers: true }).animatePlayers, true, 'broadcast motion is explicit opt-in');
  assert.equal(renderConfig({ jerseyNumbers: true, cvVisibility: false }).jerseyNumbers, true);
  assert.equal(renderConfig({ animatePlayers: false, cvVisibility: true }).animatePlayers, false);
  assert.throws(() => renderConfig({ jerseyNumbers: 1 as never }));
  assert.throws(() => renderConfig({ animatePlayers: 'yes' as never }));
});
