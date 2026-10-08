/**
 * How GoalGetter judges a data source, with no React in sight.
 *
 * Four decisions, each the kind of thing that quietly rots inside a component:
 * which column probably means what, where to pick a half-finished setup back up,
 * whether a connected source is working, and whether the numbers on a leaderboard
 * are current. Pulled out here so they can be tested — and mutation-tested —
 * without mounting anything.
 *
 * The last two share `isLate`, deliberately. The integrations list and a
 * leaderboard's "as of" line have to mean the same thing by "overdue", and two
 * definitions of late would agree right up until somebody adjusted one.
 */

import { dayName } from '../time';

export interface DiscoveredField {
  name: string;
  kind: string;
  samples: string[];
  /**
   * Every distinct value, when there are few enough for the column to be a
   * choice rather than data. Empty otherwise — which is how a category is told
   * apart from a name, and therefore what a column can be filtered on.
   *
   * Optional because a connector that cannot cheaply say simply does not.
   */
  values?: string[];
}

export interface MappingDraft {
  subject_field: string;
  occurred_at_field: string;
  /** null means count each row as one, which is how a "deals won" metric works. */
  value_field: string | null;
  external_id_field: string | null;
}

export type DraftKey = keyof MappingDraft;

export interface Suggestion {
  draft: MappingDraft;
  /**
   * Why each column was chosen, in a sentence.
   *
   * Shown beside every picker rather than kept internal. A guess an admin cannot
   * see the reasoning for is a guess they have to verify from scratch, which
   * costs more than being asked outright — and a *wrong* guess with its reason
   * showing is obvious at a glance instead of mysterious three weeks later.
   */
  reasons: Record<DraftKey, string>;
}

/**
 * Words that suggest a column's role, strongest first.
 *
 * Deliberately generous. Guessing wrong costs one click; not guessing costs
 * every admin reading every column name and typing four of them.
 */
const SUBJECT_WORDS = [
  'owner',
  'rep',
  'salesperson',
  'seller',
  'agent',
  'assignee',
  'assigned',
  'user',
  'employee',
  'closer',
  'person',
  'email',
  'who',
];
const DATE_WORDS = [
  'closed',
  'won',
  'completed',
  'occurred',
  'happened',
  'date',
  'created',
  'timestamp',
  'time',
  'at',
  'on',
];
const AMOUNT_WORDS = [
  'amount',
  'value',
  'revenue',
  'total',
  'price',
  'premium',
  'commission',
  'mrr',
  'arr',
  'sum',
  'size',
  'quantity',
  'count',
];
const ID_WORDS = [
  'external_id',
  'event_id',
  'record_id',
  'deal_id',
  'opportunity_id',
  'transaction_id',
  'reference',
  'uuid',
  'guid',
  'id',
];

/** Kinds that can plausibly be a date, and ones that can be a number. */
const DATE_KINDS = ['date', 'datetime'];
const NUMBER_KINDS = ['number'];

/**
 * A field name split into words, so hints match on words rather than letters.
 *
 * `id` must not match `paid`, `width` or `candidate`, and that is exactly what a
 * substring search does. Handles `closed_at`, `closedAt` and `Closed At` the
 * same way, because all three turn up in real payloads.
 */
export function words(name: string): string[] {
  return name
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .split(/[^A-Za-z0-9]+/)
    .filter(Boolean)
    .map((word) => word.toLowerCase());
}

/** `closed_at`, from anything spelled like it. For multi-word hints. */
function normalised(name: string): string {
  return words(name).join('_');
}

/**
 * How well a name matches a hint list: 0 is the best match, -1 is none.
 *
 * The index is the score, so the order of the word lists above is the order of
 * preference, and adding a weaker synonym at the end cannot outrank a strong one.
 */
export function hintScore(name: string, hints: string[]): number {
  const parts = words(name);
  const joined = normalised(name);
  // `entries()` rather than an index loop: with `noUncheckedIndexedAccess` on,
  // `hints[i]` is `string | undefined` and every use needs proving otherwise.
  for (const [i, hint] of hints.entries()) {
    if (hint.includes('_') ? joined.includes(hint) : parts.includes(hint))
      return i;
  }
  return -1;
}

