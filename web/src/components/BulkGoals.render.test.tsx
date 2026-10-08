// @vitest-environment jsdom
/** One target for a team, adjusted person by person (6.12). */
import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, test, vi } from 'vitest';

import BulkGoals, { plannedWords, summary } from './BulkGoals';

vi.mock('../api', () => ({ api: vi.fn() }));
vi.mock('../auth', () => ({
  useAuth: () => ({ user: { team_id: 1 }, can: () => true }),
}));

const { api } = await import('../api');

const ROSTER = {
  group_name: 'Sales',
  metric_name: 'Deals',
  unit: 'count',
  decimal_places: 0,
  unit_label: null,
  direction: 'higher_is_better',
  period_label: 'October 2026',
  last_period_label: 'September 2026',
  suggested_target: '30.0000',
  people: [
    { user_id: 1, name: 'Ann', team_name: 'Sales', photo_digest: null, last_value: '28', existing: null },
    { user_id: 2, name: 'Bob', team_name: 'Sales', photo_digest: null, last_value: '9', existing: { goal_id: 7, target_value: '20.0000' } },
    { user_id: 3, name: 'Cat', team_name: 'Sales', photo_digest: null, last_value: '0', existing: null },
  ],
};

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation(async (path: string) => {
    if (path === '/api/metrics') return [{ id: 5, name: 'Deals' }] as never;
    if (path === '/api/teams') return [{ id: 1, name: 'Sales' }] as never;
    if (path === '/api/offices') return [{ id: 9, name: 'Phoenix' }] as never;
    if (path === '/api/goals/bulk/roster') return ROSTER as never;
    return { created: 2, updated: 1 } as never;
  });
});

async function open(onSaved = vi.fn(async () => {})) {
  render(<BulkGoals onClose={() => {}} onSaved={onSaved} />);
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  // Chosen, not assumed (Q2-14).
  fireEvent.change(screen.getByLabelText('Team'), { target: { value: '1' } });
  await screen.findByText('Ann');
  return onSaved;
}

describe('the grid', () => {
  test('starts everybody on the suggested target, with last period beside them', async () => {
    await open();
    expect((screen.getByLabelText('Target for everyone') as HTMLInputElement).value).toBe('30');
    expect(screen.getByText('September 2026')).toBeDefined();
    expect(screen.getByText('28')).toBeDefined();
    // Bob has a goal of 20, so saving changes it rather than adding a second.
    expect(screen.getByText('Changes from 20')).toBeDefined();
    expect(screen.getByTestId('bulk-summary').textContent).toBe('Saving makes 2 goals and changes 1.');
  });

  test('saves everybody, with anybody given their own and anybody left out', async () => {
    const onSaved = await open();
    fireEvent.change(screen.getByLabelText('Target for Ann'), { target: { value: '35' } });
    fireEvent.click(screen.getByLabelText('Include Cat'));
    expect(screen.getByTestId('bulk-summary').textContent).toBe(
      'Saving makes 1 goal and changes 1. 1 left out.',
    );

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Set goals' }));
    });

    const call = vi.mocked(api).mock.calls.find(([path]) => path === '/api/goals/bulk')!;
    const body = JSON.parse((call[1] as RequestInit).body as string);
    expect(body.rows).toEqual([
      { user_id: 1, target_value: '35' },
      { user_id: 2, target_value: '30' },
    ]);
    expect(body).toMatchObject({ metric_id: 5, group_type: 'team', group_id: 1, period_type: 'month' });
    expect(onSaved).toHaveBeenCalledWith('2 goals set, 1 changed for Sales');
  });

  test('will not save while somebody has no target', async () => {
    await open();
    fireEvent.change(screen.getByLabelText('Target for everyone'), { target: { value: '' } });
    expect(screen.getByTestId('bulk-summary').textContent).toBe('3 people need a target.');
    expect((screen.getByRole('button', { name: 'Set goals' }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe('the team', () => {
  test('is chosen, not the first in the list (Q2-14)', async () => {
    render(<BulkGoals onClose={() => {}} onSaved={vi.fn()} />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect((screen.getByLabelText('Team') as HTMLSelectElement).value).toBe('');
    expect(vi.mocked(api).mock.calls.some(([path]) => path === '/api/goals/bulk/roster')).toBe(false);
  });
});

describe('the words', () => {
  test('say what saving does', () => {
    expect(plannedWords({ new: 1, update: 0, out: 0 })).toBe('Saving makes 1 goal.');
    expect(plannedWords({ new: 0, update: 0, out: 2 })).toBe('Nothing to change. 2 left out.');
    expect(summary(0, 3, 'Phoenix')).toBe('3 changed for Phoenix');
  });
});

describe('people with nothing last period (8.2)', () => {
  test('can be left out in one go', async () => {
    await open();
    fireEvent.click(screen.getByRole('button', { name: 'Leave out the 1 who recorded nothing in September 2026' }));
    expect(screen.getByTestId('bulk-summary').textContent).toBe('Saving makes 1 goal and changes 1. 1 left out.');
  });
});
