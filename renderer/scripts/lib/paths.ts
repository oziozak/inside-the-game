import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
export const SIMULATOR_SOURCE = '../data/generated/renderer-m007/';
export const SIMULATOR_TRIMMED = '../data/generated/renderer-integration-trimmed/';
export const simulatorOptions = {
  metadata: { type: 'string', default: `${SIMULATOR_SOURCE}match_info.json` },
  tracking: { type: 'string', default: `${SIMULATOR_SOURCE}tracking.jsonl` },
  start: { type: 'string', default: '2503' }, end: { type: 'string', default: '2513' },
} as const;
/** Shared artifact root for browser checks and video validators. */
export async function artifactDirectory(): Promise<string> {
  const directory = resolve(process.env.RENDERER_TEST_ARTIFACT_DIR ?? '../data/renders');
  await mkdir(directory, { recursive: true });
  return directory;
}
