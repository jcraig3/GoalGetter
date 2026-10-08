import { useState } from 'react';

/** A value with a small Copy beside it. */
export default function CopyValue({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <span className="flex min-w-0 items-center gap-2">
      <span className="min-w-0 truncate font-mono" title={text}>
        {text}
      </span>
      <button
        type="button"
        onClick={() =>
          void navigator.clipboard
            ?.writeText(text)
            .then(() => {
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            })
            .catch(() => undefined)
        }
        className="shrink-0 rounded border border-edge px-2 py-0.5 text-xs text-content-muted transition-colors hover:bg-surface-hover hover:text-content"
      >
        {copied ? 'Copied' : 'Copy'}
      </button>
    </span>
  );
}
