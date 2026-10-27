import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { loadTs } from './support/load-ts.mjs';
const web = fileURLToPath(new URL('../', import.meta.url));
const { FeedSwitcher, feedsSynchronized } = loadTs(`${web}/src/playback/feeds.ts`);
const { buildRoster, drawOverlays } = loadTs(`${web}/src/render/draw.ts`);
const { buildCamera } = loadTs(`${web}/src/render/camera.ts`);
const json = name => JSON.parse(readFileSync(new URL(`../../data/fake/sample_a/${name}`, import.meta.url), 'utf8'));
const info = json('match_info.json');
const pass = json('events.json').find(e => e.type === 'pass');
const first = JSON.parse(readFileSync(new URL('../../data/fake/sample_a/tracking.jsonl', import.meta.url), 'utf8').split('\n')[0]);
class Media extends EventTarget {
  currentTime = 5; duration = 12; paused = true; playbackRate = 1.5; muted = true; volume = .3; hidden = false;
  pause() { this.paused = true; this.dispatchEvent(new Event('pause')); }
  play() { this.paused = false; this.dispatchEvent(new Event('play')); return Promise.resolve(); }
}

test('feed switching preserves paused/playing state, time, rate, audio and last-toggle intent', async () => {
  for (const playing of [true, false]) for (const time of [0, 5, 11.99, 12]) {
    const broadcast = new Media(), ai = new Media(); broadcast.paused = !playing; broadcast.currentTime = time;
    const controller = new FeedSwitcher(broadcast, ai, () => {});
    controller.switchTo(true);
    assert.equal(controller.active, ai);
    assert.equal(ai.currentTime, time);
    assert.equal(ai.paused, !playing || time === 12);
    assert.equal(ai.playbackRate, 1.5); assert.equal(ai.muted, true); assert.equal(ai.volume, .3);
    for (let i = 0; i < 21; i++) controller.switchTo(i % 2 !== 0);
    assert.equal(controller.active, broadcast);
    assert.equal(broadcast.currentTime, time);
    assert.equal(broadcast.hidden, false); assert.equal(ai.hidden, true);
  }
});

test('AI failure restores broadcast at current time and user-paused state', () => {
  const broadcast = new Media(), ai = new Media();
  const controller = new FeedSwitcher(broadcast, ai, () => {});
  controller.switchTo(true); ai.currentTime = 9; ai.pause(); controller.fail();
  assert.equal(controller.active, broadcast); assert.equal(broadcast.currentTime, 9); assert.equal(broadcast.paused, true);
});

test('AI decode failure resumes a previously playing feed at its latest position', () => {
  const broadcast = new Media(), ai = new Media(); broadcast.paused = false;
  const controller = new FeedSwitcher(broadcast, ai, () => {});
  controller.switchTo(true); ai.currentTime = 8.2;
  ai.error = { code: 3 }; ai.pause(); controller.fail();
  assert.equal(controller.active, broadcast); assert.equal(broadcast.currentTime, 8.2);
  assert.equal(broadcast.paused, false);
});

test('browser metadata rejects changed durations and invalid rates', () => {
  assert.equal(feedsSynchronized(12, 12, 12, 25), true);
  for (const args of [[12, 11, 12, 25], [13, 12, 12, 25], [12, 12, 12, 0], [12, NaN, 12, 25]]) assert.equal(feedsSynchronized(...args), false);
});

// Explicitly synthetic overlay inputs; never reported as agent or detector output.
const base = { id: 'o9201', start: 0, duration: 60, graphic: 'insight_text', event_ids: [pass.id], text: 'Synthetic stacking test', mode: 'analyst', lang: 'en' };
const ctx = new Proxy({ measureText: text => ({ width: text.length * 5 }) }, { get: (o, key) => o[key] ?? (() => {}) });

test('every effective corner retains two highest priorities with stable ties at desktop/mobile widths', () => {
  const corners = ['top-left', 'top-right', 'bottom-left', 'bottom-right', 'bottom-center'];
  const overlays = corners.flatMap(position => [1, 3, 3, 2].map((priority, i) => ({ ...base, id: `${position}-${i}`, position, priority })));
  const fallback = { ...base, id: 'fallback', player: null, position: 'follow-player', priority: 5 };
  for (const width of [1280, 343]) {
    const regions = drawOverlays(ctx, width, width * 9 / 16, [...overlays, fallback], buildRoster(info), new Map([[pass.id, pass]]), { info, frames: [] }, 10);
    assert.equal(regions.length, 10);
    for (const corner of corners) {
      const ids = regions.filter(r => r.overlay.position === corner || corner === 'bottom-left' && r.overlay.id === 'fallback').map(r => r.overlay.id);
      assert.deepEqual(ids, corner === 'bottom-left' ? ['fallback', `${corner}-1`] : [`${corner}-1`, `${corner}-2`]);
    }
  }
});

test('projected player tags survive saturated fixed corners and keep evidence references', () => {
  const match = { info, frames: [first] };
  const actor = first.players.find(p => p.team === 'home');
  const event = { ...pass, from: actor.id };
  const tag = { ...base, id: 'tag', player: actor.id, position: 'follow-player' };
  const cards = [1, 2, 3].map(priority => ({ ...base, id: `fixed-${priority}`, position: 'bottom-left', priority }));
  const camera = buildCamera('cv_full_pitch', match, 0, 16 / 9);
  const regions = drawOverlays(ctx, 1280, 720, [...cards, tag], buildRoster(info), new Map([[pass.id, event]]), match, 1, camera);
  assert.deepEqual(regions.map(r => r.overlay.id), ['fixed-3', 'fixed-2', 'tag']);
  assert.equal(regions.at(-1).overlay, tag);
  assert.deepEqual(regions.at(-1).overlay.event_ids, [pass.id]);
});
