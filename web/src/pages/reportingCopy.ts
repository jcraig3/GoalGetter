import { formatMetric, type MetricFormat } from '../components/MetricValue';

/**
 * Turning a gap into a sentence somebody can say out loud.
 *
 * **This is the only part of the reporting tab that is not already a number
 * somewhere else.** A percentage is a colour and a projection is a line; what
 * a manager needs at a one-to-one is "you are on four a day and it needs to be
 * eleven", and nothing in the product said that before.
 *
 * Separated from the page because sentences are where the mistakes are. A
 * rendering bug is visible; a sentence that says "needs 0 a day" for somebody
 * who is 400 short is not, and neither is one that says "1 days".
 */

export interface Gap {
  goal_id: number;
  goal_name: string;
  subject_name: string;
  metric_name: string;
  unit: string;
  decimal_places: number;
  unit_label?: string | null;
  current: string;
  target: string;
  behind_by: number;
  days_left: number;
  rate_so_far: string | null;
  rate_needed: string | null;
}

export interface Season {
  label: string;
  value: string;
  met_target: boolean;
  /** False before the goal began, with nothing recorded — not a miss (7.6). */
  counted?: boolean;
}

export interface TrackRecord {
  goal_id: number;
  goal_name: string;
  subject_name: string;
  metric_name: string;
  unit: string;
  decimal_places: number;
  unit_label?: string | null;
  target: string;
  seasons: Season[];
  considered: number;
  hit: number;
  hit_rate: number;
  current_streak: number;
  best_streak: number;
}

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

/**
 * What closing the gap would take, or an honest admission that there is no
 * rate to quote.
 *
 * A metric that does not accumulate has no per-day answer — an average
 * response time is not something you do eighteen of a day — so rather than
 * inventing one, the sentence falls back to the shortfall itself.
 */
export function gapSentence(gap: Gap): string {
  const format: MetricFormat = {
    unit: gap.unit,
    decimal_places: gap.decimal_places,
    unit_label: gap.unit_label,
  };
  const days = plural(gap.days_left, 'working day', 'working days');

  if (gap.rate_needed === null) {
    const short = Number(gap.target) - Number(gap.current);
    if (!Number.isFinite(short) || short <= 0) return `${days} left.`;
    return `${formatMetric(short, format)} short, with ${days} left.`;
  }

  const needed = formatMetric(gap.rate_needed, format);
  if (gap.rate_so_far === null) {
    return `Needs ${needed} a day for ${days}.`;
  }
  return `Needs ${needed} a day for ${days} (${formatMetric(gap.rate_so_far, format)} a day so far).`;
}

/** How hard the rate has to change, as a multiple of the rate so far. */
export function stepUp(gap: Gap): number | null {
  if (gap.rate_needed === null || gap.rate_so_far === null) return null;
  const so_far = Number(gap.rate_so_far);
  const needed = Number(gap.rate_needed);
  // A rate of zero has no multiple — "infinitely faster" is true and useless.
  if (!Number.isFinite(so_far) || !Number.isFinite(needed) || so_far <= 0) {
    return null;
  }
  return Math.round((needed / so_far) * 10) / 10;
}

/** `neutral`: too early to tell (Q2-10). */
export type Tone = 'good' | 'warn' | 'bad' | 'neutral';

/**
 * The colour of the headline number.
 *
 * **Bands, not a gradient.** A chip that shifts hue by one percentage point
 * is a chip nobody reads as anything; three states are three things a manager
 * can act on differently.
 */
export function tone(percent: number): Tone {
  if (percent >= 80) return 'good';
  if (percent >= 50) return 'warn';
  return 'bad';
}

export const TONE_TEXT: Record<Tone, string> = {
  good: 'text-success',
  warn: 'text-warning',
  bad: 'text-danger',
  neutral: 'text-content-muted',
};

export const TONE_BORDER: Record<Tone, string> = {
  good: 'border-success',
  warn: 'border-warning',
  bad: 'border-danger',
  neutral: 'border-edge',
};

/**
 * A streak said the way people say it, or nothing at all.
 *
 * Returns an empty string rather than "0 in a row", which reads as a taunt on
 * a page somebody is already on because things are going badly.
 */
export function streakLabel(record: TrackRecord): string {
  if (record.current_streak >= 2) {
    return `${record.current_streak} in a row`;
  }
  if (record.current_streak === 1) return 'Hit last period';
  if (record.best_streak >= 2) return `Best run ${record.best_streak}`;
  return '';
}

/** "4 of 6" — the fraction behind the percentage, because 67% of what matters. */
export function hitLabel(record: TrackRecord): string {
  return `${record.hit} of ${record.considered}`;
}

export interface Run {
  competition_id: number;
  name: string;
  ended_on: string;
  winner_name: string;
  value: string;
}

export interface CompetitionReport {
  competition_id: number;
  name: string;
  state: string;
  metric_name: string;
  unit: string;
  decimal_places: number;
  unit_label?: string | null;
  entity_type: string;
  leader_name: string | null;
  leader_value: string | null;
  elapsed_percent: number;
  predicted: string | null;
  /** Too little of the window gone to forecast from (P3-11). */
  too_early?: boolean;
  runs: Run[];
  all_time_high: string | null;
  all_time_high_name: string | null;
  first: string | null;
  previous: string | null;
  basis: string | null;
  vs_first: string | null;
  vs_previous: string | null;
  vs_high: string | null;
}

/**
 * A comparison, with its sign said in words rather than left to a minus.
 *
 * `null` when there is nothing to compare against, so a caller can leave the
 * row out entirely instead of printing a dash a reader has to interpret.
 */
export function deltaLabel(
  delta: string | null,
  report: CompetitionReport,
): { text: string; tone: Tone } | null {
  if (delta === null) return null;
  const amount = Number(delta);
  if (!Number.isFinite(amount)) return null;

  const format: MetricFormat = {
    unit: report.unit,
    decimal_places: report.decimal_places,
    unit_label: report.unit_label,
  };
  if (amount === 0) return { text: 'level', tone: 'warn' };

  const size = formatMetric(Math.abs(amount), format);
  return amount > 0
    ? { text: `${size} ahead`, tone: 'good' }
    : { text: `${size} behind`, tone: 'bad' };
}

/**
 * What the comparisons are being made from, said plainly.
 *
 * **A prediction and a result are not the same claim**, and a page that showed
 * one number without saying which would let somebody quote a forecast as a
 * score.
 */
export function basisLabel(report: CompetitionReport): string {
  return report.state === 'ended' || report.state === 'closed'
    ? 'Final score'
    : 'On pace to finish at';
}