/**
 * The best field for one role, or null.
 *
 * `kinds` is the strong signal and filters first: a column of dates is a better
 * guess for "when" than a column merely *named* `date`. Within the kind, name
 * hints rank, and ties fall back to the order the source reported — which is the
 * order the columns appear in, and therefore the order somebody would read them.
 */
function best(
  fields: DiscoveredField[],
  kinds: string[],
  hints: string[],
): { field: DiscoveredField; byKind: boolean; byName: boolean } | null {
  const ranked = (candidates: DiscoveredField[]) =>
    candidates
      .map((field, index) => ({
        field,
        score: hintScore(field.name, hints),
        index,
      }))
      .sort((a, b) => {
        // A named match beats an unnamed one; among named, the stronger hint;
        // among equals, the original order.
        const aNamed = a.score >= 0;
        const bNamed = b.score >= 0;
        if (aNamed !== bNamed) return aNamed ? -1 : 1;
        if (aNamed && a.score !== b.score) return a.score - b.score;
        return a.index - b.index;
      })
      .at(0);

  const byKind = ranked(fields.filter((f) => kinds.includes(f.kind)));
  if (byKind) {
    return { field: byKind.field, byKind: true, byName: byKind.score >= 0 };
  }

  // No column of the right kind. A name match is still worth offering — a date
  // arriving as a string is extremely common — but nothing else is.
  //
  // **Except a number, when what is wanted is a date.** `new_within_last_month`
  // and `created_count` are counts whose names read like dates, and offering one
  // as "when it happened" produces a mapping that fails on every row with
  // "contained 0, which is not a date". A date that arrives as a number is a unix
  // timestamp, which `DATE_KINDS` catches by value long before this fallback.
  const wantsDate = kinds.some((k) => DATE_KINDS.includes(k));
  const plausible = fields.filter((f) => !(wantsDate && f.kind === 'number'));
  const byName = ranked(plausible.filter((f) => hintScore(f.name, hints) >= 0));
  if (!byName) return null;
  return { field: byName.field, byKind: false, byName: true };
}

/**
 * A mapping to start from, guessed from what the source actually sent.
 *
 * This is the whole difference between "connect a source in a minute" and "read
 * the docs, then type four column names". It is a suggestion in both directions:
 * every pick is editable, and every pick says why.
 */
export function suggestMapping(fields: DiscoveredField[]): Suggestion {
  const who =
    best(fields, ['email'], SUBJECT_WORDS) ??
    // Falling back to any string at all, because a mapping without a subject
    // cannot be saved — better to preselect the first column and be visibly
    // wrong than to leave a required picker empty.
    best(fields, ['string'], SUBJECT_WORDS) ??
    (fields[0] ? { field: fields[0], byKind: false, byName: false } : null);

  const when = best(fields, DATE_KINDS, DATE_WORDS);
  const much = best(fields, NUMBER_KINDS, AMOUNT_WORDS);
  // No kinds to filter on: an id can be a string or a number, so the name is the
  // only signal. Passing an empty list means `best` skips straight to its
  // name-match fallback and returns null when nothing matches — which is what a
  // guard in front of this used to say twice. Mutation testing found it saying
  // nothing.
  const which = best(fields, [], ID_WORDS);

  return {
    draft: {
      subject_field: who?.field.name ?? '',
      occurred_at_field: when?.field.name ?? '',
      value_field: much?.field.name ?? null,
      external_id_field: which?.field.name ?? null,
    },
    reasons: {
      subject_field: !who
        ? 'Nothing here looks like a person. Pick the column naming who did it.'
        : who.field.kind === 'email'
          ? 'These values look like email addresses.'
          : who.byName
            ? `Named like the person who did it.`
            : 'A guess — nothing here looks like a person, so this is the first column.',
      occurred_at_field: !when
        ? // **Not "pick one" any more.** Empty is a real answer: the fact is
          // dated by when its number last changed. Telling somebody to choose a
          // column that does not exist is the instruction a pre-aggregated view
          // cannot follow.
          'Nothing here looks like a date. Leave it empty and each row is dated when its number last changes.'
        : who && when.field.name === who.field.name
          ? 'Also matched as the person. One of these two needs changing.'
          : when.byKind
            ? 'These values parse as dates.'
            : 'Named like a date, though the values arrive as text.',
      value_field: much
        ? much.byName
          ? 'Named like an amount.'
          : 'The only number column here.'
        : 'No number column, so each row counts as one — right for a "deals won" metric.',
      external_id_field: which
        ? 'Looks like the source’s own id for the row, which is what makes re-importing safe.'
        : 'Nothing here looks like a record id. Pick the column holding one — without it, and unless the source supplies its own, every row is imported again on each sync.',
    },
  };
}

