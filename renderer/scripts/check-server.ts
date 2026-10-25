import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { chromium } from 'playwright';

// An OS-assigned port avoids sharing a fixed port with concurrent checks.
const server = spawn(process.execPath, ['scripts/serve.mjs'], { env: { ...process.env, PORT: '0', HOST: '127.0.0.1' }, stdio: ['ignore', 'pipe', 'inherit'] });
const closed = new Promise<void>(resolve => server.once('close', () => resolve()));
let browser: Awaited<ReturnType<typeof chromium.launch>> | undefined;
try {
  const port = await new Promise<number>((resolve, reject) => {
    let log = '';
    server.once('error', reject);
    server.once('close', code => reject(new Error(`Static server exited before readiness: ${code}`)));
    server.stdout.on('data', bytes => {
      log += bytes;
      const match = /Renderer listening on (\d+)/.exec(log);
      if (match) resolve(Number(match[1]));
    });
  });
  const base = `http://127.0.0.1:${port}`;
  const health = await fetch(`${base}/healthz`);
  assert.equal(health.status, 200); assert.deepEqual(await health.json(), { status: 'ok' });
  const html = await fetch(base).then(r => { assert.equal(r.status, 200); return r.text(); });
  for (const [, path] of html.matchAll(/(?:src|href)="(\/assets\/[^" ]+)"/g)) assert.equal((await fetch(base + path)).status, 200);
  assert.equal((await fetch(`${base}/sample/match_info.json`)).status, 200);
  assert.equal((await fetch(`${base}/.env`)).status, 404);
  assert.equal((await fetch(base, { method: 'POST' })).status, 405);
  assert.equal((await fetch(base, { method: 'HEAD' })).status, 200);
  browser = await chromium.launch({ args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const page = await browser.newPage();
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto(base); await page.waitForFunction(() => !document.querySelector<HTMLButtonElement>('#play')!.disabled);
  assert.equal((await page.evaluate(() => window.broadcast.inspect())).players.length, 22);
  assert.deepEqual(errors, []);
  console.log(`Production server passed: configured ephemeral port ${port}, health, static assets, sample loading, GET/HEAD, POST rejection, and no .env exposure.`);
} finally {
  try { await browser?.close(); } finally { server.kill(); await closed; }
}
