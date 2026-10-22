import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createServer } from 'vite';

/** Automation must not reload when another process builds or optimizes the same repository. */
export async function renderingServer() {
  const cacheDir = await mkdtemp(join(tmpdir(), 'renderer-vite-'));
  try {
    const server = await createServer({
      cacheDir,
      server: { host: '127.0.0.1', port: 0, watch: null, hmr: false },
      logLevel: 'error',
    });
    return { server, async closeServer() {
      try { await server.close(); } finally { await rm(cacheDir, { recursive: true, force: true }); }
    } };
  } catch (error) {
    await rm(cacheDir, { recursive: true, force: true });
    throw error;
  }
}
