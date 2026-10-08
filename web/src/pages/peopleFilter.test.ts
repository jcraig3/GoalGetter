import { describe, expect, it } from 'vitest';

import {
  NO_TEAM,
  apply,
  isNarrowed,
  matchesSearch,
  NO_FILTERS,
  optionsFor,
  type Filterable,
} from './peopleFilter';

const person = (over: Partial<Filterable> = {}): Filterable => ({
  full_name: 'Sam Rivera',
  email: 'sam@acme.com',
  job_title: 'Account Executive',
  department: 'Sales',
  office_location: 'Phoenix',
  team_name: 'Phoenix Sales',
  ...over,
});

const PEOPLE = [
  person(),
  person({
    full_name: 'Alex Chen',
    email: 'alex@acme.com',
    job_title: 'SDR',
    department: 'Sales',
    office_location: 'Dallas',
  }),
  person({
    full_name: 'Jo Patel',
    email: 'jo@acme.com',
    job_title: 'Account Executive',
    department: 'Support',
    office_location: 'Phoenix',
  }),
];

describe('matchesSearch', () => {
  it('finds people by name and by email', () => {
    expect(matchesSearch(person(), 'rivera')).toBe(true);
    expect(matchesSearch(person(), 'sam@')).toBe(true);
  });

  it('ignores case and surrounding space', () => {
    expect(matchesSearch(person(), '  SAM  ')).toBe(true);
  });

  it('does not search titles or departments', () => {
    // **Deliberate.** Searching every field would surface everybody in Sales for
    // a search of "sal" — a list nobody asked for and cannot tell apart from the
    // one they did. The dropdowns are how you filter by department.
    expect(matchesSearch(person(), 'Sales')).toBe(false);
  });

  it('matches everybody when nothing is typed', () => {
    expect(matchesSearch(person(), '   ')).toBe(true);
  });
});

describe('apply', () => {
  it('keeps everybody when nothing is set', () => {
    expect(apply(PEOPLE, NO_FILTERS)).toHaveLength(3);
  });

  it('narrows on one field', () => {
    const found = apply(PEOPLE, { ...NO_FILTERS, department: 'Sales' });

    expect(found.map((p) => p.full_name)).toEqual(['Sam Rivera', 'Alex Chen']);
  });

  it('narrows on several at once rather than the last one winning', () => {
    // The three dropdowns have to compose. One resetting the others would make
    // "Account Executives in Phoenix" impossible to ask for.
    const found = apply(PEOPLE, {
      ...NO_FILTERS,
      job_title: 'Account Executive',
      office_location: 'Phoenix',
    });

    expect(found.map((p) => p.full_name)).toEqual(['Sam Rivera', 'Jo Patel']);
  });

  it('combines the search with the dropdowns', () => {
    const found = apply(PEOPLE, { ...NO_FILTERS, department: 'Sales', search: 'alex' });

    expect(found.map((p) => p.full_name)).toEqual(['Alex Chen']);
  });

  it('can produce nothing, which is a real answer', () => {
    expect(apply(PEOPLE, { ...NO_FILTERS, department: 'Legal' })).toEqual([]);
  });
});

describe('optionsFor', () => {
  it('offers each value once, sorted, with a count', () => {
    // The count feeds the dropdown's own display: "Sales · 2" answers *how much
    // will this narrow it* before the click rather than after.
    expect(optionsFor(PEOPLE, 'department')).toEqual([
      { value: 'Sales', people: 2 },
      { value: 'Support', people: 1 },
    ]);
  });

  it('folds case together and keeps the first spelling seen', () => {
    const found = optionsFor(
      [person({ department: 'Sales' }), person({ department: 'sales' })],
      'department',
    );

    expect(found).toEqual([{ value: 'Sales', people: 2 }]);
  });

  it('leaves blanks out', () => {
    // "" already means *any* at the top of the dropdown. Offering it again as a
    // value would give one entry two meanings.
    const found = optionsFor(
      [person({ department: '' }), person({ department: '  ' }), person()],
      'department',
    );

    expect(found).toEqual([{ value: 'Sales', people: 1 }]);
  });

  it('only offers values somebody actually has', () => {
    // A dropdown listing a department nobody is in is a filter whose only
    // possible result is an empty screen.
    expect(optionsFor(PEOPLE, 'office_location').map((o) => o.value)).toEqual([
      'Dallas',
      'Phoenix',
    ]);
  });
});

describe('isNarrowed', () => {
  it('is false for untouched filters', () => {
    expect(isNarrowed(NO_FILTERS)).toBe(false);
  });

  it('ignores a search of nothing but spaces', () => {
    expect(isNarrowed({ ...NO_FILTERS, search: '   ' })).toBe(false);
  });

  it('is true once anything narrows the list', () => {
    expect(isNarrowed({ ...NO_FILTERS, department: 'Sales' })).toBe(true);
    expect(isNarrowed({ ...NO_FILTERS, search: 'sam' })).toBe(true);
  });
});

describe('team and role (review §7)', () => {
  const crew = [
    person({ full_name: 'On Metropolis', team_name: 'Metropolis', org_role: 'agent' }),
    person({ full_name: 'On nothing', team_name: null, org_role: 'agent' }),
    person({ full_name: 'A manager', team_name: null, org_role: 'manager' }),
  ];

  it('narrows to one team, or to people on none', () => {
    expect(apply(crew, { ...NO_FILTERS, team: 'Metropolis' }).map((p) => p.full_name)).toEqual([
      'On Metropolis',
    ]);
    expect(apply(crew, { ...NO_FILTERS, team: NO_TEAM }).map((p) => p.full_name)).toEqual([
      'On nothing',
      'A manager',
    ]);
  });

  it('and by role, together with the team', () => {
    expect(
      apply(crew, { ...NO_FILTERS, team: NO_TEAM, role: 'agent' }).map((p) => p.full_name),
    ).toEqual(['On nothing']);
    expect(isNarrowed({ ...NO_FILTERS, role: 'agent' })).toBe(true);
  });
});
