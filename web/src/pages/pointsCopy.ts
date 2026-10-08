/**
 * How the economy reads.
 *
 * The numbers come from the server; what lives here is the wording around
 * them, and the wording is where an economy is won or lost. "165,340 points"
 * with nothing beside it is the exact number that killed the account this
 * feature was designed against — it went up forever and told nobody anything.
 * "3rd, 2,400 behind 2nd, 18 days left" is a thing somebody can act on.
 */

import { dayMonth } from '../time';

export interface Season {
  id: number;
  name: string;
  starts_on: string;
  ends_on: string;
  closed_at: string | null;
}

export interface Standing {
  user_id: number;
  name: string;
  points: number;
  rank: number;
  /** The rung this balance reaches. Null when no ladder is set up. */
  tier: string | null;
  /** A ring they bought and are wearing. */
  ring?: string | null;
  title?: string | null;
}

export interface Tier {
  id: number;
  name: string;
  threshold: number;
}

export interface Award {
  id: number;
  points: number;
  event_key: string;
  subject_type: string;
  subject_id: number;
  reason: string;
  created_at: string;
}

/**
 * What each event is called where somebody can read it.
 *
 * The keys are the server's; these are not. A price list that said
 * `goal.achieved` would be a settings page only its author could use.
 */
export const EVENT_LABELS: Record<string, string> = {
  'goal.achieved': 'Hitting a goal',
  'goal.stretch.1': 'Reaching a first stretch level',
  'goal.stretch.2': 'Reaching a second stretch level',
  'goal.stretch.3': 'Reaching a third stretch level',
  'competition.won': 'Winning a competition',
  'competition.placed': 'Finishing 2nd or 3rd',
  recognition: 'Being recognised',
  'person.birthday': 'Birthday',
  'person.work_anniversary': 'Work anniversary',
  manual: 'Awarded by hand',
};

/**
 * A note under the ones whose value is not obvious.
 *
 * Every line here is a decision somebody will otherwise reverse without
 * knowing what it was for — so the reasoning sits next to the box rather than
 * in a document nobody opens.
 */
export const EVENT_NOTES: Record<string, string> = {
  recognition:
    'Once per person per day, however many times they are recognised. It is the one award a colleague can hand out freely.',
  'person.birthday':
    'Worth nothing by default. It is celebrated on the wall, and it is not an achievement.',
  'person.work_anniversary':
    'Worth nothing by default, for the same reason as a birthday.',
  'competition.placed': 'Entering and finishing third should beat not entering.',
};

export function labelFor(eventKey: string): string {
  if (EVENT_LABELS[eventKey]) return EVENT_LABELS[eventKey];
  // An achievement rule, keyed `achievement.<id>`. The reason line on the
  // award already names the rule, so this only has to say what kind it is.
  if (eventKey.startsWith('achievement.')) return 'Achievement';
  if (eventKey.startsWith('badge.')) return 'Badge';
  if (eventKey === 'wallet.unlock') return 'Bought a cosmetic';
  if (eventKey === 'wallet.spin') return 'Spun the prize wheel';
  if (eventKey === 'wallet.win') return 'Won on the prize wheel';
  return eventKey;
}

/** "1st", "2nd", "3rd", "4th" — including the teens, which are all "th". */
export function ordinal(n: number): string {
  const lastTwo = n % 100;
  if (lastTwo >= 11 && lastTwo <= 13) return `${n}th`;
  switch (n % 10) {
    case 1:
      return `${n}st`;
    case 2:
      return `${n}nd`;
    case 3:
      return `${n}rd`;
    default:
      return `${n}th`;
  }
}

export function formatPoints(points: number): string {
  return points.toLocaleString();
}

/** "+120" / "−50", so a correction reads as one at a glance. */
export function signed(points: number): string {
  // A real minus sign, not a hyphen: it lines up with digits in a tabular
  // font, which matters in a column of them.
  return points < 0
    ? `−${Math.abs(points).toLocaleString()}`
    : `+${points.toLocaleString()}`;
}

/** Whole days from today through the season's last day, inclusive. */
export function daysLeft(season: Season, today = new Date()): number {
  const end = new Date(`${season.ends_on}T00:00:00`);
  const now = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const days = Math.round((end.getTime() - now.getTime()) / 86_400_000) + 1;
  return Math.max(days, 0);
}

/**
 * How much of the season has gone, 0–100.
 *
 * Used for a bar, so it is clamped: a season somebody has since shortened can
 * legitimately be more than finished, and a bar past its own end reads as a
 * rendering bug rather than as information.
 */
export function elapsedPercent(season: Season, today = new Date()): number {
  const start = new Date(`${season.starts_on}T00:00:00`).getTime();
  const end = new Date(`${season.ends_on}T00:00:00`).getTime() + 86_400_000;
  const now = today.getTime();
  if (end <= start) return 100;
  return Math.min(100, Math.max(0, ((now - start) / (end - start)) * 100));
}

/**
 * How long is left, said the way somebody would say it.
 *
 * **The sentence the whole feature turns on.** A season with no visible clock
 * is a season nobody is racing against, which makes it an ordinary running
 * total with a name.
 */
export function timeLeftLabel(season: Season, today = new Date()): string {
  if (season.closed_at) return 'Finished';
  const days = daysLeft(season, today);
  if (days === 0) return 'Finished';
  if (days === 1) return 'Last day';
  if (days <= 14) return `${days} days left`;
  const weeks = Math.round(days / 7);
  return `${weeks} weeks left`;
}

/** "1 Jan – 31 Mar 2028". */
export function seasonWindow(season: Season): string {
  const sameYear = season.starts_on.slice(0, 4) === season.ends_on.slice(0, 4);
  // A season always says its year, unlike a date in passing (Q2-29).
  // Judged against its own end, so the year is said once.
  const end = new Date(`${season.ends_on}T12:00:00`);
  return `${dayMonth(season.starts_on, end, !sameYear)} – ${dayMonth(season.ends_on, end, true)}`;
}

/**
 * How far behind the person immediately above.
 *
 * **The gap that matters is to the next place, not to first.** "240 behind
 * 4th" is something somebody can do this week; "18,400 behind 1st" is a reason
 * to stop trying — the same argument the competition standings already make.
 *
 * Null for the leader, and null when the viewer is not on the board at all.
 */
export function gapToNext(
  standings: Standing[],
  userId: number,
): { points: number; rank: number } | null {
  const index = standings.findIndex((row) => row.user_id === userId);
  const mine = index > 0 ? standings[index] : undefined;
  if (!mine) return null;

  // Walk up past anybody tied with them: the person "above" is the next one
  // with more points, not the next row.
  for (let i = index - 1; i >= 0; i -= 1) {
    const above = standings[i];
    if (above && above.points > mine.points) {
      return { points: above.points - mine.points, rank: above.rank };
    }
  }
  return null;
}

/**
 * How far to the next rung, said out loud.
 *
 * **The only part of a ladder that changes behaviour.** The badge rewards what
 * already happened; this is the reason to do something this week. Null when
 * there is no ladder, or when somebody is already on the top rung — in which
 * case saying nothing is right, because there is nothing to say.
 */
export function toNextLabel(
  toNext: number | null,
  nextTier: string | null,
): string | null {
  if (toNext === null || nextTier === null) return null;
  return `${formatPoints(toNext)} to ${nextTier}`;
}
