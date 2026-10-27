/** Two metadata-ready videos share clip time, never a new overlay time origin. */
export class FeedSwitcher {
  active: HTMLVideoElement;
  private generation = 0;
  private lastPlaying = false;

  constructor(
    readonly broadcast: HTMLVideoElement, readonly ai: HTMLVideoElement,
    private changed: (ai: boolean) => void,
  ) {
    this.active = broadcast;
    ai.addEventListener('play', () => { this.lastPlaying = true; });
    ai.addEventListener('pause', () => { if (!ai.error) this.lastPlaying = false; });
  }

  switchTo(useAI: boolean, resume = !this.active.paused): void {
    const target = useAI ? this.ai : this.broadcast;
    if (target === this.active) return;
    const previous = this.active;
    const time = previous.currentTime;
    const generation = ++this.generation;
    previous.pause();
    target.playbackRate = previous.playbackRate;
    target.muted = previous.muted;
    target.volume = previous.volume;
    // Metadata is loaded before enabling the toggle. Setting currentTime is synchronous;
    // Chromium replaces a pending seek on rapid toggles, without reloading either source.
    target.currentTime = Math.min(time, target.duration);
    this.active = target;
    previous.hidden = true;
    target.hidden = false;
    this.lastPlaying = resume;
    this.changed(useAI);
    if (resume && target.currentTime < target.duration) {
      void target.play().catch(() => {
        if (generation !== this.generation) return;
        // A blocked play request leaves a usable paused feed; actual decode/network
        // errors use the media error handler and restore the broadcast.
        this.lastPlaying = false;
        this.changed(useAI);
      });
    }
  }

  /** Retain state even when the failed media element has already paused itself. */
  fail(): void {
    if (this.active === this.ai) this.switchTo(false, !this.ai.paused || this.lastPlaying);
  }
}

/** Recheck decoded metadata in the browser in case prepared assets were replaced. */
export function feedsSynchronized(broadcast: number, ai: number, duration: number, fps: number): boolean {
  const tolerance = 0.5 / fps + 0.000001;
  return [broadcast, ai, duration, fps].every(n => Number.isFinite(n) && n > 0)
    && Math.abs(broadcast - duration) <= tolerance && Math.abs(ai - duration) <= tolerance;
}
