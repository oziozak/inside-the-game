import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { loadTs } from './support/load-ts.mjs';

const web = fileURLToPath(new URL('../', import.meta.url));
const json = path => JSON.parse(readFileSync(new URL(`../../${path}`, import.meta.url), 'utf8'));
const info = json('data/fake/sample_a/match_info.json');
const sample = json('data/fake/sample_a/events.json');
const { buildRoster, drawOverlays, standardCardLayout } = loadTs(`${web}/src/render/draw.ts`);
const { overlayIdentity } = loadTs(`${web}/src/data/identity.ts`);

// Synthetic UI fixtures at the agents' length limits (title 40, text 110); not agent output.
const LONG = {
  en: ['H. Koc finds the edge with a raking pass', 'Long ball into the final third, H. Koc keeps Bosphorus FC on top at 0-0 and stretches the back line, diff 8/10'],
  tr: ['E. Demir çıkışı buldu ve hücumu başlattı', "Uzun pasla son üçte birlik bölgeye indi, E. Demir A. Kurt'u buldu ve baskıyı kırdı, skor hâlâ 0-0, zorluk 8/10"],
  es: ['P. Rowntree abre el campo con un cambio.', 'Balón largo al último tercio: P. Rowntree encuentra a C. Hollis; Thames United sigue en 0-0 y presiona alto ya'],
};
const pass = sample.find(e => e.type === 'pass' && e.start && e.end);
const events = new Map([[pass.id, pass]]);
const base = { id: 'o9301', start: 0, duration: 60, graphic: 'pass_card', event_ids: [pass.id], player: null, position: 'bottom-left', mode: 'analyst', values: { distance_m: 28, difficulty: 8 } };
const card = (lang, [title, text] = LONG[lang]) => ({ ...base, lang, title, text });

/** Canvas stand-in: text is 0.6 x font size per character; records every fillText with its position and font. */
function context() {
  const drawn = [];
  const target = {
    font: '',
    fillText(text, x, y) { drawn.push({ text, x, y, font: this.font }); },
    measureText(text) { return { width: text.length * Number(/([\d.]+)px/.exec(this.font)?.[1] ?? 10) * 0.6 }; },
  };
  return { drawn, ctx: new Proxy(target, { get: (o, k) => o[k] ?? (() => {}) }) };
}

test('fixtures sit exactly at the agents\' 40/110 character limits', () => {
  for (const [title, text] of Object.values(LONG)) { assert.equal([...title].length, 40); assert.equal([...text].length, 110); }
});

test('a 40-character title and 110-character body keep every word in at most 2 + 3 lines (en/tr/es)', () => {
  for (const lang of ['en', 'tr', 'es']) {
    const { ctx } = context();
    const overlay = card(lang);
    const layout = standardCardLayout(ctx, overlay, overlayIdentity(overlay, events, info), info, events, 1);
    assert.ok(layout.title.lines.length <= 2, `${lang} title lines`);
    assert.ok(layout.body.lines.length <= 3, `${lang} body lines`);
    assert.equal(layout.title.lines.join(' '), overlay.title);
    assert.equal(layout.body.lines.join(' '), overlay.text);
    assert.ok(layout.title.size >= 34 * 0.75, `${lang} title shrinks at most to 75%`);
  }
});

test('a short title stays one line at full size; longer text makes the card taller', () => {
  const { ctx } = context();
  const short = card('en', ['H. Koc', '28 m pass']);
  const long = card('en');
  const layoutOf = o => standardCardLayout(ctx, o, overlayIdentity(o, events, info), info, events, 1);
  const shortCard = layoutOf(short), longCard = layoutOf(long);
  assert.deepEqual(shortCard.title.lines, ['H. Koc']); assert.equal(shortCard.title.size, 34);
  assert.deepEqual(shortCard.body.lines, ['28 m pass']);
  assert.ok(longCard.h > shortCard.h);
});

const words = text => text.split(/\s+/).filter(Boolean);
const drawnWords = drawn => new Set(drawn.flatMap(d => words(d.text)));

