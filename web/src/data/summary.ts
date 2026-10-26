import type { MatchEvent } from '../types';

export interface Score { home: number; away: number }

/** Final score from goal events — same rule the agents/director use: numbers come from code, never invented. */
export function finalScore(events: MatchEvent[]): Score {
  return events.reduce<Score>((score, e) => {
    if (e.type !== 'goal' || !e.team) return score;
    return { ...score, [e.team]: score[e.team] + 1 };
  }, { home: 0, away: 0 });
}

export interface CompareRow { label: string; home: number; away: number }

function countByTeam(events: MatchEvent[], type: MatchEvent['type']): Score {
  return events.reduce<Score>((acc, e) => {
    if (e.type !== type || !e.team) return acc;
    return { ...acc, [e.team]: acc[e.team] + 1 };
  }, { home: 0, away: 0 });
}

export function compareRows(events: MatchEvent[]): CompareRow[] {
  const shots = countByTeam(events, 'shot');
  const goals = countByTeam(events, 'goal');
  const passes = countByTeam(events, 'pass');
  const successfulPasses = events.reduce<Score>((acc, e) => {
    if (e.type !== 'pass' || !e.team || !e.success) return acc;
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
