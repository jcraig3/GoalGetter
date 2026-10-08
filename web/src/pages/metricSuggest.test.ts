import { describe, expect, test } from 'vitest';

import {
  AGGREGATIONS,
  DIRECTIONS,
  UNITS,
  edited,
  filterClauses,
  keyFor,
  metricsFor,
  subjectFor,
  suggestFilterValues,
  suggestMetrics,
  columnForMetric,
  periodMismatch,
  splitPeriod,
  suggestRoles,
  tableOf,
} from './metricSuggest';

const field = (name: string, kind = 'string') => ({ name, kind, samples: [] });

/** The workbook the Excel connector is tested against, column for column. */
const CLOSED_DEALS = [
  field('deal_id'),
  field('rep_email', 'email'),
  field('closed_date', 'date'),
  field('amount', 'number'),
  field('stage'),
  field('region'),
];

describe('what a sheet can measure', () => {
  test('a table of deals measures both how many and how much', () => {
    // The whole point: proposing only one would leave somebody to work out that
    // the other was possible.
    const found = suggestMetrics(CLOSED_DEALS, { subject: 'Closed Deals' });

    expect(found.map((m) => [m.name, m.value_field])).toEqual([
      ['Closed Deals', null],
      ['Closed Deals Amount', 'amount'],
    ]);
  });

  test('the count metric reads no column at all', () => {
    // `null` is what tells `mapping.value_of` to count the row as one. A column
    // of literal 1s is the thing this avoids.
    const [count] = suggestMetrics(CLOSED_DEALS, { subject: 'Closed Deals' });

    expect(count?.value_field).toBeNull();
    expect(count?.unit).toBe('count');
    expect(count?.decimal_places).toBe(0);
  });

  test('an amount column is money, to two places', () => {
    const [, amount] = suggestMetrics(CLOSED_DEALS, {
      subject: 'Closed Deals',
    });

    expect(amount?.unit).toBe('currency');
    expect(amount?.decimal_places).toBe(2);
  });

  test('a numeric identifier is never proposed as a measurement', () => {
    // **The one that matters.** A deal id is a number, sums beautifully, and
    // means nothing — a leaderboard of summed deal ids looks plausible for a week.
    const found = suggestMetrics(
      [
        field('deal_id', 'number'),
        field('invoice_id', 'number'),
        field('amount', 'number'),
      ],
      { subject: 'Deals' },
    );

    expect(found.map((m) => m.value_field)).toEqual([null, 'amount']);
  });

  test('a year column is not a measurement either', () => {
    const found = suggestMetrics([field('year', 'number')], {
      subject: 'Deals',
    });

    expect(found.map((m) => m.value_field)).toEqual([null]);
  });

  test('every numeric column gets its own metric', () => {
    const found = suggestMetrics(
      [
        field('amount', 'number'),
        field('commission', 'number'),
        field('units', 'number'),
      ],
      { subject: 'Sales' },
    );

    expect(found.map((m) => m.name)).toEqual([
      'Sales',
      'Sales Amount',
      'Sales Commission',
      'Sales Units',
    ]);
  });
});

describe('units, from what the column is called', () => {
  test.each([
    ['revenue', 'currency', 2],
    ['premium', 'currency', 2],
    ['commission', 'currency', 2],
    ['conversion_rate', 'percent', 1],
    ['margin', 'percent', 1],
    ['handle_time', 'duration', 0],
    ['minutes', 'duration', 0],
    ['calls', 'count', 0],
    ['widgets', 'count', 0],
  ])('%s is %s', (column, unit, places) => {
    const [, metric] = suggestMetrics([field(column, 'number')], {
      subject: 'Work',
    });

    expect(metric?.unit).toBe(unit);
    expect(metric?.decimal_places).toBe(places);
  });
});

