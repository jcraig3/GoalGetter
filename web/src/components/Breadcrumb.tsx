import { Link } from 'react-router-dom';

/**
 * "Goals › Clark — Closed Deals", above a detail page's title.
 *
 * A trail rather than "← Goals" (review §4): it says where you are as well as
 * where back goes, and the section it names is the same word as the nav.
 */
export default function Breadcrumb({
  parent,
  here,
}: {
  parent: { to: string; label: string };
  /** Left off while the page is still loading what it is about. */
  here?: string;
}) {
  return (
    <nav aria-label="Breadcrumb" className="mb-4 text-sm">
      <ol className="flex flex-wrap items-center gap-1.5 text-content-muted">
        <li>
          <Link to={parent.to} className="text-brand hover:underline">
            {parent.label}
          </Link>
        </li>
        {here && (
          <>
            <li aria-hidden="true">›</li>
            <li aria-current="page" className="min-w-0 truncate text-content">
              {here}
            </li>
          </>
        )}
      </ol>
    </nav>
  );
}
