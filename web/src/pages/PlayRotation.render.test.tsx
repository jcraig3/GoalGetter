// @vitest-environment jsdom
/** "Play rotation" in the channel editor (8.5): each slide for its own time. */
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { sampleSlide } from '../components/wall/sample';
import { PlayRotation } from './ChannelEditor';

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

const SLIDES = [
  { slide: sampleSlide('leaderboard', 'Deals board'), dwell: 10, label: 'Deals board' },
  { slide: sampleSlide('achievements', 'Recent wins'), dwell: 5, label: 'Recent wins' },
];

test('moves on after each slide’s own time, and can be paused', async () => {
  render(<PlayRotation slides={SLIDES} onClose={() => {}} />);
  expect(screen.getByText('1 of 2 · Deals board · 10s')).toBeDefined();

  await act(async () => {
    await vi.advanceTimersByTimeAsync(10_000);
  });
  expect(screen.getByText('2 of 2 · Recent wins · 5s')).toBeDefined();

  fireEvent.click(screen.getByRole('button', { name: 'Pause' }));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(20_000);
  });
  expect(screen.getByText('2 of 2 · Recent wins · 5s')).toBeDefined();

  fireEvent.click(screen.getByRole('button', { name: 'Next' }));
  expect(screen.getByText('1 of 2 · Deals board · 10s')).toBeDefined();
});
