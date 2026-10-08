/**
 * Something is coming, drawn roughly where it will be.
 *
 * Grey bars rather than the word "Loading…": the word jumps to a table or a
 * row of cards when the answer lands, and the page shifts under whoever was
 * about to click (review §5). Still says "Loading…" to a screen reader.
 */
export default function Loading({ rows = 3 }: { rows?: number }) {
  return (
    <div role="status" className="space-y-3" aria-live="polite">
      <span className="sr-only">Loading…</span>
      {Array.from({ length: rows }, (_, i) => (
        <div
          key={i}
          aria-hidden="true"
          className="h-10 animate-pulse rounded-md bg-surface motion-reduce:animate-none"
          // Ragged widths read as content on its way; identical bars read as
          // a broken table.
          style={{ width: `${[100, 92, 84, 96, 88][i % 5]}%` }}
        />
      ))}
    </div>
  );
}
