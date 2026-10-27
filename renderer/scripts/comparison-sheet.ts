import { readFile, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { chromium } from 'playwright';
import { artifactDirectory } from './lib/paths';

// This is a review artifact, never composited into exported CV footage.
const artifacts = await artifactDirectory();
const root = resolve('../data/renders/visual-overhaul');
const times = ['2503', '2508', '2512.96'];
const panels = [];
for (const t of times) for (const directory of ['before-rich', 'after-rich']) {
  const bytes = await readFile(`${root}/${directory}/broadcast-${t}.png`);
  panels.push(`<figure><figcaption>${directory === 'before-rich' ? 'Phase 3 baseline' : 'Visual overhaul'} · ${t} s</figcaption><img src="data:image/png;base64,${bytes.toString('base64')}" /></figure>`);
}
const html = `<!doctype html><meta charset="utf-8"><style>*{box-sizing:border-box}body{margin:0;padding:24px;background:#101b29;color:#eaf2ed;font:22px system-ui}h1{margin:0 0 20px;font-size:30px}main{display:grid;grid-template-columns:1fr 1fr;gap:16px}figure{margin:0}figcaption{padding:8px 0}img{display:block;width:100%}</style><h1>Inside the Game · Genuine simulator comparison · Same input timestamps</h1><main>${panels.join('')}</main>`;
await writeFile(`${artifacts}/comparison-sheet.html`, html);
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1920, height: 1200 }, deviceScaleFactor: 1 });
  await page.setContent(html); await page.locator('img').evaluateAll(images => Promise.all(images.map(image => (image as HTMLImageElement).decode())));
  await page.screenshot({ path: `${artifacts}/comparison-sheet.png`, fullPage: true });
} finally { await browser.close(); }
console.log(`Saved exact-source comparison sheet to ${artifacts}`);
