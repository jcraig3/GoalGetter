import { describe, expect, it } from 'vitest';

import { fold, isKnown, matching, peopleFor, SHOWING, type Option } from './optionMatch';

const options = (...pairs: [string, number][]): Option[] =>
  pairs.map(([value, people]) => ({ value, people }));

const DEPARTMENTS = options(
  ['Sales', 24],
  ['Inside Sales', 6],
  ['Support', 11],
  ['Finance', 3],
);

describe('matching', () => {
  it('offers everything, capped, before anything is typed', () => {
    const many = options(...Array.from({ length: 20 }, (_, i) => [`Dept ${i}`, 1] as [string, number]));

    expect(matching(many, '')).toHaveLength(SHOWING);
    expect(matching(DEPARTMENTS, '   ')).toEqual(DEPARTMENTS);
  });

  it('puts what the typing starts with ahead of what merely contains it', () => {
    // Somebody typing "sa" means Sales far more often than Inside Sales, and a
    // list that leads with the substring hit makes the obvious choice the one you
    // scroll for.
    expect(matching(DEPARTMENTS, 'sa').map((o) => o.value)).toEqual([
      'Sales',
      'Inside Sales',
    ]);
  });

  it('ignores case and surrounding space', () => {
    expect(matching(DEPARTMENTS, '  SALES ').map((o) => o.value)).toEqual([
      'Sales',
      'Inside Sales',
    ]);
  });

  it('offers nothing for a value the directory does not hold', () => {
    expect(matching(DEPARTMENTS, 'Marketing')).toEqual([]);
  });
});

describe('isKnown', () => {
  it('accepts an exact value, whatever the case and spacing', () => {
    expect(isKnown(DEPARTMENTS, 'sales')).toBe(true);
    expect(isKnown(DEPARTMENTS, ' Sales ')).toBe(true);
  });

  it('rejects a near miss, which is the whole point', () => {
    // **The failure this exists to catch.** A rule is a string comparison against
    // what the provider sent, so "Sales Team" against a tenant that says "Sales"
    // saves cleanly and matches nobody.
    expect(isKnown(DEPARTMENTS, 'Sales Team')).toBe(false);
  });

  it('treats empty as fine, because empty means any', () => {
    expect(isKnown(DEPARTMENTS, '')).toBe(true);
  });

  it('is fine with anything when the directory has told us nothing yet', () => {
    // Before the first sync there is no list, and a form that warned about every
    // value would be warning about all of them.
    expect(isKnown([], '')).toBe(true);
    expect(isKnown([], 'Sales')).toBe(false);
  });
});

describe('peopleFor', () => {
  it('counts an exact match', () => {
    expect(peopleFor(DEPARTMENTS, 'Sales')).toBe(24);
  });

  it('separates "no such value" from "nobody has it"', () => {
    // Different things, said differently: null is a typo, zero is a department
    // whose last person left.
    expect(peopleFor(DEPARTMENTS, 'Marketing')).toBeNull();
    expect(peopleFor(options(['Empty Dept', 0]), 'Empty Dept')).toBe(0);
  });
});

describe('fold', () => {
  it('keeps inner spacing, which distinguishes real departments', () => {
    // Folding these together would offer a value that matches nobody, which is
    // exactly the bug this dropdown removes.
    expect(fold('Inside Sales')).not.toBe(fold('InsideSales'));
    expect(fold('  Sales  ')).toBe('sales');
  });
});
