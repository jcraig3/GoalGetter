import { describe, expect, it } from 'vitest';

import { bestOvertake, overtakes } from './overtakes';
import type { Entry } from './types';

/**
 * Who passed whom.
 *
 * **The distinction every naive version gets wrong** is between a rank
 * improving and a pair changing order. Somebody climbs two places because two
 * people above them left the company; announcing that as an overtake is
 * congratulating them on a resignation.
 */
function board(...names: string[]): Entry[] {
  return names.map((name, index) => ({
    rank: index + 1,
    entity_id: name.charCodeAt(0),
    entity_name: name,
    photo_digest: null,
    team_name: null,
    value: String(100 - index),
    movement: null,
  }));
}

describe('overtakes', () => {
  it('finds a straight swap', () => {
    const found = overtakes(board('A', 'B'), board('B', 'A'));

    expect(found).toHaveLength(1);
    expect(found[0]).toMatchObject({ who: 'B', passed: 'A', rank: 1 });
  });

  it('says nothing when nothing moved', () => {
    expect(overtakes(board('A', 'B', 'C'), board('A', 'B', 'C'))).toEqual([]);
  });

  it('is not fooled by somebody leaving', () => {
    // C climbs from 3rd to 2nd because B is gone. Nobody was passed.
    expect(overtakes(board('A', 'B', 'C'), board('A', 'C'))).toEqual([]);
  });

  it('is not fooled by somebody arriving', () => {
    // A new entrant above C has not passed C — they were not racing yet.
    expect(overtakes(board('A', 'C'), board('A', 'B', 'C'))).toEqual([]);
  });

  it('reports every pair when somebody jumps several places', () => {
    const found = overtakes(board('A', 'B', 'C', 'D'), board('D', 'A', 'B', 'C'));

    expect(found.map((o) => o.passed).sort()).toEqual(['A', 'B', 'C']);
    expect(found.every((o) => o.who === 'D')).toBe(true);
  });

  it('puts the change nearest the top first', () => {
    // A room glancing up has time for one line, and first place is the one
    // worth spending it on.
    const found = overtakes(
      board('A', 'B', 'C', 'D'),
      board('B', 'A', 'D', 'C'),
    );

    expect(found[0]).toMatchObject({ who: 'B', rank: 1 });
  });

  it('an empty board announces nothing', () => {
    // A board with nothing on it is the ordinary state of a new metric, not a
    // moment where everybody was overtaken.
    expect(overtakes([], board('A'))).toEqual([]);
    expect(overtakes(board('A'), [])).toEqual([]);
  });

  it('a tie breaking is not a pass', () => {
    // Nobody moved; the tie-break did. Strict comparison both ways is what
    // keeps this out.
    const tied = board('A', 'B');
    tied[1]!.rank = 1;

    expect(overtakes(tied, board('B', 'A'))).toEqual([]);
  });

  it('two separate races are both found', () => {
    const found = overtakes(
      board('A', 'B', 'C', 'D'),
      board('B', 'A', 'D', 'C'),
    );

    expect(found).toHaveLength(2);
  });
});

describe('bestOvertake', () => {
  it('is the one nearest the top', () => {
    const found = bestOvertake(
      board('A', 'B', 'C', 'D'),
      board('B', 'A', 'D', 'C'),
    );

    expect(found?.who).toBe('B');
  });

  it('is null when nothing happened', () => {
    // Null rather than an empty object, so the caller renders nothing rather
    // than an empty banner over the board it is about.
    expect(bestOvertake(board('A', 'B'), board('A', 'B'))).toBeNull();
  });
});
