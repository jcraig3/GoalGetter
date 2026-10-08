import type { Slide } from './types';

/**
 * Plausible numbers for a screen nobody has connected data to yet.
 *
 * **Designing a wall should not require a working integration.** Somebody
 * setting up a TV on their first afternoon has a connector half-configured and
 * no facts; without this, every preview is an empty table and the only way to
 * see a leaderboard is to wait a day. The same data makes screenshots for a
 * deployment guide possible without exporting anybody's real figures.
 *
 * Deliberately unmistakable as fiction. Real-looking fake names in a preview get
 * screenshotted into a slide deck and asked about in a meeting.
 */

const CAST = [
  { name: 'Peter Parker', value: '48200' },
  { name: 'Clark Kent', value: '41900' },
  { name: 'Diana Prince', value: '33400' },
  { name: 'Bruce Banner', value: '28750' },
  { name: 'Richard Rider', value: '21300' },
  { name: 'Barry Allen', value: '17900' },
];

/** Teams, for a board or contest that ranks teams — people's names on a team
 *  board was the preview telling a small lie (Q2-3). */
const TEAM_CAST = ['Northern Lights', 'Harbour', 'Summit', 'Riverside', 'Meridian', 'Lakeside'];

/** Six values, best first, that look like the unit they are in. */
const VALUES: Record<string, string[]> = {
  currency: CAST.map((c) => c.value),
  count: ['48', '41', '33', '28', '21', '17'],
  percent: ['96', '91', '87', '82', '77', '71'],
  duration: ['95', '120', '150', '185', '220', '260'],
};

/**
 * **What the form says**, so the sample follows it (7.4, Q2-3). Every field
 * optional: an editor passes what it knows, and the rest stays sample.
 */
export interface SampleContext {
  unit?: string;
  decimal_places?: number;
  unit_label?: string | null;
  direction?: string;
  /** `user`, `team` or `office`. */
  entity_type?: string;
  /** "Last 30 days", "This month". */
  period_label?: string;
  /** How many rows the board shows. */
  rows?: number;
  finish_line?: string | null;
  /** A goal's person or team, by name. */
  subject_name?: string;
  /** A goal's target. */
  target?: string;
  prize?: string | null;
  ends_at?: string | null;
  /** A contest's entrants, by name, in the order chosen. */
  entrants?: string[];
}

/** The sample's rows, in the form's unit and the form's kind of entrant. */
function castFor(ctx: SampleContext) {
  const unit = ctx.unit ?? 'currency';
  const values = VALUES[unit] ?? VALUES.count!;
  const lower = ctx.direction === 'lower_is_better';
  // Best first either way: for a metric where lower is better, the smallest
  // number leads.
  const ordered = lower ? [...values].sort((a, b) => Number(a) - Number(b)) : values;
  const teams = ctx.entity_type === 'team' || ctx.entity_type === 'office';
  const names = ctx.entrants?.length ? ctx.entrants : teams ? TEAM_CAST : CAST.map((c) => c.name);
  return names.slice(0, 6).map((name, index) => ({ name, value: ordered[index] ?? ordered.at(-1)! }));
}

/** The fields every slide carries, so each factory sets only what it means. */
/** A moment before now, so a sample's "2 minutes ago" stays true. */
function minutesAgo(minutes: number): string {
  return new Date(Date.now() - minutes * 60_000).toISOString();
}

const EMPTY: Slide = {
  id: 0,
  kind: 'leaderboard',
  dwell_seconds: 20,
  title: '',
  subtitle: null,
  entries: [],
  total_entrants: 0,
  entity_type: 'user',
  unit: 'currency',
  decimal_places: 0,
  direction: 'higher_is_better',
  current_value: null,
  target_value: null,
  percent: null,
  status: null,
  prize: null,
  ends_at: null,
  state: null,
  final: false,
  achievements: [],
  person: null,
  stats: [],
  streak_days: null,
  panels: [],
  url: null,
  media_kind: null,
  body: null,
};

