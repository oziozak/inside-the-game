import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { loadTs } from './support/load-ts.mjs';

const web = fileURLToPath(new URL('../', import.meta.url));
const json = path => JSON.parse(readFileSync(new URL(`../../${path}`, import.meta.url), 'utf8'));
const info = json('data/fake/sample_a/match_info.json');
const example = json('schemas/examples/report.example.json');
const { ui, trMaybe } = loadTs(`${web}/src/i18n.ts`);
const { renderAnalysis, renderInsightEvidence } = loadTs(`${web}/src/ui/analysis.ts`);
const { renderEvidence } = loadTs(`${web}/src/ui/evidence.ts`);
const { teamSheetHtml, renderOnPitchPanel, renderLineupCard } = loadTs(`${web}/src/ui/lineups.ts`);
const { onPitchAt } = loadTs(`${web}/src/data/onPitch.ts`);
const { cardKind } = loadTs(`${web}/src/render/draw.ts`);
const { languageNotice } = loadTs(`${web}/src/render/schedule.ts`);
const { compareRows } = loadTs(`${web}/src/data/summary.ts`);

// The page's own English words (#95). With TR or ES selected none of them may show; names are data, not UI.
const ENGLISH = /CLIP ANALYSIS|\bCLOSE\b|WHAT THE AI SAW|\bSEEN\b|HEDGED|Covers this clip|FULL-CLIP|INSIGHT EVIDENCE|FACTS \(CODE\)|cited event|SOURCE EVENTS|Detected from video|CV confidence|\bPLAYERS\b|SENT OFF|ON THE PITCH|\bLINEUPS\b|\bSKIP\b|SHAPE|PRESSING|PROGRESSION|FLANKS|LINE HEIGHT/;

function panel() {
  const p = { innerHTML: '', hidden: true, classList: { remove() { p.hidden = false; }, add() { p.hidden = true; }, contains() { return false; } },
    querySelector() { return null; }, querySelectorAll() { return []; } };
  return p;
}

test('every static string in index.html has an entry in all three languages', () => {
  const html = readFileSync(`${web}/index.html`, 'utf8');
  const keys = [...html.matchAll(/data-i18n(?:-aria)?="([^"]+)"/g)].map(m => m[1]);
  assert.ok(keys.length > 30);
  for (const key of keys) for (const lang of ['en', 'tr', 'es']) {
    assert.ok(trMaybe(lang, key, '') !== '', `${key} in ${lang}`);
  }
  // the strings #95 names are all tagged
  for (const key of ['compare.kicker', 'compare.title', 'nav.match', 'nav.lineups', 'nav.how', 'hero.synthetic']) assert.ok(keys.includes(key), key);
});

test('the analysis panel and its evidence have no English chrome in TR and ES, and say they are a full-clip report', () => {
  for (const lang of ['tr', 'es']) {
    const p = panel();
    renderAnalysis(p, example, lang, info, () => {}, () => {});
    assert.doesNotMatch(p.innerHTML, ENGLISH, lang);
    assert.ok(p.innerHTML.includes(ui(lang, 'analysis.fullClip')), lang);
    const evidence = panel();
    renderInsightEvidence(evidence, example.insights[0], example, new Map(), info, lang);
    assert.doesNotMatch(evidence.innerHTML, ENGLISH, lang);
  }
  const en = panel();
  renderAnalysis(en, example, 'en', info, () => {}, () => {});
  assert.match(en.innerHTML, /FULL-CLIP REPORT · FINAL SCORE SHOWN/);
});

test('lineups, the ON THE PITCH panel and the lineup card follow the language', () => {
  const teams = onPitchAt(info, [], 0);
  for (const lang of ['tr', 'es']) {
    assert.doesNotMatch(teamSheetHtml(info, 'home', teams.home, true, lang), ENGLISH, lang);
    const p = panel();
    renderOnPitchPanel(p, info, [], 0, () => {}, lang);
    assert.doesNotMatch(p.innerHTML, ENGLISH, lang);
    const card = panel();
    renderLineupCard(card, info, [], 0, () => {}, lang);
    assert.doesNotMatch(card.innerHTML, ENGLISH, lang);
  }
  assert.match(teamSheetHtml(info, 'home', teams.home, true, 'tr'), /11 OYUNCU/);
});

test('evidence, card labels, stat labels and the language notice are translated', () => {
  const red = { id: 'e9101', match_id: info.match_id, t: 10, period: 1, type: 'red_card', subtype: 'second_yellow', team: 'home', from: 10, to: null, source: 'sim', confidence: 1 };
  const goal = { id: 'e9102', match_id: info.match_id, t: 12, period: 1, type: 'goal', team: 'home', from: 9, to: null, source: 'cv', confidence: 0.73 };
  const events = new Map([red, goal].map(e => [e.id, e]));
  const banner = { id: 'o9101', start: 10, duration: 6, graphic: 'card_banner', event_ids: [red.id], position: 'top-right', mode: 'analyst', text: '' };
  assert.equal(cardKind({ ...banner, lang: 'tr' }, events), 'KIRMIZI KART');
  assert.equal(cardKind({ ...banner, lang: 'es' }, events), 'TARJETA ROJA');
  assert.equal(cardKind({ ...banner, lang: 'en' }, events), 'RED CARD');
  for (const lang of ['tr', 'es']) {
    const p = panel();
    renderEvidence(p, { ...banner, lang, event_ids: [red.id, goal.id] }, events, info, lang);
    assert.doesNotMatch(p.innerHTML, ENGLISH, lang);
    assert.doesNotMatch(p.innerHTML, /second yellow|RED_CARD|\bgoal\b/i, lang);
  }
  for (const row of compareRows([], 0, 10, 60)) {
    assert.notEqual(trMaybe('tr', `stat.${row.label}`, row.label), row.label, row.label);
  }
  assert.equal(languageNotice([], 'es', 'analyst', 'es'), 'No hay gráficos en español para este partido.');
  assert.equal(languageNotice([], 'tr', 'analyst', 'tr'), 'Bu maç için Türkçe grafik yok.');
});
