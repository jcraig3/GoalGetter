// @vitest-environment jsdom
/**
 * The banner's timing, which is where its bugs live.
 *
 * The comparison itself is tested in `overtakes.test.ts`. What is left is when
 * a banner appears, how long it stays and — the one that bit during
 * development — that it does not survive the slide it is about.
 */
import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import OvertakeBanner from './OvertakeBanner';
import type { Entry } from './types';

function board(...names: string[]): Entry[] {
  return names.map((name, index) => ({
    rank: index + 1,
    entity_id: name.charCodeAt(0),
    entity_name: name,
    photo_digest: null,
    team_name: null,
    value: String(100 - index),
    movement: null,
  }));
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe('OvertakeBanner', () => {
  test('says nothing the first time a board is seen', () => {
    // There is no "before" yet. Announcing the current order as news would
    // greet every wall on startup with an overtake that never happened.
    render(<OvertakeBanner slideId={1} entries={board('A', 'B')} />);

    expect(screen.queryByRole('alert')).toBeNull();
  });

  test('announces a pass on the next update', () => {
    const { rerender } = render(
      <OvertakeBanner slideId={1} entries={board('A', 'B')} />,
    );

    rerender(<OvertakeBanner slideId={1} entries={board('B', 'A')} />);

    expect(screen.getByRole('alert').textContent).toContain('B passed A');
    expect(screen.getByRole('alert').textContent).toContain('1st');
  });

  test('does not repeat itself on the next poll', () => {
    // The snapshot advances even when nothing is announced, so the same
    // overtake cannot be re-announced every refresh for as long as the slide
    // stays up.
    const { rerender } = render(
      <OvertakeBanner slideId={1} entries={board('A', 'B')} />,
    );
    rerender(<OvertakeBanner slideId={1} entries={board('B', 'A')} />);
    act(() => void vi.advanceTimersByTime(10_000));

    rerender(<OvertakeBanner slideId={1} entries={board('B', 'A')} />);

    expect(screen.queryByRole('alert')).toBeNull();
  });

  test('clears itself after a while', () => {
    const { rerender } = render(
      <OvertakeBanner slideId={1} entries={board('A', 'B')} />,
    );
    rerender(<OvertakeBanner slideId={1} entries={board('B', 'A')} />);

    act(() => void vi.advanceTimersByTime(10_000));

    expect(screen.queryByRole('alert')).toBeNull();
  });

  test('never outlives the slide it is about', () => {
    // **The bug this catches** would put "B passed A" over the goal screen
    // that came after the board.
    const { rerender } = render(
      <OvertakeBanner slideId={1} entries={board('A', 'B')} />,
    );
    rerender(<OvertakeBanner slideId={1} entries={board('B', 'A')} />);
    expect(screen.getByRole('alert')).toBeDefined();

    rerender(<OvertakeBanner slideId={2} entries={board('C', 'D')} />);

    expect(screen.queryByRole('alert')).toBeNull();
  });

  test('compares a board with the last time that same board was up', () => {
    // **The whole design.** A board holds the wall for twenty seconds out of a
    // two-minute rotation, so almost every overtake happens while it is off
    // screen. Comparing against the last time the room could see it is the
    // question a room actually has.
    const { rerender } = render(
      <OvertakeBanner slideId={1} entries={board('A', 'B')} />,
    );

    // Away to another slide, and back to find the order changed.
    rerender(<OvertakeBanner slideId={2} entries={board('C', 'D')} />);
    rerender(<OvertakeBanner slideId={1} entries={board('B', 'A')} />);

    expect(screen.getByRole('alert').textContent).toContain('B passed A');
  });

  test('two boards keep separate memories', () => {
    const { rerender } = render(
      <OvertakeBanner slideId={1} entries={board('A', 'B')} />,
    );
    rerender(<OvertakeBanner slideId={2} entries={board('C', 'D')} />);

    // Board 2's own order is unchanged, whatever board 1 did.
    rerender(<OvertakeBanner slideId={2} entries={board('C', 'D')} />);

    expect(screen.queryByRole('alert')).toBeNull();
  });
});
