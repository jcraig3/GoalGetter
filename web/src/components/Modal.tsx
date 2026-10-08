import { useEffect, useRef, type ReactNode } from 'react';

import { ask } from '../confirm';

/**
 * A centred dialog over a dimmed page.
 *
 * Hand-rolled rather than `<dialog>`: the native element brings its own
 * top-layer stacking and `::backdrop`, which fight the Tailwind tokens
 * everywhere else, and its polyfill story is worse than the ~40 lines here.
 *
 * Four behaviours people expect from a dialog, each of which is missing often
 * enough to be worth naming:
 *
 *   Escape closes it.
 *   Clicking the backdrop closes it; clicking inside does not.
 *   Focus moves into it on open and returns where it was on close.
 *   The page behind does not scroll.
 *
 * And a fifth: **a form somebody has typed into asks before Escape, the
 * backdrop or × throw it away** (QA-24). Noticed from the typing itself, so no
 * form has to report whether it is dirty; a form's own Cancel button is a
 * decision already made and closes straight away.
 *
 * **On a phone it is a full-screen sheet** (5i): no margin round it, the title
 * and × stay at the top while it scrolls, and the form's action row stays at
 * the bottom (`.gg-sheet-body` in theme.css). The competition form is about
 * 2,000 px tall, and its Publish button used to be a long scroll away.
 */
/** "Keep editing" says which way the other button goes (P5-10). */
function askToDiscard(): Promise<boolean> {
  return ask('Discard your changes?', {
    confirmLabel: 'Discard',
    cancelLabel: 'Keep editing',
    danger: true,
  });
}

export default function Modal({
  title,
  description,
  onClose,
  children,
  wide,
  side,
}: {
  title: string;
  description?: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
  /**
   * Shown beside the form from 1024 px up, and held in view while the form
   * scrolls: the large wall preview of 5j. Narrower than that there is no
   * room beside anything, and the form shows its own smaller preview.
   */
  side?: ReactNode;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const typedInto = useRef(false);

  // **In a ref, so the effect below runs once.** It used to depend on
  // `onClose`, and a parent passing a new arrow on every render re-ran it —
  // re-remembering the "opener" as something inside the dialog, so closing
  // sent focus to the page body instead of the button that opened it (QA-24).
  const close = useRef(onClose);
  close.current = onClose;

  async function requestClose() {
    if (typedInto.current && !(await askToDiscard())) return;
    close.current();
  }
  const requestCloseRef = useRef(requestClose);
  requestCloseRef.current = requestClose;

  useEffect(() => {
    // Remembered before focus moves, so closing returns the user to the
    // control they opened it from rather than the top of the page.
    const opener = document.activeElement as HTMLElement | null;
    panel.current?.focus();

    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') void requestCloseRef.current();
    };
    const onInput = () => {
      typedInto.current = true;
    };
    // **Not only typing** (P4-14): a dropdown, a switch or a picked option is
    // as much an edit, and closing threw those away without asking.
    const onClick = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest('[role="switch"], [aria-pressed], [role="radio"], [role="option"]')) {
        typedInto.current = true;
      }
      // **A form's own Cancel asks too, once something changed** (P5-10).
      // It closed straight away by design (5d), as a decision already made —
      // but with dropdowns now counting as changes, one stray press threw
      // away a whole edit. Caught here, before React's handler sees it, so
      // no form has to know.
      const button = target?.closest('button');
      if (
        typedInto.current &&
        button &&
        button.type !== 'submit' &&
        button.textContent?.trim() === 'Cancel'
      ) {
        event.stopPropagation();
        event.preventDefault();
        void askToDiscard().then((discard) => {
          if (discard) close.current();
        });
      }
    };
    const element = panel.current;
    element?.addEventListener('input', onInput);
    element?.addEventListener('change', onInput);
    element?.addEventListener('click', onClick);
    document.addEventListener('keydown', onKey);

    // Without this the page scrolls behind the dialog, which on a long form
    // silently moves what you come back to.
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    return () => {
      document.removeEventListener('keydown', onKey);
      element?.removeEventListener('input', onInput);
      element?.removeEventListener('change', onInput);
      element?.removeEventListener('click', onClick);
      document.body.style.overflow = previousOverflow;
      opener?.focus?.();
    };
  }, []);

  return (
    <div
      className="fixed inset-0 z-50 flex items-stretch justify-center overflow-y-auto bg-black/60 sm:items-center sm:p-4"
      // Only when the backdrop itself was clicked. Without the target check, a
      // drag that starts inside the panel and ends outside would close it —
      // which is how selecting text in a field dismisses your own form.
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) void requestClose();
      }}
    >
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-title"
        tabIndex={-1}
        className={`min-h-full w-full bg-surface shadow-xl outline-none sm:my-auto sm:min-h-0 sm:rounded-lg sm:border sm:border-edge ${
          side ? 'max-w-2xl lg:max-w-6xl' : wide ? 'max-w-2xl' : 'max-w-md'
        }`}
      >
        <div className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-edge bg-surface px-4 py-4 sm:static sm:rounded-t-lg sm:px-6">
          <div className="min-w-0">
            <h2 id="modal-title" className="text-h3 text-content">
              {title}
            </h2>
            {description && (
              <p className="mt-1 text-sm text-content-muted">{description}</p>
            )}
          </div>
          <button
            onClick={() => void requestClose()}
            aria-label="Close"
            className="shrink-0 rounded-md p-1.5 text-content-muted transition-colors hover:bg-surface-hover hover:text-content"
          >
            <svg
              className="size-5"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.75"
              strokeLinecap="round"
              aria-hidden="true"
            >
              <path d="M6 6l12 12M18 6 6 18" />
            </svg>
          </button>
        </div>

        {side ? (
          <div className="lg:grid lg:grid-cols-[minmax(0,30rem)_minmax(0,1fr)]">
            <div className="gg-sheet-body px-4 py-5 sm:px-6">{children}</div>
            <aside className="hidden border-l border-edge px-6 py-5 lg:block">
              <div className="sticky top-6">{side}</div>
            </aside>
          </div>
        ) : (
          <div className="gg-sheet-body px-4 py-5 sm:px-6">{children}</div>
        )}
      </div>
    </div>
  );
}
