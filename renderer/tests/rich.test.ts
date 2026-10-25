import assert from 'node:assert/strict';
import { test } from 'node:test';
import { richGait } from '../src/scene/rich';

test('rich gait has stable idle, bounded movement and seek-independent speed blending', () => {
  for (const t of [0, 1.2, 2503, 2508.72, 5400]) {
    assert.equal(richGait(t, 17, 0), 0);
    for (const speed of [0.2, 1, 2, 4, 8, 12]) {
      const direct = richGait(t, 17, speed);
      richGait(999, 2, 4); richGait(0, 17, 0);
      assert.equal(richGait(t, 17, speed), direct);
      assert.ok(Math.abs(direct) <= 0.58);
      assert.ok(Math.abs(richGait(t, 17, speed + 0.001) - direct) < 0.002, 'small speed changes must not cause clock-dependent phase jumps');
      assert.ok(Math.abs(richGait(t + 0.001, 17, speed) - direct) < 0.01);
    }
  }
});
