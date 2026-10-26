import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, copyFile, writeFile, readFile, readdir, rm, access, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { prepareMatch } from '../scripts/prepare.mjs';

const ROOT = fileURLToPath(new URL('../../', import.meta.url));
const required = ['events.json', 'match.mp4', 'match.mp4.manifest.json', 'match_info.json', 'overlays.json'];
const prepared = [...required, 'feeds.json'].sort();

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
  assert.deepEqual((await readdir(f.outputDir)).sort(), [...prepared, 'tracking.jsonl'].sort());
  assert.deepEqual(await readFile(join(f.outputDir, 'match.mp4')), await readFile(join(f.repoRoot, 'data/renders/sample_a-60s.mp4')));
});

test('explicit selection needs only five files and replaces stale optional/unrelated assets', async t => {
  const f = await fixture(t);
  await prepareMatch({ repoRoot: f.repoRoot, outputDir: f.outputDir });
  await writeFile(join(f.outputDir, 'stale.json'), '{}');
  await writeFile(join(f.selected, 'unrelated-large-file.bin'), 'do not publish');
  await prepareMatch(f);
  assert.deepEqual((await readdir(f.outputDir)).sort(), prepared);
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

/** report.example.json moved to the fixture's match, citing its first events. */
async function fixtureReport(f) {
  const info = JSON.parse(await readFile(join(f.selected, 'match_info.json'), 'utf8'));
  const events = JSON.parse(await readFile(join(f.selected, 'events.json'), 'utf8'));
  const report = JSON.parse(await readFile(join(ROOT, 'schemas/examples/report.example.json'), 'utf8'));
  report.match_id = info.match_id;
  for (const insight of report.insights) insight.event_ids = insight.event_ids.length ? [events[0].id] : [];
  return report;
}

test('an optional report.json is published when present, and its absence changes nothing', async t => {
  const f = await fixture(t);
  await prepareMatch(f);
  assert.ok(!(await readdir(f.outputDir)).includes('report.json'));
  await writeFile(join(f.selected, 'report.json'), JSON.stringify(await fixtureReport(f)));
  await prepareMatch(f);
  assert.deepEqual((await readdir(f.outputDir)).sort(), [...prepared, 'report.json'].sort());
  assert.deepEqual(await readFile(join(f.outputDir, 'report.json')), await readFile(join(f.selected, 'report.json')));
});

test('rejects a report from another match or citing events this bundle lacks', async t => {
  const f = await fixture(t);
  const report = await fixtureReport(f);
  await writeFile(join(f.selected, 'report.json'), JSON.stringify({ ...report, match_id: 'wrong-match' }));
  await assert.rejects(prepareMatch(f), /report.json match_id must equal/);
  report.insights[0].event_ids = ['e9999'];
  await writeFile(join(f.selected, 'report.json'), JSON.stringify(report));
  await assert.rejects(prepareMatch(f), /report.json: i1 cites an event missing/);
  await assert.rejects(access(f.outputDir));
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

// Duplicated calibration media tests transport, not genuine detector output.
test('optional AI feed is probed, copied and cleared when switching to one feed', async t => {
  const f = await fixture(t);
  await copyFile(join(f.selected, 'match.mp4'), join(f.selected, 'ai_view.mp4'));
  await copyFile(join(f.selected, 'match.mp4.manifest.json'), join(f.selected, 'ai_view.mp4.manifest.json'));
  await prepareMatch(f);
  const descriptor = JSON.parse(await readFile(join(f.outputDir, 'feeds.json')));
  assert.deepEqual(descriptor, { aiView: true, fps: 25, duration: 12 });
  assert.deepEqual(await readFile(join(f.outputDir, 'ai_view.mp4')), await readFile(join(f.selected, 'match.mp4')));
  await prepareMatch({ repoRoot: f.repoRoot, outputDir: f.outputDir });
  assert.equal(JSON.parse(await readFile(join(f.outputDir, 'feeds.json'))).aiView, false);
  await assert.rejects(access(join(f.outputDir, 'ai_view.mp4')));
});

test('corrupt AI media and mismatched source interval/identity fail preparation', async t => {
  const f = await fixture(t);
  await writeFile(join(f.selected, 'ai_view.mp4'), 'explicitly corrupt test video');
  await assert.rejects(prepareMatch(f), /Cannot validate.*ai_view/);
  await assert.rejects(access(f.outputDir));
  await copyFile(join(f.selected, 'match.mp4'), join(f.selected, 'ai_view.mp4'));
  const manifest = JSON.parse(await readFile(join(f.selected, 'match.mp4.manifest.json')));
  for (const change of [{ match_id: 'different' }, { start: 1 }, { fps: 30 }]) {
    await writeFile(join(f.selected, 'ai_view.mp4.manifest.json'), JSON.stringify({ ...manifest, ...change }));
    await assert.rejects(prepareMatch(f), /must match broadcast/);
    await assert.rejects(access(f.outputDir));
  }
  await rm(join(f.selected, 'ai_view.mp4.manifest.json'));
  await writeFile(join(f.selected, 'match.mp4.manifest.json'), JSON.stringify({ ...manifest, end: 11 }));
  await assert.rejects(prepareMatch(f), /matching duration, frame rate/);
});
