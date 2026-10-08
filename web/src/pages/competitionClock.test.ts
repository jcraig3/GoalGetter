import { describe, expect, it } from 'vitest';

import {
  countdown,
  endTime,
  fromLocalInput,
  toLocalInput,
  canCancel,
  canDelete,
  canUnpublish,
  phaseHelp,
  phaseLabel,
  phaseOf,
  phaseTone,
  place,
  remaining,
  statusLine,
  tabOf,
  tickInterval,
  type Clock,
} from './competitionClock';

const NOW = new Date('2026-09-10T12:00:00Z');

function clock(overrides: Partial<Clock> = {}): Clock {
  return {
    state: 'active',
    starts_at: '2026-09-01T00:00:00Z',
    ends_at: '2026-09-15T00:00:00Z',
    settles_at: '2026-09-16T00:00:00Z',
    ...overrides,
  };
}

describe('countdown', () => {
  it('shows two units, never three', () => {
    // "2d 4h 17m 3s" is a thing you have to read. "2d 4h" is a glance.
    expect(countdown(2 * 86400000 + 4 * 3600000 + 17 * 60000 + 3000)).toBe('2d 4h');
  });

  it('truncates the larger unit rather than rounding it', () => {
    // 47 hours is "1d 23h". Calling it "2d" would promise a day that is not
    // there — and for a deadline, promising extra time is the wrong direction to
    // be wrong in.
    expect(countdown(47 * 3600000)).toBe('1d 23h');
  });

  it('drops to hours and minutes inside a day', () => {
    expect(countdown(5 * 3600000 + 30 * 60000)).toBe('5h 30m');
  });

  it('counts seconds in the last minute', () => {
    expect(countdown(45000)).toBe('45s');
  });

  it('shows minutes and seconds under an hour', () => {
    expect(countdown(9 * 60000 + 5000)).toBe('9m 5s');
  });

  it('keeps the second unit when it is zero', () => {
    // "3d 0h" rather than "3d". Dropping it makes the width jump around in a
    // list, and a stable width is most of why the pair is fixed at two.
    expect(countdown(3 * 86400000)).toBe('3d 0h');
  });

  it('says "now" rather than counting backwards', () => {
    expect(countdown(0)).toBe('now');
    expect(countdown(-5000)).toBe('now');
  });
});

describe('remaining', () => {
  it('measures forward to the deadline', () => {
    expect(remaining('2026-09-10T13:30:00Z', NOW)).toBe(90 * 60000);
  });

  it('floors at zero once the deadline has passed', () => {
    // A negative would format as a countdown running backwards.
    expect(remaining('2026-09-09T00:00:00Z', NOW)).toBe(0);
  });
});

describe('phaseOf', () => {
  it('reads the stored state, not the dates', () => {
    // The two legitimately disagree for up to one job interval: a contest whose
    // end passed a minute ago is still `active` until advance() runs. In that
    // gap the stored state is the one that knows whether the result is frozen,
    // and a page that decided for itself would print "final" beside numbers
    // still moving.
    const ended = clock({ state: 'active', ends_at: '2026-09-05T00:00:00Z' });
    expect(phaseOf(ended)).toBe('running');
  });

  it.each([
    ['draft', 'draft'],
    ['scheduled', 'upcoming'],
    ['active', 'running'],
    ['ended', 'provisional'],
    ['closed', 'finished'],
    ['cancelled', 'cancelled'],
  ])('maps %s to %s', (state, expected) => {
    expect(phaseOf(clock({ state }))).toBe(expected);
  });
});

describe('tabOf', () => {
  it('files a provisional competition with the live ones', () => {
    // It has ended but has no result yet. Under "Finished" with no winner beside
    // it, it reads as a bug.
    expect(tabOf(clock({ state: 'ended' }))).toBe('live');
  });

  it('files cancelled with finished', () => {
    expect(tabOf(clock({ state: 'cancelled' }))).toBe('finished');
  });

  it.each([
    ['draft', 'drafts'],
    ['scheduled', 'upcoming'],
    ['active', 'live'],
    ['closed', 'finished'],
  ])('files %s under %s', (state, expected) => {
    expect(tabOf(clock({ state }))).toBe(expected);
  });
});

describe('statusLine', () => {
  it('counts down to the start of an upcoming competition', () => {
    const soon = clock({ state: 'scheduled', starts_at: '2026-09-12T12:00:00Z' });
    expect(statusLine(soon, NOW)).toBe('Starts in 2d 0h');
  });

  it('counts down to the end of a running one', () => {
    expect(statusLine(clock(), NOW)).toBe('4d 12h left');
  });

  it('explains what provisional means rather than just saying it', () => {
    // The one status line that has to teach a word. Everywhere else the phase is
    // self-evident; "provisional" alone reads as "broken".
    const line = statusLine(clock({ state: 'ended' }), NOW);
    expect(line).toContain('late data');
    expect(line).toContain('5d 12h');
  });

  it('says nothing about time for a finished competition', () => {
    expect(statusLine(clock({ state: 'closed' }), NOW)).toBe('Final result');
  });

  it('is explicit that a cancelled competition has no winner', () => {
    expect(statusLine(clock({ state: 'cancelled' }), NOW)).toBe('Cancelled — no result');
  });
});

