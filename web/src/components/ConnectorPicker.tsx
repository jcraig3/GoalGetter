import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import { grouped, needsStructure, type Pickable } from '../pages/connectorPicker';
import ConnectorMark from './connectorMark';
import { SearchIcon } from './icons';

/**
 * Choosing a connector — the grid, the search box, and the headings.
 *
 * One component for the two places that ask the question: the connect wizard's
 * first step, and the "add another" grid on the integrations page. They differed
 * only in whether a card was a link or a button, which is not enough difference to
 * justify keeping two copies of a search box in sync.
 *
 * **All the deciding lives in `pages/connectorPicker.ts`**, which has no React in
 * it — what counts as a match, which group a connector belongs to, and when the
 * list is long enough to need structure at all. This file is the markup and the
 * one piece of state.
 */
export default function ConnectorPicker({
  connectors,
  to,
  onChoose,
  disabled = false,
}: {
  connectors: Pickable[];
  /**
   * Renders links, for a page somebody might middle-click.
   *
   * **Returning `null` for one connector hands it to `onChoose` instead.** Most
   * cards start a wizard, which is a page and should behave like one; a
   * connector whose setup is a dialog on this page is not, and making it a link
   * to somewhere it never goes would break the back button for the sake of
   * consistency nobody asked for.
   */
  to?: (key: string) => string | null;
  /** Renders buttons, for a wizard step that acts in place. */
  onChoose?: (key: string) => void;
  disabled?: boolean;
}) {
  const [query, setQuery] = useState('');

  // Below a handful, a search box and six headings are chrome around a list that
  // was already one glance.
  const structured = needsStructure(connectors.length);
  const groups = useMemo(
    () => grouped(connectors, structured ? query : ''),
    [connectors, query, structured],
  );

  return (
    <div>
      {structured && (
        <label className="relative mb-4 block max-w-sm">
          <SearchIcon
            className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-content-subtle"
          />
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search — Salesforce, Postgres, xlsx…"
            aria-label="Search connectors"
            className="w-full rounded-md border border-edge bg-surface py-2 pl-9 pr-3 text-sm text-content placeholder:text-content-subtle focus:border-brand focus:outline-none"
          />
        </label>
      )}

      {groups.length === 0 ? (
        <NoMatch query={query} onClear={() => setQuery('')} />
      ) : (
        groups.map((entry) => (
          <section key={entry.group} className="mb-6 last:mb-0">
            {/* Headings only once there is enough to organize. One heading over a
                whole short list names nothing. */}
            {structured && (
              <h3 className="mb-3 text-caption uppercase tracking-wide text-content-subtle">
                {entry.group}
              </h3>
            )}
            <div className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(15rem,1fr))]">
              {entry.connectors.map((connector) => {
                const href = to?.(connector.key) ?? null;
                return href ? (
                  <Link key={connector.key} to={href} className={CARD}>
                    <Inside connector={connector} />
                  </Link>
                ) : (
                  <button
                    key={connector.key}
                    type="button"
                    onClick={() => onChoose?.(connector.key)}
                    disabled={disabled}
                    className={`${CARD} text-left disabled:opacity-50`}
                  >
                    <Inside connector={connector} />
                  </button>
                );
              })}
            </div>
          </section>
        ))
      )}
    </div>
  );
}

const CARD =
  'flex items-center gap-3 rounded-lg border border-edge bg-surface p-4 transition-colors hover:bg-surface-hover';

/**
 * The name and its mark. Nothing else.
 *
 * There used to be a line of subtext under each — "GoalGetter fetches on a
 * schedule" — and it was the same sentence on almost every card. A caption that
 * does not vary is not information, it is noise that makes the grid twice as tall
 * and every card slower to scan. The fetch-or-receive distinction still matters,
 * but it matters on the *connect* step, where it changes what somebody does next.
 */
function Inside({ connector }: { connector: Pickable }) {
  return (
    <>
      <ConnectorMark connector={connector.key} className="size-7 shrink-0" />
      <p className="min-w-0 truncate font-medium text-content">
        {connector.display_name}
      </p>
    </>
  );
}

/**
 * Nothing matched — which for a connector list has a real answer, not an apology.
 *
 * Somebody searching for a system we do not have a connector for is the case this
 * has to handle well: there are two general-purpose connectors that work with
 * almost anything, and this is the moment to say so. Searching for the missing
 * product is exactly when the escape hatch is worth knowing about.
 */
function NoMatch({ query, onClear }: { query: string; onClear: () => void }) {
  return (
    <div className="rounded-lg border border-dashed border-edge px-4 py-6 text-sm text-content-muted">
      <p>
        Nothing here is called “{query.trim()}”.
      </p>
      <p className="mt-2">
        Most systems can still be connected: anything that can send an HTTP request
        works through the <strong className="font-medium text-content">webhook</strong>,
        and anything with a JSON API works through the{' '}
        <strong className="font-medium text-content">API</strong> connector.
      </p>
      <button
        type="button"
        onClick={onClear}
        className="mt-3 rounded-md border border-edge px-3 py-1.5 text-sm text-content transition-colors hover:bg-surface-hover"
      >
        Show everything
      </button>
    </div>
  );
}
