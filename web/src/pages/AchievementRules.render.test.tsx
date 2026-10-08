// @vitest-environment jsdom
/**
 * Trying a rule before it is saved (5j).
 *
 * What has to be true: "Check the last 4 weeks" sends the form as it stands and says
 * how often the rule would have fired; a noisy rule is called noisy; and the
 * answer goes away once the rule is changed, because it was about a different
 * rule.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, test, vi } from 'vitest';

import AchievementRules from './AchievementRules';

vi.mock('../api', () => ({ api: vi.fn(), ApiError: class extends Error {} }));
vi.mock('../auth', () => ({
  useAuth: () => ({ can: () => true }),
  Can: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

const { api } = await import('../api');

const RULE = {
  id: 4,
  name: 'Big deal closed',
  metric_id: 1,
  metric_name: 'Revenue',
  comparator: 'gte',
  threshold: '5000',
  scope: 'everyone',
  scope_team_id: null,
  scope_team_name: null,
  message: '',
  media_url: null,
  media_kind: null,
  media_start_seconds: null,
  allow_personal_media: true,
  enabled: true,
  points: 10,
};

const CELEBRATION = {
  title: 'Big deal closed',
  body: 'Alice — 6,000.00',
  about_name: 'Alice',
  occasion: 'Big deal closed',
  media_url: null,
  media_kind: null,
  media_id: null,
  media_digest: null,
  media_start_seconds: null,
  media_end_seconds: null,
  hold_seconds: 8,
};

let fired = 3;

beforeEach(() => {
  fired = 3;
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation(((path: string) => {
    if (path === '/api/achievement-rules') return Promise.resolve([RULE]);
    if (path === '/api/sounds')
      return Promise.resolve({ pack: [], library: [], defaults: {}, kinds: [] });
    if (path === '/api/metrics')
      return Promise.resolve([
        { id: 1, name: 'Revenue', aggregation: 'sum', unit: 'currency', archived: false },
      ]);
    if (path.startsWith('/api/achievement-rules/suggest'))
      return Promise.resolve({ metric_id: 1, threshold: '6200.0000', would_fire: 27, weeks: 4 });
    if (path === '/api/achievement-rules/preview')
      return Promise.resolve({ fired, people: 2, days: 28, recorded: 9, celebration: CELEBRATION });
    return Promise.resolve([]);
  }) as never);
});

async function openRule() {
  render(
    <MemoryRouter>
      <AchievementRules />
    </MemoryRouter>,
  );
  await userEvent.click(await screen.findByRole('button', { name: 'Edit' }));
}

const tries = () =>
  vi.mocked(api).mock.calls.filter(([path]) => path === '/api/achievement-rules/preview');

test('a check says how often the rule would have fired last week', async () => {
  await openRule();
  await userEvent.click(screen.getByRole('button', { name: 'Check the last 4 weeks' }));

  expect(
    await screen.findByText(/Would have fired 3 times in the last 4 weeks \(about 1 a week\), for 2 people\./),
  ).toBeDefined();
  expect(JSON.parse(String(tries()[0]![1]!.body))).toMatchObject({
    name: 'Big deal closed',
    metric_id: 1,
    threshold: '5000',
  });
});

test('a rule that would fire many times a day is called noisy', async () => {
  fired = 280; // Ten a day over the four weeks.
  await openRule();
  await userEvent.click(screen.getByRole('button', { name: 'Check the last 4 weeks' }));

  expect(await screen.findByText(/About 10 a day/)).toBeDefined();
});

test('changing the rule clears an answer that was about the old one', async () => {
  await openRule();
  await userEvent.click(screen.getByRole('button', { name: 'Check the last 4 weeks' }));
  await screen.findByText(/Would have fired 3 times/);

  await userEvent.type(screen.getByLabelText('Name'), '!');

  await waitFor(() => expect(screen.queryByText(/Would have fired/)).toBeNull());
});

test('a starter fills the form, with a bar from the organization’s own numbers (6.4)', async () => {
  render(
    <MemoryRouter>
      <AchievementRules />
    </MemoryRouter>,
  );
  await userEvent.click(await screen.findByRole('button', { name: 'New rule' }));
  await userEvent.click(screen.getByRole('button', { name: 'Big deal' }));

  expect(await screen.findByText(/Set from your own Revenue: it would have fired 27 times in the last 4 weeks/)).toBeDefined();
  expect((screen.getByLabelText('Name') as HTMLInputElement).value).toBe('Big deal');
  expect((screen.getByLabelText('Threshold') as HTMLInputElement).value).toBe('6200');
  expect(
    vi.mocked(api).mock.calls.some(([path]) => path === '/api/achievement-rules/suggest?unit=currency&per_week=7'),
  ).toBe(true);
});

test('no numbers at all is said as no numbers, not as a high bar (Q2-4)', async () => {
  fired = 0;
  vi.mocked(api).mockImplementation(((path: string) => {
    if (path === '/api/achievement-rules') return Promise.resolve([RULE]);
    if (path === '/api/sounds') return Promise.resolve({ pack: [], library: [], defaults: {}, kinds: [] });
    if (path === '/api/metrics')
      return Promise.resolve([{ id: 1, name: 'Revenue', unit: 'currency', aggregation: 'sum' }]);
    if (path === '/api/achievement-rules/preview')
      return Promise.resolve({ fired: 0, people: 0, days: 28, recorded: 0, celebration: CELEBRATION });
    return Promise.resolve([]);
  }) as never);
  await openRule();
  await userEvent.click(screen.getByRole('button', { name: 'Check the last 4 weeks' }));
  expect(await screen.findByText(/No Revenue arrived in the last 4 weeks/)).toBeDefined();
  expect(screen.queryByText(/lower the bar/)).toBeNull();
});
