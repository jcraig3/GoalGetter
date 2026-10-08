// @vitest-environment jsdom
/**
 * A wall on its side (6.11).
 *
 * jsdom does no layout, so the stage cannot measure itself here; the shape is
 * fixed through `shape`, the way the editor's preview fixes it. That the
 * stage measures the screen is `shapeOf`, tested on its own.
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, test } from 'vitest';

import Board from './Board';
import Comparison from './Comparison';
import Podium from './Podium';
import Spotlight from './Spotlight';
import WallPreview from './WallPreview';
import WallStage, { shapeOf, type WallShape } from './WallStage';
import { sampleSlide } from './sample';
import type { Slide } from './types';

function onA(shape: WallShape, children: React.ReactNode) {
  return render(
    <WallStage fill="parent" shape={shape}>
      {children}
    </WallStage>,
  );
}

const board = sampleSlide('leaderboard');

describe('the stage', () => {
  test('is portrait when the screen is taller than wide', () => {
    expect(shapeOf(1080, 1920)).toBe('portrait');
    expect(shapeOf(1920, 1080)).toBe('landscape');
    expect(shapeOf(1000, 1000)).toBe('landscape');
  });

  test('turns its 1920×1080 on its side', () => {
    const { container } = onA('portrait', null);
    const stage = container.querySelector<HTMLElement>('[data-wall-stage]')!;
    expect(stage.dataset.wallShape).toBe('portrait');
    expect([stage.style.width, stage.style.height]).toEqual(['1080px', '1920px']);
  });
});

describe('the list', () => {
  test('gives the top three a larger row on a portrait wall', () => {
    const { container } = onA('portrait', <Board slide={board} paged />);
    const heroes = [...container.querySelectorAll('[data-hero]')].map((row) => row.textContent);
    expect(heroes).toHaveLength(3);
    expect(heroes[0]).toContain('Peter Parker');
  });

  test('and nobody one on a landscape one', () => {
    const { container } = onA('landscape', <Board slide={board} paged />);
    expect(container.querySelectorAll('[data-hero]')).toHaveLength(0);
  });

  test('nor in a comparison panel, which is a small list wherever it is', () => {
    const { container } = onA('portrait', <Board slide={board} size="panel" />);
    expect(container.querySelectorAll('[data-hero]')).toHaveLength(0);
  });
});

describe('the podium', () => {
  test('is taller on a portrait wall, with bigger faces', () => {
    const tall = onA('portrait', <Podium slide={board} />).container;
    const first = tall.querySelector('[data-step="1"]')!;
    expect(first.className).toContain('w-72');
    expect(first.querySelector('.size-40')).not.toBeNull();
  });

  test('and as it was on a landscape one', () => {
    const wide = onA('landscape', <Podium slide={board} />).container;
    const first = wide.querySelector('[data-step="1"]')!;
    expect(first.className).toContain('w-64');
    expect(first.querySelector('.size-24')).not.toBeNull();
  });
});

describe('a comparison', () => {
  const panel = { ...board, title: 'Calls', subtitle: null };
  const withPanels = (count: number): Slide => ({
    ...board,
    kind: 'comparison',
    panels: Array.from({ length: count }, (_, i) => ({ ...panel, title: `Board ${i + 1}` })),
  });
  const columns = (shape: WallShape, count: number) =>
    onA(shape, <Comparison slide={withPanels(count)} />).container.querySelector<HTMLElement>('.grid')!
      .style.gridTemplateColumns;

  test('stacks on a portrait wall, and makes a square of four', () => {
    expect(columns('portrait', 2)).toBe('repeat(1, minmax(0, 1fr))');
    expect(columns('portrait', 4)).toBe('repeat(2, minmax(0, 1fr))');
    expect(columns('landscape', 4)).toBe('repeat(4, minmax(0, 1fr))');
  });
});

describe('the preview', () => {
  afterEach(() => window.localStorage.clear());

  test('can be turned, and remembers it', () => {
    const { container, unmount } = render(<WallPreview kind="leaderboard" turnable />);
    const box = () => container.querySelector<HTMLElement>('[data-preview-shape]')!;
    expect(box().dataset.previewShape).toBe('landscape');

    fireEvent.click(screen.getByRole('button', { name: 'Portrait' }));
    expect(box().dataset.previewShape).toBe('portrait');
    expect(box().className).toContain('aspect-[9/16]');
    unmount();

    // The next preview opens the same way up.
    const again = render(<WallPreview kind="leaderboard" turnable />).container;
    expect(again.querySelector<HTMLElement>('[data-preview-shape]')!.dataset.previewShape).toBe('portrait');
  });

  test('offers no switch where it is only a picture of a board', () => {
    window.localStorage.setItem('gg:preview-shape', 'portrait');
    const { container } = render(<WallPreview kind="leaderboard" />);
    expect(screen.queryByRole('button', { name: 'Portrait' })).toBeNull();
    expect(container.querySelector<HTMLElement>('[data-preview-shape]')!.dataset.previewShape).toBe('landscape');
  });
});

describe('a spotlight', () => {
  const slide = sampleSlide('spotlight');
  test('stacks the face above the name on a portrait wall', () => {
    const { container } = onA('portrait', <Spotlight slide={slide} />);
    expect(container.querySelector('[data-spotlight-shape="portrait"]')).not.toBeNull();
    expect(container.querySelector('.size-96')).not.toBeNull();
  });

  test('and sits beside it on a landscape one', () => {
    const { container } = onA('landscape', <Spotlight slide={slide} />);
    expect(container.querySelector('[data-spotlight-shape="landscape"]')).not.toBeNull();
    expect(container.querySelector('.size-64')).not.toBeNull();
  });
});