export function sampleSlide(kind: string, title?: string, ctx: SampleContext = {}): Slide {
  const cast = castFor(ctx);
  const teams = ctx.entity_type === 'team' || ctx.entity_type === 'office';
  const format = {
    unit: ctx.unit ?? 'currency',
    decimal_places: ctx.decimal_places ?? 0,
    unit_label: ctx.unit_label ?? null,
    direction: ctx.direction ?? 'higher_is_better',
    entity_type: ctx.entity_type ?? 'user',
  };
  const period = ctx.period_label ?? 'This month';
  const entries = cast.map((person, index) => ({
    rank: index + 1,
    entity_id: index + 1,
    entity_name: person.name,
    // No photographs: a preview that invents faces for people who do not exist
    // is a preview showing something the real screen cannot.
    photo_digest: null,
    team_name: teams ? null : index % 2 === 0 ? 'Enterprise' : 'SMB',
    value: person.value,
    movement: index === 1 ? 2 : index === 3 ? -1 : null,
    // As the server sends it for a race layout — measured against the leader,
    // since a sample board has no finish line. Carried on every sample entry
    // so switching a preview to the race needs nothing else.
    progress:
      format.direction === 'lower_is_better'
        ? Number(cast[0]!.value) / Number(person.value)
        : Number(person.value) / Number(cast[0]!.value),
    finished: false,
    token: index === 1 ? 'car' : index === 3 ? 'bike' : null,
  }));

  switch (kind) {
    case 'goal': {
      const target = Number(ctx.target) > 0 ? Number(ctx.target) : format.unit === 'currency' ? 250000 : 100;
      const current = Math.round(target * 0.74 * 100) / 100;
      return {
        ...EMPTY,
        ...format,
        kind,
        title: title ?? 'Revenue this month',
        // Who it is for, as the form says — not "Everyone" for a person's goal.
        subtitle: [ctx.subject_name ?? 'Everyone', ctx.period_label].filter(Boolean).join(' · '),
        current_value: String(current),
        target_value: String(target),
        percent: 74,
        status: 'on_track',
      };
    }

    case 'competition': {
      // As many as are entered, when the form says; a sample's six otherwise.
      const count = ctx.entrants?.length ? Math.max(ctx.entrants.length, 1) : 14;
      const shown = entries.slice(0, Math.min(count, ctx.rows ?? 10));
      return {
        ...EMPTY,
        ...format,
        kind,
        title: title ?? 'Month-end push',
        subtitle: shown.length === 2 ? `${shown[0]!.entity_name} vs ${shown[1]!.entity_name}` : period,
        entries: shown,
        total_entrants: count,
        prize: 'prize' in ctx ? (ctx.prize || null) : 'Steak dinner',
        // Far enough out that the countdown reads in days, which is the shape
        // a room actually sees most of the time — unless the form has an end.
        ends_at: ctx.ends_at ?? new Date(Date.now() + 1000 * 60 * 60 * 52).toISOString(),
        state: 'active',
      };
    }

    case 'champion':
      return {
        ...EMPTY,
        // A settled contest, which is a competition slide the wall draws
        // differently rather than a screen kind of its own.
        kind: 'competition',
        title: title ?? 'Month-end push',
        subtitle: 'Revenue',
        entries: entries.slice(0, 3),
        total_entrants: 14,
        prize: 'Steak dinner',
        state: 'closed',
        final: true,
      };

    case 'achievements':
      return {
        ...EMPTY,
        kind,
        title: title ?? 'Recent wins',
        achievements: [
          {
            id: 1,
            about_name: 'Peter Parker',
            title: 'hit target for March',
            body: null,
            figure: '$48,200',
            created_at: minutesAgo(2),
          },
          {
            id: 2,
            about_name: 'Diana Prince',
            title: 'Big deal',
            body: null,
            figure: '$12,400',
            created_at: minutesAgo(25),
          },
          {
            id: 3,
            about_name: 'Bruce Banner',
            title: 'Recognition',
            body: null,
            created_at: minutesAgo(90),
          },
        ],
      };

    case 'spotlight':
      return {
        ...EMPTY,
        kind,
        title: title ?? 'Peter Parker',
        subtitle: 'Revenue this month · March',
        person: {
          id: 1,
          name: 'Peter Parker',
          // No photograph, for the same reason as the board: a preview that
          // invents a face shows something the real screen cannot.
          photo_digest: null,
          job_title: 'Account Executive',
          team_name: 'Enterprise',
        },
        stats: [
          {
            label: 'Revenue this month',
            value: '48200',
            unit: 'currency',
            decimal_places: 0,
            rank: 1,
            movement: 2,
            of: 14,
          },
        ],
        streak_days: 9,
        achievements: [
          {
            id: 1,
            about_name: 'Peter Parker',
            title: 'hit target for March',
            body: null,
          },
          {
            id: 2,
            about_name: 'Peter Parker',
            title: 'closed the biggest deal this week',
            body: null,
          },
        ],
      };

    case 'comparison':
      return {
        ...EMPTY,
        kind,
        title: title ?? 'Calls vs Deals',
        panels: [
          {
            title: 'Calls',
            subtitle: 'Calls made · March',
            entries: entries.slice(0, 5).map((entry, index) => ({
              ...entry,
              value: String(180 - index * 17),
            })),
            total_entrants: CAST.length,
            entity_type: 'user',
            unit: 'count',
            decimal_places: 0,
            direction: 'higher_is_better',
          },
          {
            title: 'Deals',
            // Deliberately a different order from Calls. The whole point of
            // the screen is the person who is top of one and not the other,
            // and sample data that agrees with itself hides that.
            subtitle: 'Revenue · March',
            entries: [...entries]
              .reverse()
              .slice(0, 5)
              .map((entry, index) => ({
                ...entry,
                rank: index + 1,
                value: String(52000 - index * 6100),
              })),
            total_entrants: CAST.length,
            entity_type: 'user',
            unit: 'currency',
            decimal_places: 0,
            direction: 'higher_is_better',
          },
        ],
      };

    case 'message':
      return {
        ...EMPTY,
        kind,
        title: title ?? 'All-hands Friday',
        body: 'Doors at 4, the room by the kitchen. There will be cake.',
      };

    default:
      return {
        ...EMPTY,
        ...format,
        kind: 'leaderboard',
        title: title ?? 'Revenue this month',
        subtitle: period,
        entries: entries.slice(0, ctx.rows ?? entries.length),
        total_entrants: entries.length,
        finish_line: ctx.finish_line ?? null,
      };
  }
}
