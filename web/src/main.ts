import { loadMatch, loadEvents, loadOverlays, loadManifest } from './data/loadMatch';
import { activeOverlays, clock } from './render/schedule';
import { buildCamera } from './render/camera';
import { buildRoster, drawOverlays, type HitRegion } from './render/draw';
import { renderEvidence } from './ui/evidence';
import { renderHero, renderCompare, renderLineups } from './ui/page';
import { initScrollGlow } from './ui/scrollGlow';
import type { Mode, MatchEvent } from './types';

initScrollGlow();

const video = document.querySelector<HTMLVideoElement>('#broadcast')!;
const canvas = document.querySelector<HTMLCanvasElement>('#overlay')!;
const ctx = canvas.getContext('2d')!;
const evidencePanel = document.querySelector<HTMLElement>('#evidence')!;
const playPause = document.querySelector<HTMLButtonElement>('#play-pause')!;
const iconPlay = document.querySelector<SVGElement>('#icon-play')!;
const iconPause = document.querySelector<SVGElement>('#icon-pause')!;
const seek = document.querySelector<HTMLInputElement>('#seek')!;
const clockEl = document.querySelector<HTMLElement>('#clock')!;
const totalClockEl = document.querySelector<HTMLElement>('#total-clock')!;
const scrubFill = document.querySelector<HTMLElement>('#scrub-fill')!;
const scrubPlayhead = document.querySelector<HTMLElement>('#scrub-ph')!;
const scrubTicks = document.querySelector<HTMLElement>('#scrub-ticks')!;
const scrubMinutes = document.querySelector<HTMLElement>('#scrub-minutes')!;
const modeTabs = document.querySelector<HTMLElement>('#modeTabs')!;
const langTabs = document.querySelector<HTMLElement>('#langTabs')!;
const liveBtn = document.querySelector<HTMLButtonElement>('#live')!;

function wireSegmented(group: HTMLElement, onPick: (value: string) => void) {
  group.querySelectorAll<HTMLButtonElement>('button').forEach(btn => {
    btn.addEventListener('click', () => {
      group.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', 'false'));
      btn.setAttribute('aria-pressed', 'true');
      onPick(btn.dataset.value!);
    });
  });
}

