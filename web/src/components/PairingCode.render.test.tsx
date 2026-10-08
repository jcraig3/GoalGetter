// @vitest-environment jsdom
/**
 * A pairing code on a television, new or disconnected (6.1).
 *
 * What has to be true: the code is shown; once an admin claims it the screen
 * is told its new address; and a code that lapses is replaced, not left on
 * screen looking valid.
 */
import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import PairingCode from './PairingCode';

vi.mock('../api', () => ({ api: vi.fn(), ApiError: class extends Error {} }));

const { api } = await import('../api');

let claimed = false;
let started = 0;

beforeEach(() => {
  vi.useFakeTimers();
  claimed = false;
  started = 0;
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation((async (path: string) => {
    if (path === '/api/displays/pair/start') {
      started += 1;
      return { code: started === 1 ? 'K7QX' : 'M3RT', secret: `s${started}`, expires_in_seconds: 600 };
    }
    if (path.startsWith('/api/displays/pair/')) {
      if (!claimed) throw new Error('204');
      return { url: '/display/fresh-token' };
    }
    throw new Error('unexpected');
  }) as never);
});

afterEach(() => vi.useRealTimers());

async function tick(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

test('shows the code, and hands over the new address once it is claimed', async () => {
  const onPaired = vi.fn();
  render(<PairingCode heading="This screen was disconnected" onPaired={onPaired} />);
  await tick(0);

  expect(screen.getByText('This screen was disconnected')).toBeDefined();
  expect(screen.getByText('K7QX')).toBeDefined();

  await tick(3_000);
  expect(onPaired).not.toHaveBeenCalled();

  claimed = true;
  await tick(3_000);
  expect(onPaired).toHaveBeenCalledWith('/display/fresh-token');
});

test('a code that lapses is replaced', async () => {
  render(<PairingCode onPaired={vi.fn()} />);
  await tick(0);
  expect(screen.getByText('K7QX')).toBeDefined();

  // A second at a time: the countdown re-arms itself from an effect.
  for (let second = 0; second <= 600; second += 1) await tick(1_000);

  expect(screen.getByText('M3RT')).toBeDefined();
});
