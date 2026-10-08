// @vitest-environment jsdom
/** "Real numbers" beside a form (8.7): the form as saved, drawn by the wall's renderer. */
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import EditorPreview from './EditorPreview';
import { sampleSlide } from './sample';

vi.mock('../../api', () => ({ api: vi.fn() }));
const { api } = await import('../../api');

beforeEach(() => {
  vi.useFakeTimers();
  vi.mocked(api).mockReset();
});
afterEach(() => vi.useRealTimers());

const REAL = { path: '/api/leaderboards/draft-slide', body: { name: 'Deals', metric_id: 5 } };

test('asks for the form drawn with real numbers, and says so', async () => {
  vi.mocked(api).mockResolvedValue({ ...sampleSlide('leaderboard', 'Deals'), title: 'Deals for real' } as never);
  render(<EditorPreview kind="leaderboard" title="Deals" chosen={{}} inherited={null} real={REAL} />);

  fireEvent.click(screen.getByRole('button', { name: 'Real numbers' }));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(500);
  });

  expect(vi.mocked(api)).toHaveBeenCalledWith('/api/leaderboards/draft-slide', {
    method: 'POST',
    body: JSON.stringify(REAL.body),
  });
  expect(screen.getByText('Deals for real')).toBeDefined();
  expect(screen.getByText(/Real numbers, as a wall for everyone would draw this board now/)).toBeDefined();
});

test('falls back to the sample, saying why, when there is nothing to draw', async () => {
  vi.mocked(api).mockResolvedValue(null as never);
  render(<EditorPreview kind="goal" title="Calls" chosen={{}} inherited={null} real={REAL} />);

  fireEvent.click(screen.getByRole('button', { name: 'Real numbers' }));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(500);
  });

  expect(screen.getByText(/Nothing to show with real numbers yet/)).toBeDefined();
});

test('cannot be asked until the form says enough', () => {
  render(<EditorPreview kind="goal" title="Calls" chosen={{}} inherited={null} real={null} />);

  expect((screen.getByRole('button', { name: 'Real numbers' }) as HTMLButtonElement).disabled).toBe(true);
});
