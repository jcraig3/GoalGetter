import { useEffect, useState } from 'react';

/**
 * **What a wall shows out of hours** (6.10), instead of its rotation.
 *
 * `clock` is a large clock and the date, for a room that is still in use but
 * whose numbers have gone quiet — and for a channel whose slides are all
 * scheduled for some other time, which would otherwise be a black screen that
 * looks broken. `dark` is near-black with a small dim clock, for an empty
 * office at night.
 *
 * **Both drift.** A television left on one still image all night keeps a
 * ghost of it, so the clock wanders slowly round the screen on two
 * different, unrelated periods — it never retraces the same path closely
 * enough to wear one in.
 *
 * Told in the organization's time zone rather than the television's, which is
 * routinely set to wherever it was made.
 */
export default function QuietScreen({
  mode,
  until,
  timeZone,
  channelName,
  now,
}: {
  mode: 'clock' | 'dark';
  /** When night mode ends, as ISO. Null for "nothing scheduled", which ends
   *  whenever a slide's hours come round. */
  until: string | null;
  timeZone: string;
  channelName: string;
  /** The shared clock — see `wallClock.ts`. */
  now: () => number;
}) {
  const [at, setAt] = useState(() => now());
  useEffect(() => {
    const timer = window.setInterval(() => setAt(now()), 1000);
    return () => window.clearInterval(timer);
  }, [now]);

  const dark = mode === 'dark';
  const { x, y } = driftAt(at, dark ? 38 : 22, dark ? 40 : 24);
  const time = formatIn(timeZone, at, { hour: 'numeric', minute: '2-digit' });
  const date = formatIn(timeZone, at, { weekday: 'long', month: 'long', day: 'numeric' });
  const back = until ? backAt(timeZone, at, new Date(until).getTime()) : null;

  return (
    <div
      data-testid="quiet-screen"
      data-mode={mode}
      className="absolute inset-0 overflow-hidden"
      style={{
        background: dark
          ? '#020203'
          : 'radial-gradient(ellipse at 50% 40%, #151b2b 0%, #080a10 70%)',
      }}
    >
      <div
        className="absolute text-center"
        style={{
          left: `${x}%`,
          top: `${y}%`,
          transform: 'translate(-50%, -50%)',
          // An absolutely placed box near the right edge shrinks to the room
          // left, which would break "4:28 PM" over two lines.
          whiteSpace: 'nowrap',
          // Moved once a second; the transition makes that a glide.
          transition: 'left 1s linear, top 1s linear',
          color: dark ? 'rgba(226, 232, 240, 0.32)' : '#f1f5f9',
        }}
      >
        <p
          className="font-semibold tabular-nums leading-none tracking-tight"
          style={{ fontSize: dark ? 88 : 220 }}
        >
          {time}
        </p>
        {!dark && (
          <>
            <p className="mt-6 text-5xl" style={{ color: 'rgba(241, 245, 249, 0.7)' }}>
              {date}
            </p>
            <p className="mt-10 text-2xl" style={{ color: 'rgba(241, 245, 249, 0.4)' }}>
              {channelName}
              {back && ` · back ${back}`}
            </p>
          </>
        )}
      </div>
    </div>
  );
}

/**
 * Where the clock is at a moment, as a percentage of the screen: two slow
 * sine waves with periods that share no factor (seven and eleven minutes), so
 * the path takes over an hour to repeat. The same on every screen on a
 * channel, because it runs from the shared clock.
 */
export function driftAt(ms: number, ampX: number, ampY: number): { x: number; y: number } {
  const minutes = ms / 60_000;
  return {
    x: 50 + ampX * Math.sin((2 * Math.PI * minutes) / 7),
    y: 50 + ampY * Math.sin((2 * Math.PI * minutes) / 11),
  };
}

/** "at 7:00 AM" later today, "Mon 7:00 AM" on another day. */
export function backAt(timeZone: string, now: number, until: number): string {
  const day = { year: 'numeric', month: 'numeric', day: 'numeric' } as const;
  const time = formatIn(timeZone, until, { hour: 'numeric', minute: '2-digit' });
  return formatIn(timeZone, now, day) === formatIn(timeZone, until, day)
    ? `at ${time}`
    : `${formatIn(timeZone, until, { weekday: 'short' })} ${time}`;
}

function formatIn(timeZone: string, ms: number, options: Intl.DateTimeFormatOptions): string {
  try {
    return new Intl.DateTimeFormat(undefined, { ...options, timeZone }).format(ms);
  } catch {
    // An unknown zone on an old television: its own time beats nothing.
    return new Intl.DateTimeFormat(undefined, options).format(ms);
  }
}
