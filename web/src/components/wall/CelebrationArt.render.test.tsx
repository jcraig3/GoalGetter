// @vitest-environment jsdom
/**
 * The trophy on a celebration (6.6): one for each kind of win, the same
 * confetti on every screen, and in step for a screen that joins late.
 */
import { render } from '@testing-library/react';
import { expect, test } from 'vitest';

import CelebrationArt, { pieceFor } from './CelebrationArt';

test('each kind of win has its own piece', () => {
  expect(pieceFor('goal.achieved')).toBe('cup');
  expect(pieceFor('goal.stretch.1')).toBe('cup');
  expect(pieceFor('competition.won')).toBe('laurel');
  expect(pieceFor('recognition')).toBe('medal');
  expect(pieceFor('achievement:big-deal')).toBe('rocket');
  expect(pieceFor('birthday')).toBe('cake');
  expect(pieceFor('work_anniversary')).toBe('rosette');
  expect(pieceFor(undefined)).toBe('cup');
});

test('every screen throws the same confetti for the same win', () => {
  const a = render(<CelebrationArt celebration={{ id: 'win:42', event_key: 'goal.achieved' }} />);
  const b = render(<CelebrationArt celebration={{ id: 'win:42', event_key: 'goal.achieved' }} />);
  const style = (r: typeof a) =>
    [...r.container.querySelectorAll('span')].map((s) => s.getAttribute('style'));
  expect(style(a)).toEqual(style(b));
});

test('a screen joining late is put at the same moment, not replayed', () => {
  const { container } = render(
    <CelebrationArt celebration={{ id: 'win:7', event_key: 'recognition' }} joinedAt={3} />,
  );
  const entrance = container.querySelector('[class*="gg-trophy-in"]') as HTMLElement;
  expect(entrance.style.animationDelay).toBe('-3s');
});
