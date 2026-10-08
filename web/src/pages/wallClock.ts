/**
 * One clock for every screen on a channel.
 *
 * **Screens used to count from whenever they loaded**, so two tabs of the same
 * wall — or two televisions on the same channel — rotated at different moments
 * and drifted further apart with every celebration, because each one paused
 * its own count while a win was on screen. A room with three screens showing
 * three different boards looks broken rather than busy.
 *
 * So the rotation is now a function of the time rather than a count. Every
 * screen asks the same question — "what should be showing at this instant?" —
 * and gets the same answer, because it asks it of the same clock:
 *
 *     the cycle     every slide's dwell, added up
 *     the position  the current time, modulo the cycle
 *
 * That only works if every screen agrees on the time, and a television's own
 * clock is routinely seconds or minutes out. So each screen sets its clock by
 * the server's: every feed carries the server's time, and a screen works out
 * how far its own clock is from it.
 *
 * Kept pure, for the reason `celebrationQueue.ts` is: this is scheduling
 * arithmetic, and a test of it should not have to mount a page.
 */

/** Used only if a slide somehow arrives without its own dwell time. */
export const FALLBACK_DWELL = 20;

/** How many recent clock readings to choose the best from. */
const SAMPLES = 8;

export interface Sample {
  /** Add to the local clock to get the server's. */
  offset: number;
  /** How long the request took, which is how far to trust it. */
  roundTrip: number;
}

/**
 * One reading of how far this screen's clock is from the server's.
 *
 * The server stamped the time somewhere between the request leaving and the
 * answer arriving, and the honest guess is halfway — so the error is at most
 * half the round trip.
 */
export function sample(serverTime: number, sentAt: number, receivedAt: number): Sample {
  return {
    offset: serverTime - (sentAt + receivedAt) / 2,
    roundTrip: Math.max(receivedAt - sentAt, 0),
  };
}

/**
 * Keep the last few readings.
 */
export function remember(samples: Sample[], next: Sample): Sample[] {
  return [...samples, next].slice(-SAMPLES);
}

/**
 * The offset to use: the reading with the shortest round trip.
 *
 * **Not the average.** A reading taken over a slow request can be wrong by half
 * of however slow it was, and averaging it in drags a good answer toward a bad
 * one. The quickest request is the one whose halfway guess was closest, so it
 * is the one to believe.
 */
export function bestOffset(samples: Sample[]): number {
  if (samples.length === 0) return 0;
  let best = samples[0]!;
  for (const s of samples) {
    if (s.roundTrip < best.roundTrip) best = s;
  }
  return best.offset;
}

export interface Position {
  index: number;
  /** How much longer the current slide has, in milliseconds. */
  remaining: number;
  /** How long the current slide shows for in all, in milliseconds. */
  length: number;
}

/**
 * Which slide should be showing at `now` (the server's time, in ms), and for
 * how much longer.
 *
 * Measured from the start of the epoch rather than from anything a screen
 * knows about itself, which is what makes every screen's answer the same: two
 * screens with the same slides and the same clock land on the same slide at
 * the same millisecond, however long either has been running.
 */
export function positionAt(dwellSeconds: number[], now: number): Position | null {
  if (dwellSeconds.length === 0) return null;
  const lengths = dwellSeconds.map(
    (seconds) => Math.max(1, seconds || FALLBACK_DWELL) * 1000,
  );
  const cycle = lengths.reduce((total, length) => total + length, 0);
  let into = ((now % cycle) + cycle) % cycle;
  for (let index = 0; index < lengths.length; index += 1) {
    const length = lengths[index]!;
    if (into < length) return { index, remaining: length - into, length };
    into -= length;
  }
  // Unreachable — `into` is always inside the cycle — but a wall must not
  // throw because floating point disagreed with itself.
  return { index: 0, remaining: lengths[0]!, length: lengths[0]! };
}

/**
 * How long to wait before asking for the channel again.
 *
 * **On a shared boundary, not on a private interval.** A screen that polled
 * every sixty seconds from whenever it loaded would learn that a slide had
 * been added up to a minute after the screen beside it, and the two would
 * rotate through different lists for that minute. Polling on the minute —
 * every screen at once, give or take a moment — means a change reaches them
 * all together.
 *
 * `spread` is a few random milliseconds so that forty screens do not arrive at
 * the server in the same instant.
 */
export function nextPollIn(now: number, refreshSeconds: number, spread: number): number {
  const period = Math.max(refreshSeconds, 5) * 1000;
  const untilBoundary = period - (((now % period) + period) % period);
  return untilBoundary + spread;
}
