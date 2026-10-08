/**
 * What a competition's dates mean right now.
 *
 * Its own module, away from the page, for the reason `channelOrder.ts` is: this
 * is arithmetic with rounding decisions in it, and a test of arithmetic should
 * not have to import a React page, a router, an auth context and an HTTP client
 * to reach it. The version that did hung the test runner.
 *
 * Every function takes `now` rather than reading the clock, so a test can stand
 * at any moment in the lifecycle and the render is deterministic.
 */

import { dayAndTimeInFull } from '../time';

const SECOND = 1000;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** The five things a competition can be *doing*, from its dates and state. */
export type Phase =
  | 'draft'
  | 'upcoming'
  | 'running'
  | 'provisional'
  | 'finished'
  | 'cancelled';

export interface Clock {
  state: string;
  starts_at: string;
  ends_at: string;
  settles_at: string;
}

/**
 * What this competition is doing, as one word the UI can switch on.
 *
 * Read from the stored state rather than recomputed from the dates. The two can
 * legitimately disagree for up to a job interval — a contest whose `ends_at`
 * passed a minute ago is still `active` until `advance()` runs — and in that gap
 * the stored state is the one that governs whether the result has been frozen.
 * A page that decided for itself would show "final" beside numbers still moving.
 */
export function phaseOf(competition: Clock): Phase {
  switch (competition.state) {
    case 'draft':
      return 'draft';
    case 'scheduled':
      return 'upcoming';
    case 'ended':
      return 'provisional';
    case 'closed':
      return 'finished';
    case 'cancelled':
      return 'cancelled';
    default:
      return 'running';
  }
}

/**
 * Milliseconds until `to`, floored at zero.
 *
 * Zero rather than a negative number, because every caller wants "no time left"
 * and a negative would format as a countdown running backwards.
 */
export function remaining(to: string, now: Date): number {
  return Math.max(0, new Date(to).getTime() - now.getTime());
}

/**
 * A countdown, at the coarseness the size of the gap deserves.
 *
 * Two units, never three: "2d 4h" is a glance and "2d 4h 17m 3s" is a thing you
 * have to read. The pair shifts down as the deadline approaches, so the last
 * minute counts seconds and next week does not.
 *
 * The larger unit is truncated, not rounded — 47 hours is "1d 23h", and calling
 * it "2d" would promise a day that is not there.
 */
