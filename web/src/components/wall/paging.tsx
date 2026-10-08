import {
  createContext,
  useContext,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from 'react';

/**
 * Where the showing slide is in the rotation, on the shared clock.
 *
 * Provided by the television, which is the only thing that rotates. The
 * editor's preview has none, so a paged board there shows its first page.
 */
export interface Rotation {
  /** The server's time, in ms. See `wallClock.ts`. */
  now: () => number;
  /** When this slide began showing, on that clock. */
  start: number;
  /** How long it shows for, in ms. */
  length: number;
  /** Somebody at the screen is holding it still. */
  paused: boolean;
}

export const WallRotation = createContext<Rotation | null>(null);

/**
 * The rows of a ranked list that fit on the screen, a page at a time.
 *
 * **Paged, not cut off.** The wall is a fixed 1920×1080 stage, so how many
 * rows fit is a fact about the layout rather than about the television — and a
 * board asked for more than fit used to push the last of them off the bottom
 * (QA-3). Now it shows as many as fit and turns the page partway through the
 * slide's time, so ten rows that need two pages get half the dwell each.
 *
 * **Measured, by removing rows until nothing overflows.** Row height depends on
 * the organization's font and type scale, the header, whether there is a
 * subtitle or a prize line — too many things to add up. The slide's body
 * (`data-wall-body`) is a fixed height, so the list starts with every row and
 * loses one at a time, before paint, until the body's content fits inside it.
 *
 * **Turned by the shared clock**, the same one that decides which slide shows,
 * so every television on a channel is on the same page at the same moment.
 */
export function usePages<T>(items: T[], enabled = true) {
  const listRef = useRef<HTMLOListElement>(null);
  // Remembered with the length it was measured for, so a list that grows or
  // shrinks is measured from every row again rather than from a stale fit.
  const [fit, setFit] = useState({ total: items.length, perPage: items.length, settled: false });
  const current = fit.total === items.length;
  const perPage = current ? fit.perPage : items.length;
  const settled = !enabled || (current && fit.settled);

  // Each pass removes a row while something overflows, then marks the fit
  // settled — before paint, within a few passes. **Always measured on the
  // first page**, which is full: a screen joining partway through would
  // otherwise measure a short last page and decide everything fits.
  useLayoutEffect(() => {
    if (settled) return;
    const body = listRef.current?.closest<HTMLElement>('[data-wall-body]');
    const overflows = !!body && body.scrollHeight > body.clientHeight + 1;
    setFit({
      total: items.length,
      perPage: overflows && perPage > 1 ? perPage - 1 : perPage,
      settled: !overflows || perPage <= 1,
    });
  });

  const fits = Math.max(1, Math.min(perPage, items.length));
  const pages = Math.max(1, Math.ceil(items.length / fits));
  // **Shared out evenly once measured**: ten rows where seven fit are two
  // pages of five, not seven and then three — and never a page of one, which
  // spends half a slide's time on a single name.
  const size = settled ? Math.ceil(items.length / pages) : fits;
  const clockPage = usePage(settled ? pages : 1);
  const page = settled ? clockPage : 0;

  // **A short last page keeps the full page's height**, so its rows start
  // where the first page's did instead of jumping to the middle of the screen.
  // Taken only once the fit has settled: while it is still being measured the
  // first page holds rows that are about to be removed, and holding later
  // pages to that height would make every one of them overflow.
  const fullHeight = useRef(0);
  useLayoutEffect(() => {
    if (settled && page === 0 && listRef.current) {
      fullHeight.current = listRef.current.offsetHeight;
    }
  });

  return {
    listRef,
    shown: items.slice(page * size, (page + 1) * size),
    page,
    pages,
    listStyle:
      settled && pages > 1 && fullHeight.current ? { minHeight: fullHeight.current } : undefined,
  };
}

function usePage(pages: number): number {
  const rotation = useContext(WallRotation);
  const [page, setPage] = useState(0);
  const start = rotation?.start;
  const length = rotation?.length;
  const paused = rotation?.paused ?? false;
  const now = rotation?.now;

  useEffect(() => {
    if (!now || start === undefined || !length || pages <= 1) {
      setPage(0);
      return;
    }
    // Held where it is while somebody is standing at the screen.
    if (paused) return;

    let timer: number | undefined;
    const tick = () => {
      const pageLength = length / pages;
      const into = now() - start;
      const current = Math.min(pages - 1, Math.max(0, Math.floor(into / pageLength)));
      setPage(current);
      if (current < pages - 1) {
        timer = window.setTimeout(tick, (current + 1) * pageLength - into);
      }
    };
    tick();
    return () => window.clearTimeout(timer);
  }, [now, start, length, paused, pages]);

  return Math.min(page, pages - 1);
}

/** Which page is showing, for a list that needs more than one. */
export function PageDots({ page, pages }: { page: number; pages: number }) {
  if (pages <= 1) return null;
  // On a panel of its own, because the dots are small and a wall's background
  // can be anything — a pale dot on a bright photograph is not there at all.
  return (
    <div className="mt-4 flex justify-center">
      <div
        className="wall-panel flex gap-3 px-4 py-2"
        role="img"
        aria-label={`Page ${page + 1} of ${pages}`}
      >
        {Array.from({ length: pages }, (_, i) => (
          <span
            key={i}
            className={`size-3 rounded-full ${i === page ? 'bg-content' : 'bg-content/30'}`}
          />
        ))}
      </div>
    </div>
  );
}
