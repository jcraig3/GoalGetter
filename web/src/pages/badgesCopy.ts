/**
 * How a badge reads.
 *
 * Kept apart from the components for the same reason the points and reporting
 * sentences are: a rendering bug is visible the first time somebody opens the
 * page, and a sentence that says "1 more this months" is not.
 */

export interface Held {
  badge_id: number;
  name: string;
  description: string;
  icon: string;
  reason: string;
  earned_at: string;
  times: number;
}

export interface Progress {
  badge_id: number;
  name: string;
  description: string;
  icon: string;
  have: number;
  need: number;
  remaining: number;
  counted_over: string;
}

export interface Badge {
  id: number;
  name: string;
  description: string;
  kind: 'manual' | 'count';
  icon: string;
  points: number;
  achievement_rule_id: number | null;
  achievement_rule_name: string | null;
  threshold: number | null;
  counted_over: string | null;
  holders: number;
}

const WINDOW_WORD: Record<string, string> = {
  week: 'this week',
  month: 'this month',
  season: 'this season',
};

/**
 * "2 more this month".
 *
 * **The half of a badge that changes behaviour.** The badge rewards what
 * already happened; this is the reason to do something today.
 */
export function remainingLabel(progress: Progress): string {
  const when = WINDOW_WORD[progress.counted_over] ?? '';
  return `${progress.remaining} more ${when}`.trim();
}

/**
 * The multiple a badge is held, or nothing.
 *
 * Nothing for once rather than "×1", which reads as a count somebody forgot
 * to hide. Twice and up is the interesting part — it is the difference between
 * a good month and a habit.
 */
export function timesLabel(held: Held): string {
  return held.times > 1 ? `×${held.times}` : '';
}

/** How a counted badge is earned, said as its terms. */
export function termsLabel(badge: Badge): string {
  if (badge.kind === 'manual') return 'Given by hand';
  const when = WINDOW_WORD[badge.counted_over ?? ''] ?? '';
  const rule = badge.achievement_rule_name ?? 'an achievement';
  // "in a month" rather than "this month": these are the badge's terms, true
  // of every month, not a statement about the current one.
  const window = when.replace('this ', 'in a ');
  return `${badge.threshold}× ${rule} ${window}`.trim();
}

/** How full the bar is, 0–100. */
export function progressPercent(progress: Progress): number {
  if (progress.need <= 0) return 100;
  return Math.min(100, Math.round((progress.have / progress.need) * 100));
}