describe('names that read like names', () => {
  test('a name does not stutter when the column repeats the sheet', () => {
    // "Closed Deals" + "deals closed" must not become "Closed Deals Deals Closed".
    const found = suggestMetrics([field('deals_closed', 'number')], {
      subject: 'Closed Deals',
    });

    expect(found.map((m) => m.name)).toEqual(['Closed Deals']);
  });

  test('two columns collapsing to one name propose one metric, not two', () => {
    // Deduplicated on key, because the second would fail on save with a
    // collision — at the end of a wizard, which is the worst place to find out.
    const found = suggestMetrics(
      [field('deals_closed', 'number'), field('closed_deals', 'number')],
      { subject: 'Closed Deals' },
    );

    expect(found).toHaveLength(1);
  });

  test('a metric that already exists is not offered again', () => {
    const found = suggestMetrics(CLOSED_DEALS, {
      subject: 'Closed Deals',
      taken: ['closed_deals'],
    });

    expect(found.map((m) => m.key)).toEqual(['closed_deals_amount']);
  });

  test('a sheet with no name still proposes something usable', () => {
    const found = suggestMetrics([], { subject: '   ' });

    expect(found.map((m) => [m.key, m.name])).toEqual([['rows', 'Rows']]);
  });
});

describe('keys the API will accept', () => {
  test.each([
    ['Closed Deals', 'closed_deals'],
    ['closedDeals', 'closed_deals'],
    ['Closed-Deals!', 'closed_deals'],
    ['  Revenue  ', 'revenue'],
  ])('%s becomes %s', (name, key) => {
    expect(keyFor(name)).toBe(key);
  });

  test('a name starting with a digit is prefixed rather than rejected', () => {
    // `KEY_PATTERN` demands a leading letter. Fixing it here beats a 422 at the
    // end of the wizard naming a field the person never filled in.
    expect(keyFor('2026 Bookings')).toBe('m_2026_bookings');
  });

  test('every proposed key is one the API would accept', () => {
    const pattern = /^[a-z][a-z0-9_]*$/;
    const found = suggestMetrics(
      [field('2026 total', 'number'), field('amount', 'number')],
      { subject: '2026 Deals' },
    );

    expect(found.length).toBeGreaterThan(0);
    for (const proposal of found) {
      expect(proposal.key).toMatch(pattern);
      expect(proposal.key.length).toBeLessThanOrEqual(64);
    }
  });
});

describe('what the data is about', () => {
  test('the worksheet wins, because it is the only name that means anything', () => {
    expect(
      subjectFor(
        { worksheet: 'Closed Deals', file_name: 'Sales.xlsx' },
        'Microsoft Excel',
        'Microsoft Excel',
      ),
    ).toBe('Closed Deals');
  });

  test('the workbook is next, without its extension', () => {
    expect(
      subjectFor(
        { file_name: 'Closed Deals.xlsx' },
        'Microsoft Excel',
        'Microsoft Excel',
      ),
    ).toBe('Closed Deals');
  });

  test.each(['Report.xlsx', 'Report.xls', 'Report.xlsm', 'Report.XLSX'])(
    '%s loses its extension',
    (file) => {
      expect(subjectFor({ file_name: file }, 'x', 'x')).toBe('Report');
    },
  );

  test('a source still named after its connector is not a subject', () => {
    // **The reported bug.** A source is created named "Microsoft Excel", so
    // falling back to it produced a metric called "Microsoft Excel Amount" —
    // named after the software rather than the thing being measured.
    expect(subjectFor({}, 'Microsoft Excel', 'Microsoft Excel')).toBe('');
  });

  test('and then nothing is proposed under that name either', () => {
    const found = suggestMetrics([field('amount', 'number')], {
      subject: subjectFor({}, 'Microsoft Excel', 'Microsoft Excel'),
    });

    expect(found.map((m) => m.name)).toEqual(['Rows', 'Rows Amount']);
  });

  test('a name somebody actually typed is used', () => {
    // Renaming is an answer. Only the untouched default is rejected.
    expect(subjectFor({}, 'Q3 Bookings', 'Microsoft Excel')).toBe(
      'Q3 Bookings',
    );
  });

  test('a connector with no default name still yields the source name', () => {
    expect(subjectFor({}, 'Webhook feed')).toBe('Webhook feed');
  });
});

