import {
  hintScore,
  suggestMapping,
  words,
  type DiscoveredField,
} from './sourceWizard';

/**
 * What a source could measure, proposed rather than assumed.
 *
 * **The gap this fills was a dead end.** Connecting a spreadsheet ended at "there
 * are no metrics to import into yet — create one first, then come back", which
 * sends somebody to a form asking for a key, a unit, an aggregation and a
 * direction about data they are looking at on the previous screen. Everything
 * that form asks for is derivable from the columns; asking anyway was making a
 * person translate their own spreadsheet into our vocabulary.
 *
 * **One sheet is more than one metric, and that is the main insight.** A table of
 * closed deals measures two things: how many, and how much. Those are a count
 * metric with no value column — `mapping.value_of` treats a missing one as "count
 * the row as one" — and a currency metric summing the amount column. Proposing
 * only one would leave somebody to work out that the other was possible.
 *
 * **Proposed, never created silently.** Metrics are org-wide vocabulary that show
 * up on leaderboards and goals; inventing them from column names without a
 * decision would be the same mistake as creating accounts from a directory
 * without approval. Every proposal here is editable and unticked-able before
 * anything is written — the names especially, because a column called `amount`
 * cannot tell us whether the company calls it revenue, premium or GWP.
 */
export const UNITS = ['count', 'currency', 'percent', 'duration'] as const;
export type Unit = (typeof UNITS)[number];

/** What the API accepts, in `models/metric_definition.py`. */
export const AGGREGATIONS = [
  'sum',
  'count',
  'avg',
  'max',
  'min',
  'last',
] as const;
export type Aggregation = (typeof AGGREGATIONS)[number];

export const DIRECTIONS = ['higher_is_better', 'lower_is_better'] as const;
export type Direction = (typeof DIRECTIONS)[number];

/** Said the way somebody thinks about it, not the way it is stored. */
export const AGGREGATION_LABELS: Record<Aggregation, string> = {
  sum: 'Add them up',
  count: 'Count the rows',
  avg: 'Average them',
  max: 'Highest',
  min: 'Lowest',
  last: 'Most recent',
};

export const DIRECTION_LABELS: Record<Direction, string> = {
  higher_is_better: 'Higher is better',
  lower_is_better: 'Lower is better',
};

export interface MetricProposal {
  /** Storage key. Lowercase, underscores, starts with a letter. */
  key: string;
  name: string;
  unit: Unit;
  aggregation: Aggregation;
  decimal_places: number;
  /** The column to read, or `null` for "each row counts as one". */
  value_field: string | null;
  /** Why this was proposed, shown beside it so the guess is auditable. */
  why: string;
}

/**
 * A proposal after somebody has edited it.
 *
 * **Kept apart from the proposal it came from**, so re-detecting — which happens
 * whenever the column roles change — cannot quietly revert a name or a unit
 * somebody chose. The edits are a sparse overlay keyed by the proposal's key;
 * anything not overridden follows detection, which is what makes changing a
 * column role still update the metrics below it.
 */
export type MetricEdit = Partial<
  Pick<
    MetricProposal,
    'name' | 'unit' | 'aggregation' | 'decimal_places' | 'value_field'
  >
> & { direction?: Direction };

/** A proposal with its overrides applied, ready to create. */
export function edited(
  proposal: MetricProposal,
  edits: MetricEdit | undefined,
): MetricProposal & { direction: Direction } {
  return {
    ...proposal,
    direction: 'higher_is_better',
    ...(edits ?? {}),
    // The name decides the key, so an edited name must not keep the old one —
    // that is how two differently-named metrics collide on save.
    name: (edits?.name ?? proposal.name).trim() || proposal.name,
    key: keyFor((edits?.name ?? proposal.name).trim() || proposal.name),
  };
}

/** Column names that mean money. Order is preference — see `hintScore`. */
const MONEY_WORDS = [
  'revenue',
  'amount',
  'premium',
  'commission',
  'price',
  'value',
  'total',
  'mrr',
  'arr',
  'sales',
  'cost',
  'fee',
  'payment',
  'gross',
  'net',
  'spend',
];

