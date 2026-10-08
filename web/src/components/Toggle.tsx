export default function Toggle({
  label,
  hint,
  checked,
  onChange,
  disabled,
}: {
  label: string;
  hint?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}) {
  const id = label.toLowerCase().replace(/\s+/g, '-');

  return (
    <div className="flex items-start gap-3">
      {/* A real checkbox rather than a styled div: keyboard, screen readers,
          and form semantics all work for free. Custom toggles usually
          reimplement those badly, or not at all. */}
      <input
        id={id}
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        aria-describedby={hint ? `${id}-hint` : undefined}
        className="mt-0.5 size-4 shrink-0 accent-[var(--gg-brand)]"
      />
      <div>
        <label htmlFor={id} className="text-sm text-content">
          {label}
        </label>
        {hint && (
          <p id={`${id}-hint`} className="text-xs text-content-muted">
            {hint}
          </p>
        )}
      </div>
    </div>
  );
}
