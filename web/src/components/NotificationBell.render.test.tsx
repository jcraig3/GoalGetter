// @vitest-environment jsdom
/** Clearing the bell (12.1): one, or all, each with an Undo. */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, test, vi } from 'vitest';

import type { Notification } from '../notifications';
import NotificationBell from './NotificationBell';

const note = (id: number, title: string): Notification => ({
  id,
  event_key: 'recognition',
  title,
  body: null,
  link_url: '/recognition',
  created_at: new Date().toISOString(),
  read_at: null,
  celebrated_at: null,
  celebrate: false,
  from_name: null,
});

const spies = {
  markRead: vi.fn(async () => {}),
  markAllRead: vi.fn(async () => {}),
  dismiss: vi.fn(async () => {}),
  dismissAll: vi.fn(async () => [1, 2]),
  restore: vi.fn(async () => {}),
};

vi.mock('../notifications', () => ({
  useNotifications: () => ({
    notifications: [note(1, 'Sam recognised you'), note(2, 'You hit your goal')],
    unread: 2,
    refresh: async () => {},
    markCelebrated: async () => {},
    ...spies,
  }),
}));

const toasts: { message: string; action?: { label: string; run: () => void } }[] = [];
vi.mock('../toast', () => ({
  toast: (message: string, _link: unknown, action?: { label: string; run: () => void }) =>
    toasts.push({ message, action }),
}));

beforeEach(() => {
  toasts.length = 0;
  Object.values(spies).forEach((spy) => spy.mockClear());
});

async function open() {
  render(
    <MemoryRouter>
      <NotificationBell />
    </MemoryRouter>,
  );
  await userEvent.click(screen.getByRole('button', { name: 'Notifications, 2 unread' }));
}

test('clearing one does not open it, and can be undone', async () => {
  await open();

  await userEvent.click(screen.getByRole('button', { name: 'Clear “Sam recognised you”' }));

  expect(spies.dismiss).toHaveBeenCalledWith(1);
  expect(spies.markRead).not.toHaveBeenCalled();
  await waitFor(() => expect(toasts[0]?.message).toBe('Cleared from your notifications'));
  toasts[0]!.action!.run();
  expect(spies.restore).toHaveBeenCalledWith([1]);
});

test('clear all says how many, and Undo brings back exactly those', async () => {
  await open();

  await userEvent.click(screen.getByRole('button', { name: 'Clear all' }));

  await waitFor(() => expect(toasts[0]?.message).toBe('Cleared 2 notifications'));
  toasts[0]!.action!.run();
  expect(spies.restore).toHaveBeenCalledWith([1, 2]);
});