/** What the connect flow needs to know to resume, and nothing more. */
export interface SetupState {
  credentialsSet: boolean;
  /** Whether the source has told us its columns yet. For a webhook that means
   *  something has actually been posted to it. */
  hasFields: boolean;
  mappingCount: number;
}

/**
 * The steps, by number, so the UI and this file cannot disagree.
 *
 * **Three, and it was five.** Two of them asked questions that did not need
 * answering yet: one for a name and a schedule, which have sensible defaults and
 * are editable on the source's own page afterwards; and a closing summary of what
 * the step before it already showed. Both are gone. What is left is the three
 * things somebody genuinely has to do — say what they are connecting, connect it,
 * and say what the columns mean.
 */
/**
 * The wizard's steps.
 *
 * **Review came back, and the reason it went away no longer holds.** It was
 * merged into Map on the grounds that the mapping editor already shows ten real
 * rows as the facts they would become — which *is* the confirmation, for one
 * mapping. Creating metrics from the columns makes several at once, and the
 * editor can only ever show one of them: the other two were set up, switched on
 * and invisible, and finishing from that screen meant finishing without having
 * seen most of what was about to start importing.
 */
export const STEPS = ['Choose', 'Connect', 'Map', 'Review'] as const;

/**
 * Which step a half-finished source should open on.
 *
 * Setup gets abandoned — a browser tab closes, an admin goes to find the
 * credential they need. Dropping them back at step one to retype what is already
 * saved is the sort of thing that makes a tool feel hostile.
 *
 * Never step one: reaching this function at all means a source exists, so the
 * connector has been chosen and asking again would be a step whose only purpose is
 * to be clicked through.
 */
export function resumeStep(state: SetupState): number {
  if (!state.credentialsSet) return 2;
  if (!state.hasFields) return 2;
  return 3;
}

/** Everything the list needs to judge a source at a glance. */
export interface SourceStatus {
  enabled: boolean;
  archived: boolean;
  connector_missing: boolean;
  credentials_set: boolean;
  mappings: unknown[];
  last_status: string | null;
  last_run_at: string | null;
  next_run_at: string | null;
  interval_minutes: number;
  failure_count: number;
  pending_identities: number;
  /** When the newest number it wrote happened (7.3). */
  newest_row_at?: string | null;
  /** Working days with nothing new, when the server judges it worth saying.
   *  The judgement is the server's (`app/staleness.py`) so the Inbox and Home
   *  say the same thing as this card. */
  stale_working_days?: number | null;
}

export type Tone = 'good' | 'warn' | 'bad' | 'idle';

export interface Health {
  tone: Tone;
  label: string;
  detail: string;
  /** True when the fix is to go back through the connect flow. */
  resumable: boolean;
}

/**
 * How late a run may be before it is worth saying so.
 *
 * A whole interval of grace, floored at ten minutes. The job loop ticks rather
 * than firing to the second, so a source due at 09:00 running at 09:02 is not
 * late — and a badge that cries wolf at two minutes is a badge nobody reads by
 * the end of the week.
 */
/** `interval_minutes` for a source that reads once and stops. */
export const READ_ONCE = 0;

export function graceMinutes(intervalMinutes: number): number {
  return Math.max(10, intervalMinutes);
}

/**
 * One sentence on whether this source is working.
 *
 * Ordered by what an admin can act on, not by severity: a source nobody finished
 * setting up is reported as unfinished rather than as "never synced", because the
 * second is true and useless.
 */