// ── Roles, and the filter that stops a metric being wrong ────────────────────

const CHOICES = (name: string, values: string[]) => ({
  name,
  kind: 'string',
  samples: [values[0] ?? ''],
  values,
});

const DEALS = [
  field('deal_id'),
  field('rep_email', 'email'),
  field('closed_date', 'date'),
  field('amount', 'number'),
  CHOICES('stage', ['Closed Won', 'Closed Lost', 'Negotiation']),
  CHOICES('region', ['West', 'Central', 'East']),
];

describe('what each column is for', () => {
  test('every column gets a role, and nothing is left unaccounted for', () => {
    // **The other half of the reported problem.** Six columns went in and two
    // metrics came out, with nothing said about the other four — so correct
    // behaviour read as a failure.
    expect(suggestRoles(DEALS)).toEqual({
      deal_id: 'id',
      rep_email: 'subject',
      closed_date: 'date',
      amount: 'measure',
      stage: 'filter',
      region: 'ignore',
    });
  });

  test('only one filter is proposed, and it is the one named like a stage', () => {
    // A sheet of deals has `stage` AND `region`. Filtering on the second is a
    // guess nobody asked for.
    const roles = suggestRoles(DEALS);
    expect(Object.values(roles).filter((r) => r === 'filter')).toHaveLength(1);
    expect(roles.stage).toBe('filter');
  });

  test('a category with no obvious success value is left alone', () => {
    // **Refusing to guess.** A filter set to the wrong stage is worse than no
    // filter: it is invisibly wrong, where no filter is at least visibly total.
    const roles = suggestRoles([
      field('rep_email', 'email'),
      field('closed_date', 'date'),
      CHOICES('status', ['Open', 'Pending', 'Review']),
    ]);
    expect(roles.status).toBe('ignore');
  });

  test('a high-cardinality text column is never a filter', () => {
    const roles = suggestRoles([
      field('rep_email', 'email'),
      field('closed_date', 'date'),
      { name: 'notes', kind: 'string', samples: ['blah'], values: [] },
    ]);
    expect(roles.notes).toBe('ignore');
  });

  test('the filter starts on the value that means it happened', () => {
    const roles = suggestRoles(DEALS);
    expect(suggestFilterValues(DEALS, roles)).toEqual({ stage: 'Closed Won' });
  });

  test('the clauses are the shape the mapping API enforces', () => {
    const roles = suggestRoles(DEALS);
    expect(filterClauses(roles, suggestFilterValues(DEALS, roles))).toEqual([
      { field: 'stage', op: 'eq', value: 'Closed Won' },
    ]);
  });

  test('a filter with no value chosen produces no clause', () => {
    // Rather than an `eq ''` that matches nothing and empties the leaderboard.
    expect(filterClauses({ stage: 'filter' }, { stage: '' })).toEqual([]);
  });
});

describe('metrics follow the roles, including corrected ones', () => {
  test('the detected roles give the same answer as before', () => {
    const found = metricsFor(DEALS, suggestRoles(DEALS), {
      subject: 'Closed Deals',
    });
    expect(found.map((m) => [m.name, m.value_field])).toEqual([
      ['Closed Deals', null],
      ['Closed Deals Amount', 'amount'],
    ]);
  });

  test('marking a column as a measure creates a metric for it', () => {
    const roles = { ...suggestRoles(DEALS), region: 'measure' as const };
    const found = metricsFor(DEALS, roles, { subject: 'Closed Deals' });
    expect(found.map((m) => m.name)).toContain('Closed Deals Region');
  });

  test('a deliberate measure is not second-guessed by the id guard', () => {
    // `deal_id` is refused by *detection* on purpose. Refusing it again after
    // somebody ticked it would silently drop a column they had just chosen.
    const roles = { ...suggestRoles(DEALS), deal_id: 'measure' as const };
    const found = metricsFor(DEALS, roles, { subject: 'Deals' });
    expect(found.map((m) => m.value_field)).toContain('deal_id');
  });

  test('unmarking the measure leaves only the count', () => {
    const roles = { ...suggestRoles(DEALS), amount: 'ignore' as const };
    const found = metricsFor(DEALS, roles, { subject: 'Closed Deals' });
    expect(found.map((m) => m.name)).toEqual(['Closed Deals']);
  });
});

