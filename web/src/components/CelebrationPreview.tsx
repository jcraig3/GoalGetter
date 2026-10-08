import { useEffect, useRef } from 'react';

import type { Celebration } from '../pages/celebrationQueue';
import AnnouncementScreen from './AnnouncementScreen';

/** An announcement as a preview endpoint returns it: no place in a timetable. */
export type CelebrationShape = Omit<Celebration, 'id' | 'created_at' | 'starts_at' | 'ends_at'>;

/** A preview's announcement, scheduled to start the moment it is pressed. */
export function startingNow(shape: CelebrationShape): Celebration {
  const now = Date.now();
  return {
    ...shape,
    id: `preview:${now}`,
    created_at: new Date(now).toISOString(),
    starts_at: now,
    ends_at: now + shape.hold_seconds * 1000,
  };
}

/**
 * The announcement, full-screen in the editor, for as long as it would hold a
 * wall — and then gone.
 *
 * **It goes away on its own**, and says how to make it go sooner. The "send a
 * test to the wall" button removed in 4f was removed partly because its
 * screen would not go away; this one closes when the clip ends, on Escape, or
 * on its own button, whichever comes first.
 *
 * Shared by the walk-up editor and the rule editor (5j).
 *
 * Pressing Preview is a click, which is what lets a browser play it with
 * sound — so the preview is heard as the wall will be heard.
 */
export default function CelebrationPreview({
  celebration,
  label,
  onClose,
}: {
  celebration: Celebration;
  /** What a screen reader announces: "Walk-up preview", "Rule preview". */
  label: string;
  onClose: () => void;
}) {
  // **The close callback is held in a ref, not listed as a dependency.** The
  // editor hands over a fresh arrow function every time it renders, and a
  // timer keyed on that would restart whenever anything behind the preview
  // re-rendered — which is precisely how a screen ends up not going away.
  // Only a new preview should restart the countdown.
  const close = useRef(onClose);
  close.current = onClose;

  useEffect(() => {
    const timer = window.setTimeout(
      () => close.current(),
      celebration.hold_seconds * 1000,
    );
    // **Caught first, and kept.** Played from inside a dialog (the rule
    // editor), the dialog's own Escape would otherwise also fire, and ask
    // whether to throw the form away.
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.stopPropagation();
      close.current();
    };
    window.addEventListener('keydown', onKey, true);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener('keydown', onKey, true);
    };
  }, [celebration]);

  return (
    <AnnouncementScreen
      celebration={celebration}
      label={label}
      // Through the signed-in route: an editor has a session and no display
      // token, which is the only thing that differs from the wall.
      fileUrl={(digest) => `/api/images/${digest}`}
      footer={
        <div className="mt-8 flex items-center justify-center gap-4">
          <span className="rounded bg-black/60 px-3 py-1 text-sm uppercase tracking-widest text-white">
            Preview — only on this screen
          </span>
          <button
            type="button"
            onClick={onClose}
            autoFocus
            className="rounded-md bg-white px-4 py-2 text-sm font-medium text-black"
          >
            Close preview
          </button>
        </div>
      }
    />
  );
}
