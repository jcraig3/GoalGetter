// @vitest-environment jsdom
/**
 * The reporting page, as somebody reads it.
 *
 * The sentences are tested next door in `reportingCopy.test.ts`. What is
 * worth asserting here is the part a pure function cannot see: that the
 * coaching gaps reach the screen with a name on them, that an empty answer
 * says so instead of rendering a blank panel, and that a panel which failed
 * to load does not read as "nothing to report".
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, test, vi } from 'vitest';

import Reporting from './Reporting';

vi.mock('../api', () => ({
  api: vi.fn(),
  ApiError: class extends Error {},
}));

const { api } = await import('../api');

const GAP = {
  goal_id: 7,
  goal_name: 'Calls this month',
  subject_name: 'Peter Parker',
  metric_name: 'Calls made',
  unit: 'count',
  decimal_places: 0,
  current: '20',
  target: '100',
  behind_by: 30,
  days_left: 8,
  rate_so_far: '4',
  rate_needed: '10',
};

const OVERVIEW = {
  total: 4,
  on_pace: 1,
  behind: 1,
  hit: 2,
  on_pace_percent: 75,
  gaps: [GAP],
};

const RECORD = {
  goal_id: 7,
  goal_name: 'Calls this month',
  subject_name: 'Peter Parker',
  metric_name: 'Calls made',
  unit: 'count',
  decimal_places: 0,
  target: '100',
  seasons: [
    { label: 'March', value: '120', met_target: true },
    { label: 'April', value: '40', met_target: false },
  ],
  considered: 2,
  hit: 1,
  hit_rate: 50,
  current_streak: 0,
  best_streak: 1,
};

function routes(answers: Record<string, unknown>) {
  vi.mocked(api).mockImplementation((path: string) => {
    const key = Object.keys(answers).find((prefix) => path.startsWith(prefix));
    if (key === undefined) return Promise.reject(new Error(`no stub: ${path}`));
    const answer = answers[key];
    return answer instanceof Error
      ? Promise.reject(answer)
      : Promise.resolve(answer as never);
  });
}

function show() {
  render(
    <MemoryRouter>
      <Reporting />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.mocked(api).mockReset();
});

test('the headline is the percentage on pace', async () => {
  routes({ '/api/reporting/overview': OVERVIEW });
  show();

  expect(await screen.findByText('75%')).toBeTruthy();
});

test('a gap says who it is about and what it would take', async () => {
  // **A gap with no name on it is not a coaching gap**, it is a statistic.
  routes({ '/api/reporting/overview': OVERVIEW });
  show();

  expect(await screen.findByText('Peter Parker')).toBeTruthy();
  expect(
    screen.getByText('Needs 10 a day for 8 working days (4 a day so far).'),
  ).toBeTruthy();
});

test('a gap links to the goal it is about', async () => {
  // Because the next thing somebody does after reading it is open it.
  routes({ '/api/reporting/overview': OVERVIEW });
  show();

  const link = await screen.findByRole('link', { name: /Peter Parker/ });

  expect(link.getAttribute('href')).toBe('/goals/7');
});

test('no goals running says so rather than showing 0%', async () => {
  // A page claiming nobody is on pace because there are no goals is worse
  // than an empty one.
  routes({
    '/api/reporting/overview': { ...OVERVIEW, total: 0, gaps: [], on_pace_percent: 0 },
  });
  show();

  expect(await screen.findByText('No goals are running')).toBeTruthy();
  expect(screen.queryByText('0%')).toBeNull();
});

test('nobody behind draws no warning panel at all', async () => {
  // A permanent "nobody is behind" panel trains people to stop looking at
  // the spot warnings appear in.
  routes({
    '/api/reporting/overview': { ...OVERVIEW, behind: 0, gaps: [] },
  });
  show();

  await screen.findByText('75%');

  expect(screen.queryByText('What is missing')).toBeNull();
});

test('a panel that failed to load says so', async () => {
  // Silence here reads as "nothing to report", which on a page about who is
  // behind is the more dangerous of the two.
  routes({ '/api/reporting/overview': new Error('Could not load.') });
  show();

  const alert = await screen.findByRole('alert');

  expect(alert.textContent).toContain('Could not load.');
});

test('the track record shows each period and the hit rate', async () => {
  routes({
    '/api/reporting/overview': OVERVIEW,
    '/api/reporting/records': [RECORD],
  });
  show();

  await screen.findByText('75%');
  await userEvent.click(screen.getByRole('button', { name: 'Track record' }));

  expect(await screen.findByText('50%')).toBeTruthy();
  expect(screen.getByText(/1 of 2/)).toBeTruthy();
  expect(screen.getByText('March')).toBeTruthy();
  expect(screen.getByText('April')).toBeTruthy();
});

test('the export is a plain link the browser downloads', async () => {
  // Not a fetch: the session cookie goes with it, so nothing here has to
  // hold a file in memory.
  routes({
    '/api/reporting/overview': OVERVIEW,
    '/api/reporting/records': [RECORD],
  });
  show();

  await screen.findByText('75%');
  await userEvent.click(screen.getByRole('button', { name: 'Track record' }));

  const link = await screen.findByRole('link', { name: 'Download CSV' });

  expect(link.getAttribute('href')).toBe('/api/reporting/records.csv');
});

test('a competition report names what it is being compared against', async () => {
  // **The bars are past results; the line is this one's forecast.** Nothing
  // stores what an earlier contest was predicted to reach part-way through.
  routes({
    '/api/reporting/overview': OVERVIEW,
    '/api/competitions': [{ id: 3, name: 'August sprint', state: 'active' }],
    '/api/reporting/competitions/3': {
      competition_id: 3,
      name: 'August sprint',
      state: 'active',
      metric_name: 'Revenue',
      unit: 'currency',
      decimal_places: 2,
      entity_type: 'user',
      leader_name: 'Peter Parker',
      leader_value: '5000',
      elapsed_percent: 50,
      predicted: '10000',
      runs: [
        {
          competition_id: 1,
          name: 'July sprint',
          ended_on: '2026-07-31',
          winner_name: 'Clark Kent',
          value: '9000',
        },
      ],
      all_time_high: '9000',
      all_time_high_name: 'Clark Kent',
      first: '9000',
      previous: '9000',
      basis: '10000',
      vs_first: '1000',
      vs_previous: '1000',
      vs_high: '1000',
    },
  });
  show();

  await screen.findByText('75%');
  await userEvent.click(screen.getByRole('button', { name: 'Competitions' }));

  await waitFor(() => expect(screen.getByText('July sprint')).toBeTruthy());
  expect(screen.getByText('On pace to finish at')).toBeTruthy();
  expect(screen.getAllByText('$1,000 ahead').length).toBeGreaterThan(0);
});

test('a contest with nothing to compare against says that plainly', async () => {
  routes({
    '/api/reporting/overview': OVERVIEW,
    '/api/competitions': [{ id: 3, name: 'August sprint', state: 'active' }],
    '/api/reporting/competitions/3': {
      competition_id: 3,
      name: 'August sprint',
      state: 'active',
      metric_name: 'Revenue',
      unit: 'currency',
      decimal_places: 2,
      entity_type: 'user',
      leader_name: null,
      leader_value: null,
      elapsed_percent: 10,
      predicted: null,
      runs: [],
      all_time_high: null,
      all_time_high_name: null,
      first: null,
      previous: null,
      basis: null,
      vs_first: null,
      vs_previous: null,
      vs_high: null,
    },
  });
  show();

  await screen.findByText('75%');
  await userEvent.click(screen.getByRole('button', { name: 'Competitions' }));

  expect(
    await screen.findByText(/Nothing to compare it against yet/),
  ).toBeTruthy();
});
