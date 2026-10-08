// @vitest-environment jsdom
/** A ranked slide with nothing in it yet (10.1): never a blank TV. */
import { render, screen } from '@testing-library/react';
import { expect, test } from 'vitest';

import { nobodyYet } from './NobodyYet';
import { sampleSlide } from './sample';
import WallScreen from './WallScreen';

function board(entries: { entity_id: number; entity_name: string; value: string }[], previous?: unknown) {
  const slide = sampleSlide('leaderboard', 'Deals board');
  return {
    ...slide,
    unit: 'currency',
    decimal_places: 2,
    entries: entries.map((e, i) => ({ ...slide.entries[0]!, ...e, rank: i + 1 })),
    previous: previous as never,
  };
}

test('an empty list board says so, with last month’s top three', () => {
  render(
    <WallScreen
      slide={board([], {
        label: 'September 2026',
        entries: [{ ...sampleSlide('leaderboard').entries[0]!, entity_id: 9, entity_name: 'Arthur Curry', value: '8450.00' }],
      })}
      channelName=""
    />,
  );

  expect(screen.getByText('Nobody has scored yet.')).toBeDefined();
  expect(screen.getByText('September 2026’s top place')).toBeDefined();
  expect(screen.getByText('Arthur Curry')).toBeDefined();
});

test('every row at zero is nothing yet — unless lower is better', () => {
  const zeros = board([{ entity_id: 1, entity_name: 'Ann', value: '0' }]);
  expect(nobodyYet(zeros)).toBe(true);
  expect(nobodyYet({ ...zeros, direction: 'lower_is_better' })).toBe(false);
  expect(nobodyYet(board([{ entity_id: 1, entity_name: 'Ann', value: '3' }]))).toBe(false);
});

test('old numbers say when they are from (10.6)', () => {
  render(<WallScreen slide={{ ...board([{ entity_id: 1, entity_name: 'Ann', value: '3' }]), as_of: 'Wed 23 Sep' }} channelName="" />);
  expect(screen.getByText('Numbers as of Wed 23 Sep')).toBeDefined();
});
