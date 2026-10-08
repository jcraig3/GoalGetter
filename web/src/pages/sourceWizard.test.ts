import { describe, expect, it } from 'vitest';

import {
  STEPS,
  agoInWords,
  currencyOf,
  graceMinutes,
  hintScore,
  isLate,
  resumeStep,
  sourceHealth,
  suggestMapping,
  words,
  type DiscoveredField,
  type MetricFreshness,
  type SourceStatus,
} from './sourceWizard';

function field(name: string, kind = 'string'): DiscoveredField {
  return { name, kind, samples: [] };
}

const NOW = new Date('2026-08-19T12:00:00Z');

function source(overrides: Partial<SourceStatus> = {}): SourceStatus {
  return {
    enabled: true,
    archived: false,
    connector_missing: false,
    credentials_set: true,
    mappings: [{}],
    last_status: 'ok',
    last_run_at: '2026-08-19T11:30:00Z',
    next_run_at: '2026-08-19T12:30:00Z',
    interval_minutes: 60,
    failure_count: 0,
    pending_identities: 0,
    ...overrides,
  };
}

describe('words', () => {
  it('splits the three spellings a payload actually uses', () => {
    expect(words('closed_at')).toEqual(['closed', 'at']);
    expect(words('closedAt')).toEqual(['closed', 'at']);
    expect(words('Closed At')).toEqual(['closed', 'at']);
  });

  it('keeps digits, which appear in real column names', () => {
    expect(words('field2Name')).toEqual(['field2', 'name']);
  });
});

describe('hintScore', () => {
  it('ranks by the order of the hint list, so a strong word wins', () => {
    expect(hintScore('owner', ['owner', 'user'])).toBe(0);
    expect(hintScore('user', ['owner', 'user'])).toBe(1);
  });

  it('matches words, not letters', () => {
    // The bug this exists to prevent: `id` inside `paid` picking the money
    // column as the row identifier.
    expect(hintScore('paid', ['id'])).toBe(-1);
    expect(hintScore('candidate', ['id'])).toBe(-1);
    expect(hintScore('deal_id', ['id'])).toBe(0);
  });

  it('matches a multi-word hint against the whole name', () => {
    expect(hintScore('EventID', ['event_id'])).toBe(0);
  });
});

describe('suggestMapping', () => {
  it('reads a typical CRM payload without being told anything', () => {
    const { draft } = suggestMapping([
      field('owner', 'email'),
      field('amount', 'number'),
      field('closed_at', 'date'),
      field('deal_id'),
      field('stage'),
    ]);

    expect(draft).toEqual({
      subject_field: 'owner',
      value_field: 'amount',
      occurred_at_field: 'closed_at',
      external_id_field: 'deal_id',
    });
  });

  it('prefers the email column for the person over one merely named like one', () => {
    // Kind beats name: a column of addresses is a better guess than a column
    // called `rep_name` holding "Alice".
    const { draft } = suggestMapping([
      field('rep_name'),
      field('contact', 'email'),
    ]);

    expect(draft.subject_field).toBe('contact');
  });

  it('picks the best-named column when several are the right kind', () => {
    const { draft } = suggestMapping([
      field('updated_at', 'date'),
      field('closed_at', 'date'),
    ]);

    expect(draft.occurred_at_field).toBe('closed_at');
  });

  it('prefers a well-named column over an earlier unnamed one of the same kind', () => {
    // Both parse as dates. Only one says which date it is, and reading order is
    // a much weaker signal than the column's own name.
    const { draft } = suggestMapping([
      field('synced', 'date'),
      field('closed_at', 'date'),
    ]);

    expect(draft.occurred_at_field).toBe('closed_at');
  });

  it('will not offer a number column as the person when a text one exists', () => {
    // Neither column is named like a person, so nothing but kind separates them
    // — and without the text fallback this picks `amount`, the first column,
    // presenting a money column as the salesperson.
    const { draft } = suggestMapping([
      field('amount', 'number'),
      field('handled_by_initials'),
    ]);

    expect(draft.subject_field).toBe('handled_by_initials');
  });

  it('still offers something for the person when every column is a number', () => {
    // A payload of `{"id": 1, "amount": 100}` has nobody in it. The picker is
    // required, so it has to hold something an admin can see is wrong.
    const { draft, reasons } = suggestMapping([
      field('id', 'number'),
      field('amount', 'number'),
    ]);

    expect(draft.subject_field).toBe('id');
    expect(reasons.subject_field).toContain('A guess');
  });

  it('falls back to a text column named like a date', () => {
    // Extremely common: a spreadsheet or JSON payload where the date arrives as
    // a string the type-guesser did not recognise.
    const { draft, reasons } = suggestMapping([
      field('owner', 'email'),
      field('close date'),
    ]);

    expect(draft.occurred_at_field).toBe('close date');
    expect(reasons.occurred_at_field).toContain('arrive as text');
  });

  it('leaves the value empty when there is no number, and says why', () => {
    const { draft, reasons } = suggestMapping([
      field('owner', 'email'),
      field('closed_at', 'date'),
    ]);

    expect(draft.value_field).toBeNull();
    expect(reasons.value_field).toContain('each row counts as one');
  });

  it('does not invent a row id from a column that is not one', () => {
    // Guessing wrong here is worse than not guessing: a bad external id makes
    // re-imports either duplicate or overwrite the wrong fact.
    const { draft } = suggestMapping([
      field('owner', 'email'),
      field('amount', 'number'),
      field('notes'),
    ]);

    expect(draft.external_id_field).toBeNull();
  });

  it('picks the first column for the person when nothing looks like one', () => {
    // A required picker left empty reads as broken. Visibly wrong is better.
    const { draft, reasons } = suggestMapping([field('alpha'), field('beta')]);

    expect(draft.subject_field).toBe('alpha');
    expect(reasons.subject_field).toContain('A guess');
  });

  it('says so when one column got picked for two roles', () => {
    // `date` matches the subject list through no word at all, but `created_by`
    // matches both people and dates — and silently mapping one column to two
    // roles produces a sync that fails on every row.
    const { draft, reasons } = suggestMapping([field('created_by')]);

    expect(draft.subject_field).toBe('created_by');
    expect(draft.occurred_at_field).toBe('created_by');
    expect(reasons.occurred_at_field).toContain('needs changing');
  });

  it('suggests nothing at all from nothing at all', () => {
    const { draft } = suggestMapping([]);

    expect(draft.subject_field).toBe('');
    expect(draft.occurred_at_field).toBe('');
  });
});

