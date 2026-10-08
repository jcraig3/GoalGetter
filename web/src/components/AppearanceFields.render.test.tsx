// @vitest-environment jsdom
/**
 * One thing's own look, in the form that creates it.
 *
 * **The property worth protecting is that "unset" survives a visit.** Opening
 * the panel, reading what the defaults are and closing it again must leave the
 * item inheriting — if merely looking wrote every placeholder to the row, a
 * later change to the organization's brand would stop reaching anything anyone
 * had ever glanced at.
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeAll, describe, expect, test, vi } from 'vitest';

import AppearanceFields from './AppearanceFields';
import type { Appearance } from '../appearance';

beforeAll(() => {
  // The preview measures itself; jsdom has no ResizeObserver. See
  // `WallPreview.render.test.tsx`.
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as never;
});

const INHERITED = {
  logo: null,
  slogan: null,
  primary: '#6366f1',
  secondary: '#0f172a',
  accent: '#f59e0b',
  font: 'system',
  font_scale: 1,
  panel_opacity: 0.8,
  panel_blur: 0,
  panel_radius: 12,
  ranked_layout: 'list',
  row_count: 10,
  show_values: true,
  goal_layout: 'gauge',
  name_display: 'full',
  end_time_format: 'default',
  milestones: 'all',
  background: null,
} as Appearance;

function open() {
  fireEvent.click(screen.getByRole('button', { name: /own appearance/i }));
}

describe('AppearanceFields', () => {
  test('starts closed, so the questions that matter come first', () => {
    // A board form asks who is on it and what it measures. Eight optional
    // controls above those would bury them.
    render(
      <AppearanceFields
        kind="leaderboard"
        chosen={{}}
        inherited={INHERITED}
        onChange={() => {}}
      />,
    );

    expect(screen.queryByText('On a wall')).toBeNull();
  });

  test('opens already expanded when the item has a look of its own', () => {
    // Otherwise the only sign that a board is themed is a line of small text,
    // and somebody editing it changes the name and never sees the colour.
    render(
      <AppearanceFields
        kind="leaderboard"
        chosen={{ ranked_layout: 'podium' }}
        inherited={INHERITED}
        onChange={() => {}}
      />,
    );

    expect(screen.getByText('On a wall')).toBeDefined();
  });

  test('looking writes nothing', () => {
    const onChange = vi.fn();
    render(
      <AppearanceFields
        kind="leaderboard"
        chosen={{}}
        inherited={INHERITED}
        onChange={onChange}
      />,
    );

    open();

    expect(onChange).not.toHaveBeenCalled();
  });

  test('choosing sends only the chosen field', () => {
    // The row stays sparse: everything absent still follows the organization,
    // so changing the brand later reaches this board.
    const onChange = vi.fn();
    render(
      <AppearanceFields
        kind="leaderboard"
        chosen={{}}
        inherited={INHERITED}
        onChange={onChange}
      />,
    );
    open();

    fireEvent.change(screen.getByLabelText('Layout'), {
      target: { value: 'podium' },
    });

    expect(onChange).toHaveBeenCalledWith({ ranked_layout: 'podium' });
  });

  test('resetting removes the key rather than writing the default', () => {
    // Writing '#6366f1' back would pin this board to today's brand colour.
    const onChange = vi.fn();
    render(
      <AppearanceFields
        kind="leaderboard"
        chosen={{ primary: '#ff0000' }}
        inherited={INHERITED}
        onChange={onChange}
      />,
    );

    fireEvent.click(
      screen.getByRole('button', { name: /Reset Highlight colour/i }),
    );

    expect(onChange).toHaveBeenCalledWith({});
  });

  test('offers a dial to a goal and a podium to a board', () => {
    // The layouts are not interchangeable: a goal has one number and a board
    // has a ranking, so offering "podium" for a goal would be a setting that
    // cannot take effect.
    const { unmount } = render(
      <AppearanceFields
        kind="goal"
        chosen={{ goal_layout: 'gauge' }}
        inherited={INHERITED}
        onChange={() => {}}
      />,
    );
    expect(screen.getByText('Dial')).toBeDefined();
    expect(screen.queryByText('Podium')).toBeNull();
    unmount();

    render(
      <AppearanceFields
        kind="leaderboard"
        chosen={{ ranked_layout: 'list' }}
        inherited={INHERITED}
        onChange={() => {}}
      />,
    );
    expect(screen.getByText('Podium')).toBeDefined();
    expect(screen.queryByText('Dial')).toBeNull();
  });

  test('says what a field will do when it is left alone', () => {
    render(
      <AppearanceFields
        kind="leaderboard"
        chosen={{ primary: '#ff0000' }}
        inherited={INHERITED}
        onChange={() => {}}
      />,
    );

    expect(screen.getAllByText(/Following the default/).length).toBeGreaterThan(
      0,
    );
  });

  test('survives having nothing to inherit from', () => {
    // The organization request can fail or still be in flight. A form that
    // throws in that window is worse than one showing built-in defaults.
    expect(() =>
      render(
        <AppearanceFields
          kind="competition"
          chosen={{}}
          inherited={null}
          onChange={() => {}}
        />,
      ),
    ).not.toThrow();
  });
});