describe('tickInterval', () => {
  it('ticks every second only when seconds are on screen', () => {
    expect(tickInterval(30 * 60000)).toBe(1000);
  });

  it('ticks once a minute inside a day', () => {
    expect(tickInterval(5 * 3600000)).toBe(60000);
  });

  it('slows right down for a week-long gap', () => {
    // Ticking a week-long countdown every second is 3,599 renders an hour that
    // produce identical pixels.
    expect(tickInterval(7 * 86400000)).toBe(600000);
  });

  it('does not spin when there is no time left', () => {
    expect(tickInterval(0)).toBe(3600000);
  });
});

describe('datetime-local conversion', () => {
  const NY = 'America/New_York';

  it('round-trips an instant through the input format', () => {
    // The pair has to compose, or a form that loads a competition and saves it
    // again without touching the dates would move it.
    const iso = '2026-09-01T17:30:00.000Z';
    expect(fromLocalInput(toLocalInput(iso, NY), NY)).toBe(iso);
  });

  it("reads and writes the organization's clock, not the browser's", () => {
    // QA-14: an admin in Pacific typing 5pm for a New York floor meant New
    // York's 5pm. Whatever zone this test runs in, the answer is the same.
    expect(fromLocalInput('2026-10-02T17:00', NY)).toBe('2026-10-02T21:00:00.000Z');
    expect(toLocalInput('2026-10-02T21:00:00Z', NY)).toBe('2026-10-02T17:00');
    expect(fromLocalInput('2026-10-02T17:00', 'America/Los_Angeles')).toBe(
      '2026-10-03T00:00:00.000Z',
    );
  });

  it('uses the offset in force on the day, across a clock change', () => {
    // New York leaves daylight time on 1 November 2026.
    expect(fromLocalInput('2026-10-31T09:00', NY)).toBe('2026-10-31T13:00:00.000Z');
    expect(fromLocalInput('2026-11-02T09:00', NY)).toBe('2026-11-02T14:00:00.000Z');
  });

  it('writes midnight as 00, never 24', () => {
    expect(toLocalInput('2026-10-03T04:00:00Z', NY)).toBe('2026-10-03T00:00');
  });

  it('produces the exact shape the control requires', () => {
    expect(toLocalInput('2026-09-01T17:30:00Z', NY)).toMatch(
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/,
    );
  });

  it('refuses a date with no time rather than guessing at midnight', () => {
    expect(fromLocalInput('2026-09-01', NY)).toBeNull();
  });

  it('refuses empty and malformed input', () => {
    expect(fromLocalInput('', NY)).toBeNull();
    expect(fromLocalInput('not a date', NY)).toBeNull();
    expect(fromLocalInput('2026-13-45T99:99', NY)).toBeNull();
    expect(fromLocalInput('2026-02-30T09:00', NY)).toBeNull();
  });

  it('returns empty rather than "NaN-NaN-NaN" for an unparseable instant', () => {
    expect(toLocalInput('nonsense', NY)).toBe('');
  });
});

describe('place', () => {
  it.each([
    [1, '1st'],
    [2, '2nd'],
    [3, '3rd'],
    [4, '4th'],
    [21, '21st'],
    [22, '22nd'],
    [23, '23rd'],
    [101, '101st'],
  ])('names %i as %s', (rank, expected) => {
    expect(place(rank)).toBe(expected);
  });

  it.each([
    [11, '11th'],
    [12, '12th'],
    [13, '13th'],
    [111, '111th'],
    [112, '112th'],
    [113, '113th'],
  ])('takes "th" for %i despite its last digit', (rank, expected) => {
    // The whole reason this is a function and not a lookup on the last digit.
    // A naive version reads "11st".
    expect(place(rank)).toBe(expected);
  });
});

