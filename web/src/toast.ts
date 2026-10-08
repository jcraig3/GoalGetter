import { useEffect, useState } from 'react';

/**
 * A short "done" after a create, a save or a delete.
 *
 * **There were none.** A form closed, a list changed somewhere below the fold,
 * and whether the thing had saved was left for somebody to work out (review
 * #5). One line, for five seconds, with a link to what was made when there is
 * somewhere worth going.
 *
 * **A store, not a provider.** Any page — or a helper with no React in it —
 * calls `toast()`, and the one `<Toasts />` in the shell draws whatever is
 * waiting. A component rendered on its own in a test has nowhere to show it,
 * and nothing breaks.
 */
export interface Toast {
  id: number;
  message: string;
  /** Somewhere to go: the thing just made, usually. */
  href?: string;
  linkLabel?: string;
  /** Something to do instead, such as Undo (7.5). */
  action?: { label: string; run: () => void };
}

/** Long enough to read twice, short enough not to pile up. */
export const TOAST_MS = 5000;

/**
 * One that carries an Undo stays twice as long (P4-4): at five seconds a
 * cleared notification was gone for good before anybody reached the button.
 */
export const UNDO_TOAST_MS = 10_000;

let nextId = 1;
let showing: Toast[] = [];
const listeners = new Set<(toasts: Toast[]) => void>();

function publish() {
  for (const listener of listeners) listener(showing);
}

export function toast(
  message: string,
  link?: { href: string; label?: string },
  action?: { label: string; run: () => void },
): void {
  const item: Toast = {
    id: nextId++,
    message,
    href: link?.href,
    linkLabel: link?.label ?? (link ? 'View' : undefined),
    action,
  };
  // Three at most: a bulk action that toasts per row would otherwise bury the
  // page, and the newest is the one being read.
  showing = [...showing, item].slice(-3);
  publish();
  setTimeout(() => dismiss(item.id), action ? UNDO_TOAST_MS : TOAST_MS);
}

export function dismiss(id: number): void {
  const next = showing.filter((t) => t.id !== id);
  if (next.length === showing.length) return;
  showing = next;
  publish();
}

export function useToasts(): Toast[] {
  const [items, setItems] = useState(showing);
  useEffect(() => {
    listeners.add(setItems);
    setItems(showing);
    return () => {
      listeners.delete(setItems);
    };
  }, []);
  return items;
}
