// @vitest-environment jsdom
/**
 * The admin inbox (6.2).
 *
 * What has to be true: each item says what is wrong and links to where it is
 * fixed; an item with a one-press fix offers it, and the list is asked again
 * afterwards rather than trusted; and an empty inbox says so plainly.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, test, vi } from 'vitest';

import Inbox, { type InboxItem } from './Inbox';

vi.mock('../api', () => ({ api: vi.fn(), ApiError: class extends Error {} }));

const { api } = await import('../api');

const TV: InboxItem = {
  kind: 'tv_disconnected',
  key: 'tv_disconnected:4',
  severity: 'todo',
  title: 'Lobby TV is showing a pairing code',
  detail: 'It was disconnected and is on, waiting.',
  link: '/channels',
  since: new Date(Date.now() - 3 * 3_600_000).toISOString(),
  action: { label: 'Reconnect', method: 'POST', path: '/api/displays/4/reconnect' },
};

const SOURCE: InboxItem = {
  kind: 'source_failing',
  key: 'source_failing:2',
  severity: 'problem',
  title: 'CRM is failing',
  detail: 'The password has expired.',
  link: '/integrations/sources/2',
  since: null,
  action: null,
};

let items: InboxItem[] = [];
let away: InboxItem[] = [];

beforeEach(() => {
  items = [SOURCE, TV];
  away = [];
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation((async (path: string, init?: { body?: string }) => {
    if (path === '/api/inbox') return { items, dismissed: away, count: items.length };
    if (path === TV.action!.path) {
      items = [SOURCE];
      return {};
    }
    const key = init?.body ? (JSON.parse(init.body) as { key: string }).key : '';
    if (path === '/api/inbox/dismiss') {
      away = items.filter((i) => i.key === key);
      items = items.filter((i) => i.key !== key);
      return null;
    }
    if (path === '/api/inbox/restore') {
      items = [...items, ...away.filter((i) => i.key === key)];
      away = away.filter((i) => i.key !== key);
      return null;
    }
    throw new Error(`unexpected ${path}`);
  }) as never);
});

function show() {
  render(
    <MemoryRouter>
      <Inbox />
    </MemoryRouter>,
  );
}

test('each item says what is wrong, and where to fix it', async () => {
  show();

  expect(await screen.findByText('CRM is failing')).toBeDefined();
  expect(screen.getByText('The password has expired.')).toBeDefined();
  expect(screen.getByText('Problem')).toBeDefined();
  expect(screen.getByText('Since 3 hours ago')).toBeDefined();
  const opens = screen.getAllByRole('link', { name: 'Open' });
  expect(opens[0]!.getAttribute('href')).toBe('/integrations/sources/2');
});

test('a one-press fix is offered, and the list is asked again after it', async () => {
  show();

  await userEvent.click(await screen.findByRole('button', { name: 'Reconnect' }));

  await waitFor(() => expect(screen.queryByText('Lobby TV is showing a pairing code')).toBeNull());
  expect(screen.getByText('CRM is failing')).toBeDefined();
});

test('not now puts one away, listed underneath, and it can be brought back (12.2)', async () => {
  show();
  await screen.findByText('CRM is failing');

  await userEvent.click(screen.getAllByRole('button', { name: 'Not now' })[0]!);

  const shelf = await screen.findByRole('button', { name: /1 notice was dismissed/ });
  expect(screen.queryByText('CRM is failing')).toBeNull();
  await userEvent.click(shelf);
  await userEvent.click(screen.getByRole('button', { name: 'Bring back' }));

  expect(await screen.findByText('CRM is failing')).toBeDefined();
  expect(screen.queryByRole('button', { name: /dismissed/ })).toBeNull();
});

test('an empty inbox says so', async () => {
  items = [];
  show();

  expect(await screen.findByText('Nothing needs you')).toBeDefined();
});
