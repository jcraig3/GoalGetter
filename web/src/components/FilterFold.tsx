import { useState, type ReactNode } from 'react';

/**
 * A page's filters, folded behind one button on a phone (5i).
 *
 * Six filters stacked one per line pushed the list itself below the first
 * screen. Below 640 px they sit behind "Filters (2)", the count being how many
 * are set, so a narrowed list never looks like the whole of it. From 640 px up
 * the wrapper is `display: contents`: the filters take part in the page's own
 * grid or flex row exactly as they did before.
 *
 * Search stays outside, on show: it is the one people reach for first.
 */
export default function FilterFold({
  active,
  children,
}: {
  /** How many of the folded filters are set. */
  active: number;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className={`self-end rounded-md border px-3 py-2 text-sm transition-colors sm:hidden ${
          active ? 'border-brand text-content' : 'border-edge text-content-muted hover:text-content'
        }`}
      >
        {open ? 'Hide filters' : `Filters${active ? ` (${active})` : ''}`}
      </button>
      <div className={`${open ? 'grid' : 'hidden'} w-full gap-3 sm:contents`}>{children}</div>
    </>
  );
}
