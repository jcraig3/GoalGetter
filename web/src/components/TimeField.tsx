import { useId, useState } from 'react';

/** "1:30", "90" or "1:02:03" as seconds; null if it isn't a time. */
export function parseTime(text: string): number | null {
  const value = text.trim();
  if (!value) return null;
  if (/^\d+$/.test(value)) return Number(value);
  const parts = value.split(':');
  if (parts.length > 3 || parts.some((part) => !/^\d+$/.test(part))) return null;
  const [rest, seconds] = [parts.slice(0, -1), Number(parts[parts.length - 1])];
  if (seconds > 59) return null;
  return rest.reduce((total, part) => total * 60 + Number(part), 0) * 60 + seconds;
}

/** Seconds as people say them: 90 → "1:30", 40 → "0:40". */
export function formatTime(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = String(seconds % 60).padStart(2, '0');
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${rest}` : `${minutes}:${rest}`;
}

/**
 * A length of time, typed the way people say it: "1:30" or "90" (Phase 26).
 * The value is seconds, or null while it's empty or not yet a time.
 */
export default function TimeField({
  label,
  seconds,
  onChange,
  placeholder,
  hint,
  min = 0,
  max,
}: {
  label: string;
  seconds: number | null;
  onChange: (seconds: number | null) => void;
  placeholder?: string;
  hint?: string;
  min?: number;
  max?: number;
}) {
  const id = useId();
  const [text, setText] = useState(seconds === null ? '' : formatTime(seconds));
  const parsed = parseTime(text);
  const problem =
    text.trim() && parsed === null
      ? 'Write it as minutes and seconds, like 1:30, or as seconds.'
      : parsed !== null && parsed < min
        ? `At least ${formatTime(min)}.`
        : parsed !== null && max !== undefined && parsed > max
          ? `At most ${formatTime(max)}.`
          : null;
  return (
    <div>
      <label htmlFor={id} className="block text-sm text-content-muted">
        {label}
      </label>
      <input
        id={id}
        value={text}
        inputMode="numeric"
        placeholder={placeholder}
        onChange={(e) => {
          const next = e.target.value;
          setText(next);
          const value = parseTime(next);
          onChange(value);
        }}
        className={`mt-1 block w-full rounded-md border bg-bg px-3 py-2 text-sm text-content outline-none focus:border-brand ${
          problem ? 'border-danger' : 'border-edge'
        }`}
      />
      <p className={`mt-1 text-xs ${problem ? 'text-danger' : 'text-content-subtle'}`}>{problem ?? hint}</p>
    </div>
  );
}
