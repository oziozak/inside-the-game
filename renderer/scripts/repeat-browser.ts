import { spawn } from 'node:child_process';
import { mkdir, mkdtemp, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { parseArgs } from 'node:util';
const { values } = parseArgs({ options: {
  runs: { type: 'string', default: '3' }, concurrency: { type: 'string', default: '1' }, load: { type: 'boolean', default: false },
} });
const runs = Number(values.runs), concurrency = Number(values.concurrency);
if (![runs, concurrency].every(n => Number.isInteger(n) && n >= 1) || concurrency > runs) throw new Error('runs and concurrency must be positive integers, with concurrency <= runs');
await mkdir('../runs', { recursive: true });
const artifacts = await mkdtemp(resolve('../runs/browser-repeat-'));
async function run(script: string, id: string) {
  const directory = `${artifacts}/${id}`; await mkdir(directory);
  const child = spawn(process.execPath, ['--import', 'tsx', script], {
    env: { ...process.env, RENDERER_TEST_ARTIFACT_DIR: directory },
  });
  let log = '';
  child.stdout!.on('data', bytes => { log += bytes; }); child.stderr!.on('data', bytes => { log += bytes; });
  const code = await new Promise<number | null>((resolve, reject) => { child.once('error', reject); child.once('close', resolve); });
  await writeFile(`${directory}/output.log`, log);
  console.log(`${id}: ${code === 0 ? 'PASS' : 'FAIL'}`);
  return { id, code };
}
const results = [];
for (let offset = 0; offset < runs; offset += concurrency) {
  const wave = Array.from({ length: Math.min(concurrency, runs - offset) }, (_, i) => run('scripts/smoke.ts', `browser-${offset + i}`));
  if (values.load) wave.push(run('scripts/check-calibration.ts', `calibration-load-${offset}`));
  results.push(...await Promise.all(wave));
}
await writeFile(`${artifacts}/results.json`, JSON.stringify({ runs, concurrency, load: values.load, results }, null, 2));
console.log(`Strict screenshot results: ${artifacts}/results.json`);
if (results.some(r => r.code !== 0)) process.exitCode = 1;
