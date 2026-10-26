import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, copyFile, writeFile, readFile, readdir, rm, access, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { prepareMatch } from '../scripts/prepare.mjs';

const ROOT = fileURLToPath(new URL('../../', import.meta.url));
const required = ['events.json', 'match.mp4', 'match.mp4.manifest.json', 'match_info.json', 'overlays.json'];

/** Reuse the committed calibration match, export, and labels in an isolated repository layout. */
async function fixture(t) {
  const repoRoot = await mkdtemp(join(tmpdir(), 'web-match-test-'));
  t.after(() => rm(repoRoot, { recursive: true, force: true }));
  const outputDir = join(repoRoot, 'web/public/sample');
  const selected = join(repoRoot, 'data/demo/second');
  const defaults = {
    'match_info.json': 'data/fake/sample_a/match_info.json',
    'events.json': 'data/fake/sample_a/events.json',
    'overlays.json': 'data/generated/sample_a/overlays.json',
    'match.mp4': 'data/renders/sample_a-60s.mp4',
    'match.mp4.manifest.json': 'data/renders/sample_a-60s.mp4.manifest.json',
    'tracking.jsonl': 'data/fake/sample_a/tracking.jsonl',
  };
  const sources = {
    'match_info.json': 'vision/fixtures/calibration/match_info.json',
    'events.json': 'renderer/fixtures/calibration/ground_truth.events.json',
    'match.mp4': 'vision/fixtures/calibration/calibration.mp4',
    'match.mp4.manifest.json': 'vision/fixtures/calibration/calibration.mp4.manifest.json',
    'tracking.jsonl': 'renderer/fixtures/calibration/tracking.jsonl',
  };
  await mkdir(selected, { recursive: true });
  for (const [name, source] of Object.entries(sources)) {
    const target = join(repoRoot, defaults[name]);
    await mkdir(join(target, '..'), { recursive: true });
    await copyFile(join(ROOT, source), target);
    if (name !== 'tracking.jsonl') await copyFile(join(ROOT, source), join(selected, name));
  }
  // Retain only existing fixture overlays whose evidence is present in the calibration labels.
  const events = JSON.parse(await readFile(join(selected, 'events.json'), 'utf8'));
  const ids = new Set(events.map(e => e.id));
  const overlays = JSON.parse(await readFile(join(ROOT, 'data/fake/sample_a/overlays.json'), 'utf8'))
    .filter(o => o.event_ids.every(id => ids.has(id)));
  for (const target of [join(repoRoot, defaults['overlays.json']), join(selected, 'overlays.json')]) {
    await mkdir(join(target, '..'), { recursive: true });
    await writeFile(target, JSON.stringify(overlays));
  }
  return { repoRoot, outputDir, selected, match: 'data/demo/second' };
}

test('default uses the existing sample_a paths and retains tracking', async t => {
  const f = await fixture(t);
  await prepareMatch({ repoRoot: f.repoRoot, outputDir: f.outputDir });
  assert.deepEqual((await readdir(f.outputDir)).sort(), [...required, 'tracking.jsonl'].sort());
  assert.deepEqual(await readFile(join(f.outputDir, 'match.mp4')), await readFile(join(f.repoRoot, 'data/renders/sample_a-60s.mp4')));
});

test('explicit selection needs only five files and replaces stale optional/unrelated assets', async t => {
  const f = await fixture(t);
  await prepareMatch({ repoRoot: f.repoRoot, outputDir: f.outputDir });
  await writeFile(join(f.outputDir, 'stale.json'), '{}');
  await writeFile(join(f.selected, 'unrelated-large-file.bin'), 'do not publish');
  await prepareMatch(f);
  assert.deepEqual((await readdir(f.outputDir)).sort(), required);
  for (const name of required) assert.deepEqual(await readFile(join(f.outputDir, name)), await readFile(join(f.selected, name)));
});

test('explicit optional tracking is included when present', async t => {
  const f = await fixture(t);
  await copyFile(join(ROOT, 'renderer/fixtures/calibration/tracking.jsonl'), join(f.selected, 'tracking.jsonl'));
  await prepareMatch(f);
  assert.ok((await readdir(f.outputDir)).includes('tracking.jsonl'));
});

for (const name of required) test(`missing ${name} fails clearly and clears the previous match`, async t => {
  const f = await fixture(t);
  await prepareMatch({ repoRoot: f.repoRoot, outputDir: f.outputDir });
  await rm(join(f.selected, name));
  await assert.rejects(prepareMatch(f), error => error.message.includes('MATCH=data/demo/second') && error.message.includes(name));
  await assert.rejects(access(f.outputDir));
});

test('missing default output fails instead of silently keeping an old bundle', async t => {
  const f = await fixture(t);
  await prepareMatch(f);
  await rm(join(f.repoRoot, 'data/generated/sample_a/overlays.json'));
  await assert.rejects(prepareMatch({ repoRoot: f.repoRoot, outputDir: f.outputDir }), /Missing required assets for default sample_a/);
  await assert.rejects(access(f.outputDir));
});

test('rejects mismatched manifest/events and leaves no partially published files', async t => {
  const f = await fixture(t);
  const manifestPath = join(f.selected, 'match.mp4.manifest.json');
  const original = await readFile(manifestPath);
  const manifest = JSON.parse(original);
  manifest.match_id = 'wrong-match';
  await writeFile(manifestPath, JSON.stringify(manifest));
  await assert.rejects(prepareMatch(f), /manifest.json match_id must equal/);
  await assert.rejects(access(f.outputDir));
  await writeFile(manifestPath, original);
  const eventsPath = join(f.selected, 'events.json');
  const events = JSON.parse(await readFile(eventsPath));
  events[0].match_id = 'wrong-match';
  await writeFile(eventsPath, JSON.stringify(events));
  await assert.rejects(prepareMatch(f), /events.json contains a different match_id/);
  assert.deepEqual(await readdir(join(f.repoRoot, 'web/public')), []);
});

test('rejects overlays citing events from another bundle', async t => {
  const f = await fixture(t);
  const overlays = JSON.parse(await readFile(join(ROOT, 'data/fake/sample_a/overlays.json')));
  await writeFile(join(f.selected, 'overlays.json'), JSON.stringify(overlays));
  await assert.rejects(prepareMatch(f), /cites an event missing/);
});

test('invalid explicit paths never fall back, including symlink escapes', async t => {
  const f = await fixture(t);
  for (const match of ['', '../outside', f.selected, 'data/demo/does-not-exist']) {
    await assert.rejects(prepareMatch({ ...f, match }), /MATCH/);
    await assert.rejects(access(f.outputDir));
  }
  await symlink(tmpdir(), join(f.repoRoot, 'outside'));
  await assert.rejects(prepareMatch({ ...f, match: 'outside' }), /within the repository/);
});
