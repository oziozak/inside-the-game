/** Click an empty part of the page and a football drops from the cursor and bounces to a stop. Pure flourish, no state. */

const INTERACTIVE_SELECTOR = 'a, button, input, select, label, .evidence, .analysis, #seek';

const FOOTBALL_SVG = `<svg viewBox="0 0 32 32" width="26" height="26" aria-hidden="true">
  <circle cx="16" cy="16" r="14.5" fill="#EDF0EA" stroke="#07090B" stroke-width="1.3"/>
  <polygon points="16,8.5 21,12 19.2,17.8 12.8,17.8 11,12" fill="#07090B"/>
  <g stroke="#07090B" stroke-width="1.1" fill="none">
    <path d="M16 8.5 L16 4" />
    <path d="M21 12 L26 10.3" />
    <path d="M19.2 17.8 L21.6 23.6" />
    <path d="M12.8 17.8 L10.4 23.6" />
    <path d="M11 12 L6 10.3" />
  </g>
</svg>`;

function reduceMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/** Spawns one ball at a viewport position (e.g. event.clientX/Y). Removes itself once its fall animation ends. */
export function dropFootballAt(x: number, y: number): void {
  if (reduceMotion()) return;
  const layer = document.querySelector<HTMLElement>('#football-layer');
  if (!layer) return;

  const wrap = document.createElement('div');
  wrap.className = 'football-drop';
  wrap.style.left = `${x}px`;
  wrap.style.top = `${y}px`;
  wrap.style.setProperty('--fall', `${170 + Math.random() * 90}px`);
  wrap.style.setProperty('--drift', `${(Math.random() * 2 - 1) * 24}px`);

  const spin = document.createElement('div');
  spin.className = 'football-spin';
  spin.style.animationDuration = `${0.5 + Math.random() * 0.3}s`;
  spin.style.animationDirection = Math.random() < 0.5 ? 'reverse' : 'normal';
  spin.innerHTML = FOOTBALL_SVG;

  wrap.appendChild(spin);
  layer.appendChild(wrap);
  wrap.addEventListener('animationend', () => wrap.remove(), { once: true });
}

/** Wires a page-wide click listener; skips real controls (buttons, links, the evidence/analysis panels, the scrubber). */
export function initFootballDrops(): void {
  document.addEventListener('click', event => {
    const target = event.target as HTMLElement | null;
    if (!target) return;
    // #overlay (the video canvas) handles its own drop, only when the click didn't land on a card.
    if (target.closest(INTERACTIVE_SELECTOR) || target.closest('#overlay')) return;
    dropFootballAt(event.clientX, event.clientY);
  });
}
