// @vitest-environment jsdom
/**
 * Badge art (6.5): a drawn emblem by key, the organization's own picture by
 * `asset:<digest>`, and the medal for a key this build does not know.
 */
import { render } from '@testing-library/react';
import { expect, test } from 'vitest';

import { BADGE_MARKS, BadgeMark } from './badgeMarks';

test('every key draws an emblem, each with its own gradients', () => {
  const { container } = render(
    <>
      {Object.keys(BADGE_MARKS).map((key) => (
        <BadgeMark key={key} icon={key} />
      ))}
    </>,
  );
  expect(container.querySelectorAll('svg')).toHaveLength(Object.keys(BADGE_MARKS).length);
  // Ids unique per drawing, so two badges on one page do not share a finish.
  const ids = [...container.querySelectorAll('linearGradient')].map((g) => g.id);
  expect(new Set(ids).size).toBe(ids.length);
});

test("the organization's own picture is drawn as it was uploaded", () => {
  const digest = 'a'.repeat(64);
  const { container } = render(<BadgeMark icon={`asset:${digest}`} />);
  expect(container.querySelector('img')?.getAttribute('src')).toBe(`/api/images/${digest}`);
});

test('a key this build does not know still draws a badge', () => {
  const { container } = render(<BadgeMark icon="from_a_newer_version" />);
  expect(container.querySelector('svg')).not.toBeNull();
});
