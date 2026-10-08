// @vitest-environment jsdom
/**
 * Choosing people out of hundreds by typing (review #1).
 *
 * What has to be true: typing narrows by name, email or team; two people with
 * one name are told apart; Enter chooses; many can be chosen as chips, a whole
 * team at once, or everybody matched; and the ranking puts the obvious match
 * first.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, test } from 'vitest';

import PeoplePicker from './PeoplePicker';
import { matchPeople, matchTeams, type PickPerson } from './peoplePick';

const PEOPLE: PickPerson[] = [
  { id: 1, full_name: 'Peter Parker', email: 'peter.p@acme.example', team_id: 1, team_name: 'Metropolis' },
  { id: 2, full_name: 'Peter Parker', email: 'pparker@acme.example', team_id: 2, team_name: 'Gotham' },
  { id: 3, full_name: 'Amy Peterson', email: 'amy@acme.example', team_id: 1, team_name: 'Metropolis' },
  { id: 4, full_name: 'Zoë Adams', email: 'zoe@acme.example', team_id: 1, team_name: 'Metropolis' },
  { id: 5, full_name: 'Carl Stone', email: 'carl@acme.example', team_id: null, team_name: null },
];

describe('matching', () => {
  test('a name that starts with it beats one that only contains it', () => {
    expect(matchPeople(PEOPLE, 'peter').map((p) => p.id)).toEqual([1, 2, 3]);
  });

  test('every word must match somewhere, so the team narrows it', () => {
    expect(matchPeople(PEOPLE, 'peter gotham').map((p) => p.id)).toEqual([2]);
  });

  test('accents do not stand in the way', () => {
    expect(matchPeople(PEOPLE, 'zoe').map((p) => p.id)).toEqual([4]);
  });

  test('a team is offered with the members not yet chosen', () => {
    expect(matchTeams(PEOPLE, 'met', new Set([3]))).toEqual([{ name: 'Metropolis', ids: [1, 4] }]);
  });
});

function One() {
  const [value, setValue] = useState<number | null>(null);
  return <PeoplePicker label="Who" people={PEOPLE} value={value} onChange={setValue} />;
}

function Many() {
  const [value, setValue] = useState<number[]>([]);
  return <PeoplePicker multiple label="Entrants" people={PEOPLE} value={value} onChange={setValue} />;
}

test('two people with one name are two different rows', async () => {
  render(<One />);

  await userEvent.type(screen.getByRole('combobox'), 'peter parker');

  expect(screen.getByText('Metropolis · peter.p@acme.example')).toBeDefined();
  expect(screen.getByText('Gotham · pparker@acme.example')).toBeDefined();
});

test('Enter chooses the highlighted person, who is then shown with a way to change', async () => {
  render(<One />);

  await userEvent.type(screen.getByRole('combobox'), 'carl{Enter}');

  expect(screen.getByText('Carl Stone')).toBeDefined();
  expect(screen.getByText('No team · carl@acme.example')).toBeDefined();
  await userEvent.click(screen.getByRole('button', { name: 'Change' }));
  expect(screen.getByRole('combobox')).toBeDefined();
});

test('several are chosen as chips, and one can be taken off again', async () => {
  render(<Many />);
  const box = screen.getByRole('combobox');

  await userEvent.type(box, 'carl{Enter}');
  await userEvent.type(box, 'amy{Enter}');

  expect(screen.getByRole('button', { name: 'Remove Carl Stone' })).toBeDefined();
  await userEvent.click(screen.getByRole('button', { name: 'Remove Carl Stone' }));
  expect(screen.queryByRole('button', { name: 'Remove Carl Stone' })).toBeNull();
  expect(screen.getByRole('button', { name: 'Remove Amy Peterson' })).toBeDefined();
});

test('a whole team in one go', async () => {
  render(<Many />);

  await userEvent.type(screen.getByRole('combobox'), 'metropolis');
  await userEvent.click(screen.getByRole('option', { name: 'Add everyone on Metropolis (3)' }));

  expect(screen.getAllByRole('button', { name: /^Remove / })).toHaveLength(3);
});

test('everybody the search found, in one go', async () => {
  render(<Many />);

  await userEvent.type(screen.getByRole('combobox'), 'peter');
  await userEvent.click(screen.getByRole('option', { name: 'Add all 3 matching “peter”' }));

  expect(screen.getAllByRole('button', { name: /^Remove / })).toHaveLength(3);
});

test('the list closes after a pick, and typing opens it again (8.3)', async () => {
  render(<Many />);
  const box = screen.getByRole('combobox');

  await userEvent.type(box, 'carl{Enter}');
  expect(screen.queryAllByRole('option')).toHaveLength(0);
  // Still focused, ready for the next name.
  expect(document.activeElement).toBe(box);

  await userEvent.type(box, 'am');
  expect(screen.getAllByRole('option').length).toBeGreaterThan(0);
});