export function sourceHealth(source: SourceStatus, now: Date): Health {
  // First, above everything. Archiving forgets the credential, so without this a
  // removed source reports as *setup unfinished* and offers to resume a setup
  // somebody deliberately took away.
  if (source.archived) {
    return {
      tone: 'idle',
      label: 'Removed',
      detail:
        'It no longer imports anything. What it already imported is kept.',
      resumable: false,
    };
  }

  if (source.connector_missing) {
    return {
      tone: 'bad',
      label: 'Unavailable',
      detail: 'This build has no connector of that type, so it will never run.',
      resumable: false,
    };
  }

  if (!source.credentials_set) {
    return {
      tone: 'warn',
      label: 'Setup unfinished',
      detail: 'It has no credentials yet, so there is nothing to sync with.',
      resumable: true,
    };
  }

  if (source.mappings.length === 0) {
    return {
      tone: 'warn',
      label: 'Setup unfinished',
      detail: 'Nothing is mapped yet, so no numbers are being imported.',
      resumable: true,
    };
  }

  // Checked after the setup states on purpose: a paused half-built source is
  // more usefully described as half-built.
  if (!source.enabled) {
    return {
      tone: 'idle',
      label: 'Paused',
      detail:
        'It keeps everything it has imported and will not sync again until resumed.',
      resumable: false,
    };
  }

  if (source.last_status === 'failed') {
    const times = source.failure_count;
    return {
      tone: 'bad',
      label: 'Failing',
      detail:
        times > 1
          ? `The last ${times} attempts failed. Retries are slowing down.`
          : 'The last attempt failed.',
      resumable: false,
    };
  }

  if (!source.last_run_at) {
    return {
      tone: 'idle',
      label: 'Waiting',
      detail: 'Set up, but it has not run yet.',
      resumable: false,
    };
  }

  if (isLate(source, now)) {
    return {
      tone: 'warn',
      label: 'Late',
      detail:
        'It was due a while ago and has not run. Check the scheduler is running.',
      resumable: false,
    };
  }

  if (source.pending_identities > 0) {
    const n = source.pending_identities;
    return {
      tone: 'warn',
      label: 'Needs attention',
      detail: `${n} ${n === 1 ? 'name' : 'names'} in the data ${
        n === 1 ? 'does' : 'do'
      } not match anyone here. Those rows are waiting, not lost.`,
      resumable: false,
    };
  }

  if (source.last_status === 'partial') {
    return {
      tone: 'warn',
      label: 'Needs attention',
      detail: 'The last sync could not use everything it read.',
      resumable: false,
    };
  }

  // Last, so anything wrong with the read it made is still said first. Not
  // "Working": that reads as a live feed, and this one stopped on purpose.
  if (source.interval_minutes === READ_ONCE) {
    return {
      tone: 'idle',
      label: 'Read once',
      detail: 'It read once, cleanly, and reads again only when somebody presses Sync now.',
      resumable: false,
    };
  }

  // **Clean, and still stuck** (7.3, Q2-5): a sheet nobody has updated
  // syncs without an error forever. Said before "Working", which it is not.
  if (source.stale_working_days && source.newest_row_at) {
    return {
      tone: 'warn',
      label: 'No new numbers',
      detail: `It syncs cleanly, but the newest row is from ${shortDate(
        source.newest_row_at,
      )} — nothing new in ${source.stale_working_days} working days. Has whatever feeds it stopped being updated?`,
      resumable: false,
    };
  }

  return {
    tone: 'good',
    label: 'Working',
    detail: source.newest_row_at
      ? `The last sync completed cleanly. Newest row ${shortDate(source.newest_row_at)}.`
      : 'The last sync completed cleanly.',
    resumable: false,
  };
}

/** "Wed 23 Sep" — the order the Inbox and Home write it in. */
function shortDate(iso: string): string {
  return dayName(iso);
}

/**
 * Whether a source has missed its slot.
 *
 * Measured from `next_run_at`, which is what the scheduler actually promised,
 * rather than recomputed from the interval — two places calculating the same
 * moment is two places to drift apart.
 */
