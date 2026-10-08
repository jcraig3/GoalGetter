import { describe, expect, test } from 'vitest';

import type { Source } from '../dataSources';
import { acceptsMore, addLabel, groupSources, worksheetOf } from './sourceGroups';

function source(id: number, connector: string, name: string, config = {}): Source {
  return {
    id,
    name,
    connector,
    connector_name: connector === 'microsoft_excel' ? 'Excel' : connector,
    enabled: true,
    config,
    interval_minutes: 60,
    backfill_days: 90,
    timezone: null,
    next_run_at: null,
    last_run_at: null,
    last_status: 'ok',
    failure_count: 0,
    credentials_set: true,
    connector_missing: false,
    archived: false,
    activated: true,
    mappings: [],
  } as unknown as Source;
}

describe('one integration reads as one thing', () => {
  test('four spreadsheets are one group of four, not four integrations', () => {
    // The reported problem: four loose cards all called Microsoft Excel, each
    // looking like a separate connection.
    const groups = groupSources([
      source(1, 'microsoft_excel', 'Closed Deals'),
      source(2, 'microsoft_excel', 'Q3 Pipeline'),
      source(3, 'microsoft_excel', 'Commissions'),
      source(4, 'microsoft_excel', 'Renewals'),
    ]);

    expect(groups).toHaveLength(1);
    expect(groups[0]?.connector_name).toBe('Excel');
    expect(groups[0]?.sources.map((s) => s.name)).toEqual([
      'Closed Deals',
      'Q3 Pipeline',
      'Commissions',
      'Renewals',
    ]);
  });

  test('each sheet stays its own row', () => {
    // **Not a compromise.** Per-source health is the reason to open this page;
    // one collapsed row would hide a sheet that has been failing for days.
    const groups = groupSources([
      source(1, 'microsoft_excel', 'Closed Deals'),
      source(2, 'microsoft_excel', 'Q3 Pipeline'),
    ]);

    expect(groups[0]?.sources.map((s) => s.id)).toEqual([1, 2]);
  });

  test('different connectors are different groups', () => {
    const groups = groupSources([
      source(1, 'microsoft_excel', 'Deals'),
      source(2, 'webhook', 'Zapier'),
      source(3, 'microsoft_excel', 'Pipeline'),
    ]);

    expect(groups.map((g) => [g.connector, g.sources.length])).toEqual([
      ['microsoft_excel', 2],
      ['webhook', 1],
    ]);
  });

  test('order is first appearance, so adding one does not reshuffle the page', () => {
    const before = groupSources([
      source(1, 'webhook', 'Zapier'),
      source(2, 'microsoft_excel', 'Deals'),
    ]).map((g) => g.connector);

    const after = groupSources([
      source(1, 'webhook', 'Zapier'),
      source(2, 'microsoft_excel', 'Deals'),
      source(3, 'microsoft_excel', 'Pipeline'),
    ]).map((g) => g.connector);

    expect(after).toEqual(before);
  });

  test('an empty list is no groups, not one empty group', () => {
    expect(groupSources([])).toEqual([]);
  });

  test('a connector this build no longer ships still renders as something', () => {
    const orphan = { ...source(1, 'retired', 'Old feed'), connector_name: '' };
    expect(groupSources([orphan as Source])[0]?.connector_name).toBe('retired');
  });
});

describe('what distinguishes one sheet from its siblings', () => {
  test('the worksheet, because the names alone can be identical', () => {
    expect(
      worksheetOf(source(1, 'microsoft_excel', 'Deals', { worksheet: 'Closed Deals' })),
    ).toBe('Closed Deals');
  });

  test('nothing for a source with no worksheet configured', () => {
    // Pre-picker sources hold no worksheet. Showing an empty pair of quotes
    // would look like a rendering fault.
    expect(worksheetOf(source(1, 'microsoft_excel', 'Deals', { worksheet: '' }))).toBe('');
    expect(worksheetOf(source(1, 'microsoft_excel', 'Deals'))).toBe('');
  });

  test('nothing for anything that is not a spreadsheet', () => {
    expect(worksheetOf(source(1, 'webhook', 'Zapier'))).toBe('');
  });

  test('a non-string worksheet is not rendered as one', () => {
    expect(worksheetOf(source(1, 'microsoft_excel', 'D', { worksheet: 7 }))).toBe('');
  });
});

describe('where "add another" belongs', () => {
  test.each([
    ['microsoft_excel', true],
    ['google_sheets', true],
    ['webhook', false],
    ['sql', false],
  ])('%s accepts more: %s', (connector, expected) => {
    expect(acceptsMore(connector)).toBe(expected);
  });

  test('the button uses that connector own noun', () => {
    expect(addLabel('microsoft_excel')).toBe('Add a spreadsheet');
    expect(addLabel('sql')).toBe('Add another');
  });
});
