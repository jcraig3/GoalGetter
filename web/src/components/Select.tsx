import type { ReactNode } from 'react';

/**
 * A labelled dropdown.
 *
 * Six pages had each grown their own copy of this, and they had drifted into
 * four different shapes — one taking `children`, one `disabled`, two `hint`, one
 * neither. This is the superset, so a page needing one more prop stops being a
 * reason to fork it again. The existing six still hold their own copies; moving
 * them over is a mechanical change that belongs in its own pass, not in the
 * middle of a feature.
 *
 * `options` or `children`, not both: a list of values is the common case, and
 * `children` is for the times a caller needs `<optgroup>` or a disabled entry.
 */
export default function Select({
  label,
  value,
  onChange,
  options,
  children,
  hint,
  disabled,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options?: { value: string; label: string }[];
  children?: ReactNode;
  hint?: string;
  disabled?: boolean;
}) {
  const id = label.toLowerCase().replace(/\s+/g, '-');
  return (
    <div>
      <label htmlFor={id} className="block text-sm text-content-muted">
        {label}
      </label>
      <select
        id={id}
        value={value}
        disabled={disabled}
        aria-describedby={hint ? `${id}-hint` : undefined}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full rounded-md border border-edge bg-bg px-3 py-2 text-content outline-none focus:border-brand disabled:opacity-60"
      >
        {options
          ? options.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))
          : children}
      </select>
      {hint && (
        <p id={`${id}-hint`} className="mt-1 text-xs text-content-muted">
          {hint}
        </p>
      )}
    </div>
  );
}
