// @vitest-environment jsdom
/** A two-entrant contest on the wall is two sides, not a table (8.5). */
import { render, screen } from '@testing-library/react';
import { expect, test } from 'vitest';

import { sampleSlide } from './sample';
import WallScreen from './WallScreen';

function contest(entrants: number) {
  const slide = sampleSlide('competition', 'Sprint');
  return {
    ...slide,
    unit: 'currency',
    decimal_places: 0,
    entries: slide.entries.slice(0, entrants).map((e, i) => ({
      ...e,
      value: i === 0 ? '1500' : '1000',
      photo_digest: null,
    })),
  };
}

test('two entrants face each other, with the gap under whoever is behind', () => {
  render(<WallScreen slide={contest(2)} channelName="" />);

  expect(screen.getByTestId('head-to-head')).toBeDefined();
  expect(screen.getByText('vs')).toBeDefined();
  expect(screen.getByText(/behind/).textContent).toBe('$500 behind');
});

test('three or more are still a table', () => {
  render(<WallScreen slide={contest(3)} channelName="" />);

  expect(screen.queryByTestId('head-to-head')).toBeNull();
});
