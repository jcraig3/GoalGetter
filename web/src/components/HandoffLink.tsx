import { useState, type ReactNode } from 'react';

/**
 * A single-use link for an admin to copy and hand over.
 *
 * Used by invitations and password resets — the same mechanism with different
 * wording, so one component rather than two that drift. Deliberately not only
 * emailed: many internal deployments have no SMTP on day one, and the tool has
 * to be fully usable without it. Pasting the link into Slack works, and email
 * becomes an enhancement rather than a dependency.
 */
export default function HandoffLink({
  message,
  link,
  onDismiss,
}: {
  message: ReactNode;
  link: string;
  onDismiss: () => void;
}) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access can be denied — over plain HTTP, or without a user
      // gesture. The link is visible and selectable, so there is still a way to
      // get it and no need to fail loudly.
    }
  }

  return (
    <div className="mt-6 rounded-lg border border-brand bg-brand-subtle p-4">
      <div className="flex items-start justify-between gap-4">
        <p className="text-sm text-content">{message}</p>
        <button
          onClick={onDismiss}
          className="shrink-0 text-xs text-content-muted hover:text-content"
        >
          Dismiss
        </button>
      </div>
      <div className="mt-3 flex gap-2">
        <input
          readOnly
          value={link}
          aria-label="Link to copy"
          // Selecting on focus so keyboard users can copy without a mouse.
          onFocus={(e) => e.currentTarget.select()}
          className="min-w-0 flex-1 rounded-md border border-edge bg-bg px-3 py-2 text-sm text-content"
        />
        <button
          onClick={() => void copy()}
          className="shrink-0 rounded-md bg-brand px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover"
        >
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
    </div>
  );
}
