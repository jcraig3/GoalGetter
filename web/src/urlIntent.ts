/**
 * What the address asks a page to do on arrival (7.9): open its "new" form,
 * or point at one row. How the command palette's actions and its teams,
 * offices, rules, badges and metrics land somewhere useful rather than at the
 * top of a list.
 *
 * Read on every change of the address, not only on mount, so choosing "New
 * goal" from the palette while already on Goals still opens the form. The
 * parameter is removed once acted on, so Back does not open it again.
 */
import { useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';

/** Calls `open` when `?<param>` is in the address, then takes it out. */
export function useOpenFromUrl(param: string, open: () => void): void {
  const [params, setParams] = useSearchParams();
  const wanted = params.get(param) !== null;
  useEffect(() => {
    if (!wanted) return;
    open();
    setParams(
      (now) => {
        const next = new URLSearchParams(now);
        next.delete(param);
        return next;
      },
      { replace: true },
    );
    // `open` is a fresh arrow each render; the address is what matters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wanted, param, setParams]);
}

/** The row `?focus=<id>` names, in view and picked out, once the list is drawn. */
export function useFocusRow(ready: boolean): void {
  const [params, setParams] = useSearchParams();
  const focus = params.get('focus');
  useEffect(() => {
    if (!ready || !focus) return;
    const row = document.getElementById(`row-${focus}`);
    if (row) {
      row.scrollIntoView?.({ block: 'center' });
      row.classList.add('gg-focus-row');
      window.setTimeout(() => row.classList.remove('gg-focus-row'), 2400);
    }
    setParams(
      (now) => {
        const next = new URLSearchParams(now);
        next.delete('focus');
        return next;
      },
      { replace: true },
    );
  }, [ready, focus, setParams]);
}
