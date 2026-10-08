// @vitest-environment jsdom
/**
 * What a wall actually honours.
 *
 * **These exist because most of the Appearance tab did nothing.** The settings
 * were stored, validated, inherited and previewed, and the television read
 * exactly two of them. A test per setting is the only thing that keeps "it is
 * in the model" from being mistaken for "it works".
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, test } from 'vitest';

import WallScreen from './WallScreen';
import { sampleSlide } from './sample';
import type { Slide } from './types';

const slide = (over: Partial<Slide> = {}): Slide => ({
  ...sampleSlide('leaderboard'),
  ...over,
});

const contest = (appearance: Record<string, unknown>): Slide => ({
  ...sampleSlide('competition'),
  ends_at: new Date(Date.now() + 1000 * 60 * 60 * 50).toISOString(),
  appearance: appearance as Slide['appearance'],
});

describe('what a wall honours', () => {
  test('the slogan, which used to be editable and rendered nowhere', () => {
    render(
      <WallScreen
        slide={slide({ appearance: { slogan: 'Always be closing' } })}
        channelName="Main floor"
      />,
    );

    expect(screen.getByText('Always be closing')).toBeDefined();
  });

  test('no slogan means no empty line', () => {
    const { container } = render(
      <WallScreen slide={slide({ appearance: {} })} channelName="Main floor" />,
    );

    expect(container.textContent).not.toContain('undefined');
  });

  test('the deadline format, in each of its four answers', () => {
    const { unmount } = render(
      <WallScreen
        slide={contest({ end_time_format: 'simple' })}
        channelName="Main floor"
      />,
    );
    expect(screen.getByText('2 days left')).toBeDefined();
    unmount();

    render(
      <WallScreen
        slide={contest({ end_time_format: 'default' })}
        channelName="Main floor"
      />,
    );
    // A regex, not the exact string: the milliseconds between building the
    // slide and rendering it decide whether the hours round to 1 or 2, and a
    // test that fails on timing teaches nothing.
    expect(screen.getByText(/^2d \d+h left$/)).toBeDefined();
  });

  test('"off" removes the countdown rather than emptying it', () => {
    // An empty element still takes a line, and a blank space where a clock was
    // reads as a broken clock.
    render(
      <WallScreen
        slide={contest({ end_time_format: 'off' })}
        channelName="Main floor"
      />,
    );

    expect(screen.queryByText(/left/)).toBeNull();
  });

  test('the slide’s own layout, not a prop', () => {
    // The appearance chain is resolved on the server; the props exist only so
    // an unsaved edit can be previewed.
    const { container } = render(
      <WallScreen
        slide={slide({ appearance: { ranked_layout: 'podium' } })}
        channelName="Main floor"
      />,
    );

    // The podium draws medal-coloured steps; the list does not.
    expect(container.querySelector('.border-gold')).not.toBeNull();
  });

  test('an unsaved edit in a preview wins over what the server resolved', () => {
    // The preview merges the edit onto the slide rather than passing it
    // beside — one place decides how a wall is drawn, so there is nothing for
    // the two renderers to drift apart on.
    const server = slide({ appearance: { ranked_layout: 'podium' } });
    const edited = {
      ...server,
      appearance: { ...server.appearance, ranked_layout: 'list' },
    };

    const { container } = render(
      <WallScreen slide={edited} channelName="Main floor" />,
    );

    expect(container.querySelector('.border-gold')).toBeNull();
  });

  test('an unrecognised layout falls back rather than blanking', () => {
    // An older screen, a newer server, a typo in a seed file: none of them
    // should empty a television nobody is standing next to.
    render(
      <WallScreen
        slide={slide({
          appearance: { ranked_layout: 'hexagon' } as Slide['appearance'],
        })}
        channelName="Main floor"
      />,
    );

    expect(screen.getByText('Peter Parker')).toBeDefined();
  });
});
