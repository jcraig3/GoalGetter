import { describe, expect, it } from 'vitest';

import { filterInput, forInput, numericPattern, rangeError, type NumericRule } from './Field';

/** The component's own keystroke handler, called directly. */
function typeInto(current: string, next: string, rule: NumericRule): string {
  return filterInput(current, next, { numeric: rule });
}

describe('numeric filtering', () => {
  const money: NumericRule = { decimals: 4 };

  it.each(['0', '5', '250', '1234.5', '0.0001', '1000000'])(
    'accepts %s',
    (value) => {
      expect(numericPattern(money).test(value)).toBe(true);
    },
  );

  it.each([
    'abc',
    '12abc',
    '1e5', // what <input type="number"> would have accepted
    '--5',
    '1.2.3',
    '1,000', // thousands separator: a real paste, and not a number
    ' 5',
    '5 ',
    '$5',
    '+5',
  ])('rejects %s', (value) => {
    expect(numericPattern(money).test(value)).toBe(false);
  });

  it('rejects a negative unless the field allows one', () => {
    expect(numericPattern({ decimals: 4 }).test('-5')).toBe(false);
    expect(numericPattern({ decimals: 4, allowNegative: true }).test('-5')).toBe(true);
  });

  it('allows a trailing decimal point while it is being typed', () => {
    // Rejecting "12." would make the decimal point impossible to type at all,
    // because every value passes through that state on the way to "12.5".
    expect(numericPattern(money).test('12.')).toBe(true);
  });

  it('stops at the declared number of decimals', () => {
    const twoPlaces: NumericRule = { decimals: 2 };
    expect(numericPattern(twoPlaces).test('1.23')).toBe(true);
    expect(numericPattern(twoPlaces).test('1.234')).toBe(false);
  });

  it('refuses a decimal point entirely when decimals is 0', () => {
    const integers: NumericRule = { decimals: 0 };
    expect(numericPattern(integers).test('587')).toBe(true);
    expect(numericPattern(integers).test('58.7')).toBe(false);
    expect(numericPattern(integers).test('587.')).toBe(false);
  });
});

describe('what actually reaches the field', () => {
  const money: NumericRule = { decimals: 4 };

  it('keeps the previous value when a bad character is typed', () => {
    expect(typeInto('12', '12a', money)).toBe('12');
  });

  it('lets a field be cleared', () => {
    // Otherwise a rule could trap a value the user has no way to remove.
    expect(typeInto('12', '', money)).toBe('');
  });

  it('builds up a decimal one keystroke at a time', () => {
    let value = '';
    for (const next of ['1', '12', '12.', '12.5', '12.50']) {
      value = typeInto(value, next, money);
    }
    expect(value).toBe('12.50');
  });

  it('never lets a paste of a formatted number land half-parsed', () => {
    // "1,234.50" is rejected whole rather than becoming "1" or "1234.50" —
    // silently changing a pasted figure is worse than refusing it.
    expect(typeInto('', '1,234.50', money)).toBe('');
  });
});

describe('range messages', () => {
  it('reports a value below the minimum', () => {
    expect(rangeError('0', { min: 1 })).toBe('Must be at least 1.');
  });

  it('reports a value above the maximum', () => {
    expect(rangeError('70000', { max: 65535 })).toBe('Must be at most 65535.');
  });

  it('accepts the boundaries themselves', () => {
    expect(rangeError('1', { min: 1, max: 65535 })).toBeNull();
    expect(rangeError('65535', { min: 1, max: 65535 })).toBeNull();
  });

  it.each(['', '-', '12.'])('stays quiet for the mid-typing state %o', (value) => {
    // Flagging "-" the moment someone starts a negative number, or "12." the
    // moment they reach for the decimal, makes the field feel broken.
    expect(rangeError(value, { min: 0, max: 100 })).toBeNull();
  });

  it('has nothing to say when no bounds are declared', () => {
    expect(rangeError('999999', {})).toBeNull();
  });
});

describe('forInput', () => {
  it('drops the padding a NUMERIC(18,4) column adds', () => {
    // The bug: editing a rule whose threshold is 25 offered "25.0000", which is
    // four characters to delete before you can type your own number.
    expect(forInput('25.0000')).toBe('25');
  });

  it('keeps the decimals that carry information', () => {
    expect(forInput('25.5000')).toBe('25.5');
    expect(forInput('0.2500')).toBe('0.25');
    expect(forInput('1.0500')).toBe('1.05');
  });

  it('never strips trailing zeros from an integer', () => {
    // The case that makes this a regex and not a `replace`. Turning a target of
    // ten thousand into one is the worst possible outcome here.
    expect(forInput('1000')).toBe('1000');
    expect(forInput('10')).toBe('10');
    expect(forInput(2500)).toBe('2500');
  });

  it('collapses a zero to a single digit', () => {
    expect(forInput('0.0000')).toBe('0');
    expect(forInput('-0.0000')).toBe('0');
  });

  it('handles negatives', () => {
    expect(forInput('-12.3400')).toBe('-12.34');
  });

  it('preserves exactness beyond what a double can hold', () => {
    // `String(Number('12345678901234567.5000'))` loses the last digits. The
    // whole reason this works on the string.
    expect(forInput('12345678901234567.5000')).toBe('12345678901234567.5');
  });

  it('leaves anything that is not a plain decimal alone', () => {
    // A presentation step, not a validator. Mangling an unexpected value would
    // hide the problem instead of showing it.
    expect(forInput('')).toBe('');
    expect(forInput('1e5')).toBe('1e5');
    expect(forInput('abc')).toBe('abc');
    expect(forInput(null)).toBe('');
    expect(forInput(undefined)).toBe('');
  });
});
