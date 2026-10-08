/**
 * Starter templates for the forms that begin blank (6.4): rules,
 * competitions and channels.
 *
 * A blank form asks somebody new to invent a celebration, a contest or a
 * playlist from nothing. These are the ones most floors want first, filled in
 * with the parts that do not depend on the organization — names, messages,
 * dates, prizes — and, for a rule, a bar worked out from its own data. Every
 * one lands in the ordinary form, with its preview (5j), so nothing is saved
 * until somebody has looked at it.
 */
import { fromLocalInput, toLocalInput } from './competitionClock';

// ── Rules ────────────────────────────────────────────────────────────────

export interface RuleTemplate {
  key: string;
  name: string;
  /** One line, for the button that offers it. */
  blurb: string;
  /** Which kind of metric it is for. */
  unit: 'currency' | 'count';
  /** How often it should fire, which the suggested bar is worked out from. */
  perWeek: number;
  message: string;
  points: number;
}

export const RULE_TEMPLATES: RuleTemplate[] = [
  {
    key: 'big-deal',
    name: 'Big deal',
    blurb: 'A deal bigger than most — about one a day',
    unit: 'currency',
    perWeek: 7,
    message: '{first_name} just closed {value}!',
    points: 10,
  },
  {
    key: 'deal-of-the-week',
    name: 'Deal of the week',
    blurb: 'The kind of deal that happens about once a week',
    unit: 'currency',
    perWeek: 1,
    message: 'Deal of the week: {name}, {value}!',
    points: 25,
  },
  {
    key: 'big-day',
    name: 'Big day',
    blurb: 'A count well above the usual — about one a day',
    unit: 'count',
    perWeek: 7,
    message: '{first_name} hit {value}!',
    points: 10,
  },
];

/** The metric a rule template should use: the first of its kind. */
export function metricFor<M extends { id: number; unit: string; aggregation?: string }>(
  template: RuleTemplate,
  metrics: M[],
): M | undefined {
  return metrics.find((m) => m.unit === template.unit && m.aggregation !== 'ratio');
}

// ── Competitions ─────────────────────────────────────────────────────────

export interface CompetitionTemplate {
  key: string;
  name: string;
  blurb: string;
  entity_type: 'user' | 'team';
  starts_at: string;
  ends_at: string;
  prize: string;
  repeat: '' | 'daily' | 'weekly' | 'monthly';
}

/** A calendar day in `zone`, `days` after today, at `clock`. */
function at(now: Date, zone: string, days: number, clock: string): string {
  const today = toLocalInput(now.toISOString(), zone);
  const day = new Date(Date.UTC(+today.slice(0, 4), +today.slice(5, 7) - 1, +today.slice(8, 10) + days))
    .toISOString()
    .slice(0, 10);
  return fromLocalInput(`${day}T${clock}`, zone) ?? now.toISOString();
}

/** 0 for Sunday … 6 for Saturday, as the organization's calendar has it. */
function weekday(now: Date, zone: string): number {
  const today = toLocalInput(now.toISOString(), zone);
  return new Date(Date.UTC(+today.slice(0, 4), +today.slice(5, 7) - 1, +today.slice(8, 10))).getUTCDay();
}

/** Days from today to the next `target` weekday — a week, not zero, if it is today. */
function until(now: Date, zone: string, target: number): number {
  return ((target - weekday(now, zone) + 7) % 7) || 7;
}

/** Days from today to the last day of this month. */
function toMonthEnd(now: Date, zone: string): number {
  const today = toLocalInput(now.toISOString(), zone);
  const year = +today.slice(0, 4);
  const month = +today.slice(5, 7);
  const last = new Date(Date.UTC(year, month, 0)).getUTCDate();
  return last - +today.slice(8, 10);
}

