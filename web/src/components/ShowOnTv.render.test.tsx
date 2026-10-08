// @vitest-environment jsdom
/** "Show on a TV" finishes the job (review §5): the channels, which already play it, and Add. */
import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, test, vi } from 'vitest';

import { ShowOnTvDialog } from './ShowOnTv';

vi.mock('../api', () => ({ api: vi.fn() }));
vi.mock('../toast', () => ({ toast: vi.fn() }));

const { api } = await import('../api');
const { toast } = await import('../toast');

const board = (id: number) => ({ kind: 'leaderboard', leaderboard_id: id, goal_id: null, competition_id: null });

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation(async (path: string, init?: RequestInit) => {
    if (path === '/api/channels') {
      return [
        { id: 1, name: 'Sales floor', display_count: 2, screens: [board(7)] },
        { id: 2, name: 'Lobby', display_count: 0, screens: [board(3)] },
      ] as never;
    }
    if (path === '/api/displays') return [] as never;
    if (path === '/api/channels/2/screens' && init?.method === 'POST') {
      return { id: 2, name: 'Lobby', display_count: 0, screens: [board(3), board(7)] } as never;
    }
    throw new Error(`unexpected ${path}`);
  });
});

async function open() {
  render(
    <MemoryRouter>
      <ShowOnTvDialog kind="leaderboard" id={7} name="Deals board" onClose={() => {}} />
    </MemoryRouter>,
  );
  await screen.findByText('Sales floor');
}

test('says which channels already play it, and adds it to another in a click', async () => {
  await open();

  expect(screen.getByText('Already on')).toBeDefined();
  expect(screen.getByText('2 TVs')).toBeDefined();
  expect(screen.getByText('No TVs playing it yet')).toBeDefined();

  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
  });

  const call = vi.mocked(api).mock.calls.find(([p]) => p === '/api/channels/2/screens')!;
  expect(JSON.parse((call[1] as RequestInit).body as string)).toEqual({
    kind: 'leaderboard',
    leaderboard_id: 7,
  });
  expect(screen.getAllByText('Already on')).toHaveLength(2);
  expect(toast).toHaveBeenCalledWith('Deals board added to Lobby');
});

test('passes on the reason a channel refuses it', async () => {
  vi.mocked(api).mockImplementation(async (path: string, init?: RequestInit) => {
    if (path === '/api/channels') {
      return [{ id: 2, name: 'Dallas', display_count: 1, screens: [] }] as never;
    }
    if (path === '/api/displays') return [] as never;
    if (init?.method === 'POST') throw new Error('This board is for Phoenix.');
    throw new Error(`unexpected ${path}`);
  });
  render(
    <MemoryRouter>
      <ShowOnTvDialog kind="leaderboard" id={7} name="Deals board" onClose={() => {}} />
    </MemoryRouter>,
  );
  await screen.findByText('Dallas');

  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
  });

  expect(screen.getByRole('alert').textContent).toBe('This board is for Phoenix.');
});
