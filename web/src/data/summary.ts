import type { MatchEvent } from '../types';

export interface Score { home: number; away: number }

/** Score as of t, including available pre-clip history. Undefined means the opening score is unknown.
 * `opening` is the score at clipStart (match_info.score_at_start, #83); events before clipStart are then ignored. */
export function scoreAt(events: MatchEvent[], t: number, clipStart = 0, opening?: Score): Score | undefined {
  const past = events.filter(e => e.t <= t && (!opening || e.t >= clipStart)).sort((a, b) => a.t - b.t);
  let score: Score | undefined = opening ? { ...opening }
    : clipStart === 0 || past.some(e => e.type === 'kickoff' && e.t === 0) ? { home: 0, away: 0 } : undefined;
  for (const e of past) {
    // A score field is an explicit after-event snapshot, not a guess from a pass/shot's success.
    const snapshot = e.score;
    if (snapshot && Number.isInteger(snapshot.home) && Number.isInteger(snapshot.away)
        && snapshot.home! >= 0 && snapshot.away! >= 0) {
      score = { home: snapshot.home!, away: snapshot.away! };
    } else if (score && e.type === 'goal' && (e.team === 'home' || e.team === 'away')) {
      score = { ...score, [e.team]: score[e.team] + 1 };
    }
  }
  return score;
}

export interface CompareRow { label: string; home: number; away: number }

function countByTeam(events: MatchEvent[], type: MatchEvent['type']): Score {
  return events.reduce<Score>((acc, e) => {
    if (e.type !== type || (e.team !== 'home' && e.team !== 'away')) return acc;
    return { ...acc, [e.team]: acc[e.team] + 1 };
  }, { home: 0, away: 0 });
}

/** This clip so far: start-inclusive, export-end-exclusive, with no events after playback time. */
export function compareRows(input: MatchEvent[], start: number, t: number, end: number): CompareRow[] {
  const events = input.filter(e => e.t >= start && e.t <= t && e.t < end);
  const shots = countByTeam(events, 'shot');
  const goals = countByTeam(events, 'goal');
  const passes = countByTeam(events, 'pass');
  const successfulPasses = events.reduce<Score>((acc, e) => {
    if (e.type !== 'pass' || (e.team !== 'home' && e.team !== 'away') || !e.success) return acc;
    return { ...acc, [e.team]: acc[e.team] + 1 };
  }, { home: 0, away: 0 });
  const yellows = countByTeam(events, 'yellow_card');
  const reds = countByTeam(events, 'red_card');
  return [
    { label: 'SHOTS', home: shots.home, away: shots.away },
    { label: 'GOALS', home: goals.home, away: goals.away },
    { label: 'PASSES', home: passes.home, away: passes.away },
    { label: 'PASS ACCURACY %', home: pct(successfulPasses.home, passes.home), away: pct(successfulPasses.away, passes.away) },
    { label: 'YELLOW CARDS', home: yellows.home, away: yellows.away },
    { label: 'RED CARDS', home: reds.home, away: reds.away },
  ];
}

function pct(part: number, total: number): number {
  return total ? Math.round((part / total) * 100) : 0;
}