export function competitionTemplates(now: Date, zone: string): CompetitionTemplate[] {
  const friday = until(now, zone, 5);
  const monday = until(now, zone, 1);
  // Fewer than three days left and the push is next month's: a "month-end
  // push" that starts tomorrow and ends tomorrow is not a push.
  let monthEnd = toMonthEnd(now, zone);
  if (monthEnd < 3) {
    const nextMonth = new Date(now.getTime() + (monthEnd + 1) * 86_400_000);
    monthEnd = monthEnd + 1 + toMonthEnd(nextMonth, zone);
  }
  return [
    {
      key: 'friday-sprint',
      name: 'Friday sprint',
      blurb: 'One day, nine to five, every Friday',
      entity_type: 'user',
      starts_at: at(now, zone, friday, '09:00'),
      ends_at: at(now, zone, friday, '17:00'),
      prize: 'Lunch on us',
      repeat: 'weekly',
    },
    {
      key: 'month-end-push',
      name: 'Month-end push',
      blurb: 'From tomorrow to the last day of the month',
      entity_type: 'user',
      starts_at: at(now, zone, 1, '09:00'),
      ends_at: at(now, zone, monthEnd, '17:00'),
      prize: 'Steak dinner',
      repeat: '',
    },
    {
      key: 'team-vs-team',
      name: 'Team vs team',
      blurb: 'Teams against each other, Monday to Friday',
      entity_type: 'team',
      starts_at: at(now, zone, monday, '09:00'),
      ends_at: at(now, zone, monday + 4, '17:00'),
      prize: 'Team lunch',
      repeat: '',
    },
  ];
}

// ── Channels ─────────────────────────────────────────────────────────────

export interface Eligible {
  leaderboards: { id: number; name: string }[];
  competitions: { id: number; name: string; state?: string | null }[];
}

/** One slide, in the shape `POST /channels/{id}/screens` takes. */
export interface ScreenDraft {
  kind: string;
  leaderboard_id?: number;
  competition_id?: number;
  title?: string;
  dwell_seconds?: number;
  appearance?: Record<string, unknown>;
}

export interface ChannelTemplate {
  key: string;
  name: string;
  blurb: string;
  /** The slides, from what this channel may show. */
  slides: (eligible: Eligible) => ScreenDraft[];
}

export const CHANNEL_TEMPLATES: ChannelTemplate[] = [
  {
    key: 'sales-floor',
    name: 'Sales floor',
    blurb: 'Every board, every running competition, and recent wins',
    slides: (eligible) => [
      ...eligible.leaderboards.map((b) => ({ kind: 'leaderboard', leaderboard_id: b.id })),
      // Running or about to: a finished contest's slide is a result, not a push.
      ...eligible.competitions
        .filter((c) => c.state === 'active' || c.state === 'scheduled')
        .map((c) => ({ kind: 'competition', competition_id: c.id })),
      // Untitled, so the wall titles it — "Latest wins" once the newest is
      // over a day old (P3-9). A typed title is left alone, so this one
      // never switched.
      { kind: 'achievements' },
    ],
  },
  {
    key: 'lobby',
    name: 'Lobby',
    blurb: 'The top three on one board, as a podium, and recent wins',
    slides: (eligible) => [
      ...eligible.leaderboards.slice(0, 1).map((b) => ({
        kind: 'leaderboard',
        leaderboard_id: b.id,
        dwell_seconds: 30,
        appearance: { ranked_layout: 'podium', row_count: 3 },
      })),
      // Untitled, so the wall titles it — "Latest wins" once the newest is
      // over a day old (P3-9). A typed title is left alone, so this one
      // never switched.
      { kind: 'achievements' },
    ],
  },
];

/** "3 boards, 1 competition and recent wins" — said before anything is made. */
export function describeSlides(slides: ScreenDraft[]): string {
  const boards = slides.filter((s) => s.kind === 'leaderboard').length;
  const contests = slides.filter((s) => s.kind === 'competition').length;
  const parts: string[] = [];
  if (boards) parts.push(`${boards} ${boards === 1 ? 'board' : 'boards'}`);
  if (contests) parts.push(`${contests} ${contests === 1 ? 'competition' : 'competitions'}`);
  if (slides.some((s) => s.kind === 'achievements')) parts.push('recent wins');
  if (parts.length <= 1) return parts[0] ?? 'nothing yet';
  return `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}`;
}
