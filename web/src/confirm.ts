import { useEffect, useState } from 'react';

/**
 * "Are you sure?", in the app's own dialog rather than the browser's.
 *
 * **The words were already good**; the box was the browser's — unstyled, a
 * different font, "localhost:8080 says" across the top, and on some browsers a
 * checkbox offering to stop the site asking (review §5). Every call site keeps
 * its sentence and swaps `confirm(…)` for `await ask(…)`.
 *
 * **A store, like `toast`.** The one `<ConfirmHost />` in the shell draws the
 * question. Where there is no host — a component rendered alone in a test —
 * it falls back to the browser's own `confirm`, so behaviour and the tests
 * that stub it stay exactly as they were.
 */
export interface Question {
  message: string;
  /** The button that says yes. Worked out from the message when left out. */
  confirmLabel: string;
  /** The button that says no. "Cancel", except beside a "Cancel …" yes. */
  cancelLabel: string;
  /** Deleting, removing, revoking: the yes button is drawn as a danger. */
  danger: boolean;
  answer: (yes: boolean) => void;
}

/** Verbs a question can start with that name what the yes button does. */
const ACTIONS = [
  'Delete', 'Remove', 'Revoke', 'Stop', 'Archive', 'Hide', 'Reset', 'Disconnect',
  'Discard', 'Cancel', 'Take', 'Replace', 'Settle', 'Forget', 'Turn',
];
const DANGEROUS = new Set(['Delete', 'Remove', 'Revoke', 'Disconnect', 'Discard', 'Reset', 'Forget']);

let current: Question | null = null;
const listeners = new Set<(q: Question | null) => void>();

function publish() {
  for (const listener of listeners) listener(current);
}

/** How a question's yes button is labelled and drawn, from its first word. */
export function reading(message: string): {
  confirmLabel: string;
  cancelLabel: string;
  danger: boolean;
} {
  const first = message.trim().split(/\s+/)[0]?.replace(/[^A-Za-z]/g, '') ?? '';
  const verb = ACTIONS.find((a) => a === first);
  if (!verb) return { confirmLabel: 'Continue', cancelLabel: 'Cancel', danger: false };
  // **Never "Cancel" beside "Cancel"** (P3-4): "Cancel this competition?"
  // offered [Cancel] [Cancel], and the first press went to the wrong one.
  if (verb === 'Cancel') return { confirmLabel: 'Yes, cancel it', cancelLabel: 'Keep it', danger: true };
  // "Take … off the shelf" and "Turn … off" read oddly as one word.
  const label = verb === 'Take' || verb === 'Turn' ? 'Yes' : verb;
  return { confirmLabel: label, cancelLabel: 'Cancel', danger: DANGEROUS.has(verb) };
}

export function ask(
  message: string,
  options: Partial<Pick<Question, 'confirmLabel' | 'cancelLabel' | 'danger'>> = {},
): Promise<boolean> {
  if (listeners.size === 0) {
    return Promise.resolve(window.confirm(message));
  }
  // One at a time. A second question while one is open answers the first no.
  current?.answer(false);
  return new Promise((resolve) => {
    current = {
      message,
      ...reading(message),
      ...options,
      answer: (yes) => {
        current = null;
        publish();
        resolve(yes);
      },
    };
    publish();
  });
}

export function useQuestion(): Question | null {
  const [question, setQuestion] = useState(current);
  useEffect(() => {
    listeners.add(setQuestion);
    return () => {
      listeners.delete(setQuestion);
    };
  }, []);
  return question;
}
