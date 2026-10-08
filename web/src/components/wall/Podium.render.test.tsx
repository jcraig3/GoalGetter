// @vitest-environment jsdom
/**
 * The top three on steps.
 *
 * Two things are worth pinning: the visual order is second-first-third while
 * the *reading* order stays first-second-third, and a board with fewer than
 * three entrants still draws — small teams are the common case on a new
 * deployment, and a wall nobody is standing next to must not go blank.
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, test } from 'vitest';

import Podium from './Podium';
import WallScreen from './WallScreen';
import { sampleSlide } from './sample';
import type { Slide } from './types';

/** The same slide, drawn the way the appearance chain resolved to. */
function drawnAs(slide: Slide, appearance: Record<string, string>): Slide {
  return { ...slide, appearance: { ...slide.appearance, ...appearance } };
}

function withEntrants(count: number): Slide {
  const slide = sampleSlide('leaderboard');
  return { ...slide, entries: slide.entries.slice(0, count) };
}

describe('Podium', () => {
  test('puts first in the middle, where the eye lands', () => {
    // The tallest block is central, so a room reads "who won" before it has
    // read a single name.
    const { container } = render(<Podium slide={withEntrants(3)} />);
    const shown = [...container.querySelectorAll('.w-64')].map(
      (step) => step.textContent,
    );

    expect(shown[0]).toContain('Clark Kent'); // 2nd
    expect(shown[1]).toContain('Peter Parker'); // 1st
    expect(shown[2]).toContain('Diana Prince'); // 3rd
  });

  test('lists everybody below the podium, quietly', () => {
    render(<Podium slide={withEntrants(6)} />);

    // Ranks four onwards are a list, not steps.
    expect(screen.getByText('Bruce Banner')).toBeDefined();
    expect(screen.getByText('Barry Allen')).toBeDefined();
  });

  test.each([1, 2, 3])('draws with %i entrant(s)', (count) => {
    // A two-person board is a real thing on a small team.
    expect(() => render(<Podium slide={withEntrants(count)} />)).not.toThrow();
  });

  test('says so rather than drawing an empty podium', () => {
    render(<Podium slide={withEntrants(0)} />);

    expect(screen.getByText(/Nobody has scored yet/i)).toBeDefined();
  });

  test('draws initials when somebody has no photograph', () => {
    render(<Podium slide={withEntrants(3)} />);

    expect(screen.getByText('PP')).toBeDefined();
  });
});

describe('choosing a layout', () => {
  test('a leaderboard is a list unless asked otherwise', () => {
    const { container } = render(
      <WallScreen slide={sampleSlide('leaderboard')} channelName="Floor" />,
    );

    expect(container.querySelector('ol')).not.toBeNull();
    expect(container.querySelector('.w-64')).toBeNull();
  });

  test('a leaderboard becomes a podium when asked', () => {
    const { container } = render(
      <WallScreen
        slide={drawnAs(sampleSlide('leaderboard'), { ranked_layout: 'podium' })}
        channelName="Floor"
      />,
    );

    expect(container.querySelector('.w-64')).not.toBeNull();
  });

  test('a competition becomes a podium too', () => {
    // The prize and the countdown stay; only the table underneath changes.
    render(
      <WallScreen
        slide={drawnAs(sampleSlide('competition'), { ranked_layout: 'podium' })}
        channelName="Floor"
      />,
    );

    expect(screen.getByText('Steak dinner')).toBeDefined();
    expect(screen.getByText('Peter Parker')).toBeDefined();
  });

  test('an unknown layout falls back rather than blanking the wall', () => {
    // A channel that sets a house style passes it to every screen, including
    // ones with no drawing for it. A wall nobody is standing next to must not
    // go empty over a mismatch.
    render(
      <WallScreen
        slide={drawnAs(sampleSlide('leaderboard'), { ranked_layout: 'hexagon' })}
        channelName="Floor"
      />,
    );

    expect(screen.getByText('Peter Parker')).toBeDefined();
  });

  test('a goal ignores a ranked layout entirely', () => {
    render(
      <WallScreen
        slide={drawnAs(sampleSlide('goal'), { ranked_layout: 'podium' })}
        channelName="Floor"
      />,
    );

    expect(screen.getByText('74%')).toBeDefined();
  });
});

describe('Gauge', () => {
  test('is what a goal gets by default', () => {
    const { container } = render(
      <WallScreen slide={sampleSlide('goal')} channelName="Floor" />,
    );

    expect(container.querySelector('svg')).not.toBeNull();
    expect(screen.getByText('74%')).toBeDefined();
  });

  test('shows the figure and what it is out of', () => {
    render(<WallScreen slide={sampleSlide('goal')} channelName="Floor" />);

    expect(screen.getByText(/of/)).toBeDefined();
  });

  test('writes the real percentage even past the target', () => {
    // **Clamped for the drawing, not for the label.** Somebody at 130% should
    // see 130% written down — that is the good news — while the needle stops at
    // the end of the dial, because there is no more dial.
    const slide = { ...sampleSlide('goal'), percent: 130, status: 'hit' };

    render(<WallScreen slide={slide} channelName="Floor" />);

    expect(screen.getByText('130%')).toBeDefined();
  });

  test('becomes one big number when asked', () => {
    const { container } = render(
      <WallScreen
        slide={drawnAs(sampleSlide('goal'), { goal_layout: 'big_number' })}
        channelName="Floor"
      />,
    );

    expect(container.querySelector('svg')).toBeNull();
  });

  test('a big number with no target shows just the figure', () => {
    // A dial with no denominator is a dial with no end, so the honest drawing
    // is the figure alone.
    const slide = { ...sampleSlide('goal'), target_value: null };

    render(
      <WallScreen
        slide={drawnAs(slide, { goal_layout: 'big_number' })}
        channelName="Floor"
      />,
    );

    expect(screen.queryByText(/^of /)).toBeNull();
  });

  test('an unrecognised goal layout still draws', () => {
    render(
      <WallScreen
        slide={sampleSlide('goal')}
        channelName="Floor"
      />,
    );

    expect(screen.getByText('74%')).toBeDefined();
  });
});