describe('lifecycle presentation', () => {
  it('names every phase', () => {
    // Exhaustive on purpose: a phase with no label renders as blank, and a blank
    // status pill is worse than a wrong one.
    const phases = [
      'draft', 'upcoming', 'running', 'provisional', 'finished', 'cancelled',
    ] as const;
    for (const phase of phases) {
      expect(phaseLabel(phase)).not.toBe('');
      expect(phaseHelp(phase)).not.toBe('');
    }
  });

  it('says whether anyone else can see it', () => {
    // The difference between draft and scheduled is otherwise invisible, and it
    // is the thing somebody building a contest most needs to know.
    expect(phaseHelp('draft')).toContain('Only you');
    expect(phaseHelp('upcoming')).toContain('Entrants can see it');
  });

  it('reserves warning for the provisional gap', () => {
    expect(phaseTone('provisional')).toBe('warning');
    expect(phaseTone('running')).toBe('live');
    expect(phaseTone('finished')).toBe('neutral');
    expect(phaseTone('cancelled')).toBe('neutral');
  });

  it('offers back-to-draft everywhere except draft and final', () => {
    expect(canUnpublish('upcoming')).toBe(true);
    expect(canUnpublish('running')).toBe(true);
    expect(canUnpublish('provisional')).toBe(true);
    expect(canUnpublish('cancelled')).toBe(true);
    expect(canUnpublish('draft')).toBe(false);
    // Its result has been announced. Reopening would make a winner provisional
    // after the fact.
    expect(canUnpublish('finished')).toBe(false);
  });

  it('only allows deleting what never produced a result', () => {
    expect(canDelete('draft')).toBe(true);
    expect(canDelete('cancelled')).toBe(true);
    expect(canDelete('running')).toBe(false);
    expect(canDelete('provisional')).toBe(false);
    // The record of a prize somebody received.
    expect(canDelete('finished')).toBe(false);
  });

  it('does not offer cancel where it would mean nothing', () => {
    // A draft has nothing to cancel — delete it. A finished contest has a
    // result, and a cancelled one is already stopped.
    expect(canCancel('draft')).toBe(false);
    expect(canCancel('finished')).toBe(false);
    expect(canCancel('cancelled')).toBe(false);
    expect(canCancel('upcoming')).toBe(true);
    expect(canCancel('running')).toBe(true);
    expect(canCancel('provisional')).toBe(true);
  });

  it('never offers delete and cancel at the same time', () => {
    // They would read as two words for the same thing. Exactly one destructive
    // action per phase, or none.
    const phases = [
      'draft', 'upcoming', 'running', 'provisional', 'finished', 'cancelled',
    ] as const;
    for (const phase of phases) {
      expect(canDelete(phase) && canCancel(phase)).toBe(false);
    }
  });
});

describe('a scheduled contest whose start has arrived', () => {
  it('says "Starting now" rather than "Starts in now"', () => {
    // `countdown(0)` returns "now", so the old template produced "Starts in now",
    // which reads as a bug. Publishing an already-begun contest no longer lands
    // here, but one scheduled in advance still crosses its start while a page is
    // open — the job promotes it on its next pass, not instantly.
    const due = clock({ state: 'scheduled', starts_at: '2026-09-10T12:00:00Z' });
    expect(statusLine(due, NOW)).toBe('Starting now');
  });

  it('still counts down before then', () => {
    const later = clock({ state: 'scheduled', starts_at: '2026-09-10T15:00:00Z' });
    expect(statusLine(later, NOW)).toBe('Starts in 3h 0m');
  });

  it('says "Starting now" for a start already in the past', () => {
    const overdue = clock({ state: 'scheduled', starts_at: '2026-09-09T12:00:00Z' });
    expect(statusLine(overdue, NOW)).toBe('Starting now');
  });
});

describe('endTime', () => {
  const now = new Date('2026-09-25T12:00:00Z');
  const at = (hours: number) =>
    new Date(now.getTime() + hours * 60 * 60 * 1000).toISOString();

  it('the default is the compact countdown', () => {
    expect(endTime(at(50), now, 'default')).toBe('2d 2h left');
  });

  it('simple says one unit, in words', () => {
    // "2 days left" reads at a glance from across a lobby in a way
    // "1d 23h left" does not.
    expect(endTime(at(50), now, 'simple')).toBe('2 days left');
    expect(endTime(at(5), now, 'simple')).toBe('5 hours left');
  });

  it('simple says the singular when there is one of something', () => {
    expect(endTime(at(25), now, 'simple')).toBe('1 day left');
    expect(endTime(at(1.5), now, 'simple')).toBe('1 hour left');
  });

  it('simple never says "0 minutes left"', () => {
    // A contest with forty seconds on it is still running, and zero is the one
    // number that reads as finished.
    expect(endTime(at(0.01), now, 'simple')).toBe('1 minute left');
  });

  it('full says the date, so nobody has to do arithmetic', () => {
    const said = endTime(at(50), now, 'full');

    expect(said?.startsWith('Ends ')).toBe(true);
    expect(said).not.toContain('left');
  });

  it('off says nothing at all', () => {
    // Null rather than an empty string: an empty element still takes a line.
    expect(endTime(at(50), now, 'off')).toBeNull();
  });

  it('a deadline already passed is not a negative countdown', () => {
    expect(endTime(at(-3), now, 'default')).toBe('Ends now');
    expect(endTime(at(-3), now, 'simple')).toBe('Ends now');
  });

  it('but "full" still says when it ended', () => {
    // A finished contest whose slide is still up should say the date it ended,
    // not "Ends now" for ever.
    expect(endTime(at(-3), now, 'full')?.startsWith('Ends ')).toBe(true);
  });
});
