/**
 * The arithmetic behind dragging a screen into a new position.
 *
 * Its own module, away from the page, for two reasons. The maths has two
 * off-by-ones in it and deserves testing directly rather than through a
 * simulated drag — and a test of pure arithmetic should not have to import a
 * React page, a router, an auth context and an HTTP client to reach it. The
 * version that did hung the test runner.
 */

/** Where the dragged row would land: above or below the row under the cursor. */
export interface DropAt {
  id: number;
  before: boolean;
}

/**
 * The order that results from dropping `moving` at `target`.
 *
 * Two things here are easy to get wrong, and both only show up in one
 * direction of travel:
 *
 *   * The index is measured in the list with the dragged row **already
 *     removed**. Measuring it in the original list makes every downward move
 *     land one slot early.
 *   * Dropping *below* a row is that row's index **plus one**.
 *
 * Returns the input untouched when there is nothing to do, so callers can pass
 * the result straight on without checking.
 */
export function reorderIds(
  ids: number[],
  moving: number,
  target: DropAt,
): number[] {
  if (moving === target.id) return ids;

  const without = ids.filter((id) => id !== moving);
  const at = without.indexOf(target.id);
  // The target went away — a screen removed in another tab mid-drag.
  if (at === -1) return ids;

  without.splice(target.before ? at : at + 1, 0, moving);
  return without;
}