/** Column names that mean a proportion, not a quantity. */
const PERCENT_WORDS = [
  'percent',
  'pct',
  'rate',
  'ratio',
  'conversion',
  'margin',
];

/** Column names that mean elapsed time. */
const DURATION_WORDS = [
  'duration',
  'minutes',
  'hours',
  'seconds',
  'elapsed',
  'handle_time',
  'talk_time',
];

/**
 * Columns that are numeric but are not measurements.
 *
 * **The one that matters is the identifier.** A deal id is a number, sums
 * beautifully, and means absolutely nothing — a leaderboard of summed deal ids is
 * the kind of thing that looks plausible for a week.
 */
const NOT_MEASUREMENTS = [
  'external_id',
  'event_id',
  'record_id',
  'deal_id',
  'opportunity_id',
  'transaction_id',
  'invoice_id',
  'account_id',
  'user_id',
  'reference',
  'uuid',
  'guid',
  'id',
  'zip',
  'postcode',
  'phone',
  'year',
  'month',
  'day',
];

/**
 * Column-name suffixes that name a period rather than a thing.
 *
 * **The shape a warehouse holds after years of feeding a leaderboard.** Tools
 * before this one take one number per person, so the only way to offer "this
 * month" as well as "today" is a separate column for each — `amount_today`,
 * `amount_month`, `amount_year`. The period ends up in the column name because
 * there was nowhere else to put it.
 *
 * Two things follow. The period word must not be read as the *subject* of the
 * column — `NOT_MEASUREMENTS` holds `month` and `year` to veto a column that is
 * a month number, and it was vetoing `amount_month`, which is an amount. And the
 * period belongs in the metric's name, because it is genuinely part of what the
 * number means: `amount_month` on a weekly leaderboard would be a month's
 * revenue under a weekly heading.
 *
 * Longest first, so `last_month` is not read as `month`.
 */
const PERIODS: [string, string][] = [
  ['last_month', 'Last Month'],
  ['last_week', 'Last Week'],
  ['last_year', 'Last Year'],
  ['last_quarter', 'Last Quarter'],
  ['this_month', 'This Month'],
  ['this_week', 'This Week'],
  ['this_year', 'This Year'],
  ['yesterday', 'Yesterday'],
  ['today', 'Today'],
  ['mtd', 'This Month'],
  ['wtd', 'This Week'],
  ['ytd', 'This Year'],
  ['qtd', 'This Quarter'],
  ['quarter', 'This Quarter'],
  ['month', 'This Month'],
  ['week', 'This Week'],
  ['year', 'This Year'],
  ['day', 'Today'],
];

/**
 * A column split into what it measures and the period it measures it over.
 *
 * `amount_month` is *Amount*, over *This Month*. `amount` on its own has no
 * period and is left whole — a suffix is only a period when something precedes
 * it, so a column actually called `month` is not stripped to nothing.
 */
export function splitPeriod(name: string): {
  base: string;
  period: string | null;
} {
  const normalised = name.toLowerCase();
  for (const [suffix, label] of PERIODS) {
    if (!normalised.endsWith(suffix)) continue;
    const base = name
      .slice(0, name.length - suffix.length)
      .replace(/[_\-\s]+$/, '');
    if (!base) continue;
    return { base, period: label };
  }
  return { base: name, period: null };
}

/**
 * What a column would be called if a metric were built from it.
 *
 * The same string `suggestMetrics` names its proposals with, minus the source
 * prefix — so a metric created from this source can be matched back to the
 * column it came from.
 */
export function columnLabel(name: string): string {
  const { base, period } = splitPeriod(name);
  return period ? `${humanise(base)} ${period}` : humanise(name);
}

/**
 * The column a metric is most likely measuring, or null.
 *
 * **Because picking a metric should fill the form in, the way creating one
 * does.** Choosing "Amount This Month" from a dropdown and then being asked
 * which column it means is asking a question whose answer is in the name — and
 * it is the same question, asked twice, for anybody who made the metric here a
 * minute earlier.
 *
 * Matched by containment rather than equality, because the metric carries a
 * source prefix the column does not: *Sales Feed Amount This Month* contains
 * *Amount This Month*. Longest match wins, so `amount_month` beats `amount` for
 * a metric named after the month — the shorter one is a substring of every name
 * the longer one matches.
 *
 * Returns null rather than guessing when nothing matches. A wrong column is a
 * leaderboard measuring the wrong thing, and an empty picker asks a question
 * somebody can actually see.
 */
