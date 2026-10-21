import { mkdir, copyFile } from 'node:fs/promises';
// Bundle only the two renderer inputs, never events or overlays.
await mkdir(new URL('../public/sample/', import.meta.url), { recursive: true });
for (const name of ['match_info.json', 'tracking.jsonl']) await copyFile(new URL(`../../data/fake/sample_a/${name}`, import.meta.url), new URL(`../public/sample/${name}`, import.meta.url));