test('long cards draw every word with stats and ruler below the text, stacked two per corner without overlap (1440/375 px)', () => {
  for (const width of [1440, 375]) for (const lang of ['en', 'tr', 'es']) {
    const { ctx, drawn } = context();
    const overlays = [card(lang), { ...card(lang), id: 'o9302' }];
    const regions = drawOverlays(ctx, width, width * 9 / 16, overlays, buildRoster(info), events, { info, frames: [] }, 10);
    assert.equal(regions.length, 2);
    const seen = drawnWords(drawn);
    for (const word of [...words(overlays[0].title), ...words(overlays[0].text)]) assert.ok(seen.has(word), `${width}px ${lang}: "${word}" not drawn`);
    assert.ok(!drawn.some(d => d.text.includes('…')), `${width}px ${lang}: ellipsis drawn`);

    const [a, b] = regions;
    assert.ok(a.y >= b.y + b.h || b.y >= a.y + a.h, `${width}px ${lang}: stacked cards overlap`);
    for (const region of regions) {
      const inside = drawn.filter(d => d.y > region.y && d.y < region.y + region.h);
      const lastText = Math.max(...inside.filter(d => words(overlays[0].text).includes(words(d.text)[0])).map(d => d.y));
      const firstStat = Math.min(...inside.filter(d => d.text === 'DISTANCE' || d.text === 'PITCH POSITION').map(d => d.y));
      assert.ok(firstStat > lastText, `${width}px ${lang}: stats row overlaps the body`);
    }
  }
});

test('dual-team cards (momentum/stat compare) show the whole title and text, stacked without overlap (1440/375 px)', () => {
  const title = 'Thames United take control of the middle';
  const text = 'Short pass in the middle third, Thames United keep 67% of the threat in the last five minutes, still level 0-0';
  assert.equal(title.length, 40); assert.equal(text.length, 110);
  for (const width of [1440, 375]) for (const [graphic, position] of [['momentum_bar', 'top-left'], ['stat_compare', 'bottom-center']]) {
    const { ctx, drawn } = context();
    const dual = { ...base, graphic, position, title, text, lang: 'en', values: { momentum_home: 33, momentum_away: 67 } };
    const regions = drawOverlays(ctx, width, width * 9 / 16, [dual, { ...dual, id: 'o9302' }], buildRoster(info), events, { info, frames: [] }, 10);
    const seen = drawnWords(drawn);
    // The dual title keeps its uppercase label style.
    for (const word of [...words(title.toUpperCase()), ...words(text)]) assert.ok(seen.has(word), `${width}px ${graphic}: "${word}" not drawn`);
    assert.ok(!drawn.some(d => d.text.includes('…')), `${width}px ${graphic}: ellipsis drawn`);
    const [a, b] = regions;
    assert.ok(a.y >= b.y + b.h || b.y >= a.y + a.h, `${width}px ${graphic}: stacked cards overlap`);
    for (const r of regions) assert.ok(r.y >= 0 && r.y + r.h <= width * 9 / 16, `${width}px ${graphic}: card leaves the canvas`);
  }
});

test('a word wider than the card is ellipsized as a last resort without adding a blank line', () => {
  const { ctx } = context();
  const overlay = card('en', ['Supercalifragilisticexpialidociousnessly', 'Short body']);
  const layout = standardCardLayout(ctx, overlay, overlayIdentity(overlay, events, info), info, events, 1);
  assert.equal(layout.title.lines.length, 1);
  assert.ok(layout.title.lines[0].endsWith('…'));
});

test('a dual-team card without a title still shows its text', () => {
  const { ctx, drawn } = context();
  const dual = { ...base, graphic: 'momentum_bar', position: 'top-left', title: undefined, text: 'Thames United keep 67% of the threat', lang: 'en', values: { momentum_home: 33, momentum_away: 67 } };
  drawOverlays(ctx, 1280, 720, [dual], buildRoster(info), events, { info, frames: [] }, 10);
  const seen = drawnWords(drawn);
  for (const word of words(dual.text)) assert.ok(seen.has(word), `"${word}" not drawn`);
});

test('a longer title is never drawn larger than a shorter one; wrapped titles use the shrunk size', () => {
  const { ctx } = context();
  const full = LONG.en[0];
  let previous = Infinity;
  for (let n = 1; n <= full.length; n++) {
    const overlay = card('en', [full.slice(0, n), 'Short body']);
    const { title } = standardCardLayout(ctx, overlay, overlayIdentity(overlay, events, info), info, events, 1);
    assert.ok(title.size <= previous, `title of ${n} chars grew from ${previous} to ${title.size}`);
    if (title.lines.length > 1) assert.equal(title.size, 34 * 0.75);
    previous = title.size;
  }
});
