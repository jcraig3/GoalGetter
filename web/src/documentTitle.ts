import { useEffect } from 'react';

/**
 * "Goals · GoalGetter" in the browser tab.
 *
 * Every tab, bookmark and history entry used to read "GoalGetter", so eight
 * open tabs were eight identical tabs (QA-27) — and a screen reader announces
 * the title first on arriving at a page.
 */
export function useDocumentTitle(title: string | null | undefined): void {
  useEffect(() => {
    if (!title) return;
    const before = document.title;
    document.title = `${title} · GoalGetter`;
    return () => {
      document.title = before;
    };
  }, [title]);
}
