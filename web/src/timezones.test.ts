/** Timezones in words (review §7). */
import { expect, test } from 'vitest';

import { zoneChoices, zoneLabel } from './timezones';

const SUMMER = new Date('2026-07-01T12:00:00Z');

test('a zone is its name, a city and its offset', () => {
  expect(zoneLabel('America/Los_Angeles', SUMMER)).toBe('Pacific Time — Los Angeles (UTC−7)');
  expect(zoneLabel('America/New_York', SUMMER)).toBe('Eastern Time — New York (UTC−4)');
  expect(zoneLabel('UTC', SUMMER)).toBe('UTC — Coordinated Universal Time');
});

test('the usual zones come first, and the rest by name', () => {
  const { common, rest } = zoneChoices(
    ['Europe/Paris', 'America/Los_Angeles', 'Asia/Tokyo', 'America/New_York', 'UTC'],
    SUMMER,
  );

  expect(common.map((z) => z.value)).toEqual(['America/New_York', 'America/Los_Angeles', 'UTC']);
  expect(rest.map((z) => z.value)).toEqual(['Europe/Paris', 'Asia/Tokyo']);
});
