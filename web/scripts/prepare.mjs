import { mkdir, copyFile, rename, rm, access } from 'node:fs/promises';

// Bundle the dev sample into public/sample/: renderer inputs, agent-generated overlays
// (not the stale schemas/examples ones), and an exported clip if one has been rendered.
await mkdir(new URL('../public/sample/', import.meta.url), { recursive: true });

const copies = [
  ['../../data/fake/sample_a/match_info.json', 'match_info.json'],
  ['../../data/fake/sample_a/tracking.jsonl', 'tracking.jsonl'],
  ['../../data/fake/sample_a/events.json', 'events.json'],
  ['../../data/generated/sample_a/overlays.json', 'overlays.json'],
  ['../../data/renders/sample_a-60s.mp4', 'match.mp4'],
  ['../../data/renders/sample_a-60s.mp4.manifest.json', 'match.mp4.manifest.json'],
];

for (const [source, name] of copies) {
  const sourceUrl = new URL(source, import.meta.url);
  try { await access(sourceUrl); } catch { continue; }
  const target = new URL(`../public/sample/${name}`, import.meta.url);
  const temporary = new URL(`../public/sample/.${name}.${process.pid}.tmp`, import.meta.url);
  try {
    await copyFile(sourceUrl, temporary);
    await rename(temporary, target);
  } finally { await rm(temporary, { force: true }); }
}
