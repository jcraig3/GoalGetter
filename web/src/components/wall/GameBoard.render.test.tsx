// @vitest-environment jsdom
/**
 * The game boards beyond the race (6.8): each family draws its entrants with
 * the pieces they chose, their own face by default, in their colour; and the
 * picker can draw every piece.
 */
import { render, screen } from '@testing-library/react';
import { expect, test } from 'vitest';

import GameBoard, { FAMILY_LABELS, PIECE_LABELS, PieceArt } from './GameBoard';
import { sampleSlide } from './sample';

const slide = () => {
  const base = sampleSlide('leaderboard');
  return {
    ...base,
    entries: base.entries.map((e, i) => ({ ...e, token: i === 0 ? 'sailboat' : i === 1 ? 'rocket' : null })),
  };
};

test.each(['regatta', 'climb', 'space'] as const)('the %s board draws every entrant', (family) => {
  const { container } = render(<GameBoard slide={slide()} family={family} />);
  expect(container.querySelector(`[data-family="${family}"]`)).not.toBeNull();
  expect(screen.getAllByText('Peter Parker').length).toBeGreaterThan(0);
});

test("a piece is drawn when it is one of the family's own, and a face otherwise", () => {
  const { container } = render(<GameBoard slide={slide()} family="regatta" />);
  expect(container.querySelector('[data-token="sailboat"]')).not.toBeNull();
  // A rocket is not a boat: on the regatta its owner moves their face.
  expect(container.querySelector('[data-token="rocket"]')).toBeNull();
});

test('every piece the server offers can be drawn and named', () => {
  for (const token of ['car', 'truck', 'bike', 'sailboat', 'speedboat', 'duck', 'climber', 'goat', 'balloon', 'rocket', 'ufo', 'comet']) {
    const { container } = render(<PieceArt token={token} colour="#2563eb" />);
    expect(container.querySelector(`[data-token="${token}"]`), token).not.toBeNull();
    expect(PIECE_LABELS[token], token).toBeTruthy();
  }
  expect(Object.keys(FAMILY_LABELS)).toEqual(['race', 'regatta', 'climb', 'space']);
});
