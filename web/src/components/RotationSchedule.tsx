import type { Dispatch, SetStateAction } from "react";

/**
 * **When a slide plays, and when a wall goes quiet** (6.10).
 *
 * The rules themselves are the server's — see `api/app/schedule.py` — and
 * are worked out in the organization's time. These are the controls, and the
 * words that describe what was chosen in a list.
 */

/** Monday first, matching the server's 0 = Monday. */
export const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const WEEKDAYS = [0, 1, 2, 3, 4];
const WEEKEND = [5, 6];

export interface SlideSchedule {
  /** Null is every day. */
  days: number[] | null;
  /** "HH:MM", or '' for open. */
  from: string;
  until: string;
  weight: number;
}

/** The API sends "09:00:00"; a time input wants "09:00". */
export function hhmm(value: string | null | undefined): string {
  return value ? value.slice(0, 5) : "";
}

/** "9 am", "5:30 pm" — how a schedule reads in a list. */
export function clockWords(value: string): string {
  const [h, m] = value.split(":").map(Number) as [number, number];
  const suffix = h < 12 ? "am" : "pm";
  const hour = h % 12 === 0 ? 12 : h % 12;
  return m
    ? `${hour}:${String(m).padStart(2, "0")} ${suffix}`
    : `${hour} ${suffix}`;
}

function same(a: number[], b: number[]) {
  return a.length === b.length && a.every((d, i) => d === b[i]);
}

export function dayWords(days: number[] | null): string | null {
  if (!days || days.length === 7) return null;
  const sorted = [...days].sort();
  if (same(sorted, WEEKDAYS)) return "Weekdays";
  if (same(sorted, WEEKEND)) return "Weekends";
  return sorted.map((d) => DAY_LABELS[d]).join(", ");
}

/**
 * One line for the slide list: "Weekdays · 9 am–noon · 2×". Null when the
 * slide plays all the time at its ordinary weight, which is almost every
 * slide — a list where every row says "always" stops being read.
 */
export function describeSchedule(s: {
  days: number[] | null;
  play_from: string | null;
  play_until: string | null;
  weight: number;
}): string | null {
  const parts: string[] = [];
  const days = dayWords(s.days);
  if (days) parts.push(days);
  const from = hhmm(s.play_from);
  const until = hhmm(s.play_until);
  if (from && until) parts.push(`${clockWords(from)}–${clockWords(until)}`);
  else if (from) parts.push(`from ${clockWords(from)}`);
  else if (until) parts.push(`until ${clockWords(until)}`);
  if (s.weight > 1) parts.push(`${s.weight}× a cycle`);
  return parts.length ? parts.join(" · ") : null;
}

const chip =
  "rounded-full border px-3 py-1 text-xs transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand";
const chipOn = "border-brand bg-brand/10 text-content";
const chipOff =
  "border-edge text-content-muted hover:bg-surface-hover hover:text-content";

const timeInput =
  "mt-1 w-full rounded-md border border-edge bg-bg px-3 py-2 text-content outline-none focus:border-brand";

/** The "When it plays" section of the slide form. */
export function ScheduleFields({
  value,
  onChange,
}: {
  value: SlideSchedule;
  onChange: Dispatch<SetStateAction<SlideSchedule>>;
}) {
  const days = value.days ?? [0, 1, 2, 3, 4, 5, 6];
  // From the latest state, not this render's: two changes in one tick must
  // not undo each other.
  const set = (patch: Partial<SlideSchedule>) =>
    onChange((was) => ({ ...was, ...patch }));

  function toggle(day: number) {
    onChange((was) => {
      const had = was.days ?? [0, 1, 2, 3, 4, 5, 6];
      const next = had.includes(day)
        ? had.filter((d) => d !== day)
        : [...had, day].sort();
      // Every day is stored as "every day", so the two cannot drift apart.
      return { ...was, days: next.length === 7 ? null : next };
    });
  }

  const overnight = value.from && value.until && value.from > value.until;

  return (
    // The rule is on a wrapper rather than the fieldset, whose border a
    // legend would cut through.
    <div className="border-t border-edge pt-4">
      <fieldset className="space-y-3">
        <legend className="mb-3 text-sm font-medium text-content">
          When it plays
        </legend>

        <div>
          <p className="text-sm text-content-muted" id="slide-days">
            Days
          </p>
          <div
            className="mt-1 flex flex-wrap gap-1.5"
            role="group"
            aria-labelledby="slide-days"
          >
            {DAY_LABELS.map((label, day) => (
              <button
                key={label}
                type="button"
                aria-pressed={days.includes(day)}
                onClick={() => toggle(day)}
                className={`${chip} ${days.includes(day) ? chipOn : chipOff}`}
              >
                {label}
              </button>
            ))}
            <span className="mx-1 self-center text-content-subtle">·</span>
            <button
              type="button"
              onClick={() => set({ days: null })}
              className={`${chip} ${value.days === null ? chipOn : chipOff}`}
            >
              Every day
            </button>
            <button
              type="button"
              onClick={() => set({ days: WEEKDAYS })}
              className={`${chip} ${value.days && same([...value.days].sort(), WEEKDAYS) ? chipOn : chipOff}`}
            >
              Weekdays
            </button>
          </div>
          {days.length === 0 && (
            <p className="mt-1 text-xs text-danger">Choose at least one day.</p>
          )}
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label
              htmlFor="slide-from"
              className="block text-sm text-content-muted"
            >
              From (optional)
            </label>
            <input
              id="slide-from"
              type="time"
              value={value.from}
              onChange={(e) => set({ from: e.target.value })}
              className={timeInput}
            />
          </div>
          <div>
            <label
              htmlFor="slide-until"
              className="block text-sm text-content-muted"
            >
              Until (optional)
            </label>
            <input
              id="slide-until"
              type="time"
              value={value.until}
              onChange={(e) => set({ until: e.target.value })}
              className={timeInput}
            />
          </div>
        </div>
        <p className="-mt-1 text-xs text-content-muted">
          {overnight
            ? "Runs overnight, into the next morning."
            : "Leave both empty to play all day. In your organization's time."}
        </p>

        <div>
          <p className="text-sm text-content-muted" id="slide-weight">
            How often
          </p>
          <div
            className="mt-1 flex flex-wrap gap-1.5"
            role="group"
            aria-labelledby="slide-weight"
          >
            {[1, 2, 3, 4].map((n) => (
              <button
                key={n}
                type="button"
                aria-pressed={value.weight === n}
                onClick={() => set({ weight: n })}
                className={`${chip} ${value.weight === n ? chipOn : chipOff}`}
              >
                {n === 1 ? "Once a cycle" : `${n}×`}
              </button>
            ))}
          </div>
          <p className="mt-1 text-xs text-content-muted">
            More than once comes round evenly spaced, never back to back.
          </p>
        </div>
      </fieldset>
    </div>
  );
}

