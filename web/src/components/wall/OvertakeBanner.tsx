import { useEffect, useRef, useState } from 'react';

import { bestOvertake, type Overtake } from './overtakes';
import type { Entry } from './types';

/**
 * "Clark Kent passed Peter Parker into 1st."
 *
 * **The cheapest moment in the product and the one people talk about.** The
 * standings already say where everybody is; this says what just changed, which
 * is the part a room reacts to out loud. It needed no new table, no event and
 * no sweep — only remembering what the board looked like last time it was up.
 */
export default function OvertakeBanner({
  slideId,
  entries,
}: {
  /** Which board this is, so two boards do not share one memory. */
  slideId: number;
  entries: Entry[];
}) {
  //: What each board looked like the last time the room could see it.
  const seen = useRef(new Map<number, Entry[]>());
  const [announcement, setAnnouncement] = useState<Overtake | null>(null);

  // **One effect, not two.** Clearing the last banner and deciding the next
  // one are the same decision: as two effects, the clear runs second on a
  // slide change and wipes the announcement the other just made, so a banner
  // could only ever appear while a slide stayed put.
  useEffect(() => {
    setAnnouncement(null);

    const before = seen.current.get(slideId);
    // **Recorded before the comparison is used.** Leaving the old snapshot in
    // place would announce the same overtake on every poll for as long as the
    // slide stayed up.
    seen.current.set(slideId, entries);
    if (!before) return;

    const found = bestOvertake(before, entries);
    if (!found) return;

    setAnnouncement(found);
    // Long enough to read across a room, short enough to leave the board
    // visible for most of its own slot.
    const timer = setTimeout(() => setAnnouncement(null), HOLD_MS);
    return () => clearTimeout(timer);
  }, [slideId, entries]);

  if (!announcement) return null;

  return (
    <div
      // `alert`, because this is the one thing on a wall that appears
      // unprompted and is gone before anybody can go looking for it.
      role="alert"
      className="pointer-events-none absolute inset-x-0 top-0 z-20 flex justify-center"
    >
      <p className="wall-panel animate-[celebrate_400ms_ease-out] px-8 py-4 text-wall-3xl text-content shadow-lg">
        <span className="font-semibold text-accent">{announcement.who}</span>
        {' passed '}
        <span className="font-semibold">{announcement.passed}</span>
        {' into '}
        <span className="font-semibold">{ordinal(announcement.rank)}</span>
      </p>
    </div>
  );
}

/** How long the banner holds, in milliseconds. */
const HOLD_MS = 6000;

/** "1st", "2nd", "3rd" — the way a person would read a rank aloud. */
function ordinal(rank: number): string {
  const tens = rank % 100;
  if (tens >= 11 && tens <= 13) return `${rank}th`;
  const suffix = { 1: 'st', 2: 'nd', 3: 'rd' }[rank % 10] ?? 'th';
  return `${rank}${suffix}`;
}
