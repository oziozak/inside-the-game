import { mkdir, copyFile, rename, rm, stat, readFile, realpath, mkdtemp, writeFile } from 'node:fs/promises';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { dirname, resolve, relative, isAbsolute, join, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('../../', import.meta.url));
const OUTPUT = fileURLToPath(new URL('../public/sample/', import.meta.url));
const REQUIRED = ['match_info.json', 'events.json', 'overlays.json', 'match.mp4', 'match.mp4.manifest.json'];
const run = promisify(execFile);

/** Probe actual media rather than assuming that similarly named files share a timeline. */
async function probe(path) {
  try {
    const { stdout } = await run('ffprobe', ['-v', 'error', '-select_streams', 'v:0', '-show_entries',
      'stream=duration,avg_frame_rate,r_frame_rate', '-of', 'json', path]);
    const stream = JSON.parse(stdout).streams[0];
    const rate = value => { const [n, d] = value.split('/').map(Number); return n / d; };
    const fps = rate(stream.avg_frame_rate), nominal = rate(stream.r_frame_rate), duration = Number(stream.duration);
    if (!(fps > 0 && duration > 0) || !Number.isFinite(fps + duration) || Math.abs(fps - nominal) > 0.000001) {
      throw new Error('expected finite duration and constant frame rate');
    }
    return { fps, duration };
  } catch (error) { throw new Error(`Cannot validate ${path}: ${error.message}. Two-feed bundles require FFprobe and readable constant-frame-rate video.`); }
}

/** Publish only feeds validated together; an optional sidecar additionally verifies source interval/identity. */
async function prepareFeeds(folder) {
  if (!await isFile(join(folder, 'ai_view.mp4'))) return { aiView: false };
  const broadcast = await probe(join(folder, 'match.mp4'));
  const ai = await probe(join(folder, 'ai_view.mp4'));
  const manifest = await readJson(folder, 'match.mp4.manifest.json');
  const tolerance = 0.5 / broadcast.fps + 0.000001;
  if (![manifest.start, manifest.end, manifest.fps].every(Number.isFinite)
      || Math.abs(ai.fps - broadcast.fps) > 0.000001 || Math.abs(ai.duration - broadcast.duration) > tolerance
      || Math.abs(manifest.fps - broadcast.fps) > 0.000001
      || Math.abs(manifest.end - manifest.start - broadcast.duration) > tolerance) {
    throw new Error('ai_view.mp4 and match.mp4 must have matching duration, frame rate and broadcast manifest interval');
  }
  if (await isFile(join(folder, 'ai_view.mp4.manifest.json'))) {
    const sidecar = await readJson(folder, 'ai_view.mp4.manifest.json');
    if (sidecar.match_id !== manifest.match_id || ['start', 'end', 'fps'].some(key => sidecar[key] !== manifest[key])) {
      throw new Error('ai_view.mp4.manifest.json must match broadcast match_id, start, end and fps');
    }
  }
  return { aiView: true, ...broadcast };
}

function inside(parent, child) {
  const path = relative(parent, child);
  return path !== '..' && !path.startsWith(`..${sep}`) && !isAbsolute(path);
}

async function isFile(path) {
  try { return (await stat(path)).isFile(); }
  catch (error) { if (error.code === 'ENOENT') return false; throw error; }
}

async function readJson(folder, name) {
  try { return JSON.parse(await readFile(join(folder, name), 'utf8')); }
  catch (error) { throw new Error(`Invalid ${name}: ${error.message}`); }
}