describe('resumeStep', () => {
  it('sends an unconnected source back to the connect step', () => {
    expect(
      resumeStep({ credentialsSet: false, hasFields: false, mappingCount: 0 }),
    ).toBe(2);
  });

  it('keeps a connected source on connect until something has arrived', () => {
    // For a webhook, "connected" and "has told us its columns" are different
    // facts: the endpoint exists from the start, the schema only after a post.
    expect(
      resumeStep({ credentialsSet: true, hasFields: false, mappingCount: 0 }),
    ).toBe(2);
  });

  it('goes to mapping once the columns are known', () => {
    expect(
      resumeStep({ credentialsSet: true, hasFields: true, mappingCount: 0 }),
    ).toBe(3);
  });

  it('goes to mapping when there is already a mapping, not past it', () => {
    // The last step is where a mapping is confirmed *and* switched on, so there is
    // nowhere past it to go — which is the point of having merged the two.
    expect(
      resumeStep({ credentialsSet: true, hasFields: true, mappingCount: 1 }),
    ).toBe(3);
  });

  it('never returns step one, because reaching it means a source exists', () => {
    const everyState = [
      { credentialsSet: false, hasFields: false, mappingCount: 0 },
      { credentialsSet: true, hasFields: false, mappingCount: 0 },
      { credentialsSet: true, hasFields: true, mappingCount: 0 },
      { credentialsSet: true, hasFields: true, mappingCount: 3 },
    ];

    expect(everyState.map(resumeStep).every((step) => step >= 2)).toBe(true);
  });

  it('never returns a step that does not exist', () => {
    expect(
      resumeStep({ credentialsSet: true, hasFields: true, mappingCount: 1 }),
    ).toBeLessThanOrEqual(STEPS.length);
  });
});