export function columnForMetric(
  metricName: string,
  fields: DiscoveredField[],
): string | null {
  const flat = (text: string) => text.toLowerCase().replace(/[^a-z0-9]/g, '');
  const target = flat(metricName);

  let best: { name: string; length: number } | null = null;
  for (const field of fields) {
    const label = flat(columnLabel(field.name));
    if (!label || !target.includes(label)) continue;
    if (best === null || label.length > best.length) {
      best = { name: field.name, length: label.length };
    }
  }
  return best?.name ?? null;
}

//: The board period each metric-name period corresponds to.
//:
//: Only the ones that name a *current* window. "Last Month" is a frozen figure
//: and matches no board period at all, which `periodMismatch` says out loud
//: rather than leaving to be discovered.
const PERIOD_TO_BOARD: Record<string, string> = {
  Today: 'day',
  'This Week': 'week',
  'This Month': 'month',
  'This Quarter': 'quarter',
  'This Year': 'year',
};

/**
 * Why this metric does not belong on a board with this period, if it does not.
 *
 * **The trap a pre-aggregated source sets.** Such a view carries the period in
 * the column — `amount_today`, `amount_month` — so the metrics built from it
 * carry it in the name. Put *Amount This Month* on a weekly board and it shows a
 * month of revenue under a weekly heading: every number is wrong, every number
 * looks plausible, and nothing downstream can tell.
 *
 * A warning rather than a refusal. Somebody may deliberately want a month's
 * running total displayed beside weekly boards, and a product that forbids what
 * it cannot understand is worse than one that asks. Returns null when the metric
 * names no period, which is most of them.
 */
export function periodMismatch(
  metricName: string,
  boardPeriod: string,
): string | null {
  const { period } = splitPeriod(metricName.toLowerCase().replace(/\s+/g, '_'));
  if (!period) return null;

  const expected = PERIOD_TO_BOARD[period];
  if (expected === boardPeriod) return null;

  if (!expected) {
    return (
      `“${metricName}” already covers ${period.toLowerCase()}, which is a fixed ` +
      `window rather than a period that moves. It will read the same whatever ` +
      `period this board is set to.`
    );
  }
  return (
    `“${metricName}” is already totalled over ${period.toLowerCase()}. On a ` +
    `board with a different period the figures are that total, not this ` +
    `period's — they will look plausible and be wrong.`
  );
}

