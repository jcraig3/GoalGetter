// @vitest-environment jsdom
/** The announcements dashboard: made once, sent whenever you like (Phase 25). */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, test, vi } from 'vitest';

import AnnouncementsDashboard from './AnnouncementsDashboard';

vi.mock('../api', () => ({
  api: vi.fn(),
  ApiError: class ApiError extends Error {
    constructor(_status: number, message: string) {
      super(message);
    }
  },
}));
vi.mock('../toast', () => ({ toast: vi.fn() }));
vi.mock('../confirm', () => ({ ask: vi.fn().mockResolvedValue(true) }));
const { api } = await import('../api');

const LUNCH = {
  id: 7,
  title: 'Lunch is here',
  body: null,
  hold_seconds: 20,
  background: { kind: 'solid', color: '#112233' },
  media_url: null,
  media_kind: null,
  media_start_seconds: null,
  sound_url: null,
  created_by_name: 'Admin',
  created_at: '2026-10-08T12:00:00Z',
  updated_at: '2026-10-08T12:00:00Z',
  times_sent: 2,
  last_sent_at: new Date(Date.now() - 3_600_000).toISOString(),
};

function sent() {
  return vi.mocked(api).mock.calls.filter(([path]) => String(path).endsWith('/send'));
}

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation((async (path: string) => {
    if (path === '/api/tv-announcements') return [LUNCH];
    if (path === '/api/tv-announcements/channels') return [{ id: 1, name: 'Lobby' }, { id: 2, name: 'Floor' }];
    return { channels: 0, everywhere: true };
  }) as never);
});

test('each saved announcement, how often it went out, and how long it holds', async () => {
  render(<AnnouncementsDashboard />);
  expect(await screen.findByText('Lunch is here')).toBeTruthy();
  expect(screen.getByText(/Sent 2 times · last 1 hour ago · 20s on screen/)).toBeTruthy();
});

test('send to every TV', async () => {
  render(<AnnouncementsDashboard />);
  await userEvent.click(await screen.findByRole('button', { name: 'Send' }));
  await userEvent.click(screen.getByRole('button', { name: 'Send now' }));
  await waitFor(() => expect(sent()).toHaveLength(1));
  expect(JSON.parse(String(sent()[0]![1]!.body))).toEqual({ channel_ids: null });
});

test('or to the channels picked', async () => {
  render(<AnnouncementsDashboard />);
  await userEvent.click(await screen.findByRole('button', { name: 'Send' }));
  await userEvent.click(screen.getByLabelText('Chosen channels'));
  const send = screen.getByRole('button', { name: 'Send now' }) as HTMLButtonElement;
  expect(send.disabled).toBe(true);
  await userEvent.click(await screen.findByLabelText('Floor'));
  await userEvent.click(send);
  await waitFor(() => expect(sent()).toHaveLength(1));
  expect(JSON.parse(String(sent()[0]![1]!.body))).toEqual({ channel_ids: [2] });
});

test('none yet: said, with what one might be', async () => {
  vi.mocked(api).mockImplementation((async () => []) as never);
  render(<AnnouncementsDashboard />);
  expect(await screen.findByText(/No announcements yet/)).toBeTruthy();
});