describe('sourceHealth', () => {
  it('calls a working source working', () => {
    expect(sourceHealth(source(), NOW).tone).toBe('good');
  });

  it('says a one-off that has read is read once, not late and not live', () => {
    const health = sourceHealth(
      source({ interval_minutes: 0, next_run_at: '2026-08-12T12:00:00Z' }),
      NOW,
    );

    expect([health.label, health.tone]).toEqual(['Read once', 'idle']);
  });

  it('still reports a one-off whose read failed as failing', () => {
    const health = sourceHealth(
      source({ interval_minutes: 0, last_status: 'failed', failure_count: 1 }),
      NOW,
    );

    expect(health.label).toBe('Failing');
  });

  it('reports a removed source as removed, not as unfinished', () => {
    // Archiving forgets the credential, so every other check below would call
    // this *setup unfinished* and offer to resume a setup somebody deliberately
    // took away.
    const health = sourceHealth(
      source({
        archived: true,
        credentials_set: false,
        enabled: false,
        mappings: [],
      }),
      NOW,
    );

    expect(health.label).toBe('Removed');
    expect(health.resumable).toBe(false);
  });

  it('reports a missing connector above everything else', () => {
    // Nothing else is actionable — it will never run whatever else is true.
    const health = sourceHealth(
      source({
        connector_missing: true,
        enabled: false,
        last_status: 'failed',
      }),
      NOW,
    );

    expect(health.label).toBe('Unavailable');
  });

  it('describes an unmapped source as unfinished, not as never having synced', () => {
    const health = sourceHealth(
      source({ mappings: [], last_run_at: null }),
      NOW,
    );

    expect(health.label).toBe('Setup unfinished');
    expect(health.resumable).toBe(true);
  });

  it('describes a source with no credentials as unfinished', () => {
    expect(
      sourceHealth(source({ credentials_set: false }), NOW).resumable,
    ).toBe(true);
  });

  it('describes a half-built paused source as half-built', () => {
    // Both are true; only one tells them what to do.
    const health = sourceHealth(source({ enabled: false, mappings: [] }), NOW);

    expect(health.label).toBe('Setup unfinished');
  });

  it('calls a finished paused source paused', () => {
    const health = sourceHealth(source({ enabled: false }), NOW);

    expect(health.label).toBe('Paused');
    expect(health.tone).toBe('idle');
  });

  it('counts the failures when there have been several', () => {
    const health = sourceHealth(
      source({ last_status: 'failed', failure_count: 4 }),
      NOW,
    );

    expect(health.tone).toBe('bad');
    expect(health.detail).toContain('last 4 attempts');
  });

  it('does not pluralise a single failure', () => {
    const health = sourceHealth(
      source({ last_status: 'failed', failure_count: 1 }),
      NOW,
    );

    expect(health.detail).toBe('The last attempt failed.');
  });

  it('says a brand-new source is waiting rather than late', () => {
    const health = sourceHealth(
      source({ last_run_at: null, next_run_at: null }),
      NOW,
    );

    expect(health.label).toBe('Waiting');
  });

  it('reports a missed slot', () => {
    const health = sourceHealth(
      source({ next_run_at: '2026-08-19T10:00:00Z' }),
      NOW,
    );

    expect(health.label).toBe('Late');
  });

  it('holds back on quarantine until the source is otherwise healthy', () => {
    // A failing source with waiting names has one useful message, and it is not
    // the one about names.
    const health = sourceHealth(
      source({ last_status: 'failed', pending_identities: 3 }),
      NOW,
    );

    expect(health.label).toBe('Failing');
  });

  it('names how many people are waiting to be identified', () => {
    const health = sourceHealth(
      source({ pending_identities: 3, last_status: 'partial' }),
      NOW,
    );

    expect(health.label).toBe('Needs attention');
    expect(health.detail).toContain('3 names');
    expect(health.detail).toContain('waiting, not lost');
  });

  it('reads naturally for exactly one waiting name', () => {
    const health = sourceHealth(source({ pending_identities: 1 }), NOW);

    expect(health.detail).toContain('1 name in the data does not match');
  });

  it('flags a partial sync even with nobody waiting', () => {
    // A partial run with an empty quarantine means rows were skipped for some
    // other reason — a bad column, usually — and that is worth surfacing.
    const health = sourceHealth(source({ last_status: 'partial' }), NOW);

    expect(health.label).toBe('Needs attention');
  });
});

describe('isLate', () => {
  it('allows a whole interval of grace, because the loop ticks', () => {
    const due = { next_run_at: '2026-08-19T11:00:00Z', interval_minutes: 60 };

    // 60 minutes past due: inside the grace period for an hourly source.
    expect(isLate(due, new Date('2026-08-19T11:59:00Z'))).toBe(false);
    expect(isLate(due, new Date('2026-08-19T12:01:00Z'))).toBe(true);
  });

  it('gives a frequent source ten minutes rather than five', () => {
    // Half of one five-minute interval is noise, not lateness.
    const due = { next_run_at: '2026-08-19T11:00:00Z', interval_minutes: 5 };

    expect(isLate(due, new Date('2026-08-19T11:09:00Z'))).toBe(false);
    expect(isLate(due, new Date('2026-08-19T11:11:00Z'))).toBe(true);
  });

  it('treats no scheduled run as due now, not overdue', () => {
    expect(isLate({ next_run_at: null, interval_minutes: 60 }, NOW)).toBe(
      false,
    );
  });

  it('never calls a one-off late, whatever date it carries', () => {
    // QA-12: one written before the server cleared it holds "the moment it
    // finished", a week ago.
    expect(
      isLate({ next_run_at: '2026-08-12T12:00:00Z', interval_minutes: 0 }, NOW),
    ).toBe(false);
  });
});

