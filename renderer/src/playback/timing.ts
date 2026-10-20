export const FPS = 25;
/** Half-open interval [start,end), sampled from an integer frame index, never accumulated dt. */
export function exportTimes(start: number, end: number): number[] {
  if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end <= start) throw new Error('Expected 0 <= start < end');
  return Array.from({ length: Math.ceil((end - start) * FPS - 1e-8) }, (_, i) => start + i / FPS);
}
/** Match clock uses the shared second-half convention. */
export function clock(t: number, periods?: { period: number; start: number }[]): string {
  const second = periods?.find(p => p.period === 2);
  const seconds = Math.floor(second && t >= second.start ? 2700 + t - second.start : t);
  return `${Math.floor(seconds / 60).toString().padStart(2, '0')}:${(seconds % 60).toString().padStart(2, '0')}`;
}
