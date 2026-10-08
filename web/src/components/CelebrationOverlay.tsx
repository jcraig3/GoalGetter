import { useEffect, useState } from 'react';

import { pendingCelebrations, useNotifications } from '../notifications';

/** How long a celebration holds the screen before closing itself. Long enough
 *  to read and enjoy, short enough that walking away does not leave the app
 *  unusable behind it. */
const HOLD_MS = 6_000;

/**
 * The moment. One celebration at a time, over whatever you were doing.
 *
 * This is the half of the product that makes it more than a reporting tool:
 * hitting a number produces something visible rather than a row you might find
 * later. It is deliberately the only thing in the app that interrupts, which is
 * why so little qualifies — see the catalogue in `app/events.py`.
 *
 * **Reduced motion is handled in CSS**, globally, in `theme.css` — so this
 * component does not check for it.
 *
 * **Sound and walk-up media are not here.** They belong on the wall screen in
 * 2f, where a room just watched somebody earn it. A song starting at a desk
 * because somebody opened a laptop is a different and much less welcome thing.
 */
export default function CelebrationOverlay() {
  const { notifications, markCelebrated, refresh } = useNotifications();
  const [dismissed, setDismissed] = useState<number[]>([]);

  const pending = pendingCelebrations(notifications).filter(
    (n) => !dismissed.includes(n.id),
  );
  const current = pending[0] ?? null;

  // Close itself. A celebration that needs dismissing is a modal, and a modal
  // is a chore — the opposite of what this is for.
  useEffect(() => {
    if (!current) return;
    const timer = setTimeout(() => void close(current.id), HOLD_MS);
    return () => clearTimeout(timer);
    // `close` is stable enough for this and re-creating the timer on every
    // render would mean it never fires.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current?.id]);

  // Escape closes it, like anything else that covers the screen.
  useEffect(() => {
    if (!current) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape' && current) void close(current.id);
    }
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current?.id]);

  async function close(id: number) {
    // Hidden immediately, recorded afterwards. Waiting for the request would
    // leave it on screen for the length of a round trip after the moment has
    // passed, and if the request fails the worst case is seeing it once more.
    setDismissed((was) => [...was, id]);
    try {
      await markCelebrated(id);
      await refresh();
    } catch {
      // Nothing to tell anybody. It will show again next poll, which is a far
      // better failure than an error dialog on top of a celebration.
    }
  }

  if (!current) return null;

  return (
    <div
      // `alert` rather than `dialog`: it is announced when it appears and it
      // takes no input, so trapping focus would strand a keyboard user in
      // something they cannot act on.
      role="alert"
      aria-live="assertive"
      className="fixed inset-0 z-50 flex items-center justify-center bg-bg/90 p-6 backdrop-blur-sm"
      onClick={() => void close(current.id)}
    >
      <div
        // No JavaScript check for prefers-reduced-motion: theme.css already
        // collapses every animation to 0.01ms under that query, globally. A
        // second implementation in here would be a second thing to keep in
        // step, and the CSS one cannot be forgotten by a new component.
        className="max-w-lg animate-[celebrate_400ms_ease-out] rounded-2xl border border-brand bg-surface px-10 py-12 text-center shadow-2xl"
      >
        <p aria-hidden="true" className="text-6xl">
          🎉
        </p>
        <h2 className="mt-6 text-h2 text-content">{current.title}</h2>
        {current.body && (
          <p className="mt-2 text-content-muted">{current.body}</p>
        )}
        {current.from_name && (
          <p className="mt-4 text-sm text-brand">from {current.from_name}</p>
        )}
        <p className="mt-8 text-xs text-content-subtle">
          {pending.length > 1
            ? `${pending.length - 1} more · click anywhere to continue`
            : 'Click anywhere to dismiss'}
        </p>
      </div>
    </div>
  );
}
