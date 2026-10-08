/**
 * What a disabled button is waiting for, beside it.
 *
 * A greyed-out "Create rule" with no reason left somebody hunting for what was
 * missing (review §6). Each check is a condition and what to say while it
 * holds; the first that holds is said. Nothing shows once all are met.
 */
export default function MissingHint({ checks }: { checks: [boolean, string][] }) {
  const reason = checks.find(([missing]) => missing)?.[1];
  if (!reason) return null;
  return <span className="text-xs text-content-muted">{reason}</span>;
}
