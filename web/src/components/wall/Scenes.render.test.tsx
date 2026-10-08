// @vitest-environment jsdom
/**
 * Drawn backgrounds (6.9): every scene the server accepts can be drawn, moves
 * only when set to, and an unknown one still draws something.
 */
import { render } from '@testing-library/react';
import { expect, test } from 'vitest';

import Scene, { SCENE_NAMES } from './Scenes';

const colours = { base: '#0b1d33', mid: '#0e7490', top: '#38bdf8' };

// The server's list (`SCENES` in api/app/appearance.py), which this must match.
const SERVER = ['waves', 'mesh', 'bokeh', 'grid', 'lowpoly', 'skyline', 'confetti', 'contours'];

test('every scene the server accepts is drawn and named', () => {
  expect(Object.keys(SCENE_NAMES).sort()).toEqual([...SERVER].sort());
  for (const scene of SERVER) {
    const { container } = render(<Scene scene={scene} colours={colours} moving />);
    const root = container.querySelector(`[data-scene="${scene}"]`);
    expect(root, scene).not.toBeNull();
    expect(root!.children.length, scene).toBeGreaterThan(0);
  }
});

test('a scene moves only when it is set to', () => {
  const still = render(<Scene scene="confetti" colours={colours} moving={false} />);
  expect(still.container.innerHTML).not.toContain('gg-fall');
  const moving = render(<Scene scene="confetti" colours={colours} moving />);
  expect(moving.container.innerHTML).toContain('gg-fall');
});

test('a scene name this build does not know still draws one', () => {
  const { container } = render(<Scene scene="volcano" colours={colours} moving={false} />);
  expect(container.firstElementChild!.children.length).toBeGreaterThan(0);
});