/** Reject mismatched sidecars/events and evidence from a different prepared bundle. */
async function validateBundle(folder) {
  const info = await readJson(folder, 'match_info.json');
  const manifest = await readJson(folder, 'match.mp4.manifest.json');
  if (!info.match_id || manifest.match_id !== info.match_id) {
    throw new Error('match.mp4.manifest.json match_id must equal match_info.json match_id');
  }
  const events = await readJson(folder, 'events.json');
  const overlays = await readJson(folder, 'overlays.json');
  if (!Array.isArray(events) || !Array.isArray(overlays)) throw new Error('events.json and overlays.json must be JSON arrays');
  if (events.some(event => event.match_id !== info.match_id)) throw new Error('events.json contains a different match_id from match_info.json');
  const ids = new Set(events.map(event => event.id));
  for (const overlay of overlays) {
    if (!Array.isArray(overlay.event_ids) || overlay.event_ids.some(id => !ids.has(id))) {
      throw new Error(`overlays.json: ${overlay.id} cites an event missing from events.json`);
    }
  }
  // The analyst report is optional; when present it must be this match's, citing these events.
  if (await isFile(join(folder, 'report.json'))) {
    const report = await readJson(folder, 'report.json');
    if (report.match_id !== info.match_id) throw new Error('report.json match_id must equal match_info.json match_id');
    if (!Array.isArray(report.insights)) throw new Error('report.json insights must be an array');
    for (const insight of report.insights) {
      if (!Array.isArray(insight.event_ids) || insight.event_ids.some(id => !ids.has(id))) {
        throw new Error(`report.json: ${insight.id} cites an event missing from events.json`);
      }
    }
  }
}

/** Copy a complete, validated asset set; never publish a mix of old and new matches. */
export async function prepareMatch({ repoRoot = ROOT, outputDir = OUTPUT, match } = {}) {
  repoRoot = await realpath(repoRoot);
  outputDir = resolve(outputDir);
  const selected = match !== undefined;
  // Do not remove a caller-selected source that is itself inside the generated directory.
  if (selected && inside(resolve(outputDir), resolve(repoRoot, match))) {
    throw new Error('MATCH must not point into web/public/sample (generated output)');
  }
  await rm(outputDir, { recursive: true, force: true });
  let staging;
  try {
    let sources;
    if (selected) {
      if (!match.trim() || isAbsolute(match) || !inside(repoRoot, resolve(repoRoot, match))) {
        throw new Error('MATCH must be a non-empty path relative to the repository root, within that repository');
      }
      let folder;
      try { folder = await realpath(resolve(repoRoot, match)); }
      catch (error) { throw new Error(`MATCH folder not found: ${match} (${error.message})`); }
      if (!inside(repoRoot, folder) || inside(resolve(outputDir), folder)) throw new Error('MATCH must resolve within the repository and outside web/public/sample');
      sources = REQUIRED.map(name => [join(folder, name), name]);
      if (await isFile(join(folder, 'tracking.jsonl'))) sources.push([join(folder, 'tracking.jsonl'), 'tracking.jsonl']);
      for (const name of ['ai_view.mp4', 'ai_view.mp4.manifest.json', 'report.json']) {
        if (await isFile(join(folder, name))) sources.push([join(folder, name), name]);
      }
    } else {
      sources = [
        ['data/fake/sample_a/match_info.json', 'match_info.json'],
        ['data/fake/sample_a/tracking.jsonl', 'tracking.jsonl'],
        ['data/fake/sample_a/events.json', 'events.json'],
        ['data/generated/sample_a/overlays.json', 'overlays.json'],
        ['data/renders/sample_a-60s.mp4', 'match.mp4'],
        ['data/renders/sample_a-60s.mp4.manifest.json', 'match.mp4.manifest.json'],
      ].map(([source, name]) => [join(repoRoot, source), name]);
    }
    const missing = [];
    for (const [source, name] of sources) if (!await isFile(source)) missing.push(`${name}: ${source}`);
    if (missing.length) throw new Error(`Missing required assets for ${selected ? `MATCH=${match}` : 'default sample_a'}:\n${missing.join('\n')}`);
    await mkdir(dirname(outputDir), { recursive: true });
    staging = await mkdtemp(`${outputDir}.tmp-`);
    for (const [source, name] of sources) await copyFile(source, join(staging, name));
    await validateBundle(staging);
    await writeFile(join(staging, 'feeds.json'), JSON.stringify(await prepareFeeds(staging)));
    await rename(staging, outputDir);
    console.log(`Prepared ${selected ? `MATCH=${match}` : 'default sample_a'} (${sources.length} assets)`);
  } finally {
    if (staging) await rm(staging, { recursive: true, force: true });
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { await prepareMatch({ match: process.env.MATCH }); }
  catch (error) { console.error(`Web match preparation failed: ${error.message}`); process.exitCode = 1; }
}
