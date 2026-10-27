import { loadMatch, loadEvents, loadOverlays, loadManifest, loadReport } from './data/loadMatch';
import { activeOverlays, clock, languageNotice, overlayMentionsPlayer } from './render/schedule';
import { buildCamera } from './render/camera';
import { buildRoster, drawOverlays, type HitRegion } from './render/draw';
import { findPlayer, startingPlayers } from './data/identity';
import { renderEvidence } from './ui/evidence';
import { renderAnalysis, renderInsightEvidence } from './ui/analysis';
import { renderHero, renderSummary, renderLineups } from './ui/page';
import { initScrollGlow } from './ui/scrollGlow';
import { dropFootballAt, initFootballDrops } from './ui/footballs';
import { FeedSwitcher, feedsSynchronized } from './playback/feeds';
import type { Mode, MatchEvent, Overlay } from './types';

initScrollGlow();
initFootballDrops();

let video = document.querySelector<HTMLVideoElement>('#broadcast')!;
const broadcast = video;
const aiVideo = document.querySelector<HTMLVideoElement>('#ai-feed')!;
const aiToggle = document.querySelector<HTMLButtonElement>('#ai-view')!;
const feedStatus = document.querySelector<HTMLElement>('#feed-status')!;
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
const languageStatus = document.querySelector<HTMLElement>('#overlay-language-status')!;
const playerPicker = document.querySelector<HTMLElement>('#playerPicker')!;
const playerSelect = document.querySelector<HTMLSelectElement>('#playerSelect')!;
const playerOptHome = document.querySelector<HTMLOptGroupElement>('#playerOptHome')!;
const playerOptAway = document.querySelector<HTMLOptGroupElement>('#playerOptAway')!;
const followingChip = document.querySelector<HTMLElement>('#followingChip')!;
const followingTab = document.querySelector<HTMLElement>('#followingTab')!;
const followingName = document.querySelector<HTMLElement>('#followingName')!;
const followingClear = document.querySelector<HTMLButtonElement>('#followingClear')!;
const playerStatus = document.querySelector<HTMLElement>('#player-status')!;
const lineupHome = document.querySelector<HTMLElement>('#lineup-home')!;
const lineupAway = document.querySelector<HTMLElement>('#lineup-away')!;
const liveBtn = document.querySelector<HTMLButtonElement>('#live')!;
const analysisPanel = document.querySelector<HTMLElement>('#analysis')!;
const analysisBtn = document.querySelector<HTMLButtonElement>('#analysis-open')!;

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
  const [match, events, overlays, report] = await Promise.all([
    loadMatch(base), loadEvents(base), loadOverlays(base), loadReport(base),
  ]);
  const manifest = await loadManifest(`${base}/match.mp4`);
  const roster = buildRoster(match.info);
  const eventsById = new Map<string, MatchEvent>(events.map(e => [e.id, e]));

  renderHero(match.info);
  renderLineups(lineupHome, lineupAway, match.info);

  video.src = `${base}/match.mp4`;
  const videoStart = manifest?.start ?? 0;
  const cameraPreset = manifest?.render.camera ?? 'cv_full_pitch';

  let mode: Mode = 'analyst';
  let lang = 'en';
  let followedPlayer: number | null = null;
  let hitRegions: HitRegion[] = [];
  let seeking = false;
  let lastSummaryKey = '';
  let selectedEvidence: Overlay | undefined;

  const starters = startingPlayers(match.info);
  for (const [team, group] of [['home', playerOptHome], ['away', playerOptAway]] as const) {
    group.label = match.info[team].name;
    for (const p of starters.filter(p => p.team === team)) {
      const opt = document.createElement('option');
      opt.value = String(p.id);
      opt.textContent = `${p.number} ${p.name}`;
      group.appendChild(opt);
    }
  }

  /** Shows/hides the PLAYER-mode picker and, once a player is chosen, the "no moments yet" notice. */
  function updatePlayerPicker() {
    playerPicker.hidden = mode !== 'player_focus';
    playerStatus.hidden = true;
    if (mode !== 'player_focus') return;
    const chosen = followedPlayer != null ? findPlayer(match.info, followedPlayer) : undefined;
    playerSelect.hidden = !!chosen;
    followingChip.hidden = !chosen;
    playerSelect.value = followedPlayer != null ? String(followedPlayer) : '';
    if (!chosen) return;
    followingTab.textContent = chosen.team === 'home' ? match.info.home.short : match.info.away.short;
    followingTab.className = `chip ${chosen.team}`;
    followingName.textContent = chosen.name;
    const everHas = overlays.some(o => o.mode === 'player_focus' && o.lang === lang && overlayMentionsPlayer(o, eventsById, followedPlayer!));
    if (!everHas) {
      playerStatus.hidden = false;
      playerStatus.textContent = `No moments for ${chosen.name} in this clip yet.`;
    }
  }
  updatePlayerPicker();
  const feeds = new FeedSwitcher(broadcast, aiVideo, useAI => {
    video = feeds.active;
    aiToggle.setAttribute('aria-pressed', String(useAI));
    // Detection boxes belong to the supplied AI video. Browser cards remain a
    // presentation layer; use full-pitch projection for its independently tracked tags.
    setPlaying(!video.paused);
    render();
  });
  aiToggle.addEventListener('click', () => feeds.switchTo(feeds.active !== aiVideo));

  function unavailable() {
    feeds.fail();
    aiToggle.hidden = true;
    aiToggle.disabled = true;
    feedStatus.hidden = false;
    feedStatus.textContent = 'AI VIEW unavailable. Broadcast remains available.';
  }
  aiVideo.addEventListener('error', unavailable);
  // Availability is generated by preparation, avoiding SPA HTML fallbacks for missing MP4s.
  void fetch(`${base}/feeds.json`).then(r => r.json()).then(descriptor => {
    if (!descriptor.aiView) return;
    feedStatus.hidden = false;
    feedStatus.textContent = 'Loading AI VIEW…';
    const ready = () => {
      if (broadcast.readyState < 1 || aiVideo.readyState < 1) return;
      if (!feedsSynchronized(broadcast.duration, aiVideo.duration, descriptor.duration, descriptor.fps)) { unavailable(); return; }
      aiToggle.hidden = false;
      aiToggle.disabled = false;
      feedStatus.textContent = 'The AI watches the full-pitch feed. Detection boxes are in that video; browser cards are presentation overlays, not vision input.';
    };
    broadcast.addEventListener('loadedmetadata', ready);
    aiVideo.addEventListener('loadedmetadata', ready);
    aiVideo.src = `${base}/ai_view.mp4`;
    ready();
  }).catch(unavailable);

  function matchTime(): number {
    return videoStart + video.currentTime;
  }

  function buildTicks(t: number) {
    if (!Number.isFinite(video.duration) || !video.duration) return;
    const duration = video.duration;
    scrubTicks.innerHTML = '';
    for (const event of events) {
      const relT = event.t - videoStart;
      if (relT < 0 || relT >= duration || event.t > t) continue;
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
    const notice = languageNotice(overlays, lang, mode);
    if (languageStatus.textContent !== notice) languageStatus.textContent = notice;
    languageStatus.hidden = !notice;
    let visible = activeOverlays(overlays, t, mode, lang)
      .filter(o => o.event_ids.every(id => (eventsById.get(id)?.t ?? Infinity) <= t));
    if (mode === 'player_focus') {
      visible = followedPlayer == null ? [] : visible.filter(o => overlayMentionsPlayer(o, eventsById, followedPlayer!));
    }
    const end = manifest?.end ?? videoStart + (Number.isFinite(video.duration) ? video.duration : 0);
    // Refresh at event boundaries (including fractional seconds), clock ticks, and metadata load.
    const summaryKey = `${clock(t, match.info.periods)}:${events.filter(e => e.t <= t).length}:${video.duration}`;
    if (summaryKey !== lastSummaryKey) {
      renderSummary(match.info, events, videoStart, t, end);
      buildTicks(t);
      lastSummaryKey = summaryKey;
    }
    if (selectedEvidence?.event_ids.some(id => (eventsById.get(id)?.t ?? Infinity) > t)) {
      evidencePanel.classList.add('hidden');
      selectedEvidence = undefined;
    }
    const camera = match.frames.length ? buildCamera(video === aiVideo ? 'cv_full_pitch' : cameraPreset, match, t, width / height) : undefined;
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

  for (const feed of [broadcast, aiVideo]) {
    feed.addEventListener('loadedmetadata', render);
    for (const event of ['play', 'pause', 'ended']) feed.addEventListener(event, () => {
      if (feed === video) setPlaying(!feed.paused);
    });
  }

  function setPlaying(playing: boolean) {
    iconPlay.style.display = playing ? 'none' : '';
    iconPause.style.display = playing ? '' : 'none';
    playPause.setAttribute('aria-label', playing ? 'Pause' : 'Play');
  }

  function playCurrent() {
    const requested = video;
    void requested.play().catch(() => {
      // A rapid feed switch can cancel an outstanding play request.
      if (requested === video) setPlaying(!requested.paused);
    });
  }

  playPause.addEventListener('click', () => {
    if (video.paused) playCurrent(); else video.pause();
  });

  seek.addEventListener('input', () => {
    seeking = true;
    if (video.duration) video.currentTime = Number(seek.value) * video.duration;
  });
  seek.addEventListener('change', () => { seeking = false; });

  function closeEvidence() {
    selectedEvidence = undefined;
    evidencePanel.classList.add('hidden');
  }
  // Match analysis (optional report.json): opens when the clip ends, or from its button at any time.
  function closeAnalysis() {
    analysisPanel.classList.add('hidden');
    analysisBtn.setAttribute('aria-pressed', 'false');
  }
  function openAnalysis() {
    if (!report) return;
    renderAnalysis(analysisPanel, report, lang, match.info, insight => {
      selectedEvidence = undefined;  // insight evidence is not an overlay's: the playback-time rule is for cards
      renderInsightEvidence(evidencePanel, insight, report, eventsById, match.info);
    }, () => { closeAnalysis(); closeEvidence(); });
    analysisBtn.setAttribute('aria-pressed', 'true');
  }
  if (report) {
    analysisBtn.hidden = false;
    analysisBtn.addEventListener('click', () => {
      if (analysisPanel.classList.contains('hidden')) openAnalysis(); else { closeAnalysis(); closeEvidence(); }
    });
    for (const feed of [broadcast, aiVideo]) feed.addEventListener('ended', () => { if (feed === video) openAnalysis(); });
  }

  wireSegmented(modeTabs, value => { mode = value as Mode; updatePlayerPicker(); closeEvidence(); render(); });
  wireSegmented(langTabs, value => {
    lang = value; updatePlayerPicker(); closeEvidence();
    if (!analysisPanel.classList.contains('hidden')) openAnalysis();
    render();
  });

  function pickPlayer(id: number | null) {
    followedPlayer = id;
    updatePlayerPicker();
    closeEvidence();
    render();
  }
  playerSelect.addEventListener('change', () => pickPlayer(playerSelect.value ? Number(playerSelect.value) : null));
  followingClear.addEventListener('click', () => pickPlayer(null));

  // Clicking a name in Starting XI follows that player and switches to PLAYER mode.
  for (const lineup of [lineupHome, lineupAway]) {
    lineup.addEventListener('click', event => {
      const btn = (event.target as HTMLElement).closest<HTMLElement>('[data-player-id]');
      if (!btn) return;
      mode = 'player_focus';
      modeTabs.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', String(b.getAttribute('data-value') === 'player_focus')));
      pickPlayer(Number(btn.dataset.playerId));
      document.querySelector('#player')!.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }

  liveBtn.addEventListener('click', () => {
    const isLive = liveBtn.getAttribute('aria-pressed') !== 'true';
    liveBtn.setAttribute('aria-pressed', String(isLive));
    seek.disabled = isLive;
    if (isLive) playCurrent();
  });

  canvas.addEventListener('click', event => {
    const rect = canvas.getBoundingClientRect();
    const x = (event.clientX - rect.left) * (canvas.width / rect.width);
    const y = (event.clientY - rect.top) * (canvas.height / rect.height);
    const hit = hitRegions.find(r => x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h);
    if (hit) {
      selectedEvidence = hit.overlay;
      renderEvidence(evidencePanel, hit.overlay, eventsById, match.info);
    } else {
      dropFootballAt(event.clientX, event.clientY);
    }
  });
}

main().catch(error => {
  document.body.innerHTML = `<pre style="color:#f88;padding:24px;white-space:pre-wrap">${String(error?.stack ?? error)}</pre>`;
  console.error(error);
});
