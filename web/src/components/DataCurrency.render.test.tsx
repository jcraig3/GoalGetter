// @vitest-environment jsdom
/**
 * How old a page's numbers are, and the alarm when a feed behind them fails.
 *
 * What has to be true: everyone sees "Data as of …", so a stale board is never
 * passed off as current; only somebody who can fix the feed sees the warning,
 * its reason and the link to the sources (5i).
 */
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, test, vi } from 'vitest';

import DataCurrency from './DataCurrency';

vi.mock('../api', () => ({ api: vi.fn(), ApiError: class extends Error {} }));

let admin = false;
vi.mock('../auth', () => ({
  useAuth: () => ({ can: (capability: string) => admin && capability === 'integrations.manage' }),
}));

const { api } = await import('../api');

const FAILING = [
  {
    metric_id: 3,
    latest_fact_at: new Date(Date.now() - 3 * 86_400_000).toISOString(),
    imported: true,
    sources: [
      {
        last_status: 'failed',
        last_run_at: new Date().toISOString(),
        next_run_at: null,
        interval_minutes: 60,
        enabled: true,
      },
    ],
  },
];

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(api).mockResolvedValue(FAILING as never);
});

const show = () =>
  render(
    <MemoryRouter>
      <DataCurrency metricIds={[3]} />
    </MemoryRouter>,
  );

test('an agent sees how old the numbers are, without the alarm', async () => {
  admin = false;
  show();

  expect(await screen.findByText(/Data as of/)).toBeDefined();
  expect(screen.queryByText(/failing/)).toBeNull();
  expect(screen.queryByRole('link', { name: 'Check the sources' })).toBeNull();
});

test('an admin sees the warning and the way to fix it', async () => {
  admin = true;
  show();

  expect(await screen.findByText(/A feed behind these numbers is failing/)).toBeDefined();
  expect(screen.getByRole('link', { name: 'Check the sources' })).toBeDefined();
});
