import { describe, expect, it } from 'vitest';

import { reorderIds } from './channelOrder';

/** The running order as ids, which is all the reorder maths deals in. */
const LIST = [10, 20, 30, 40];

describe('where a dropped screen lands', () => {
  it('drops above the row when the cursor is in its top half', () => {
    expect(reorderIds(LIST, 40, { id: 20, before: true })).toEqual([10, 40, 20, 30]);
  });

  it('drops below the row when the cursor is in its bottom half', () => {
    // The off-by-one this function exists for: "below row 20" is index 2 in the
    // list *without* the dragged row, not index 1.
    expect(reorderIds(LIST, 40, { id: 20, before: false })).toEqual([10, 20, 40, 30]);
  });

  it('moves a row downward correctly', () => {
    // Removing first is what makes this right. Splicing into the original
    // positions would land it one slot too early.
    expect(reorderIds(LIST, 10, { id: 30, before: false })).toEqual([20, 30, 10, 40]);
  });

  it('can move a row to the very top', () => {
    expect(reorderIds(LIST, 30, { id: 10, before: true })).toEqual([30, 10, 20, 40]);
  });

  it('can move a row to the very bottom', () => {
    expect(reorderIds(LIST, 10, { id: 40, before: false })).toEqual([20, 30, 40, 10]);
  });

  it('does nothing when dropped on itself', () => {
    expect(reorderIds(LIST, 20, { id: 20, before: true })).toEqual(LIST);
    expect(reorderIds(LIST, 20, { id: 20, before: false })).toEqual(LIST);
  });

  it('leaves the order alone if the target has since gone', () => {
    // A screen removed in another tab while this one was mid-drag.
    expect(reorderIds(LIST, 10, { id: 999, before: true })).toEqual(LIST);
  });

  it('never loses or duplicates a row', () => {
    // The invariant worth checking exhaustively: a reorder is a permutation.
    for (const moving of LIST) {
      for (const target of LIST) {
        for (const before of [true, false]) {
          const next = reorderIds(LIST, moving, { id: target, before });
          expect([...next].sort()).toEqual([...LIST].sort());
        }
      }
    }
  });

  it('does not mutate the list it was given', () => {
    const original = [...LIST];
    reorderIds(LIST, 10, { id: 30, before: false });
    expect(LIST).toEqual(original);
  });
});