describe('graceMinutes', () => {
  it('never drops below ten minutes', () => {
    expect(graceMinutes(5)).toBe(10);
    expect(graceMinutes(1440)).toBe(1440);
  });
});

function feed(overrides: Partial<MetricFreshness['sources'][number]> = {}) {
  return {
    last_status: 'ok',
    last_run_at: '2026-08-19T11:30:00Z',
    next_run_at: '2026-08-19T12:30:00Z',
    interval_minutes: 60,
    enabled: true,
    ...overrides,
  };
}

function fresh(overrides: Partial<MetricFreshness> = {}): MetricFreshness {
  return {
    metric_id: 1,
    latest_fact_at: '2026-08-19T11:00:00Z',
    imported: true,
    sources: [feed()],
    ...overrides,
  };
}

describe('currencyOf', () => {
  it('puts no warning on a board fed by a one-off that has read', () => {
    // QA-12: the banner that agents see too, raised by a source doing exactly
    // what it was told.
    const { suspect, note } = currencyOf(
      [fresh({ sources: [feed({ interval_minutes: 0, next_run_at: '2026-08-12T12:00:00Z' })] })],
      [1],
      NOW,
    );

    expect([suspect, note]).toEqual([false, null]);
  });

  it('says nothing at all when everything is working', () => {
    // A banner saying "all fine" on every page is a banner people stop seeing,
    // and then it fails to work on the day it matters.
    const { note, suspect } = currencyOf([fresh()], [1], NOW);

    expect(note).toBeNull();
    expect(suspect).toBe(false);
  });

  it('reports the newest measurement across every metric on the page', () => {
    // A leaderboard can show two metrics. "As of" means the most recent thing
    // it knows, not the most recent thing the first metric knows.
    const { asOf } = currencyOf(
      [
        fresh({ metric_id: 1, latest_fact_at: '2026-08-19T09:00:00Z' }),
        fresh({ metric_id: 2, latest_fact_at: '2026-08-19T11:45:00Z' }),
      ],
      [1, 2],
      NOW,
    );

    expect(asOf?.toISOString()).toBe('2026-08-19T11:45:00.000Z');
  });

  it('counts a correction in "as of" but not in whether the feed is late (Q2-12)', () => {
    // The feed stopped on 12 Aug; somebody corrected a figure today. The page
    // is as of today, and the feed is still late.
    const { asOf, suspect } = currencyOf(
      [
        fresh({
          latest_fact_at: '2026-08-12T09:00:00Z',
          latest_any_at: '2026-08-19T11:50:00Z',
          sources: [feed({ next_run_at: '2026-08-12T12:00:00Z', last_run_at: '2026-08-12T11:00:00Z' })],
        }),
      ],
      [1],
      NOW,
    );

    expect(asOf?.toISOString()).toBe('2026-08-19T11:50:00.000Z');
    expect(suspect).toBe(true);
  });

  it('ignores metrics this page does not show', () => {
    const { note } = currencyOf(
      [
        fresh({ metric_id: 1 }),
        fresh({ metric_id: 2, sources: [feed({ last_status: 'failed' })] }),
      ],
      [1],
      NOW,
    );

    expect(note).toBeNull();
  });

  it('does not call a hand-entered metric stale', () => {
    // Nobody promised it would refresh, so warning about it invents a problem.
    const { suspect, note } = currencyOf(
      [fresh({ imported: false, sources: [], latest_fact_at: null })],
      [1],
      NOW,
    );

    expect(suspect).toBe(false);
    expect(note).toBeNull();
  });

  it('reports a failing feed', () => {
    const { suspect, note } = currencyOf(
      [fresh({ sources: [feed({ last_status: 'failed' })] })],
      [1],
      NOW,
    );

    expect(suspect).toBe(true);
    expect(note).toContain('failing');
  });

  it('reports a paused feed, because the numbers have stopped moving', () => {
    const { note } = currencyOf(
      [fresh({ sources: [feed({ enabled: false })] })],
      [1],
      NOW,
    );

    expect(note).toContain('paused');
  });

  it('is not paused while one of two feeds is still running', () => {
    const { note } = currencyOf(
      [fresh({ sources: [feed({ enabled: false }), feed()] })],
      [1],
      NOW,
    );

    expect(note).toBeNull();
  });

  it('reports an overdue feed', () => {
    const { note } = currencyOf(
      [fresh({ sources: [feed({ next_run_at: '2026-08-19T09:00:00Z' })] })],
      [1],
      NOW,
    );

    expect(note).toContain('overdue');
  });

  it('does not call a paused feed overdue', () => {
    // A paused source is deliberately not running. Reporting it as late blames
    // the scheduler for a decision somebody made on purpose.
    const { note } = currencyOf(
      [
        fresh({
          sources: [
            feed({ enabled: false, next_run_at: '2026-08-19T09:00:00Z' }),
          ],
        }),
      ],
      [1],
      NOW,
    );

    expect(note).toContain('paused');
  });

  it('does not blame the scheduler for a feed somebody paused', () => {
    // Two feeds: one healthy, one paused months ago and therefore long past its
    // last scheduled run. `paused` is false because not every feed is off, so
    // this is the case that proves the lateness check skips disabled sources.
    const { suspect, note } = currencyOf(
      [
        fresh({
          sources: [
            feed(),
            feed({ enabled: false, next_run_at: '2026-06-01T09:00:00Z' }),
          ],
        }),
      ],
      [1],
      NOW,
    );

    expect(suspect).toBe(false);
    expect(note).toBeNull();
  });

  it('says so when a feed exists but has imported nothing', () => {
    const { suspect, note } = currencyOf(
      [
        fresh({
          latest_fact_at: null,
          sources: [feed({ last_run_at: null, next_run_at: null })],
        }),
      ],
      [1],
      NOW,
    );

    expect(suspect).toBe(true);
    expect(note).toContain('Nothing has been imported');
  });

  it('prefers the failure to the overdue when both are true', () => {
    // One sentence, and the actionable one. An overdue feed that is also failing
    // is failing.
    const { note } = currencyOf(
      [
        fresh({
          sources: [
            feed({
              last_status: 'failed',
              next_run_at: '2026-08-19T09:00:00Z',
            }),
          ],
        }),
      ],
      [1],
      NOW,
    );

    expect(note).toContain('failing');
  });

  it('has nothing to say about a page showing no metrics', () => {
    expect(currencyOf([fresh()], [], NOW)).toEqual({
      asOf: null,
      suspect: false,
      note: null,
    });
  });
});

