/** Moves the fixed floodlight glow (.scroll-glow, style.css) down the page as the viewer scrolls. */
export function initScrollGlow(): void {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const root = document.documentElement;
  let ticking = false;

  function update() {
    const max = document.body.scrollHeight - window.innerHeight;
    const progress = max > 0 ? window.scrollY / max : 0;
    root.style.setProperty('--glow-y', `${(10 + progress * 80).toFixed(2)}%`);
    ticking = false;
  }

  window.addEventListener('scroll', () => {
    if (ticking) return;
    ticking = true;
    requestAnimationFrame(update);
  }, { passive: true });

  update();
}
