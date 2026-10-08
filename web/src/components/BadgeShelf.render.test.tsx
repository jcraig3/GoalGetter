// @vitest-environment jsdom
/**
 * The badge shelf under the season table.
 *
 * What is worth asserting is the thing a pure function cannot see: that a
 * person with no badges gets *no panel at all* rather than an empty heading
 * reminding them of it every day, and that a badge partway earned shows what
 * it would take — because that half is the one that changes behaviour.
 */
import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';

import BadgeShelf from './BadgeShelf';

vi.mock('../api', () => ({
  api: vi.fn(),
  ApiError: class extends Error {},
}));

const { api } = await import('../api');

beforeEach(() => {
  vi.mocked(api).mockReset();
});

const HELD = {
  badge_id: 1,
  name: 'Closer',
  description: 'Three big deals in a month',
  icon: 'trophy',
  reason: 'Closer',
  earned_at: '2028-02-01T10:00:00Z',
  times: 3,
};

const PROGRESS = {
  badge_id: 2,
  name: 'Streak',
  description: 'Five in a week',
  icon: 'spark',
  have: 3,
  need: 5,
  remaining: 2,
  counted_over: 'week',
};

test('nobody with no badges sees an empty panel', async () => {
  // An empty "Badges" heading is a small daily reminder of having none.
  vi.mocked(api).mockResolvedValue({ held: [], progress: [] } as never);

  const { container } = render(<BadgeShelf />);

  await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalled());
  expect(container.textContent).toBe('');
});

test('a badge held several times says so once', async () => {
  vi.mocked(api).mockResolvedValue({ held: [HELD], progress: [] } as never);

  render(<BadgeShelf />);

  expect(await screen.findByText('Closer')).toBeTruthy();
  expect(screen.getByText('×3')).toBeTruthy();
});

test('a badge partway earned says what it would take', async () => {
  vi.mocked(api).mockResolvedValue({ held: [], progress: [PROGRESS] } as never);

  render(<BadgeShelf />);

  expect(await screen.findByText('2 more this week')).toBeTruthy();
  expect(screen.getByRole('progressbar').getAttribute('aria-valuenow')).toBe('3');
});

test('a failed load is quiet rather than a second error box', async () => {
  // The season table above has its own error handling; a red box for a
  // secondary panel underneath it is noise.
  vi.mocked(api).mockRejectedValue(new Error('nope'));

  const { container } = render(<BadgeShelf />);

  await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalled());
  expect(container.querySelector('[role="alert"]')).toBeNull();
});