/** Title Case from anything spelled like a column name. */
export function humanise(name: string): string {
  return words(name)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

/**
 * A storage key from a display name.
 *
 * Must satisfy the API's `KEY_PATTERN` — lowercase, digits, underscores, starting
 * with a letter. A name that begins with a digit gets a prefix rather than being
 * rejected at the end of a wizard, which is where the old failure landed.
 */
export function keyFor(name: string): string {
  const slug = words(name).join('_').slice(0, 64);
  if (!slug) return 'metric';
  return /^[a-z]/.test(slug) ? slug : `m_${slug}`.slice(0, 64);
}

/** What a column measures, from what it is called. */
function unitOf(column: string): {
  unit: MetricProposal['unit'];
  decimal_places: number;
} {
  if (hintScore(column, MONEY_WORDS) >= 0)
    return { unit: 'currency', decimal_places: 2 };
  if (hintScore(column, PERCENT_WORDS) >= 0)
    return { unit: 'percent', decimal_places: 1 };
  if (hintScore(column, DURATION_WORDS) >= 0)
    return { unit: 'duration', decimal_places: 0 };
  return { unit: 'count', decimal_places: 0 };
}

/**
 * A name that says which sheet it came from without repeating itself.
 *
 * "Closed Deals" + "amount" is *Closed Deals Amount*, but "Closed Deals" +
 * "deals closed" is just *Closed Deals* — a name that stutters reads as a bug
 * even when the metric is right.
 */
function combine(subject: string, column: string): string {
  const already = new Set(words(subject));
  const rest = words(column).filter((word) => !already.has(word));
  if (rest.length === 0) return humanise(subject);
  return `${humanise(subject)} ${humanise(rest.join(' '))}`.trim();
}

/**
 * The metrics a source could feed, best first.
 *
 * `subject` is what the data is about — the worksheet name for a spreadsheet, the
 * source's own name otherwise. It carries the meaning that column names do not:
 * `amount` is nothing on its own and *Closed Deals Amount* is a metric.
 *
 * `taken` are keys that already exist, so a second sheet of the same shape
 * proposes nothing already built rather than colliding on save.
 */
export function suggestMetrics(
  fields: DiscoveredField[],
  { subject, taken = [] }: { subject: string; taken?: string[] },
  /**
   * `trustMeasures` skips the name-based refusals below. Set when the columns
   * were chosen by a person: the `deal_id` guard exists to stop *detection*
   * proposing nonsense, and applying it to a deliberate choice would silently
   * drop a column somebody had just ticked.
   */
  {
    trustMeasures = false,
    rowsAreEvents = true,
  }: { trustMeasures?: boolean; rowsAreEvents?: boolean } = {},
): MetricProposal[] {
  const already = new Set(taken);
  const label = subject.trim() || 'Rows';
  const out: MetricProposal[] = [];

  // **How many** — but only where a row is a thing that happened.
  //
  // One row per deal makes "count the rows" the most useful metric on the page:
  // deals won, calls made, tickets closed. One row *per person*, which is what a
  // pre-aggregated view is, makes it a leaderboard on which everybody scores
  // exactly 1 — offered on every such source, named after the table, and never
  // once worth creating.
  //
  // A date column is the signal, and the same one the rest of this rests on: a
  // source that can say when something happened is a source whose rows are
  // events. See `models/data_source.py` on `occurred_at_field`.
  if (rowsAreEvents) {
    out.push({
      key: keyFor(label),
      name: humanise(label),
      unit: 'count',
      aggregation: 'sum',
      decimal_places: 0,
      value_field: null,
      why: 'One per row.',
    });
  }

  // **How much**, once per numeric column worth summing.
  for (const field of fields) {
    if (!trustMeasures && field.kind !== 'number') continue;

    // **Judged on what it measures, not on the period it covers.**
    // `NOT_MEASUREMENTS` holds `month` and `year` to veto a column that *is* a
    // month number; read against the whole name it also vetoed `amount_month`,
    // so two thirds of a warehouse view built for a leaderboard came back as
    // "Not used" with nothing saying why.
    const { base, period } = splitPeriod(field.name);
    if (!trustMeasures && hintScore(base, NOT_MEASUREMENTS) >= 0) continue;

    // The period stays in the name, because it is part of what the number means:
    // `amount_month` under a weekly heading is a month's revenue on a weekly
    // leaderboard, and nothing downstream could tell.
    const name = period
      ? `${combine(label, base)} ${period}`
      : combine(label, field.name);
    const { unit, decimal_places } = unitOf(base);
    out.push({
      key: keyFor(name),
      name,
      unit,
      aggregation: 'sum',
      decimal_places,
      value_field: field.name,
      why: period
        ? `Sum of “${field.name}” — already totalled over ${period.toLowerCase()}.`
        : `Sum of “${field.name}”.`,
    });
  }

  // Deduplicated on key, because two columns can combine to the same name — and
  // dropped where one already exists, so re-running this on a second sheet does
  // not offer to build what is already there.
  const seen = new Set<string>();
  return out.filter((proposal) => {
    if (already.has(proposal.key) || seen.has(proposal.key)) return false;
    seen.add(proposal.key);
    return true;
  });
}

/**
 * What the data is about, best answer first.
 *
 * **This is where "Microsoft Excel Amount" came from.** A source is created named
 * after its connector, so falling straight back to that name produced metrics
 * named after the software rather than the thing being measured. The worksheet is
 * the real answer — it carries the meaning column names do not, since `amount` is
 * nothing on its own and "Closed Deals Amount" is a metric — with the workbook
 * next for a single-sheet file, and the source's name only as a last resort.
 *
 * `connectorName` is what the source is called when nobody has renamed it. Passed
 * in so that name can be rejected rather than used, which is the whole fix.
 */
/**
 * The table or view a query reads from, as a name for what it measures.
 *
 * **The warehouse equivalent of a worksheet name.** A Snowflake source has no
 * file and no tab, so without this the subject is empty and every metric comes
 * out called "Rows" — the same shape of uselessness as "Microsoft Excel Amount",
 * arrived at from the other direction.
 *
 * `FROM ANALYTICS.SALES.CLOSED_DEALS__V` is *Closed Deals*: the last segment,
 * with the view suffix dropped. A `__V` or `_VW` says how a thing is stored, not
 * what it holds, and nobody wants a leaderboard called "Closed Deals V".
 *
 * Deliberately not a SQL parser. It reads the first `FROM`, which is right for
 * the shape this is for — one table or view, occasionally joined to lookups — and
 * returns nothing rather than a guess when the query is more complicated than
 * that. An empty answer costs a rename; a wrong one is a metric named after a
 * dimension table.
 */
export function tableOf(query: string): string {
  const match = /\bfrom\s+([A-Za-z_][\w$]*(?:\.[A-Za-z_][\w$]*)*)/i.exec(
    query || '',
  );
  if (!match?.[1]) return '';

  const last = match[1].split('.').pop() ?? '';
  // Trailing view markers, longest first so `__VIEW` is not left as `IEW`.
  const bare = last.replace(/__?(view|vw|v)$/i, '');
  return bare ? humanise(bare) : '';
}

export function subjectFor(
  config: Record<string, unknown> | undefined,
  sourceName: string,
  connectorName = '',
): string {
  const sheet = String(config?.worksheet ?? '').trim();
  if (sheet) return sheet;

  const file = String(config?.file_name ?? '')
    .replace(/\.xlsx?$|\.xlsm$/i, '')
    .trim();
  if (file) return file;

  const named = sourceName.trim();
  if (named && named !== connectorName.trim()) return named;

  // A warehouse query has neither a worksheet nor a file, so the table it reads
  // is the only thing that says what these numbers are.
  return tableOf(String(config?.query ?? ''));
}

// ── What each column is for ──────────────────────────────────────────────────

/**
 * The job a column does.
 *
 * **Six roles, and the list is the manual override.** Detection fills these in;
 * the wizard renders one dropdown per column bound to exactly this, so correcting
 * a guess and reading a guess happen in the same place. A separate "advanced
 * mapping" screen would be a second answer to the same question, and the two
 * would disagree the first time either changed.
 */
export const ROLES = [
  'subject',
  'date',
  'measure',
  'id',
  'filter',
  'ignore',
] as const;
export type Role = (typeof ROLES)[number];

/** Said in the reader's terms, not the schema's. */
export const ROLE_LABELS: Record<Role, string> = {
  subject: "Who it's for",
  date: 'When it happened',
  measure: 'Measure it',
  id: 'Row id',
  filter: 'Only some rows',
  ignore: 'Not used',
};

/** One line each, for the dropdown's help text. */
export const ROLE_HINTS: Record<Role, string> = {
  subject: 'Matches the row to a person by email or name.',
  date: 'Which period the row counts toward.',
  measure: 'Becomes a metric summing this column.',
  id: "The source's own id, so re-importing does not double anything.",
  filter: 'Keeps only the rows you choose.',
  ignore: 'Read, but nothing is done with it.',
};

/** Column names that mean "which stage is this in". Order is preference. */
const CATEGORY_WORDS = [
  'stage',
  'status',
  'outcome',
  'result',
  'disposition',
  'state',
  'phase',
];

/**
 * Values that mean "this one actually happened".
 *
 * Used to pre-select a filter, and **only** to pre-select one. Where nothing
 * matches, the column is left unused rather than filtered on a guess: quietly
 * choosing the wrong stage is the failure this whole feature exists to prevent,
 * and it would be invisible.
 */
const SUCCESS_WORDS = [
  'closed won',
  'won',
  'closed-won',
  'complete',
  'completed',
  'success',
  'successful',
  'approved',
  'paid',
  'signed',
  'sold',
];

/** Whether a column could be filtered on at all. */
export function isChoice(field: DiscoveredField): boolean {
  return (
    (field.kind === 'string' || field.kind === 'boolean') &&
    (field.values?.length ?? 0) > 1
  );
}

/** The value that means "it happened", or `''` when nothing obviously does. */
export function successValue(field: DiscoveredField): string {
  for (const want of SUCCESS_WORDS) {
    const hit = (field.values ?? []).find(
      (v) => v.trim().toLowerCase() === want,
    );
    if (hit) return hit;
  }
  return '';
}

/**
 * What each column is for, before anybody corrects it.
 *
 * Built on `suggestMapping` for the three roles it already decides, so the
 * column table and the mapping cannot disagree about which column is the person.
 *
 * **At most one filter is proposed, and only when its value is obvious.** A sheet
 * of deals has `stage` *and* `region`; filtering on the second is a guess nobody
 * asked for. So the best-named category column gets the role — and even then only
 * if one of its values reads as "this one happened", because a filter set to the
 * wrong stage is worse than no filter at all.
 */
export function suggestRoles(fields: DiscoveredField[]): Record<string, Role> {
  const { draft } = suggestMapping(fields);
  const roles: Record<string, Role> = {};

  let bestFilter: { name: string; score: number } | null = null;

  for (const field of fields) {
    if (field.name === draft.subject_field) {
      roles[field.name] = 'subject';
    } else if (field.name === draft.occurred_at_field) {
      roles[field.name] = 'date';
    } else if (field.name === draft.external_id_field) {
      roles[field.name] = 'id';
    } else if (
      field.kind === 'number' &&
      hintScore(splitPeriod(field.name).base, NOT_MEASUREMENTS) < 0
    ) {
      roles[field.name] = 'measure';
    } else {
      roles[field.name] = 'ignore';
    }

    if (
      roles[field.name] === 'ignore' &&
      isChoice(field) &&
      successValue(field)
    ) {
      const score = hintScore(field.name, CATEGORY_WORDS);
      if (score >= 0 && (bestFilter === null || score < bestFilter.score)) {
        bestFilter = { name: field.name, score };
      }
    }
  }

  if (bestFilter) roles[bestFilter.name] = 'filter';
  return roles;
}

/** The filter values to start with, for whichever columns hold that role. */
export function suggestFilterValues(
  fields: DiscoveredField[],
  roles: Record<string, Role>,
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const field of fields) {
    if (roles[field.name] === 'filter') out[field.name] = successValue(field);
  }
  return out;
}