async function main() {
  const base = './sample';
  const [match, events, overlays] = await Promise.all([
    loadMatch(base), loadEvents(base), loadOverlays(base),
  ]);
  const manifest = await loadManifest(`${base}/match.mp4`);
  const roster = buildRoster(match.info);
  const eventsById = new Map<string, MatchEvent>(events.map(e => [e.id, e]));

  renderHero(match.info, events);
  renderCompare(document.querySelector<HTMLElement>('#compare-rows')!, events);
  renderLineups(
    document.querySelector<HTMLElement>('#lineup-home')!,
    document.querySelector<HTMLElement>('#lineup-away')!,
    match.info,
  );

  video.src = `${base}/match.mp4`;
  const videoStart = manifest?.start ?? 0;
  const cameraPreset = manifest?.render.camera ?? 'cv_full_pitch';

  let mode: Mode = 'analyst';
  let lang = 'en';
  let hitRegions: HitRegion[] = [];
  let seeking = false;
  let ticksBuilt = false;

  function matchTime(): number {
    return videoStart + video.currentTime;
  }

  function buildTicks() {
    if (ticksBuilt || !video.duration) return;
    ticksBuilt = true;
    const duration = video.duration;
    scrubTicks.innerHTML = '';
    for (const event of events) {
      const relT = event.t - videoStart;
      if (relT < 0 || relT > duration) continue;
      const pct = (relT / duration) * 100;
      if (event.type === 'goal') {
        const mark = document.createElement('div');
        mark.className = 'mark';
        mark.style.left = `${pct}%`;
        mark.style.background = event.team === 'home' ? 'var(--home)' : 'var(--away)';
        scrubTicks.appendChild(mark);
      } else if (event.type === 'yellow_card' || event.type === 'red_card') {
        const mark = document.createElement('div');
        mark.className = 'mark card';
        mark.style.left = `${pct}%`;
        if (event.type === 'red_card') mark.style.background = 'var(--red-card)';
        scrubTicks.appendChild(mark);
      } else if (event.type === 'shot') {
        const tick = document.createElement('div');
        tick.className = 'tick';
        tick.style.left = `${pct}%`;
        scrubTicks.appendChild(tick);
      }
    }
    scrubMinutes.innerHTML = '';
    for (let i = 0; i <= 5; i++) {
      const frac = i / 5;
      const label = document.createElement('span');
      label.className = 'lab';
      label.style.left = `${frac * 100}%`;
      label.textContent = clock(videoStart + frac * duration, match.info.periods);
      scrubMinutes.appendChild(label);
    }
    totalClockEl.textContent = clock(videoStart + duration, match.info.periods);
  }

  function render() {
    const width = canvas.width, height = canvas.height;
    if (width === 0 || height === 0) return;
    const t = matchTime();
    const visible = activeOverlays(overlays, t, mode, lang);
    const camera = buildCamera(cameraPreset, match, t, width / height);
    hitRegions = drawOverlays(ctx, width, height, visible, roster, eventsById, match, t, camera);
    clockEl.textContent = clock(t, match.info.periods);
    const pct = video.duration ? (video.currentTime / video.duration) * 100 : 0;
    if (!seeking) seek.value = String(video.duration ? video.currentTime / video.duration : 0);
    scrubFill.style.width = `${pct}%`;
    scrubPlayhead.style.left = `${pct}%`;
  }

  function resizeCanvas() {
    const rect = canvas.getBoundingClientRect();
    const scale = window.devicePixelRatio || 1;
    canvas.width = Math.round(rect.width * scale);
    canvas.height = Math.round(rect.height * scale);
    render();
  }
  new ResizeObserver(resizeCanvas).observe(canvas);

  function loop() {
    render();
    requestAnimationFrame(loop);
  }
  requestAnimationFrame(loop);

  video.addEventListener('loadedmetadata', buildTicks);

  function setPlaying(playing: boolean) {
    iconPlay.style.display = playing ? 'none' : '';
    iconPause.style.display = playing ? '' : 'none';
    playPause.setAttribute('aria-label', playing ? 'Pause' : 'Play');
  }

  playPause.addEventListener('click', () => {
    if (video.paused) { video.play(); setPlaying(true); } else { video.pause(); setPlaying(false); }
  });
  video.addEventListener('ended', () => setPlaying(false));

  seek.addEventListener('input', () => {
    seeking = true;
    if (video.duration) video.currentTime = Number(seek.value) * video.duration;
  });
  seek.addEventListener('change', () => { seeking = false; });

  wireSegmented(modeTabs, value => { mode = value as Mode; });
  wireSegmented(langTabs, value => { lang = value; });

  liveBtn.addEventListener('click', () => {
    const isLive = liveBtn.getAttribute('aria-pressed') !== 'true';
    liveBtn.setAttribute('aria-pressed', String(isLive));
    seek.disabled = isLive;
    if (isLive) { video.play(); setPlaying(true); }
  });

  canvas.addEventListener('click', event => {
    const rect = canvas.getBoundingClientRect();
    const x = (event.clientX - rect.left) * (canvas.width / rect.width);
    const y = (event.clientY - rect.top) * (canvas.height / rect.height);
    const hit = hitRegions.find(r => x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h);
    if (hit) renderEvidence(evidencePanel, hit.overlay, eventsById, match.info);
  });
}

main().catch(error => {
  document.body.innerHTML = `<pre style="color:#f88;padding:24px;white-space:pre-wrap">${String(error?.stack ?? error)}</pre>`;
  console.error(error);
});
