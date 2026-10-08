// @vitest-environment jsdom
/**
 * The dial on a goal screen.
 *
 * At zero it has to look empty. A dash of length zero with round caps still
 * paints a cap at each end, and two coloured dots on an empty dial read as a
 * target started — or finished (QA-18).
 */
import { render } from '@testing-library/react';
import { expect, test } from 'vitest';

import Gauge from './Gauge';
import { sampleSlide } from './sample';

function dialAt(percent: number) {
  const { container } = render(<Gauge slide={{ ...sampleSlide('goal'), percent }} />);
  return container.querySelectorAll('svg path');
}

test('an empty dial is only its track', () => {
  expect(dialAt(0)).toHaveLength(1);
});

test('any progress draws the fill over the track', () => {
  expect(dialAt(40)).toHaveLength(2);
});
