/** Dates said one way everywhere (Q2-29). Local times, so no zone in the inputs. */
import { describe, expect, test } from 'vitest';

import { clockTime, dateSpan, dayAndTime, dayAndTimeInFull, dayMonth, dayName } from './time';

const NOW = new Date('2026-10-02T09:00:00');

describe('a date', () => {
  test('is day then a short month, with a year only when it is not this one', () => {
    expect(dayMonth('2026-09-28T15:00:00', NOW)).toBe('28 Sep');
    expect(dayMonth('2025-12-31T15:00:00', NOW)).toBe('31 Dec 2025');
    expect(dayMonth('2026-09-28', NOW, true)).toBe('28 Sep 2026');
  });

  test('of a date-only value is that day, wherever the browser is', () => {
    // "2026-10-01" parsed as UTC midnight is 30 Sep in California.
    expect(dayMonth('2026-10-01', NOW)).toBe('1 Oct');
  });

  test('can say its weekday', () => {
    expect(dayName('2026-10-02T23:00:00', NOW)).toBe('Fri 2 Oct');
  });
});

describe('a time', () => {
  test('leaves off ":00" and says am or pm in lower case', () => {
    expect(clockTime('2026-10-02T23:00:00')).toBe('11 pm');
    expect(clockTime('2026-10-02T10:26:42')).toBe('10:26 am');
    expect(clockTime('2026-10-02T00:05:00')).toBe('12:05 am');
    expect(clockTime('2026-10-02T12:00:00')).toBe('12 pm');
  });

  test('goes after the day', () => {
    expect(dayAndTime('2026-10-02T23:00:00', NOW)).toBe('Fri 2 Oct, 11 pm');
    expect(dayAndTimeInFull('2026-10-02T17:00:00')).toBe('Friday 2 October, 5 pm');
  });
});

describe('a span', () => {
  test('says the month and year once', () => {
    expect(dateSpan('2026-10-01', '2026-10-02', NOW)).toBe('1 – 2 Oct');
    expect(dateSpan('2026-09-30', '2026-10-02', NOW)).toBe('30 Sep – 2 Oct');
    expect(dateSpan('2026-12-30', '2027-01-02', NOW)).toBe('30 Dec 2026 – 2 Jan 2027');
    expect(dateSpan('2027-03-01', '2027-03-31', NOW)).toBe('1 – 31 Mar 2027');
    expect(dateSpan('2026-10-02', '2026-10-02', NOW)).toBe('2 Oct');
  });
});
