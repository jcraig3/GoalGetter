import { useEffect, useRef } from 'react';

import { useQuestion } from '../confirm';

/**
 * Where `ask()` is drawn. See `confirm.ts`.
 *
 * Focus starts on the safe answer — Cancel — so a stray Enter never deletes
 * anything, and returns to whatever was focused before, which is the button
 * that asked. Escape answers no, and stops there: the dialog underneath, if
 * there is one, is not closed by the same key press.
 */
export default function ConfirmHost() {
  const question = useQuestion();
  const cancel = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!question) return;
    const opener = document.activeElement as HTMLElement | null;
    cancel.current?.focus();

    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.stopImmediatePropagation();
      question.answer(false);
    };
    // Capture, so it is heard before a Modal's own Escape handler.
    window.addEventListener('keydown', onKey, true);
    return () => {
      window.removeEventListener('keydown', onKey, true);
      opener?.focus?.();
    };
  }, [question]);

  if (!question) return null;

  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center bg-black/60 p-4"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) question.answer(false);
      }}
    >
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-message"
        className="w-full max-w-md rounded-lg border border-edge bg-surface p-6 shadow-xl"
      >
        {/* `pre-line`: several questions put their consequence on a line of
            its own, and the browser's box honoured that. */}
        <p id="confirm-message" className="whitespace-pre-line text-sm text-content">
          {question.message}
        </p>
        <div className="mt-6 flex justify-end gap-2">
          <button
            ref={cancel}
            type="button"
            onClick={() => question.answer(false)}
            className="rounded-md border border-edge px-4 py-2 text-sm text-content hover:bg-surface-hover"
          >
            {question.cancelLabel ?? 'Cancel'}
          </button>
          <button
            type="button"
            onClick={() => question.answer(true)}
            className={`rounded-md px-4 py-2 text-sm font-medium text-white ${
              question.danger ? 'bg-danger hover:opacity-90' : 'bg-brand hover:bg-brand-hover'
            }`}
          >
            {question.confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
