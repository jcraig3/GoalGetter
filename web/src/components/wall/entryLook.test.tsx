// @vitest-environment jsdom
/** How a row on the wall is known (6.7): a team by its own colour and short name. */
import { render } from '@testing-library/react';
import { expect, test } from 'vitest';

import { avatarColour } from '../avatarColour';
import { FacePicture, isTeamRow, markColour, markLabel } from './entryLook';

// The shapes the server really sends: every row has `colour` and
// `short_name`, null on a person's. A fixture without them is how every
// photograph came to be drawn as a team logo.
const team = { entity_name: 'Metropolis Sales Team', colour: '#2563eb', short_name: 'MET', is_team: true };
const person = { entity_name: 'Peter Parker', colour: null, short_name: null, is_team: false };

test("a team row uses the team's colour and short name", () => {
  expect(isTeamRow(team)).toBe(true);
  expect(markColour(team)).toBe('#2563eb');
  expect(markLabel(team)).toBe('MET');
});

test('a team with neither set falls back to the usual colour and initials', () => {
  const plain = { entity_name: 'Sales Team', colour: null, short_name: null, is_team: true };
  expect(isTeamRow(plain)).toBe(true);
  expect(markColour(plain)).toBe(avatarColour('Sales Team'));
  expect(markLabel(plain)).toBe('ST');
});

test("a person's row is a person's, null fields and all", () => {
  expect(isTeamRow(person)).toBe(false);
  expect(markLabel(person)).toBe('PP');
});

test("a person's photograph fills its circle", () => {
  const { container } = render(<FacePicture entry={person} src="/p.jpg" className="size-14" />);
  const img = container.querySelector('img')!;
  expect(img.className).toContain('object-cover');
  expect(container.querySelector('[data-team-mark]')).toBeNull();
});

test("a team's logo sits whole inside a badge of its colour", () => {
  const { container } = render(<FacePicture entry={team} src="/l.png" className="size-14" />);
  const badge = container.querySelector<HTMLElement>('[data-team-mark]')!;
  expect(badge.className).toContain('size-14');
  expect(badge.style.backgroundColor).toBe('rgb(37, 99, 235)');
  // Inset by its own size, never by padding — see `FacePicture`.
  expect(badge.querySelector('img')!.className).toContain('object-contain');
});
