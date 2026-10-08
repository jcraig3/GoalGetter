// @vitest-environment jsdom
/**
 * The race track, as a room sees it.
 *
 * The arithmetic is tested on the server, where it lives. What is worth a
 * render test is how it is *said*: a race with a finish line draws a flag and
 * crowns whoever crossed it; a race without one says it is measured against the
 * leader and crowns nobody; and a piece sits where the server put it.
 */
import { render, screen } from '@testing-library/react';
import { expect, test } from 'vitest';

import Race, { MAX_LANES } from './Race';
import { sampleSlide } from './sample';
import type { Slide } from './types';

function slide(overrides: Partial<Slide> = {}): Slide {
  return {
    ...sampleSlide('leaderboard'),
    unit: 'count',
    decimal_places: 0,
    entries: [
      { rank: 1, entity_id: 1, entity_name: 'Peter Parker', team_name: null,
        value: '50', movement: null, progress: 1, finished: true, token: 'car' },
      { rank: 2, entity_id: 2, entity_name: 'Clark Kent', team_name: null,
        value: '25', movement: null, progress: 0.5, finished: false, token: null },
    ],
    ...overrides,
  };
}

test('a finish line is named, and drawn as a flag', () => {
  const { container } = render(<Race slide={slide({ finish_line: '50' })} />);

  expect(screen.getByText(/Finish/)).toBeDefined();
  expect(container.querySelectorAll('.chequered')).toHaveLength(2);
});

test('whoever crossed it is marked', () => {
  const { container } = render(<Race slide={slide({ finish_line: '50' })} />);

  expect(container.querySelectorAll('li.ring-gold')).toHaveLength(1);
});

test('without a line it says it is measured against the leader', () => {
  // So nobody reads the front-runner as having crossed a line that was never
  // drawn — and no flag is drawn either.
  const { container } = render(
    <Race slide={slide({ finish_line: null, entries: slide().entries.map((e) => ({ ...e, finished: false })) })} />,
  );

  expect(screen.getByText('Measured against the leader')).toBeDefined();
  expect(container.querySelector('.chequered')).toBeNull();
});

test('a piece sits where the server put it', () => {
  const { container } = render(<Race slide={slide()} />);

  const pieces = [...container.querySelectorAll<HTMLElement>('li [style*="left"]')];
  expect(pieces.map((p) => p.style.left)).toEqual(['100%', '50%']);
});

test('each person brings their own piece, and a face by default', () => {
  const { container } = render(<Race slide={slide()} />);

  expect(container.querySelector('[data-token="car"]')).not.toBeNull();
  // Clark chose nothing: his initials, in his own colour.
  expect(screen.getByText('CK')).toBeDefined();
});

test('a piece wears the ring its owner bought', () => {
  // The economy showing up on the game board.
  const entries = slide().entries.map((e, i) => (i === 0 ? { ...e, ring: '#f5b301' } : e));
  const { container } = render(<Race slide={slide({ entries })} />);

  expect(container.querySelector('[data-token="car"] path')?.getAttribute('fill')).toBe('#f5b301');
});

test('eight lanes at most, whatever the row count', () => {
  // Past eight the lanes are too thin to tell apart from three metres.
  const many = Array.from({ length: 12 }, (_, i) => ({
    rank: i + 1, entity_id: i + 1, entity_name: `Agent ${i + 1}`, team_name: null,
    value: String(100 - i), movement: null, progress: (100 - i) / 100, finished: false,
  }));

  const { container } = render(<Race slide={slide({ entries: many })} rows={20} />);

  expect(container.querySelectorAll('li')).toHaveLength(MAX_LANES);
});

test('scores can be hidden, like every ranked layout', () => {
  render(<Race slide={slide()} showValues={false} />);

  expect(screen.queryByText('50')).toBeNull();
});

test('nobody on the board says so', () => {
  render(<Race slide={slide({ entries: [] })} />);

  expect(screen.getByText('Nobody has scored yet.')).toBeDefined();
});
