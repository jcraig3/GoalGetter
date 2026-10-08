// @vitest-environment jsdom
/**
 * One person, large.
 *
 * **The cases worth testing are the thin ones.** A spotlight with a board and a
 * photograph draws itself; a spotlight of somebody with no photograph, no
 * numbers and no wins is the one that either reads as an employee-of-the-month
 * card or as a broken screen, and it is the one a fresh deployment shows first.
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, test } from 'vitest';

import Spotlight, { ordinal } from './Spotlight';
import { sampleSlide } from './sample';
import type { Slide } from './types';

const spotlight = (overrides: Partial<Slide> = {}): Slide => ({
  ...sampleSlide('spotlight'),
  ...overrides,
});

describe('Spotlight', () => {
  test('puts the person first', () => {
    render(<Spotlight slide={spotlight()} />);

    expect(screen.getByText('Peter Parker')).toBeDefined();
  });

  test('draws initials when there is no photograph', () => {
    // Most directories have photographs of some people and not others, so this
    // is the ordinary case rather than something gone wrong.
    const { container } = render(<Spotlight slide={spotlight()} />);

    expect(screen.getByText('PP')).toBeDefined();
    expect(container.querySelector('img')).toBeNull();
  });

  test('uses the caller’s url builder for the face', () => {
    // A television authenticates with the token in its own address; an editor
    // has a session. Neither belongs inside this component.
    const slide = spotlight({
      person: { ...spotlight().person!, photo_digest: 'abc123' },
    });

    const { container } = render(
      <Spotlight slide={slide} imageUrl={(d) => `/api/display/t/assets/${d}`} />,
    );

    expect(container.querySelector('img')?.getAttribute('src')).toBe(
      '/api/display/t/assets/abc123',
    );
  });

  test('says the rank the way a person would read it', () => {
    render(<Spotlight slide={spotlight()} />);

    expect(screen.getByText('1st')).toBeDefined();
    expect(screen.getByText('of 14')).toBeDefined();
  });

  test('shows a streak worth having', () => {
    render(<Spotlight slide={spotlight({ streak_days: 9 })} />);

    expect(screen.getByText('9')).toBeDefined();
    expect(screen.getByText('days running')).toBeDefined();
  });

  test('a streak of one is just today, so it is not announced', () => {
    // "1 day running" is a number dressed up as an achievement.
    render(<Spotlight slide={spotlight({ streak_days: 1 })} />);

    expect(screen.queryByText('days running')).toBeNull();
  });

  test('no streak at all is not a streak of zero', () => {
    // A spotlight with no board has no metric to count one from, which is a
    // different statement from "they have done nothing".
    render(<Spotlight slide={spotlight({ streak_days: null })} />);

    expect(screen.queryByText('days running')).toBeNull();
  });

  test('a person with no numbers is still a screen', () => {
    // The employee-of-the-month card: a face and a name. Without this it
    // renders as a heading over empty space.
    render(
      <Spotlight
        slide={spotlight({ stats: [], streak_days: null, achievements: [] })}
      />,
    );

    expect(screen.getByText('Peter Parker')).toBeDefined();
    expect(screen.getByText('Account Executive · Enterprise')).toBeDefined();
  });

  test('renders nothing rather than throwing when there is nobody', () => {
    // A slide kind this build does not have data for must not take the wall
    // down with it.
    const { container } = render(<Spotlight slide={spotlight({ person: null })} />);

    expect(container.textContent).toBe('');
  });
});

describe('ordinal', () => {
  test('the ordinary suffixes', () => {
    expect(ordinal(1)).toBe('1st');
    expect(ordinal(2)).toBe('2nd');
    expect(ordinal(3)).toBe('3rd');
    expect(ordinal(4)).toBe('4th');
  });

  test('the teens, which every naive version gets wrong', () => {
    expect(ordinal(11)).toBe('11th');
    expect(ordinal(12)).toBe('12th');
    expect(ordinal(13)).toBe('13th');
  });

  test('and the twenties, which the fix for the teens can break', () => {
    expect(ordinal(21)).toBe('21st');
    expect(ordinal(22)).toBe('22nd');
    expect(ordinal(111)).toBe('111th');
  });
});
