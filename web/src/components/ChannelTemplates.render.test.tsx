// @vitest-environment jsdom
/** A template is confirmed before it is made (7.9): its name, its slides, then Create. */
import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';

import ChannelTemplates, { freeName } from './ChannelTemplates';

vi.mock('../api', () => ({ api: vi.fn() }));
vi.mock('../toast', () => ({ toast: vi.fn() }));

const { api } = await import('../api');

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation(async (path: string, init?: RequestInit) => {
    if (path === '/api/channels/eligible') {
      return {
        leaderboards: [{ id: 7, name: 'Deals board' }],
        competitions: [{ id: 3, name: 'Sprint', state: 'active' }],
        goals: [],
        people: [],
      } as never;
    }
    if (path === '/api/channels' && !init) return [{ name: 'Sales floor' }] as never;
    if (path === '/api/channels' && init?.method === 'POST') return { id: 12 } as never;
    return {} as never;
  });
});

test('says what it will make before making anything', async () => {
  const onMade = vi.fn();
  render(<ChannelTemplates onClose={() => {}} onMade={onMade} />);
  await act(async () => {
    await Promise.resolve();
  });

  fireEvent.click(screen.getByText('Sales floor'));

  // Taken already, so not a second "Sales floor".
  expect((screen.getByLabelText('Name') as HTMLInputElement).value).toBe('Sales floor 2');
  expect(screen.getByText('You already have a channel called “Sales floor”.')).toBeDefined();
  expect(screen.getByText('It will have 3 slides')).toBeDefined();
  expect(screen.getByText('Deals board')).toBeDefined();
  expect(screen.getByText('Sprint')).toBeDefined();
  expect(screen.getByText('Recent wins')).toBeDefined();
  // Nothing made yet.
  expect(vi.mocked(api).mock.calls.some(([, init]) => init?.method === 'POST')).toBe(false);

  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Create channel' }));
  });

  const posts = vi.mocked(api).mock.calls.filter(([, init]) => init?.method === 'POST');
  expect(posts[0]![0]).toBe('/api/channels');
  expect(JSON.parse(posts[0]![1]!.body as string)).toEqual({ name: 'Sales floor 2' });
  expect(posts.slice(1).map(([p]) => p)).toEqual([
    '/api/channels/12/screens',
    '/api/channels/12/screens',
    '/api/channels/12/screens',
  ]);
  expect(onMade).toHaveBeenCalledWith(12);
});

test('a free name counts on from 2', () => {
  expect(freeName('Lobby', [])).toBe('Lobby');
  expect(freeName('Lobby', ['lobby', 'Lobby 2'])).toBe('Lobby 3');
});