// ── Editing a proposal ───────────────────────────────────────────────────────

describe('what somebody changes sticks', () => {
  const [count, amount] = suggestMetrics(CLOSED_DEALS, {
    subject: 'Closed Deals',
  }) as [
    ReturnType<typeof suggestMetrics>[number],
    ReturnType<typeof suggestMetrics>[number],
  ];

  test('an unedited proposal is unchanged, with a default direction', () => {
    expect(edited(amount, undefined)).toMatchObject({
      name: 'Closed Deals Amount',
      unit: 'currency',
      aggregation: 'sum',
      value_field: 'amount',
      direction: 'higher_is_better',
    });
  });

  test('a renamed metric gets a new key', () => {
    // **Otherwise two differently-named metrics collide on save.** The key is
    // derived from the name everywhere else, so an edit that changed one and not
    // the other would fail at the end of the wizard.
    expect(edited(amount, { name: 'Revenue' })).toMatchObject({
      name: 'Revenue',
      key: 'revenue',
    });
  });

  test('whitespace or an empty name falls back rather than producing a bad key', () => {
    expect(edited(amount, { name: '   ' }).key).toBe('closed_deals_amount');
  });

  test('every field can be overridden', () => {
    expect(
      edited(count, {
        name: 'Average deal size',
        unit: 'currency',
        aggregation: 'avg',
        decimal_places: 2,
        value_field: 'amount',
        direction: 'lower_is_better',
      }),
    ).toMatchObject({
      key: 'average_deal_size',
      unit: 'currency',
      aggregation: 'avg',
      decimal_places: 2,
      value_field: 'amount',
      direction: 'lower_is_better',
    });
  });

  test('an override survives the proposal being re-detected', () => {
    // Changing a column role rebuilds every proposal. Edits are a sparse overlay
    // keyed by the original key, so a name chosen a minute ago is still there.
    const again = suggestMetrics(CLOSED_DEALS, { subject: 'Closed Deals' })[1]!;
    expect(edited(again, { name: 'Revenue' }).name).toBe('Revenue');
  });

  test('the vocabulary matches what the API accepts', () => {
    // Mirrors `models/metric_definition.py`. A value here the server rejects is
    // a 422 at the end of the wizard.
    expect([...UNITS]).toEqual(['count', 'currency', 'percent', 'duration']);
    expect([...AGGREGATIONS]).toEqual([
      'sum',
      'count',
      'avg',
      'max',
      'min',
      'last',
    ]);
    expect([...DIRECTIONS]).toEqual(['higher_is_better', 'lower_is_better']);
  });
});

// ── Naming a warehouse query ─────────────────────────────────────────────────

