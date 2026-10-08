import { describe, expect, test } from 'vitest';

import { clockWords, dayWords, describeSchedule, hhmm } from './RotationSchedule';

const always = { days: null, play_from: null, play_until: null, weight: 1 };

describe('how a slide schedule reads in the list (6.10)', () => {
  test('says nothing for a slide that always plays', () => {
    expect(describeSchedule(always)).toBeNull();
  });

  test('names weekdays and weekends rather than listing them', () => {
    expect(dayWords([4, 3, 2, 1, 0])).toBe('Weekdays');
    expect(dayWords([5, 6])).toBe('Weekends');
    expect(dayWords([0, 2])).toBe('Mon, Wed');
    expect(dayWords([0, 1, 2, 3, 4, 5, 6])).toBeNull();
  });

  test('puts the pieces together', () => {
    expect(
      describeSchedule({ days: [0, 1, 2, 3, 4], play_from: '09:00:00', play_until: '12:30:00', weight: 2 }),
    ).toBe('Weekdays · 9 am–12:30 pm · 2× a cycle');
    expect(describeSchedule({ ...always, play_from: '17:00:00' })).toBe('from 5 pm');
  });

  test('reads the clock the way people say it', () => {
    expect(clockWords('00:00')).toBe('12 am');
    expect(clockWords('12:00')).toBe('12 pm');
    expect(clockWords('19:05')).toBe('7:05 pm');
    expect(hhmm('07:00:00')).toBe('07:00');
    expect(hhmm(null)).toBe('');
  });
});
