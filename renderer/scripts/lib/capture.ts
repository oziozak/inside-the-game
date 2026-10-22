import type { Locator, Page } from 'playwright';

/** Complete WebGL commands and cross a paint boundary before strict screenshot capture.
 * No retries, pixel tolerances, timer sleeps, or simulation-time advancement.
 */
export async function captureCanvas(page: Page, options?: Parameters<Locator['screenshot']>[0]): Promise<Buffer> {
  const canvas = page.locator('canvas');
  await canvas.evaluate(async element => {
    const gl = (element as HTMLCanvasElement).getContext('webgl2');
    if (!gl || gl.isContextLost()) throw new Error('Canvas WebGL context is unavailable or lost');
    gl.finish();
    await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
  });
  return canvas.screenshot(options);
}
