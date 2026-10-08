// @vitest-environment jsdom
/**
 * Two to four boards, side by side.
 *
 * **The property worth protecting is that each panel keeps its own units.** Two
 * boards on one slide are still two metrics, and a shared format would print
 * seven deals as $7.00 — a screen that looks right and says something false.
 */
import { render, screen, within } from '@testing-library/react';
import { describe, expect, test } from 'vitest';

import Comparison from './Comparison';
import { sampleSlide } from './sample';
import type { Panel, Slide } from './types';

const comparison = (overrides: Partial<Slide> = {}): Slide => ({
  ...sampleSlide('comparison'),
  ...overrides,
});

const panel = (over: Partial<Panel> = {}): Panel => ({
  title: 'Calls',
  subtitle: 'Calls made · March',
  entries: [
    {
      rank: 1,
      entity_id: 1,
      entity_name: 'Peter Parker',
      photo_digest: null,
      team_name: 'Enterprise',
      value: '40',
      movement: null,
    },
  ],
  total_entrants: 1,
  entity_type: 'user',
  unit: 'count',
  decimal_places: 0,
  direction: 'higher_is_better',
  ...over,
});

describe('Comparison', () => {
  test('draws a column per board', () => {
    const { container } = render(<Comparison slide={comparison()} />);

    expect(container.querySelectorAll('section')).toHaveLength(2);
    expect(screen.getByText('Calls')).toBeDefined();
    expect(screen.getByText('Deals')).toBeDefined();
  });

  test('each panel formats by its own units', () => {
    // The failure this catches prints seven deals as $7.00 — a screen that
    // looks right and says something false.
    const slide = comparison({
      panels: [
        panel({ title: 'Calls', unit: 'count' }),
        panel({ title: 'Deals', unit: 'currency', entries: panel().entries }),
      ],
    });

    const { container } = render(<Comparison slide={slide} />);
    const [calls, deals] = Array.from(container.querySelectorAll('section'));

    expect(within(calls!).getByText('40')).toBeDefined();
    expect(within(deals!).queryByText('40')).toBeNull();
  });

  test('a column with nobody in it says so', () => {
    // A new metric with no facts yet is a real state, and blank space reads as
    // a bug rather than as an answer.
    const slide = comparison({
      panels: [panel(), panel({ title: 'Deals', entries: [] })],
    });

    render(<Comparison slide={slide} />);

    expect(screen.getByText('Nobody yet.')).toBeDefined();
  });

  test('two columns for two boards, four for four', () => {
    // Explicit rather than auto-fit: auto-fit reflows two wide boards onto one
    // column on a screen with room for both.
    const { container } = render(
      <Comparison
        slide={comparison({
          panels: [panel(), panel(), panel(), panel()],
        })}
      />,
    );

    const grid = container.firstElementChild as HTMLElement;
    expect(grid.style.gridTemplateColumns).toBe('repeat(4, minmax(0, 1fr))');
  });

  test('renders nothing rather than an empty grid', () => {
    const { container } = render(<Comparison slide={comparison({ panels: [] })} />);

    expect(container.textContent).toBe('');
  });

  test('uses the caller’s url builder for faces', () => {
    const slide = comparison({
      panels: [
        panel({
          entries: [{ ...panel().entries[0]!, photo_digest: 'abc123' }],
        }),
      ],
    });

    const { container } = render(
      <Comparison slide={slide} imageUrl={(d) => `/api/display/t/assets/${d}`} />,
    );

    expect(container.querySelector('img')?.getAttribute('src')).toBe(
      '/api/display/t/assets/abc123',
    );
  });

  test('the sample data disagrees with itself on purpose', () => {
    // The point of the screen is the person who is top of one board and not
    // the other. Sample panels in the same order hide exactly that.
    const slide = sampleSlide('comparison');
    const first = slide.panels.map((p) => p.entries[0]?.entity_name);

    expect(first[0]).not.toBe(first[1]);
  });
});
