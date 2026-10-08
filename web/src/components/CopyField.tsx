import { useState } from 'react';

/**
 * A read-only value with a Copy button.
 *
 * For the things an admin has to move to another system by hand: a webhook
 * endpoint, a redirect URI. Read-only rather than disabled, so the text can
 * still be selected, and selected on focus so it can be copied without a mouse.
 *
 * `HandoffLink` does something similar for invitation links, wrapped in the
 * dismissible one-time framing that context needs. Merging the two is a
 * mechanical change that belongs in its own pass rather than in the middle of
 * this one.
 */
export default function CopyField({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Denied over plain HTTP or without a gesture. The value is on screen and
      // selectable, so there is another way to get it and nothing to report.
    }
  }

  return (
    <div>
      <p className="text-sm text-content-muted">{label}</p>
      <div className="mt-1 flex gap-2">
        <input
          readOnly
          value={value}
          aria-label={label}
          onFocus={(e) => e.currentTarget.select()}
          className="min-w-0 flex-1 rounded-md border border-edge bg-bg px-3 py-2 font-mono text-sm text-content"
        />
        <button
          type="button"
          onClick={() => void copy()}
          className="shrink-0 rounded-md bg-brand px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover"
        >
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      {hint && <p className="mt-1 text-xs text-content-muted">{hint}</p>}
    </div>
  );
}
