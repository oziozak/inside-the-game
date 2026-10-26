/**
 * Design tokens ported from the "Inside the Game" broadcast telestrator concept
 * (floodlight-black ground, team tabs, Archivo + Martian Mono). Mirrored as CSS
 * custom properties in style.css for the DOM chrome — keep both in sync by hand.
 */
export const COLOR = {
  ink: '#07090B',        // floodlight black — page/video ground
  slab: '#0D1114',        // panel surface
  cell: '#0B0F12',        // data-cell surface
  card: 'rgba(9,12,14,0.92)',
  line: '#2A343B',        // gridline
  lineHi: '#4A5963',       // gridline, higher contrast
  dust: '#9CA9B0',        // secondary text / labels
  chalk: '#EDF0EA',        // primary text
  mint: '#54F0BE',        // UI accent only — never fills a team shape
  home: '#C8102E',        // Bosphorus FC — fixed
  away: '#1B4D9B',        // Thames United — fixed
  yellow: '#F7C61B',       // yellow card
  redCard: '#FF4B4B',       // red card (upright shape only)
} as const;

export const FONT = {
  display: "'Archivo', 'Arial Narrow', Arial, sans-serif", // condensed, 800-900: names, banners
  mono: "'Martian Mono', ui-monospace, Menlo, Consolas, monospace", // data, labels, timecodes
} as const;

/** Reference frame the mockup was designed at; canvas drawing scales every px by canvasWidth/REF_WIDTH. */
export const REF_WIDTH = 1280;