export interface QuietSettings {
  mode: "off" | "clock" | "dark";
  from: string;
  until: string;
  weekends: boolean;
}

const QUIET_MODES: {
  value: QuietSettings["mode"];
  label: string;
  hint: string;
}[] = [
  { value: "off", label: "Off", hint: "The rotation plays around the clock." },
  {
    value: "clock",
    label: "Clock",
    hint: "A large clock and the date, drifting slowly.",
  },
  {
    value: "dark",
    label: "Dark",
    hint: "Near-black, with a small dim clock that moves.",
  },
];

/** Night mode, in the channel's settings. */
export function QuietFields({
  value,
  onChange,
}: {
  value: QuietSettings;
  onChange: Dispatch<SetStateAction<QuietSettings>>;
}) {
  const set = (patch: Partial<QuietSettings>) =>
    onChange((was) => ({ ...was, ...patch }));
  const chosen = QUIET_MODES.find((m) => m.value === value.mode)!;

  return (
    // The rule is on a wrapper rather than the fieldset, whose border a
    // legend would cut through.
    <div className="border-t border-edge pt-4">
      <fieldset className="space-y-3">
        <legend className="mb-3 text-sm font-medium text-content">
          Night mode
        </legend>
        <div
          className="flex flex-wrap gap-1.5"
          role="group"
          aria-label="Night mode"
        >
          {QUIET_MODES.map((m) => (
            <button
              key={m.value}
              type="button"
              aria-pressed={value.mode === m.value}
              onClick={() =>
                set({
                  mode: m.value,
                  // A sensible evening to start from, rather than empty boxes.
                  ...(m.value !== "off" && !value.from && !value.until
                    ? { from: "19:00", until: "07:00" }
                    : {}),
                })
              }
              className={`${chip} ${value.mode === m.value ? chipOn : chipOff}`}
            >
              {m.label}
            </button>
          ))}
        </div>
        <p className="text-xs text-content-muted">
          {chosen.hint}
          {value.mode !== "off" &&
            " Both move, so nothing burns into the screen. Wins wait for the morning; previews you send still show."}
        </p>

        {value.mode !== "off" && (
          <>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label
                  htmlFor="quiet-from"
                  className="block text-sm text-content-muted"
                >
                  From
                </label>
                <input
                  id="quiet-from"
                  type="time"
                  value={value.from}
                  onChange={(e) => set({ from: e.target.value })}
                  className={timeInput}
                />
              </div>
              <div>
                <label
                  htmlFor="quiet-until"
                  className="block text-sm text-content-muted"
                >
                  Until
                </label>
                <input
                  id="quiet-until"
                  type="time"
                  value={value.until}
                  onChange={(e) => set({ until: e.target.value })}
                  className={timeInput}
                />
              </div>
            </div>
            <label className="flex items-start gap-2 text-sm text-content">
              <input
                type="checkbox"
                className="mt-0.5"
                checked={value.weekends}
                onChange={(e) => set({ weekends: e.target.checked })}
              />
              <span>
                All weekend too
                <span className="block text-xs text-content-subtle">
                  Saturday and Sunday stay quiet all day, not only overnight.
                </span>
              </span>
            </label>
          </>
        )}
      </fieldset>
    </div>
  );
}
