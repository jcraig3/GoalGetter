import { Link } from 'react-router-dom';

import { dismiss, useToasts } from '../toast';

/**
 * Where `toast()` shows up: bottom right, above everything, read out politely.
 *
 * `role="status"` rather than an alert: "Goal created" is news, not a problem,
 * and a screen reader should say it when it has finished its sentence rather
 * than interrupting one.
 */
export default function Toasts() {
  const toasts = useToasts();
  return (
    <div
      role="status"
      aria-live="polite"
      className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2"
    >
      {toasts.map((t) => (
        <div
          key={t.id}
          className="pointer-events-auto flex items-center gap-3 rounded-lg border border-edge bg-surface px-4 py-3 text-sm text-content shadow-lg"
        >
          <span aria-hidden="true" className="text-success">
            ✓
          </span>
          <span className="min-w-0 flex-1">{t.message}</span>
          {t.href && (
            <Link
              to={t.href}
              onClick={() => dismiss(t.id)}
              className="shrink-0 font-medium text-brand hover:underline"
            >
              {t.linkLabel}
            </Link>
          )}
          {t.action && (
            <button
              type="button"
              onClick={() => {
                t.action!.run();
                dismiss(t.id);
              }}
              className="shrink-0 font-medium text-brand hover:underline"
            >
              {t.action.label}
            </button>
          )}
          <button
            type="button"
            onClick={() => dismiss(t.id)}
            aria-label="Dismiss"
            className="shrink-0 text-content-subtle hover:text-content"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