describe('the table is what a query measures', () => {
  test.each([
    ['SELECT * FROM ANALYTICS.SALES.CLOSED_DEALS__V;', 'Closed Deals'],
    ['SELECT * FROM ANALYTICS.PUBLIC.CLOSED_DEALS', 'Closed Deals'],
    ['select a, b from deals where x >= :since', 'Deals'],
    ['SELECT * FROM sales_vw', 'Sales'],
    ['SELECT * FROM SALES_VIEW', 'Sales'],
  ])('%s -> %s', (query, expected) => {
    expect(tableOf(query)).toBe(expected);
  });

  test('a join takes the first table, not a lookup', () => {
    expect(
      tableOf(
        'SELECT * FROM ANALYTICS.DEALS d JOIN ANALYTICS.USERS u ON u.id = d.owner',
      ),
    ).toBe('Deals');
  });

  test('nothing rather than a guess when there is no table', () => {
    // An empty answer costs a rename. A wrong one is a metric named after a
    // dimension table, which nobody notices until it is on a wall.
    expect(tableOf('SELECT 1')).toBe('');
    expect(tableOf('')).toBe('');
  });

  test('a warehouse source names its metrics after the table', () => {
    // **The bug this closes.** With no worksheet and no file, the subject was
    // empty and every metric came out called "Rows".
    const fields = [
      { name: 'OWNER_EMAIL', kind: 'email', samples: ['a@b.com'], values: [] },
      { name: 'CLOSED_ON', kind: 'date', samples: ['2026-08-26'], values: [] },
      { name: 'AMOUNT', kind: 'number', samples: ['100'], values: [] },
    ];
    const subject = subjectFor(
      { query: 'SELECT * FROM ANALYTICS.SALES.CLOSED_DEALS__V' },
      'Snowflake',
      'Snowflake',
    );

    expect(subject).toBe('Closed Deals');
    expect(
      metricsFor(fields, suggestRoles(fields), { subject }).map((m) => m.name),
    ).toEqual(['Closed Deals', 'Closed Deals Amount']);
  });
});

// ── Periods hiding in column names ──────────────────────────────────────────
//
// **The shape a warehouse holds after years of feeding a leaderboard.** Tools
// before this one take one number per person, so the only way to offer "this
// month" as well as "today" is a separate column for each. The period ends up in
// the column name because there was nowhere else to put it.

describe('splitPeriod', () => {
  test.each([
    ['amount_today', 'amount', 'Today'],
    ['amount_month', 'amount', 'This Month'],
    ['amount_year', 'amount', 'This Year'],
    ['new_p1_last_month', 'new_p1', 'Last Month'],
    ['revenue_mtd', 'revenue', 'This Month'],
    ['deals_ytd', 'deals', 'This Year'],
  ])('reads %s as %s over %s', (name, base, period) => {
    expect(splitPeriod(name)).toEqual({ base, period });
  });

  test('prefers the longest suffix, so last_month is not month', () => {
    expect(splitPeriod('sales_last_month').period).toBe('Last Month');
  });

  test('leaves a column with no period whole', () => {
    expect(splitPeriod('amount')).toEqual({ base: 'amount', period: null });
  });

  test('does not strip a column that is only a period word', () => {
    // A column actually called `month` holds a month number. Stripping it would
    // leave nothing, and the veto that catches it depends on the name surviving.
    expect(splitPeriod('month')).toEqual({ base: 'month', period: null });
  });
});

describe('metrics from period columns', () => {
  const fields = [
    // A subject column, or the suggester falls back to "the first column" for it
    // and the measure under test becomes the person.
    { name: 'email', kind: 'email' as const, samples: ['a@b.com'], values: [] },
    {
      name: 'amount_today',
      kind: 'number' as const,
      samples: ['4215.37'],
      values: [],
    },
    {
      name: 'amount_month',
      kind: 'number' as const,
      samples: ['211712.89'],
      values: [],
    },
    { name: 'month', kind: 'number' as const, samples: ['9'], values: [] },
  ];

  test('offers a period column as a measure', () => {
    // `NOT_MEASUREMENTS` holds `month` to veto a column that *is* a month number.
    // Read against the whole name it also vetoed `amount_month`, so two thirds of
    // a view built for a leaderboard came back unused with nothing saying why.
    const roles = suggestRoles(fields);
    expect(roles.amount_month).toBe('measure');
    expect(roles.amount_today).toBe('measure');
  });

  test('still vetoes a column that is only a month number', () => {
    expect(suggestRoles(fields).month).not.toBe('measure');
  });

  test('keeps the period in the metric name', () => {
    // `amount_month` under a weekly heading is a month's revenue on a weekly
    // leaderboard, and nothing downstream could tell.
    const names = metricsFor(fields, suggestRoles(fields), {
      subject: 'Sales',
      taken: [],
    }).map((m) => m.name);

    expect(names).toContain('Sales Amount Today');
    expect(names).toContain('Sales Amount This Month');
  });

  test('says the number is already totalled, so nobody double counts', () => {
    const monthly = metricsFor(fields, suggestRoles(fields), {
      subject: 'Sales',
      taken: [],
    }).find((m) => m.value_field === 'amount_month');

    expect(monthly?.why).toContain('already totalled over this month');
  });
});

