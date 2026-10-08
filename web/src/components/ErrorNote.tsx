import { useEffect, useState } from 'react';

/**
 * An error somebody can put away.
 *
 * **Because the useful errors here are long.** The messages this product gives
 * for a Microsoft misconfiguration run to a paragraph — which permission, which
 * *type* of permission, what to press and in what order — and that length is
 * earned: the short version of one of them cost an afternoon of consenting to the
 * wrong thing. But a paragraph that cannot be dismissed sits on the screen
 * pushing everything else down long after it has been read and acted on.
 *
 * So: clamped to three lines with the rest one click away, and a dismiss button.
 *
 * **Auto-dismiss is deliberately slow, and never the only way out.** Ten seconds
 * is not enough to read a paragraph, act on it, and check something in another
 * tab — an error that vanishes mid-read is worse than one that overstays. A
 * minute is long enough to have finished with it, and the × is there from the
 * first moment for anybody quicker than that.
 */
export default function ErrorNote({
  message,
  onDismiss,
  after = 60,
}: {
  message: string;
  onDismiss: () => void;
  /** Seconds before it clears itself. Zero keeps it until dismissed. */
  after?: number;
}) {
  const [expanded, setExpanded] = useState(false);

  // Keyed on the message, so a *new* error restarts the clock rather than
  // inheriting the remains of the last one's.
  useEffect(() => {
    if (!after) return;
    const timer = setTimeout(onDismiss, after * 1000);
    return () => clearTimeout(timer);
  }, [message, after, onDismiss]);

  // Long enough that clamping earns its place. Short messages are left alone —
  // a "Show more" on two lines is more furniture than it saves.
  const long = message.length > 180;

  return (
    <div
      role="alert"
      className="mb-4 flex items-start gap-3 rounded-md border border-danger px-3 py-2 text-sm text-danger"
    >
      <div className="min-w-0 flex-1">
        <p className={!expanded && long ? 'line-clamp-3' : undefined}>{message}</p>
        {long && (
          <button
            type="button"
            onClick={() => setExpanded((open) => !open)}
            className="mt-1 text-xs underline opacity-80 hover:opacity-100"
          >
            {expanded ? 'Show less' : 'Show more'}
          </button>
        )}
      </div>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Dismiss"
        className="shrink-0 rounded px-1 leading-none opacity-70 transition-opacity hover:opacity-100"
      >
        ×
      </button>
    </div>
  );
}
