import { mkdir, copyFile, rename, rm } from 'node:fs/promises';
// Bundle only the two renderer inputs, never events or overlays.
await mkdir(new URL('../public/sample/', import.meta.url), { recursive: true });
for (const name of ['match_info.json', 'tracking.jsonl']) {
  const target = new URL(`../public/sample/${name}`, import.meta.url);
  const temporary = new URL(`../public/sample/.${name}.${process.pid}.tmp`, import.meta.url);
  try {
    await copyFile(new URL(`../../data/fake/sample_a/${name}`, import.meta.url), temporary);
    // A browser test fetching the sample during a build must see a complete file.
    await rename(temporary, target);
  } finally { await rm(temporary, { force: true }); }
}
