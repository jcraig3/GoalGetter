// @vitest-environment jsdom
/**
 * The wall, at desk size.
 *
 * **The property worth protecting is that this is the real screen.** A preview
 * built to imitate the wall would pass its own tests for ever while drifting
 * from what a TV actually shows, so these check that the same component renders
 * the same content — and that a preview needs no display token to exist, which
 * is what lets an editor show one before a channel has ever been created.
 */
import { render, screen } from '@testing-library/react';
import { beforeAll, describe, expect, test } from 'vitest';

import WallPreview from './WallPreview';
import WallScreen from './WallScreen';
import { sampleSlide } from './sample';

beforeAll(() => {
  // jsdom has no ResizeObserver, and the preview measures itself to decide the
  // scale. A stub that never fires leaves it at its initial scale, which is
  // fine: none of these assertions are about size.
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as never;
});

describe('WallPreview', () => {
  test('draws sample data when there is nothing connected yet', () => {
    // Designing a wall should not require a working integration. Without this,
    // every preview on a fresh deployment is an empty table.
    render(<WallPreview kind="leaderboard" />);

    expect(screen.getByText('Peter Parker')).toBeDefined();
    expect(screen.getByText('Revenue this month')).toBeDefined();
  });

  test('draws a real slide when given one', () => {
    const slide = { ...sampleSlide('leaderboard'), title: 'Closed deals' };

    render(<WallPreview slide={slide} />);

    expect(screen.getByText('Closed deals')).toBeDefined();
  });

  test('needs no display token', () => {
    // An editor has a session, not a token — and a channel being previewed may
    // not exist yet. Requiring one would put the preview behind the thing it
    // exists to help you create.
    expect(() => render(<WallPreview kind="goal" />)).not.toThrow();
  });

  test('isolates its stacking context, so a background has somewhere to sit', () => {
    // Without it the background's negative z-index sinks below the nearest
    // ancestor's own background and the photograph disappears entirely. The
    // wall carries the same class for the same reason.
    const { container } = render(<WallPreview kind="leaderboard" />);

    expect(container.querySelector('.isolate')).not.toBeNull();
  });

  test('is sixteen by nine, because that is what a television is', () => {
    // Anything else lets a layout look right here and overflow in the room.
    const { container } = render(<WallPreview />);

    expect(container.querySelector('.aspect-video')).not.toBeNull();
  });

  test.each(['leaderboard', 'goal', 'competition', 'achievements', 'message'])(
    'renders a %s without falling over',
    (kind) => {
      expect(() => render(<WallPreview kind={kind} />)).not.toThrow();
    },
  );

  test('shows the same content the wall would', () => {
    // **The extraction is the feature.** If these ever diverge, the preview has
    // become a second renderer and is no longer telling the truth.
    const slide = sampleSlide('leaderboard');

    const wall = render(<WallScreen slide={slide} channelName="Main floor" />)
      .container.textContent;
    const preview = render(
      <WallPreview slide={slide} channelName="Main floor" />,
    ).container.textContent;

    expect(preview).toBe(wall);
  });
});

describe('sample data', () => {
  test('gives a goal something to be a proportion of', () => {
    const slide = sampleSlide('goal');

    expect(slide.target_value).toBeTruthy();
    expect(slide.percent).toBeGreaterThan(0);
  });

  test('gives a competition a deadline in the future', () => {
    // A countdown that has already run out reads as a stopped clock, which is
    // not what the control being previewed looks like in use.
    const slide = sampleSlide('competition');

    expect(new Date(slide.ends_at!).getTime()).toBeGreaterThan(Date.now());
  });

  test('invents no faces', () => {
    // A preview showing photographs for people who do not exist is showing
    // something the real screen cannot.
    expect(
      sampleSlide('leaderboard').entries.every((e) => !e.photo_digest),
    ).toBe(true);
  });
});
