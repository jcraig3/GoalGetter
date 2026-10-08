// @vitest-environment jsdom
/** A manager's own team on their home page (6.13). */
import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, test, vi } from 'vitest';

import TeamCard, { type TeamHome } from './TeamCard';

vi.mock('../api', () => ({ api: vi.fn() }));
vi.mock('../notifications', () => ({ useRefreshNotifications: () => () => {} }));
vi.mock('../auth', () => ({ useAuth: () => ({ can: () => true }) }));
vi.mock('react-router-dom', () => ({ Link: ({ children }: { children: React.ReactNode }) => <a>{children}</a> }));
vi.mock('../pages/Achievements', () => ({
  RecogniseForm: ({ userId }: { userId: number }) => <p>Recognising {userId}</p>,
}));

const { api } = await import('../api');

const HOME: TeamHome = {
  team_id: 1,
  team_name: 'Sales',
  metrics: [
    { id: 5, name: 'Deals', recorded: 12 },
    { id: 6, name: 'Calls', recorded: 3 },
  ],
  metric_id: 5,
  metric_name: 'Deals',
  unit: 'count',
  decimal_places: 0,
  unit_label: 'deals',
  direction: 'higher_is_better',
  period_type: 'month',
  period_label: 'October 2026',
  members: [
    { user_id: 2, name: 'Bob', photo_digest: null, value: '30', rank: 1, goal: { goal_id: 9, target: '20', percent: 150, expected_percent: 10, status: 'hit' }, quiet_days: 0, is_me: false },
    { user_id: 3, name: 'Ann', photo_digest: null, value: '1', rank: 2, goal: { goal_id: 8, target: '40', percent: 2.5, expected_percent: 50, status: 'behind' }, quiet_days: 1, is_me: false },
    { user_id: 1, name: 'Mona', photo_digest: null, value: '0', rank: 3, goal: null, quiet_days: null, is_me: true },
  ],
  nudges: [
    { user_id: 3, name: 'Ann', kind: 'behind', value: '1', target: '40', expected: '20', days: null },
    { user_id: 4, name: 'Cat', kind: 'quiet', value: null, target: null, expected: null, days: 9 },
  ],
  shout_outs: [{ user_id: 2, name: 'Bob', kind: 'hit', value: '30', target: null, expected: null, days: null }],
};

beforeEach(() => {
  window.localStorage.clear();
  vi.mocked(api).mockReset();
  vi.mocked(api).mockResolvedValue(HOME as never);
});

async function open() {
  render(<TeamCard />);
  await act(async () => {
    await Promise.resolve();
  });
}

describe('the team card', () => {
  test('draws nothing for somebody with no team', async () => {
    vi.mocked(api).mockResolvedValue(null as never);
    await open();
    expect(screen.queryByText(/Your team/)).toBeNull();
  });

  test('ranks the team with each goal beside the number', async () => {
    await open();
    expect(screen.getByText('Sales', { exact: false })).toBeDefined();
    const bob = screen.getByLabelText('Recognise Bob').closest('li')!;
    expect(bob.textContent).toContain('of 20 deals goal');
    expect(screen.getAllByText('Behind').length).toBeGreaterThan(0);
    // Nobody is offered to recognise themselves.
    expect(screen.queryByLabelText('Recognise Mona')).toBeNull();
  });

  test('says why each person needs a nudge, figures written as everywhere', async () => {
    await open();
    const ann = screen.getAllByText('Ann').find((el) => el.closest('li')?.textContent?.includes('behind'))!;
    expect(ann.closest('li')!.textContent).toBe('Ann is behind on Deals: 1 deal of 40 deals, 20 deals expected by now');
    expect(screen.getByText("hasn’t recorded anything in 9 days")).toBeDefined();
    expect(screen.getByText('hit their Deals goal with', { exact: false })).toBeDefined();
  });

  test('recognises with the person already chosen', async () => {
    await open();
    fireEvent.click(screen.getByLabelText('Recognise Ann'));
    expect(screen.getByText('Recognising 3')).toBeDefined();
  });

  test('remembers the metric chosen', async () => {
    await open();
    fireEvent.change(screen.getByLabelText('Metric'), { target: { value: '6' } });
    await act(async () => {
      await Promise.resolve();
    });
    expect(vi.mocked(api).mock.calls.at(-1)![0]).toContain('metric_id=6');
    expect(window.localStorage.getItem('gg:team-metric')).toBe('6');
  });
});

describe('a whole team gone quiet', () => {
  test('is one note about the data, naming nobody', async () => {
    vi.mocked(api).mockResolvedValue({
      ...HOME,
      nudges: [{ user_id: 0, name: '', kind: 'team_quiet', value: '92', target: null, expected: null, days: 8 }],
    } as never);
    await open();
    expect(screen.getByText(/Nothing recorded for 92 of the team in 8 days/)).toBeDefined();
    expect(screen.getByText('Check the integrations')).toBeDefined();
  });
});

describe('a period with nothing in it yet (8.2)', () => {
  const EMPTY: TeamHome = {
    ...HOME,
    members: HOME.members.map((m) => ({ ...m, value: '0', rank: 0 })),
  };

  test('says so once, and offers last month when it had numbers', async () => {
    vi.mocked(api).mockImplementation((async (path: string) =>
      path.includes('previous=true') ? { ...HOME, period_label: 'September 2026' } : EMPTY) as never);
    render(<TeamCard />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByText('No numbers for October 2026 yet.')).toBeDefined();
    expect(screen.queryByRole('list', { name: 'Sales on Deals' })).toBeNull();

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Show last month' }));
    });
    expect(screen.getByText('Showing September 2026.')).toBeDefined();
    // The select says the period on show, not "This month" (P3-12).
    const select = screen.getByLabelText('Period') as HTMLSelectElement;
    expect(select.selectedOptions[0]!.textContent).toBe('September 2026');
    expect(screen.getByRole('list', { name: 'Sales on Deals' })).toBeDefined();
  });

  test('offers nothing when last month was empty too', async () => {
    vi.mocked(api).mockResolvedValue(EMPTY as never);
    render(<TeamCard />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(screen.getByText('No numbers for October 2026 yet.')).toBeDefined();
    expect(screen.queryByRole('button', { name: 'Show last month' })).toBeNull();
  });
});
