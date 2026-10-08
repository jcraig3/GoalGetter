/** Archiving asks only when a TV would lose it (P3-2). */
import { beforeEach, expect, test, vi } from 'vitest';

import { archiveQuestion } from './wallUse';

vi.mock('./api', () => ({ api: vi.fn() }));
const { api } = await import('./api');

beforeEach(() => {
  vi.mocked(api).mockReset();
});

test('names the channels it leaves', async () => {
  vi.mocked(api).mockResolvedValue([{ channel_id: 1, channel_name: 'Sales floor', slides: 1 }] as never);
  expect(await archiveQuestion('leaderboard', 7, 'Deals board')).toBe(
    'Archive “Deals board”?\n\nIt stops playing on Sales floor (1 slide). Restore it to bring it back.',
  );
});

test('asks nothing when it is on no TV', async () => {
  vi.mocked(api).mockResolvedValue([] as never);
  expect(await archiveQuestion('goal', 3, 'Calls')).toBeNull();
});
