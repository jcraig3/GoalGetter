// @vitest-environment jsdom
/**
 * Hiding the printers and shared mailboxes a directory sync brought in.
 *
 * What has to be true: it says how many and why, hides through the People
 * page's own audited bulk action, lets an admin untick one they want to keep,
 * and is not there at all when there is nothing to suggest.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, test, vi } from 'vitest';

import NonPeopleReview from './NonPeopleReview';

vi.mock('../api', () => ({ api: vi.fn(), ApiError: class extends Error {} }));

const { api } = await import('../api');

const FOUND = [
  { id: 7, full_name: 'MFP 3100', email: 'mfp3100@acme.example', reason: 'a number in the name' },
  { id: 8, full_name: 'No Reply', email: 'noreply@acme.example', reason: 'a no-reply address' },
];

let suggested = FOUND;

beforeEach(() => {
  suggested = FOUND;
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation((async (url: string) => {
    if (url === '/api/users/bulk') {
      suggested = [];
      return { changed: 2, skipped: [] };
    }
    return suggested;
  }) as never);
});

const hides = () =>
  vi.mocked(api).mock.calls.filter(([url]) => url === '/api/users/bulk').map(([, init]) => JSON.parse(String(init?.body)));

test('says how many, and hides them all through the bulk action', async () => {
  const onHidden = vi.fn();
  render(<NonPeopleReview onHidden={onHidden} />);

  expect(await screen.findByText(/2 accounts look like a device, a test account or a shared mailbox/)).toBeDefined();
  await userEvent.click(screen.getByRole('button', { name: 'Hide all 2' }));

  await waitFor(() => expect(onHidden).toHaveBeenCalled());
  expect(hides()).toEqual([{ ids: [7, 8], action: 'hide' }]);
  // Nothing left to suggest, so nothing left on the page.
  expect(screen.queryByText(/look like a device/)).toBeNull();
});

test('the review says why each one was suggested, and one can be kept', async () => {
  render(<NonPeopleReview onHidden={vi.fn()} />);

  await userEvent.click(await screen.findByRole('button', { name: 'Review' }));
  expect(screen.getByText('a no-reply address')).toBeDefined();

  await userEvent.click(screen.getByRole('checkbox', { name: /No Reply/ }));
  await userEvent.click(screen.getByRole('button', { name: 'Hide 1 selected' }));

  await waitFor(() => expect(hides()).toEqual([{ ids: [7], action: 'hide' }]));
});

test('with nothing to suggest there is nothing on the page', async () => {
  suggested = [];
  const { container } = render(<NonPeopleReview onHidden={vi.fn()} />);

  await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalled());
  expect(container.textContent).toBe('');
});
