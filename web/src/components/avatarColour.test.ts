import { describe, expect, it } from 'vitest';

import { avatarColour, initialsOf } from './avatarColour';

/**
 * A colour per person.
 *
 * **The property that matters is stability**, not prettiness: somebody's colour
 * has to be the same on a leaderboard, on their profile and in a celebration.
 * One that changed between screens would be worse than no colour at all,
 * because the eye learns it and is then wrong.
 */
describe('avatarColour', () => {
  it('is the same every time for the same person', () => {
    expect(avatarColour('Peter Parker')).toBe(avatarColour('Peter Parker'));
  });

  it('ignores case and stray spaces', () => {
    // The same person typed two ways is the same person, and a board built
    // from one source and a profile from another should not disagree.
    expect(avatarColour('  peter parker ')).toBe(avatarColour('Peter Parker'));
  });

  it('gives different people different colours', () => {
    const colours = new Set(
      [
        'Peter Parker',
        'Clark Kent',
        'Diana Prince',
        'Bruce Banner',
        'Richard Rider',
        'Barry Allen',
      ].map(avatarColour),
    );

    // Six names out of twelve hues: collisions are possible and fine, but all
    // six landing on one colour would mean the hash is not spreading at all.
    expect(colours.size).toBeGreaterThan(3);
  });

  it('spreads across the whole wheel rather than clustering', () => {
    const hues = new Set(
      Array.from({ length: 200 }, (_, i) => avatarColour(`Person ${i}`)),
    );

    expect(hues.size).toBe(12);
  });

  it('is always dark enough for white text', () => {
    // 4.5:1 against white is what keeps initials readable, and it is the one
    // thing a prettier palette would quietly break.
    const colour = avatarColour('Anybody');
    const lightness = Number(colour.match(/(\d+)%\)$/)?.[1]);

    expect(lightness).toBeLessThanOrEqual(45);
  });

  it('has something to say about an empty name', () => {
    // A row with no name is a data problem, not a reason to throw on a wall.
    expect(() => avatarColour('')).not.toThrow();
  });
});

describe('initialsOf', () => {
  it('takes the first letter of the first two names', () => {
    expect(initialsOf('Peter Parker')).toBe('PP');
  });

  it('handles somebody with one name', () => {
    expect(initialsOf('Cher')).toBe('C');
  });

  it('ignores the third name and beyond', () => {
    expect(initialsOf('Jean Luc Picard')).toBe('JL');
  });

  it('is not confused by extra spaces', () => {
    expect(initialsOf('  Peter   Parker  ')).toBe('PP');
  });

  it('returns nothing for nothing, rather than throwing', () => {
    expect(initialsOf('')).toBe('');
  });
});
