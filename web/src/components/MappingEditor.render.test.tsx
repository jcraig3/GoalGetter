// @vitest-environment jsdom
/**
 * The mapping editor, rendered.
 *
 * **Every bug in this screen got through a green suite.** The date picker showed
 * a column the state did not hold, because the control had no option for the
 * empty value it was given. The blocker asked for a row id on a panel that could
 * not express one. Both were invisible to a suite that only ever called pure
 * functions — so these tests render the thing and read what a person would see.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, test, vi } from 'vitest';

import MappingEditor, { type MetricOption } from './MappingEditor';
import type { SourceField } from '../dataSources';

vi.mock('../dataSources', () => ({
  dataSources: {
    addMapping: vi.fn(async () => ({ id: 1, metric_id: 1, metric_name: 'Amount' })),
    editMapping: vi.fn(async () => ({ id: 1, metric_id: 1, metric_name: 'Amount' })),
    preview: vi.fn(async () => []),
  },
}));

const FIELDS: SourceField[] = [
  { name: 'email', kind: 'email' as const, samples: ['a@b.com'], values: [] },
  { name: 'amount_today', kind: 'number' as const, samples: ['10'], values: [] },
  { name: 'amount_month', kind: 'number' as const, samples: ['99'], values: [] },
];

const METRICS: MetricOption[] = [
  { id: 1, name: 'Sales Amount Today', unit: 'currency', archived: false },
  { id: 2, name: 'Sales Amount This Month', unit: 'currency', archived: false },
];

function draw(fields: SourceField[] = FIELDS) {
  return render(
    <MappingEditor
      sourceId={1}
      fields={fields}
      metrics={METRICS}
      onSaved={() => {}}
    />,
  );
}

const pickerFor = (label: string) =>
  screen.getByLabelText(label, { exact: false }) as HTMLSelectElement;

describe('the date picker', () => {
  test('offers an empty choice, so a dateless source can say so', () => {
    // The bug: with no such option, React set `value=''` on a select that had
    // none, the browser displayed the first column instead, and what was on
    // screen was never what would be saved.
    draw();
    const when = pickerFor('When it happened');

    expect([...when.options].map((o) => o.value)).toContain('');
  });

  test('shows what it actually holds', () => {
    draw();
    const when = pickerFor('When it happened');

    // Nothing in these columns is a date, so the suggestion is empty — and the
    // control must say empty rather than showing a column it is not using.
    expect(when.value).toBe('');
  });

  test('explains what empty means', () => {
    draw();

    expect(screen.getByText(/dated when its number last changes/i)).toBeDefined();
  });
});

describe('choosing a metric', () => {
  beforeEach(() => draw());

  test('fills in the column the metric is named after', async () => {
    const user = userEvent.setup();

    await user.selectOptions(pickerFor('Import into which metric'), '2');

    await waitFor(() =>
      expect(pickerFor('The amount').value).toBe('amount_month'),
    );
  });

  test('says why that column was chosen', async () => {
    const user = userEvent.setup();

    await user.selectOptions(pickerFor('Import into which metric'), '2');

    await waitFor(() =>
      expect(screen.getByText(/Matched to/i)).toBeDefined(),
    );
  });
});

describe('a dateless mapping', () => {
  test('identifies rows by the person, without being asked', () => {
    // One row per person is what dateless means in practice, so the person is
    // what identifies the row. Starting empty opened a form that could not be
    // saved without saying the answer was already on screen.
    draw();

    expect(pickerFor("The source’s id for the row").value).toBe('email');
  });

  test('says the field is mandatory once it is cleared', async () => {
    const user = userEvent.setup();
    draw();

    await user.selectOptions(pickerFor("The source’s id for the row"), '');

    expect(
      screen.getByText(/Required here, because there is no date column/i),
    ).toBeDefined();
  });
});

describe('keeping a figure for each day', () => {
  test('is offered when the source has no dates', () => {
    draw();

    expect(screen.getByText(/Keep a figure for each day/i)).toBeDefined();
  });

  test('is not offered when the source supplies dates', () => {
    // That source already has history; the option would only invite turning one
    // sale into one a day.
    draw([
      ...FIELDS,
      { name: 'closed_at', kind: 'date' as const, samples: ['2026-03-02'], values: [] },
    ]);

    expect(screen.queryByText(/Keep a figure for each day/i)).toBeNull();
  });

  test('starts ticked when each row is a person', () => {
    // The row's id *is* the subject, so there is one row each and its number is
    // a running total — the shape that loses its history without this.
    draw();

    expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(true);
  });

  test('starts clear when rows are identified by something else', () => {
    // A deal id means one row per deal. Dating those by day would turn one sale
    // into one a day.
    draw([
      ...FIELDS,
      { name: 'deal_id', kind: 'string' as const, samples: ['D-1'], values: [] },
    ]);

    expect((screen.getByRole('checkbox') as HTMLInputElement).checked).toBe(false);
  });
});
