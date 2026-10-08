import type { Background } from '../appearance';
import type { Slide } from '../components/wall/types';
/**
 * Which win is on the wall right now.
 *
 * Its own module for the reason `competitionClock.ts` and `wallClock.ts` are:
 * this is scheduling logic, and a test of it should not have to mount a page,
 * a router and an HTTP client to reach it.
 *
 * **The server keeps the timetable; a screen only reads it.** Until 4k each
 * screen decided for itself — it played the oldest win it had not seen yet, as
 * soon as it saw one — so two televisions on a channel celebrated the same
 * person up to ten seconds apart, whenever each happened to poll. Now every
 * win arrives with the instant it takes over every screen on the channel and
 * the instant it lets go, and a screen shows whichever one the shared clock
 * says is on. Nothing is remembered between polls, because nothing needs to
 * be: "what is on now" is a question about the time, not about history.
 *
 * That also ends a quirk of the old design. A screen reloaded mid-afternoon
 * used to replay a window's worth of wins it had already shown; now it joins
 * whatever is playing, in step with the rest, and plays nothing that has
 * already finished.
 */

export interface Celebration {
  /**
   * `win:42` or `replay:7`.
   *
   * **A string, not the notification id.** The same win can arrive twice —
   * once because it happened and again because somebody pressed replay — and a
   * numeric id would make the second look like the first.
   */
  id: string;
  title: string;
  body: string | null;
  about_name: string | null;
  media_url: string | null;
  media_kind: string | null;
  media_id: string | null;
  /** An uploaded clip, by digest. Fetched through the display's own token. */
  media_digest: string | null;
  media_start_seconds: number | null;
  media_end_seconds: number | null;
  /** How long this one holds the screen. Decided by the server. */
  hold_seconds: number;
  created_at: string;
  /** When it takes over every screen on the channel, in ms since the epoch. */
  starts_at: number;
  /** When it lets go. */
  ends_at: number;
  /** What it is for: "Recognition", "Goal hit", an achievement's own name. */
  occasion?: string;
  /** Which event — so the prize wheel can spin before it says what it won. */
  event_key?: string;
  /** Sent to this one screen from an editor, and marked so on it (5j). */
  preview?: boolean;
  /** A previewed slide, drawn full-screen instead of an announcement. */
  slide?: Slide | null;
  /** The number it was for, "$500" — the largest thing on screen (7.9). */
  figure?: string | null;
  /** Their photograph, shown inside the glow (7.9). */
  photo_digest?: string | null;
  /** An announcement's own screen behind its words (Phase 25). */
  background?: Background | null;
  /** Its sound effect, a stored clip, played before the video's sound. */
  sound_digest?: string | null;
}

/**
 * The win on the wall at `now` (the server's time, in ms), or null.
 */
export function playingAt(
  timetable: Celebration[],
  now: number,
): Celebration | null {
  return timetable.find((c) => c.starts_at <= now && now < c.ends_at) ?? null;
}

/**
 * Milliseconds until something changes — the current one ends, or the next
 * one starts — or null when nothing is coming.
 *
 * A screen sleeps until then rather than checking on a tick, so a win starts
 * on the instant the server gave it rather than on the next tick after it.
 */
export function nextChangeIn(timetable: Celebration[], now: number): number | null {
  let soonest: number | null = null;
  for (const c of timetable) {
    for (const edge of [c.starts_at, c.ends_at]) {
      if (edge > now && (soonest === null || edge < soonest)) soonest = edge;
    }
  }
  return soonest === null ? null : soonest - now;
}

/**
 * How far into a celebration `now` is, in whole seconds.
 *
 * For a screen that joins one already playing: its clip should be where the
 * other screens' clips are, not back at the beginning.
 */
export function secondsIn(celebration: Celebration, now: number): number {
  return Math.max(0, Math.floor((now - celebration.starts_at) / 1000));
}

/**
 * The seconds of a clip to play, as a YouTube embed needs them.
 *
 * Returns nulls untouched rather than defaulting to zero: "no start given" and
 * "start at the beginning" happen to look the same for YouTube, but a caller
 * that cannot tell them apart will eventually be asked to.
 */
export function clipWindow(celebration: Celebration): {
  start: number | null;
  end: number | null;
} {
  return {
    start: celebration.media_start_seconds,
    end: celebration.media_end_seconds,
  };
}
