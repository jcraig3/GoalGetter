// @vitest-environment jsdom
/**
 * Who won.
 *
 * **A settled contest is a different question from a running one**, and the
 * tests worth having are about that difference: the winner is the screen, the
 * table is gone, and nothing about a countdown survives.
 */
import { render, screen } from '@testing-library/react';
import { beforeAll, describe, expect, test } from 'vitest';

import WallScreen from './WallScreen';
import Champion from './Champion';
import { sampleSlide } from './sample';
import type { Slide } from './types';

beforeAll(() => {
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as never;
});

const champion = (over: Partial<Slide> = {}): Slide => ({
  ...sampleSlide('champion'),
  ...over,
});

describe('Champion', () => {
  test('the winner is the screen', () => {
    render(<Champion slide={champion()} />);

    expect(screen.getByText('Winner')).toBeDefined();
    expect(screen.getByText('Peter Parker')).toBeDefined();
  });

  test('the prize is there, because it is why anybody entered', () => {
    render(<Champion slide={champion()} />);

    expect(screen.getByText('Steak dinner')).toBeDefined();
  });

  test('two runners-up, not a table', () => {
    // A full table underneath would put the champion back in a list, which is
    // the screen this one exists to replace.
    render(<Champion slide={champion()} />);

    expect(screen.getByText('Clark Kent')).toBeDefined();
    expect(screen.getByText('Diana Prince')).toBeDefined();
    expect(screen.queryByText('Bruce Banner')).toBeNull();
  });

  test('says how many entered, when it was more than the podium', () => {
    render(<Champion slide={champion()} />);

    expect(screen.getByText('of 14 who entered')).toBeDefined();
  });

  test('says nothing about the field when the field was the podium', () => {
    // "of 3 who entered" under three names is arithmetic nobody needed.
    render(<Champion slide={champion({ total_entrants: 3 })} />);

    expect(screen.queryByText(/who entered/)).toBeNull();
  });

  test('initials when the winner has no photograph', () => {
    const { container } = render(<Champion slide={champion()} />);

    expect(screen.getByText('PP')).toBeDefined();
    expect(container.querySelector('img')).toBeNull();
  });

  test('a contest that settled with nobody in it says so', () => {
    // Rare, and a blank screen with a prize written on it would be worse.
    render(<Champion slide={champion({ entries: [] })} />);

    expect(screen.getByText(/No result to show/)).toBeDefined();
  });
});

describe('a competition screen once it settles', () => {
  test('becomes the winner screen', () => {
    render(<WallScreen slide={champion()} channelName="Floor" />);

    expect(screen.getByText('Winner')).toBeDefined();
  });

  test('and loses the countdown entirely', () => {
    // "0s left" beside a final result reads as a stopped clock rather than a
    // finished contest, and "Final result" was a label on a table that is no
    // longer there.
    render(<WallScreen slide={champion()} channelName="Floor" />);

    expect(screen.queryByText(/left/)).toBeNull();
    expect(screen.queryByText('Final result')).toBeNull();
  });

  test('while it is still running, the table stays', () => {
    render(
      <WallScreen slide={sampleSlide('competition')} channelName="Floor" />,
    );

    expect(screen.queryByText('Winner')).toBeNull();
    expect(screen.getByText('Richard Rider')).toBeDefined();
  });
});