describe('agoInWords', () => {
  it('rounds down to the coarsest useful unit', () => {
    const then = (iso: string) => agoInWords(new Date(iso), NOW);

    expect(then('2026-08-19T11:59:30Z')).toBe('just now');
    expect(then('2026-08-19T11:59:00Z')).toBe('1 minute ago');
    expect(then('2026-08-19T11:30:00Z')).toBe('30 minutes ago');
    expect(then('2026-08-19T11:00:00Z')).toBe('1 hour ago');
    expect(then('2026-08-19T08:00:00Z')).toBe('4 hours ago');
    expect(then('2026-08-18T11:00:00Z')).toBe('1 day ago');
    expect(then('2026-08-16T11:00:00Z')).toBe('3 days ago');
  });

  it('falls back to a date once "days ago" stops being useful', () => {
    // Nobody counts in units of nine days.
    expect(agoInWords(new Date('2026-08-01T12:00:00Z'), NOW)).not.toContain(
      'ago',
    );
  });

  it('does not read as the future when a clock runs fast', () => {
    // A browser a couple of minutes ahead of the server must not say
    // "in 2 minutes" about a measurement that has already landed.
    expect(agoInWords(new Date('2026-08-19T12:02:00Z'), NOW)).toBe('just now');
  });
});

describe('STEPS', () => {
  it('ends on a review', () => {
    // **Review came back, and the reason it went away no longer holds.** It was
    // merged into Map on the grounds that the mapping editor already shows ten
    // real rows as the facts they would become — true for one mapping. Creating
    // metrics from the columns makes several, and the editor shows one.
    expect(STEPS[STEPS.length - 1]).toBe('Review');
  });

  it('resuming never lands past the mapping step', () => {
    // Review is reached by going forward, not by resuming into it: a source
    // abandoned half-mapped has nothing to review yet.
    expect(
      resumeStep({ credentialsSet: true, hasFields: true, mappingCount: 0 }),
    ).toBeLessThan(STEPS.length);
  });
});
