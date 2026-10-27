import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { loadTs } from './support/load-ts.mjs';

const web = fileURLToPath(new URL('../', import.meta.url));
const { parseClips, pickClip, clipBase, clipUrl, loadClips } = loadTs(`${web}/src/data/clips.ts`);

const clips = [{ id: 'test2', title: 'Held-out test 40\'-50\'' }, { id: 'hl1', title: 'Highlight: goal' }];

test('parseClips keeps a valid list and falls back to the id for a missing title', () => {
  assert.deepEqual(parseClips({ clips: [{ id: 'hl1' }, { id: 'hl2', title: '  Red card  ' }] }),
    [{ id: 'hl1', title: 'hl1' }, { id: 'hl2', title: 'Red card' }]);
});

test('parseClips rejects anything that is not a non-empty list of unique ids', () => {
  for (const body of [null, {}, { clips: [] }, { clips: 'x' }, { clips: [{ id: '../x' }] },
    { clips: [{ id: 'a' }, { id: 'a' }] }, { clips: [{ title: 'no id' }] }]) {
    assert.equal(parseClips(body), undefined, JSON.stringify(body));
  }
});

test('pickClip follows ?clip= and falls back to the first clip', () => {
  assert.equal(pickClip(clips, '?clip=hl1').id, 'hl1');
  assert.equal(pickClip(clips, '?clip=missing').id, 'test2');
  assert.equal(pickClip(clips, '').id, 'test2');
});

test('clipBase uses the subfolder only for a multi-clip build', () => {
  assert.equal(clipBase('./sample', undefined), './sample');
  assert.equal(clipBase('./sample', clips[1]), './sample/hl1');
});

test('clipUrl sets ?clip= and keeps other query parameters and the hash', () => {
  assert.equal(clipUrl('https://x.net/?lang=tr#player', 'hl1'), 'https://x.net/?lang=tr&clip=hl1#player');
  assert.equal(clipUrl('https://x.net/?clip=test2', 'hl1'), 'https://x.net/?clip=hl1');
});

test('loadClips treats a missing file or an HTML fallback as a one-clip build', async t => {
  const original = globalThis.fetch;
  t.after(() => { globalThis.fetch = original; });
  const reply = (status, type, body) => async () => new Response(body, { status, headers: { 'content-type': type } });
  globalThis.fetch = reply(404, 'text/plain', 'not found');
  assert.equal(await loadClips('./sample'), undefined);
  globalThis.fetch = reply(200, 'text/html', '<!doctype html>');
  assert.equal(await loadClips('./sample'), undefined);
  globalThis.fetch = reply(200, 'application/json', JSON.stringify({ clips }));
  assert.deepEqual(await loadClips('./sample'), clips);
});

test('the deployed demo (build:demo): seven clips, showcase first and the default, dev1 left out (#97)', () => {
  const pkg = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
  const ids = /MATCH=(\S+)/.exec(pkg.scripts['build:demo'])[1].split(',').map(path => path.split('/').pop());
  assert.deepEqual(ids, ['showcase', 'test2', 'test1', 'hl1', 'hl2', 'hl3', 'hl4']);
  const demo = parseClips({ clips: ids.map(id => ({ id, title: id })) });
  assert.equal(pickClip(demo, '').id, 'showcase');
  assert.equal(pickClip(demo, '?clip=dev1').id, 'showcase');   // an old link falls back, it does not break
  assert.equal(pickClip(demo, '?clip=hl2').id, 'hl2');
});
