/**
 * What a count is a count of: "48,210 deals" (§8).
 *
 * The same rules as `app/units.py` on the server, which writes the
 * announcements; the two must agree.
 */
import { expect, test } from 'vitest';

import { formatMetric, singular } from './MetricValue';

const deals = { unit: 'count', decimal_places: 0, unit_label: 'deals' };

test('a labelled count says what it counts', () => {
  expect(formatMetric('48210', deals)).toBe('48,210 deals');
  expect(formatMetric('0', deals)).toBe('0 deals');
});

test('one of them reads in the singular', () => {
  expect(formatMetric('1', deals)).toBe('1 deal');
  expect(singular('replies')).toBe('reply');
  expect(singular('glasses')).toBe('glass');
  expect(singular('NPS')).toBe('NPS');
});

test('bare leaves the noun to the number after it: "12 of 40 deals"', () => {
  expect(formatMetric('12', deals, 'USD', true)).toBe('12');
});

test('money, percentages and unlabelled counts are as they were', () => {
  expect(formatMetric('8450', { unit: 'currency', decimal_places: 0, unit_label: 'deals' })).toBe(
    '$8,450',
  );
  expect(formatMetric('73', { unit: 'percent', decimal_places: 0, unit_label: 'deals' })).toBe('73%');
  expect(formatMetric('48210', { unit: 'count', decimal_places: 0 })).toBe('48,210');
});

test('money drops ".00" on a whole amount and keeps real cents (P3-7)', () => {
  const money = { unit: 'currency', decimal_places: 2 };
  expect(formatMetric('500.0000', money)).toBe('$500');
  expect(formatMetric('250000', money)).toBe('$250,000');
  expect(formatMetric('4215.37', money)).toBe('$4,215.37');
  expect(formatMetric('0.5', money)).toBe('$0.50');
  // Rounded first: 9.999 at two places is $10, not "$10.00".
  expect(formatMetric('9.999', money)).toBe('$10');
});
