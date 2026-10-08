/**
 * How long ago, in words somebody can act on.
 *
 * **One of these, used everywhere.** There were four, some rounding down and
 * some to the nearest, so the same timestamp read "6 days ago" on one page and
 * "7 days ago" on the next (QA-36). This one rounds down: at six and a half
 * days, a week has not passed.
 *
 * Coarse on purpose. "Four hours ago" is what a reader wants; the exact minute
 * is noise they would have to do arithmetic on, and a live-updating relative
 * timestamp is a re-render every second for no decision anybody makes.
 */
export function agoInWords(then: Date, now: Date = new Date()): string {
  const minutes = Math.floor((now.getTime() - then.getTime()) / 60_000);
  // A clock a few minutes ahead of the server should not read "in 3 minutes".
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} ${minutes === 1 ? 'minute' : 'minutes'} ago`;

  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} ${hours === 1 ? 'hour' : 'hours'} ago`;

  const days = daysAgo(then, now);
  if (days < 7) return `${days} ${days === 1 ? 'day' : 'days'} ago`;
  return dayMonth(then, now);
}

/*
 * **Dates, said one way** (Q2-29). There were four — "10/1/2026", "Fri 2 Oct",
 * "Fri, Oct 2" and "Sep 23" — sometimes on one card. Day before month, a short
 * month name, a year only when it is not this one, and a time with no ":00".
 */

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const WEEKDAYS_LONG = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const MONTHS_LONG = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

type When = Date | string;

/** A date-only "2026-10-02" is that day here, not midnight in London. */
function asDate(when: When): Date {
  if (typeof when !== 'string') return when;
  return new Date(/^\d{4}-\d{2}-\d{2}$/.test(when) ? `${when}T12:00:00` : when);
}

/** "2 Oct", or "2 Oct 2025" when it is not this year. */
export function dayMonth(when: When, now: Date = new Date(), withYear = false): string {
  const d = asDate(when);
  const year = withYear || d.getFullYear() !== now.getFullYear() ? ` ${d.getFullYear()}` : '';
  return `${d.getDate()} ${MONTHS[d.getMonth()]}${year}`;
}

/** "Fri 2 Oct". */
export function dayName(when: When, now: Date = new Date()): string {
  const d = asDate(when);
  return `${WEEKDAYS[d.getDay()]} ${dayMonth(d, now)}`;
}

/** "11 pm", "10:26 am". */
export function clockTime(when: When): string {
  const d = asDate(when);
  const hour = d.getHours() % 12 || 12;
  const minutes = d.getMinutes() === 0 ? '' : `:${String(d.getMinutes()).padStart(2, '0')}`;
  return `${hour}${minutes} ${d.getHours() < 12 ? 'am' : 'pm'}`;
}

/** "Fri 2 Oct, 11 pm". */
export function dayAndTime(when: When, now: Date = new Date()): string {
  return `${dayName(when, now)}, ${clockTime(when)}`;
}

/** "Friday 2 October, 5 pm" — for a TV, read from across the room. */
export function dayAndTimeInFull(when: When): string {
  const d = asDate(when);
  return `${WEEKDAYS_LONG[d.getDay()]} ${d.getDate()} ${MONTHS_LONG[d.getMonth()]}, ${clockTime(d)}`;
}

/** "1 – 2 Oct", "30 Sep – 2 Oct", "30 Dec 2026 – 2 Jan 2027". */
export function dateSpan(from: When, to: When, now: Date = new Date()): string {
  const a = asDate(from);
  const b = asDate(to);
  if (a.getFullYear() !== b.getFullYear()) return `${dayMonth(a, now, true)} – ${dayMonth(b, now, true)}`;
  const end = dayMonth(b, now);
  if (a.getMonth() === b.getMonth()) {
    return a.getDate() === b.getDate() ? end : `${a.getDate()} – ${end}`;
  }
  return `${dayMonth(a, b)} – ${end}`;
}

/** Whole days since, rounded down — the same count `agoInWords` says. */
export function daysAgo(then: Date, now: Date = new Date()): number {
  return Math.floor((now.getTime() - then.getTime()) / 86_400_000);
}
