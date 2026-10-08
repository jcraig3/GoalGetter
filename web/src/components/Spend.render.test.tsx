// @vitest-environment jsdom
/**
 * The shop and the wheel, as somebody about to spend reads them.
 *
 * The properties worth a render test are the ones that decide whether spending
 * is honest: the odds are on the screen before a spin, a spin cannot be started
 * without the points for it, the result is announced to a screen reader as well
 * as drawn, and the page says that spending never moves the table — because
 * that is the worry that would stop anybody pressing Buy.
 */
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import PrizeWheel from './PrizeWheel';
import Shop from './Shop';

vi.mock('../api', () => ({
  api: vi.fn(),
  ApiError: class extends Error {},
}));

const { api } = await import('../api');

beforeEach(() => {
  vi.mocked(api).mockReset();
  // Reduced motion, so the result arrives without waiting out the animation —
  // which is also the behaviour being tested for people who ask for it.
  window.matchMedia = vi.fn().mockReturnValue({ matches: true }) as never;
});

afterEach(() => {
  vi.useRealTimers();
});

const SHOP = {
  wallet: 250,
  items: [
    { id: 1, name: 'Gold ring', kind: 'ring', value: '#f5b301', price: 300,
      enabled: true, owned: false, equipped: false, owners: 0 },
    { id: 2, name: 'Blue ring', kind: 'ring', value: '#2255ff', price: 100,
      enabled: true, owned: true, equipped: true, owners: 1 },
  ],
};

test('the shop says spending never moves you on the table', async () => {
  vi.mocked(api).mockResolvedValue(SHOP as never);
  render(<Shop />);

  expect(await screen.findByText(/never moves you on the season table/)).toBeTruthy();
});

test('something you cannot afford says how far short', async () => {
  // A disabled button with no reason is a puzzle.
  vi.mocked(api).mockResolvedValue(SHOP as never);
  render(<Shop />);

  const button = await screen.findByRole('button', { name: '50 short' });

  expect((button as HTMLButtonElement).disabled).toBe(true);
});

test('what you own offers wearing rather than buying', async () => {
  vi.mocked(api).mockResolvedValue(SHOP as never);
  render(<Shop />);

  const wearing = await screen.findByRole('button', { name: 'Wearing' });

  expect(wearing.getAttribute('aria-pressed')).toBe('true');
});

const WHEEL = {
  enabled: true,
  spin_cost: 100,
  wallet: 500,
  segments: [
    { id: 1, label: 'So close', kind: 'nothing', points: 0, chance: 0.975, stock: null },
    { id: 2, label: 'Long lunch', kind: 'prize', points: 0, chance: 0.025, stock: 2 },
  ],
  recent: [],
};

test('the odds are on the screen before anybody spins', async () => {
  // A wheel whose odds are hidden is a slot machine.
  vi.mocked(api).mockResolvedValue(WHEEL as never);
  render(<PrizeWheel />);

  expect(await screen.findByText('1 in 40')).toBeTruthy();
  expect(screen.getByText('98%')).toBeTruthy();
  expect(screen.getByText('2 left')).toBeTruthy();
});

test('a spin cannot be started without the points for it', async () => {
  vi.mocked(api).mockResolvedValue({ ...WHEEL, wallet: 40 } as never);
  render(<PrizeWheel />);

  const button = await screen.findByRole('button', { name: '60 short of a spin' });

  expect((button as HTMLButtonElement).disabled).toBe(true);
});

test('the result is announced as well as drawn', async () => {
  vi.mocked(api).mockImplementation((path: string, init?: RequestInit) => {
    if (path === '/api/points/wheel/spin' && init?.method === 'POST') {
      return Promise.resolve({
        id: 9, label: 'Long lunch', kind: 'prize', cost: 100, points_won: 0,
        given_at: null, created_at: '2028-02-01T10:00:00Z', prize_id: 2,
        winner_name: null,
      } as never);
    }
    return Promise.resolve(WHEEL as never);
  });
  render(<PrizeWheel />);

  await userEvent.click(await screen.findByRole('button', { name: 'Spin for 100 points' }));
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });

  const told = await screen.findByText(/You won Long lunch/);
  expect(told.getAttribute('aria-live')).toBe('polite');
});

test('a wheel that is not running says so rather than drawing an empty one', async () => {
  vi.mocked(api).mockResolvedValue({ ...WHEEL, enabled: false } as never);
  render(<PrizeWheel />);

  expect(await screen.findByText('The prize wheel is not running')).toBeTruthy();
  expect(screen.queryByRole('button', { name: /Spin/ })).toBeNull();
});