/** The mapping's filter clauses, in the shape `app/mapping.py` enforces. */
export function filterClauses(
  roles: Record<string, Role>,
  values: Record<string, string>,
): { field: string; op: string; value: string }[] {
  return Object.entries(roles)
    .filter(([name, role]) => role === 'filter' && (values[name] ?? '') !== '')
    .map(([name]) => ({
      field: name,
      op: 'eq',
      value: values[name] as string,
    }));
}

/**
 * The metrics these roles produce.
 *
 * `suggestMetrics` is this with the roles it would have guessed — kept so the
 * common path reads as one call, and so that changing a dropdown and changing
 * nothing go down the same code path.
 */
export function metricsFor(
  fields: DiscoveredField[],
  roles: Record<string, Role>,
  { subject, taken = [] }: { subject: string; taken?: string[] },
): MetricProposal[] {
  const measures = fields.filter((f) => roles[f.name] === 'measure');
  return suggestMetrics(
    measures,
    { subject, taken },
    {
      // Every measure column is one the reader chose, so the name-based refusals
      // that keep a `deal_id` out of the automatic list must not second-guess
      // them here. Saying so explicitly beats a role that silently means two
      // things.
      trustMeasures: true,
      // No date means one row per person rather than one row per event, and
      // counting those is a leaderboard where everybody scores 1.
      rowsAreEvents: Object.values(roles).includes('date'),
    },
  );
}