export function isLate(
  source: Pick<SourceStatus, 'next_run_at' | 'interval_minutes'>,
  now: Date,
): boolean {
  // No next run means "due now" to the scheduler, not "overdue" to a reader.
  if (!source.next_run_at) return false;
  // A one-off has no schedule to miss. The server clears its next run once it
  // has read, but one written before that carries a date that was already in
  // the past when it was set (QA-12).
  if (source.interval_minutes === READ_ONCE) return false;
  const due = new Date(source.next_run_at).getTime();
  return now.getTime() > due + graceMinutes(source.interval_minutes) * 60_000;
}

// ── How current the numbers are ──────────────────────────────────────────────

/**
 * One metric's freshness, as `GET /api/data-freshness` reports it.
 *
 * Deliberately thin, and the server keeps it that way: a status word and some
 * timestamps. Everyone signed in can read this, and nobody outside the
 * integrations page needs to know what an organization has plugged in.
 */
export interface MetricFreshness {
  metric_id: number;
  latest_fact_at: string | null;
  /** The newest number of any kind, corrections included (Q2-12). */
  latest_any_at?: string | null;
  imported: boolean;
  sources: {
    last_status: string | null;
    last_run_at: string | null;
    next_run_at: string | null;
    interval_minutes: number;
    enabled: boolean;
  }[];
}

export interface Currency {
  /** When the newest imported measurement happened. Null if none ever has. */
  asOf: Date | null;
  /** True when something feeding these numbers is overdue or failing. */
  suspect: boolean;
  /** One sentence, or null when there is nothing worth saying. */
  note: string | null;
}

/**
 * Whether the numbers on this page can be trusted to be current.
 *
 * **Silence is the default.** A working source produces no note at all: a banner
 * on every page saying "everything is fine" is a banner people stop seeing, and
 * then it fails to work on the day it matters. Something is said only when a feed
 * is overdue, failing, or has never delivered.
 *
 * A metric fed only by hand is never suspect. Nobody promised it would refresh,
 * so telling somebody their manually-corrected figures are stale would be
 * inventing a problem.
 */
export function currencyOf(
  freshness: MetricFreshness[],
  metricIds: number[],
  now: Date,
): Currency {
  const wanted = freshness.filter((f) => metricIds.includes(f.metric_id));
  const imported = wanted.filter((f) => f.imported);

  const stamps = wanted
    .map((f) => f.latest_fact_at)
    .filter((at): at is string => at !== null)
    .map((at) => new Date(at).getTime());
  // **What "Data as of" says includes corrections** (Q2-12): a figure made
  // partly of a 2 Oct correction is not "as of Sep 23". The imported stamps
  // still decide whether anything was ever imported, below.
  const shown = wanted
    .map((f) => f.latest_any_at ?? f.latest_fact_at)
    .filter((at): at is string => Boolean(at))
    .map((at) => new Date(at).getTime());
  const asOf = shown.length > 0 ? new Date(Math.max(...shown)) : null;

  if (imported.length === 0) {
    // Hand-entered, or nothing set up. Either way there is no schedule to be
    // late against, so there is nothing to warn about.
    return { asOf, suspect: false, note: null };
  }

  const sources = imported.flatMap((f) => f.sources);
  const failing = sources.some((s) => s.last_status === 'failed');
  const paused = sources.length > 0 && sources.every((s) => !s.enabled);
  const late = sources.some((s) => s.enabled && isLate(s, now));
  const never = sources.some((s) => s.enabled && !s.last_run_at);

  if (failing) {
    return {
      asOf,
      suspect: true,
      note: 'A feed behind these numbers is failing, so they may be incomplete.',
    };
  }
  if (paused) {
    return {
      asOf,
      suspect: true,
      note: 'Importing is paused, so these numbers stopped updating.',
    };
  }
  if (late) {
    return {
      asOf,
      suspect: true,
      note: 'A feed behind these numbers is overdue, so they may be out of date.',
    };
  }
  if (never || stamps.length === 0) {
    return {
      asOf,
      suspect: true,
      note: 'Nothing has been imported for these numbers yet.',
    };
  }

  return { asOf, suspect: false, note: null };
}

/** Moved to `time.ts`, so every page says the same thing. */
export { agoInWords } from '../time';