describe('counting the rows', () => {
  const totals = [
    { name: 'email', kind: 'email' as const, samples: ['a@b.com'], values: [] },
    {
      name: 'amount_today',
      kind: 'number' as const,
      samples: ['10'],
      values: [],
    },
  ];
  const events = [
    { name: 'email', kind: 'email' as const, samples: ['a@b.com'], values: [] },
    {
      name: 'closed_at',
      kind: 'date' as const,
      samples: ['2026-03-02'],
      values: [],
    },
    { name: 'amount', kind: 'number' as const, samples: ['10'], values: [] },
  ];

  test('is offered when a row is a thing that happened', () => {
    // One row per deal makes this the most useful metric on the page.
    const names = metricsFor(events, suggestRoles(events), {
      subject: 'Deals',
      taken: [],
    }).map((m) => m.name);

    expect(names).toContain('Deals');
  });

  test('is not offered when a row is a person', () => {
    // A pre-aggregated view has one row each, so counting them is a leaderboard
    // on which everybody scores exactly 1 — offered on every such source, named
    // after the table, and never once worth creating.
    const proposals = metricsFor(totals, suggestRoles(totals), {
      subject: 'Sales Feed',
      taken: [],
    });

    expect(proposals.map((m) => m.name)).not.toContain('Sales Feed');
    expect(proposals.every((m) => m.value_field !== null)).toBe(true);
  });

  test('still proposes the real measures without it', () => {
    const names = metricsFor(totals, suggestRoles(totals), {
      subject: 'Sales Feed',
      taken: [],
    }).map((m) => m.name);

    expect(names).toContain('Sales Feed Amount Today');
  });
});

describe('columnForMetric', () => {
  const fields = ['amount', 'amount_today', 'amount_month', 'new_p1_today'].map(
    (name) => ({ name, kind: 'number' as const, samples: ['1'], values: [] }),
  );

  test('matches a metric back to the column it was named after', () => {
    // Choosing "Amount This Month" and then being asked which column it means is
    // asking a question whose answer is in the name somebody just chose.
    expect(columnForMetric('Sales Feed Amount This Month', fields)).toBe(
      'amount_month',
    );
  });

  test('prefers the longest match', () => {
    // `amount` is a substring of every name `amount_today` matches, so the
    // shorter column would win every time without this.
    expect(columnForMetric('Sales Feed Amount Today', fields)).toBe(
      'amount_today',
    );
  });

  test('matches a plain column with no period', () => {
    expect(columnForMetric('Total Amount', fields)).toBe('amount');
  });

  test('returns nothing rather than guessing', () => {
    // A wrong column is a leaderboard measuring the wrong thing; an empty picker
    // at least asks the question visibly.
    expect(columnForMetric('Customer Satisfaction', fields)).toBeNull();
  });
});

describe('periodMismatch', () => {
  test('is silent when the metric and the board agree', () => {
    expect(periodMismatch('Sales Amount This Month', 'month')).toBeNull();
    expect(periodMismatch('Sales Amount Today', 'day')).toBeNull();
  });

  test('is silent for a metric that names no period', () => {
    // Most metrics. A warning on every board would be a warning nobody reads.
    expect(periodMismatch('Closed Deals', 'week')).toBeNull();
  });

  test('warns when the metric already covers a different period', () => {
    // A month of revenue under a weekly heading: every number wrong, every
    // number plausible, nothing downstream able to tell.
    const warning = periodMismatch('Sales Amount This Month', 'week');

    expect(warning).toContain('already totalled over this month');
    expect(warning).toContain('look plausible and be wrong');
  });

  test('warns that a fixed window ignores the board entirely', () => {
    const warning = periodMismatch('Sales New P1 Last Month', 'month');

    expect(warning).toContain('fixed window');
  });
});
