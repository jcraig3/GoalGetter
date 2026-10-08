import { describe, expect, test } from 'vitest';

import { passwordProblem, suggestPassword } from './passwordRule';

describe('the one password rule (11.4)', () => {
  test('silent while empty', () => {
    expect(passwordProblem('')).toBeNull();
  });

  test('counts down to twelve', () => {
    expect(passwordProblem('short')).toBe('7 more characters needed');
    expect(passwordProblem('elevenchars')).toBe('1 more character needed');
    expect(passwordProblem('twelve chars')).toBeNull();
  });

  test('72 bytes, not 72 characters', () => {
    // 40 accented letters are 80 bytes, which bcrypt cannot read whole.
    expect(passwordProblem('é'.repeat(40))).toBe('Too long — 72 characters at most');
    expect(passwordProblem('a'.repeat(72))).toBeNull();
  });

  test('a suggestion passes it, and is not the same twice', () => {
    const one = suggestPassword();
    expect(passwordProblem(one)).toBeNull();
    expect(one).toMatch(/^[a-z]+(-[a-z]+){3}-\d{2}$/);
    expect(suggestPassword()).not.toBe(one);
  });
});