export function countdown(ms: number): string {
  if (ms <= 0) return 'now';

  const days = Math.floor(ms / DAY);
  const hours = Math.floor((ms % DAY) / HOUR);
  const minutes = Math.floor((ms % HOUR) / MINUTE);
  const seconds = Math.floor((ms % MINUTE) / SECOND);

  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

/**
 * The same deadline, said the way the organization asked for.
 *
 * **Four answers because four rooms want different things.** A sales floor
 * watching a sprint end today wants "4h 12m"; a lobby screen showing a
 * month-long contest wants "3 days" and would look frantic ticking minutes at
 * the public; an office that plans around the deadline wants the actual date;
 * and a contest with a soft end wants no clock at all, because a countdown is
 * a promise about a moment.
 *
 * Returns `null` for "say nothing", which the caller renders as nothing rather
 * than as an empty string — an empty element still takes up a line.
 */
export function endTime(
  to: string,
  now: Date,
  style: string,
): string | null {
  if (style === 'off') return null;

  if (style === 'full') {
    // The date itself, not a duration. A wall that says "ends 3 October,
    // 5:00 pm" is the one somebody can plan around without arithmetic.
    return `Ends ${dayAndTimeInFull(to)}`;
  }

  const left = remaining(to, now);
  if (left <= 0) return 'Ends now';

  if (style === 'simple') {
    // One unit, in words. "2 days left" reads at a glance from across a lobby
    // in a way "1d 23h left" does not.
    const days = Math.floor(left / DAY);
    if (days > 0) return `${days} ${days === 1 ? 'day' : 'days'} left`;
    const hours = Math.floor(left / HOUR);
    if (hours > 0) return `${hours} ${hours === 1 ? 'hour' : 'hours'} left`;
    const minutes = Math.max(1, Math.floor(left / MINUTE));
    return `${minutes} ${minutes === 1 ? 'minute' : 'minutes'} left`;
  }

  return `${countdown(left)} left`;
}

/**
 * How often a countdown of this size needs redrawing.
 *
 * A week-long gap changes its displayed value once an hour, so ticking it every
 * second is 3,599 renders that produce identical pixels. Matched to the
 * smallest unit `countdown()` will actually show.
 */
export function tickInterval(ms: number): number {
  if (ms <= 0) return HOUR;
  if (ms < HOUR) return SECOND;
  if (ms < DAY) return MINUTE;
  return MINUTE * 10;
}

/** The sentence under a competition's name, which is different in every phase. */
export function statusLine(competition: Clock, now: Date): string {
  switch (phaseOf(competition)) {
    case 'draft':
      return 'Draft — not visible to entrants yet';
    case 'upcoming': {
      const until = remaining(competition.starts_at, now);
      // "Starts in now" is what `countdown(0)` produced here, and it read as a
      // bug. Publishing an already-begun contest no longer lands in this state at
      // all, but a contest scheduled in advance still crosses its start moment
      // while somebody is watching the page, and the job promotes it on its next
      // pass rather than instantly.
      return until === 0 ? 'Starting now' : `Starts in ${countdown(until)}`;
    }
    case 'running':
      return `${countdown(remaining(competition.ends_at, now))} left`;
    case 'provisional':
      // The one status line that explains itself. Everywhere else the phase is
      // self-evident; "provisional" is a word people will otherwise read as
      // "broken".
      return `Provisional — final in ${countdown(
        remaining(competition.settles_at, now),
      )} once late data has landed`;
    case 'finished':
      return 'Final result';
    case 'cancelled':
      return 'Cancelled — no result';
  }
}

/**
 * Which tab a competition belongs under.
 *
 * `provisional` sits with the live ones rather than the finished ones. It has
 * ended but has no result yet, and a contest filed under "Finished" with no
 * winner beside it reads as a bug.
 */
export function tabOf(competition: Clock): 'live' | 'upcoming' | 'finished' | 'drafts' {
  const phase = phaseOf(competition);
  if (phase === 'draft') return 'drafts';
  if (phase === 'upcoming') return 'upcoming';
  if (phase === 'finished' || phase === 'cancelled') return 'finished';
  return 'live';
}

/** The browser's own zone — what to use until the organization's arrives. */
export function browserZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

/**
 * A zone as people say it — "Eastern Time" — falling back to its IANA name
 * where the browser has no generic name for it.
 */
export function zoneName(zone: string): string {
  try {
    const part = new Intl.DateTimeFormat('en-US', {
      timeZone: zone,
      timeZoneName: 'longGeneric',
    })
      .formatToParts(new Date())
      .find((p) => p.type === 'timeZoneName');
    return part?.value ?? zone;
  } catch {
    return zone;
  }
}

interface WallClock {
  year: string;
  month: string;
  day: string;
  hour: string;
  minute: string;
  second: string;
}

/** The wall clock in `zone` at an instant, to the second. */
function wallClock(at: Date, zone: string): WallClock {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: zone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    // Not the default, which writes midnight as "24" in some engines.
    hourCycle: 'h23',
  }).formatToParts(at);
  const of = (type: string) => parts.find((part) => part.type === type)?.value ?? '00';
  return {
    year: of('year'),
    month: of('month'),
    day: of('day'),
    hour: of('hour'),
    minute: of('minute'),
    second: of('second'),
  };
}

/** How far `zone` is ahead of UTC at an instant, in milliseconds. */
function offsetAt(at: Date, zone: string): number {
  const p = wallClock(at, zone);
  const asIfUtc = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute, +p.second);
  return asIfUtc - (at.getTime() - at.getUTCMilliseconds());
}

/**
 * An ISO instant as the wall-clock string `<input type="datetime-local">` wants,
 * **in the organization's zone**.
 *
 * The control has no concept of a zone: it reads and writes `YYYY-MM-DDTHH:mm`.
 * Handing it `toISOString()` — which is UTC — silently shifts every competition
 * by the viewer's offset. Handing it the browser's local time was the next bug
 * (QA-14): a contest is the organization's, its boundaries are the
 * organization's, and an admin in Pacific typing "5pm" for a New York floor
 * meant New York's 5pm and got their own.
 *
 * `toLocaleString` cannot be used here because its output is a *human* format
 * and the control needs an exact one, so the parts are assembled by hand.
 */
