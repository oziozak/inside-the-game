import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { calibration } from './calibration';
import { parseMatch } from '../src/data/match';
const source = JSON.parse(await readFile(new URL('../../data/fake/sample_a/match_info.json', import.meta.url), 'utf8'));
const { metadata, frames, events } = calibration(source);
const tracking = frames.map(frame => JSON.stringify(frame)).join('\n') + '\n';
parseMatch(metadata, tracking);
const root = new URL('../fixtures/calibration/', import.meta.url);
await mkdir(root, { recursive: true });
for (const [name, text] of Object.entries({ 'match_info.json': JSON.stringify(metadata, null, 2), 'tracking.jsonl': tracking, 'ground_truth.events.json': JSON.stringify(events, null, 2) })) {
  await writeFile(new URL(name, root), text.endsWith('\n') ? text : text + '\n');
}
console.log(`Generated ${frames.length} calibration frames (12 s at 25 FPS), metadata, and isolated event truth.`);
