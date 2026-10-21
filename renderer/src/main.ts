import './style.css';
import { parseMatch, sample, type Match } from './data/match';
import { clock } from './playback/timing';
import { cameraTarget } from './camera/tracking';
import { Broadcast } from './scene/broadcast';
import { renderConfig, type RenderConfig } from './scene/config';
const element = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
const canvas = element<HTMLCanvasElement>('pitch'), seek = element<HTMLInputElement>('seek');
const play = element<HTMLButtonElement>('play'), status = element('status');
const debug = element<HTMLInputElement>('debug'), rich = element<HTMLInputElement>('rich');
const params = new URLSearchParams(location.search), exporting = params.has('export');
if (exporting) document.body.classList.add('export');
let match: Match, view: Broadcast, t = 0, playing = false, previous = 0;
let config = renderConfig();
function configure(input: Partial<RenderConfig>) {
  config = renderConfig({ ...config, ...input });
  element<HTMLInputElement>('cv-visibility').checked = config.cvVisibility;
  element<HTMLSelectElement>('camera').value = config.camera;
  element<HTMLInputElement>('player-scale').value = String(config.playerScale);
  element<HTMLInputElement>('ball-scale').value = String(config.ballScale);
  if (view) { view.configure(config); setTime(t); }
  return { ...config };
}
function setTime(time: number) {
  if (!match) throw new Error('Load a match first');
  if (!Number.isFinite(time)) throw new Error('Time must be finite');
  t = Math.max(match.frames[0].t, Math.min(time, match.frames.at(-1)!.t));
  const frame = sample(match, t); view.render(frame, config.camera === 'broadcast' ? cameraTarget(match, t) : undefined); seek.value = String(t);
  element('clock').textContent = `${match.info.home.short} · ${match.info.away.short}   ${clock(t, match.info.periods)}`;
  return { t, inputFrame: frame.frame, inputTime: frame.t, playerIds: frame.players.map(p => p.id) };
}
function load(metadata: unknown, tracking: string) {
  const parsed = parseMatch(metadata, tracking); // Leave existing view intact on invalid input.
  playing = false; play.textContent = 'Play'; view?.dispose(); match = parsed; view = new Broadcast(canvas, match.info);
  view.configure(config);
  view.setRich(rich.checked); seek.min = String(match.frames[0].t); seek.max = String(match.frames.at(-1)!.t);
  play.disabled = false; setTime(match.frames[0].t);
  element('home-name').textContent = match.info.home.name;
  element('away-name').textContent = match.info.away.name;
  status.textContent = `${match.info.match_id} · ${match.frames.length} tracking frames · ${seek.min}–${seek.max}s · no event feed loaded`;
}
function error(e: unknown) { status.textContent = e instanceof Error ? e.message : String(e); }
play.onclick = () => { if (t >= match.frames.at(-1)!.t) setTime(match.frames[0].t); playing = !playing; play.textContent = playing ? 'Pause' : 'Play'; previous = performance.now(); };
seek.oninput = () => { if (match) setTime(Number(seek.value)); };
debug.onchange = () => { element('clock').hidden = !debug.checked; };
element('cv-visibility').onchange = () => configure({ cvVisibility: element<HTMLInputElement>('cv-visibility').checked });
rich.onchange = () => { if (view) { view.setRich(rich.checked); setTime(t); } };
for (const id of ['camera', 'player-scale', 'ball-scale']) element(id).onchange = () => {
  try { configure({ camera: element<HTMLSelectElement>('camera').value as RenderConfig['camera'], playerScale: Number(element<HTMLInputElement>('player-scale').value), ballScale: Number(element<HTMLInputElement>('ball-scale').value) }); }
  catch (e) { configure(config); error(e); }
};
element('load').onclick = async () => {
  try {
    const meta = element<HTMLInputElement>('metadata').files?.[0], track = element<HTMLInputElement>('tracking').files?.[0];
    if (!meta || !track) throw new Error('Select both match_info.json and tracking.jsonl');
    load(JSON.parse(await meta.text()), await track.text());
  } catch (e) { error(e); }
};
function tick(now: number) {
  if (playing && !exporting) {
    setTime(t + Math.max(0, now - previous) / 1000 * Number(element<HTMLSelectElement>('speed').value));
    if (t >= match.frames.at(-1)!.t) { playing = false; play.textContent = 'Play'; }
  }
  previous = now; requestAnimationFrame(tick);
}
// Automation explicitly loads data and calls setTime; it never advances with requestAnimationFrame.
const api = {
  load, setTime, configure,
  inspect() { return view.inspect(); },
  resize(w: number, h: number) { view.resize(w, h); canvas.style.width = `${w}px`; canvas.style.height = `${h}px`; setTime(t); },
  setRich(value: boolean) { rich.checked = value; view.setRich(value); setTime(t); },
};
Object.assign(window, { broadcast: api });
declare global { interface Window { broadcast: typeof api } }
if (exporting || params.get('clock') === '0') { debug.checked = false; element('clock').hidden = true; }
if (!exporting) {
  Promise.all([fetch('./sample/match_info.json').then(r => { if (!r.ok) throw new Error('Sample metadata unavailable'); return r.json(); }), fetch('./sample/tracking.jsonl').then(r => { if (!r.ok) throw new Error('Sample tracking unavailable'); return r.text(); })]).then(([meta, tracking]) => load(meta, tracking)).catch(error);
  requestAnimationFrame(tick);
}