export function toLocalInput(iso: string, zone: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return '';
  const p = wallClock(at, zone);
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
}

/**
 * The reverse: a wall-clock string in `zone` back to an ISO instant.
 *
 * Two passes, because the offset to subtract is the one in force at the answer,
 * and the answer is not known until the first pass. They differ only on the
 * night the clocks change.
 */
export function fromLocalInput(local: string, zone: string): string | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(local);
  if (!m) return null;
  const [year, month, day, hour, minute] = [m[1], m[2], m[3], m[4], m[5]].map(Number) as [
    number,
    number,
    number,
    number,
    number,
  ];
  const wall = Date.UTC(year, month - 1, day, hour, minute);
  // `Date.UTC` rolls "13th month, 45th day" over into a real date rather than
  // refusing it, so a value that does not survive the trip was never a date.
  const check = new Date(wall);
  if (
    Number.isNaN(wall) ||
    check.getUTCMonth() !== month - 1 ||
    check.getUTCDate() !== day ||
    check.getUTCHours() !== hour ||
    check.getUTCMinutes() !== minute
  ) {
    return null;
  }
  const first = wall - offsetAt(new Date(wall), zone);
  return new Date(wall - offsetAt(new Date(first), zone)).toISOString();
}

/**
 * A rank as people say it: 1st, 2nd, 3rd, 11th.
 *
 * Here rather than inline in the page because of the exception — 11, 12 and 13
 * take "th" despite ending in 1, 2 and 3, and a naive version reads "11st". It
 * lives in this module because this is the competition's pure-logic file; dates
 * were simply the first thing in it.
 */
export function place(rank: number): string {
  const remainder = rank % 100;
  if (remainder >= 11 && remainder <= 13) return `${rank}th`;
  switch (rank % 10) {
    case 1:
      return `${rank}st`;
    case 2:
      return `${rank}nd`;
    case 3:
      return `${rank}rd`;
    default:
      return `${rank}th`;
  }
}

/** The one-word name for a phase, for a status pill. */
export function phaseLabel(phase: Phase): string {
  switch (phase) {
    case 'draft':
      return 'Draft';
    case 'upcoming':
      return 'Scheduled';
    case 'running':
      return 'Running';
    case 'provisional':
      return 'Provisional';
    case 'finished':
      return 'Final';
    case 'cancelled':
      return 'Cancelled';
  }
}

/**
 * Who can see it and what happens next, in one sentence.
 *
 * Separate from `statusLine`, which is the countdown. This one answers the
 * question somebody actually has while they are building a contest — *is anyone
 * looking at this yet?* — because the difference between draft and scheduled is
 * invisible otherwise.
 */
export function phaseHelp(phase: Phase): string {
  switch (phase) {
    case 'draft':
      return 'Only you can see this. Publish it when the entrants and rules are right.';
    case 'upcoming':
      return 'Entrants can see it and are waiting for it to start.';
    case 'running':
      return 'Entrants can see the standings update as data arrives.';
    case 'provisional':
      return 'The window has closed. Late data can still land, so the result is not frozen yet.';
    case 'finished':
      return 'The result is frozen. Correcting the underlying data will not change who won.';
    case 'cancelled':
      return 'Stopped with no winner. No result was recorded.';
  }
}

/**
 * The colour a phase should read as.
 *
 * Returned as a token name rather than a class string, so the caller decides
 * whether it is a dot, a border, or text — and this stays testable without
 * asserting on Tailwind.
 */
export function phaseTone(phase: Phase): 'neutral' | 'info' | 'live' | 'warning' {
  switch (phase) {
    case 'running':
      return 'live';
    case 'upcoming':
      return 'info';
    case 'provisional':
      return 'warning';
    default:
      return 'neutral';
  }
}

/** Whether a competition in this phase can be pulled back to draft. */
export function canUnpublish(phase: Phase): boolean {
  // Everything except draft (already there) and finished (its result has been
  // announced, so reopening would make a winner provisional after the fact).
  return phase !== 'draft' && phase !== 'finished';
}

/** Whether it can be deleted outright: nothing came of it, and it is not running. */
export function canDelete(phase: Phase): boolean {
  return phase === 'draft' || phase === 'cancelled';
}

/** Whether cancelling still means anything. */
export function canCancel(phase: Phase): boolean {
  return phase !== 'finished' && phase !== 'cancelled' && phase !== 'draft';
}
