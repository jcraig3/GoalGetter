import type { Entry } from './types';

/**
 * Who passed whom since a board was last on the wall.
 *
 * **Detected in the browser, not stored.** An overtake is a moment on a
 * screen, not a fact to look up later: nobody opens a page to ask who passed
 * whom last Tuesday, and the standings themselves already answer where
 * everybody is now. Making it an event would mean a table, a sweep and a row
 * per overtake, to say something that is only worth saying while somebody is
 * looking at it.
 *
 * **"Since this board was last shown", not "since the last poll".** A board
 * holds the wall for twenty seconds out of a two-minute rotation, so almost
 * every overtake happens while it is off screen. Comparing against the last
 * time the room could actually see it is the question a room has — "what
 * changed since I last looked at this?" — and it is the one that fires often
 * enough to be worth building.
 */
export interface Overtake {
  /** The one who moved up. */
  who: string;
  /** The one they went past. */
  passed: string;
  /** Where they ended up, for "…into 2nd". */
  rank: number;
}

/**
 * Every pass between two snapshots of the same board, best first.
 *
 * A pass is a *pair* changing order, not a rank improving. Somebody can climb
 * two places because two people above them left the company, and announcing
 * that as an overtake would be congratulating them on a resignation.
 *
 * Only people in both snapshots count, for the same reason: a new entrant
 * appearing above somebody has not passed them, they were not racing yet.
 */
export function overtakes(before: Entry[], after: Entry[]): Overtake[] {
  if (before.length === 0 || after.length === 0) return [];

  const was = new Map(before.map((entry) => [entry.entity_id, entry.rank]));
  const found: Overtake[] = [];

  for (const mover of after) {
    const wasRank = was.get(mover.entity_id);
    // Not there before, or no better off: nothing to announce either way.
    if (wasRank === undefined || mover.rank >= wasRank) continue;

    for (const other of after) {
      if (other.entity_id === mover.entity_id) continue;
      const otherWas = was.get(other.entity_id);
      if (otherWas === undefined) continue;

      // Behind them then, ahead of them now. Strict both ways, so two people
      // tied and then untied is not a pass — nobody moved, the tie broke.
      if (wasRank > otherWas && mover.rank < other.rank) {
        found.push({
          who: mover.entity_name,
          passed: other.entity_name,
          rank: mover.rank,
        });
      }
    }
  }

  // **Nearest the top first.** A room glancing up has time for one line, and a
  // change at the top of a board is the one worth spending it on. Ties broken
  // by who was passed, so the order is stable rather than dependent on the
  // order the server happened to send.
  return found.sort(
    (a, b) => a.rank - b.rank || a.passed.localeCompare(b.passed),
  );
}

/**
 * The one line a wall shows, or nothing.
 *
 * One, not a list: three banners stacked over a leaderboard hide the
 * leaderboard, which is the thing they are about.
 */
export function bestOvertake(before: Entry[], after: Entry[]): Overtake | null {
  return overtakes(before, after)[0] ?? null;
}
