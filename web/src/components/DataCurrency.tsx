import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { api } from '../api';
import { useAuth } from '../auth';
import { agoInWords, currencyOf, type MetricFreshness } from '../pages/sourceWizard';

/**
 * "As of four hours ago" — and a warning when that is not good enough.
 *
 * A leaderboard showing three-day-old figures looks exactly like one showing
 * current figures, and silently stale data is the fastest way to lose trust in
 * the tool. This is the line that stops that, on the pages people actually read
 * rather than only on the page an admin visits when something is already wrong.
 *
 * **Quiet when all is well.** A healthy feed produces a small grey timestamp and
 * nothing more. A banner on every page saying "everything is fine" is a banner
 * people stop seeing, and then it fails on the day it matters.
 *
 * **Everyone sees how old the numbers are; only an admin sees the alarm**
 * (5i). The people being ranked are the ones who notice their deal is missing,
 * so "Data as of 3 days ago" is never hidden from them. But an orange "the
 * Excel sync failed" on every agent's phone was a warning they could do
 * nothing about. The colour, the reason and the link go to whoever can fix it.
 */
export default function DataCurrency({
  metricIds,
  className = '',
}: {
  metricIds: number[];
  className?: string;
}) {
  const { can } = useAuth();
  const [freshness, setFreshness] = useState<MetricFreshness[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    api<MetricFreshness[]>('/api/data-freshness')
      .then((found) => {
        if (!cancelled) setFreshness(found);
      })
      // Silent on failure, deliberately. This is a footnote about other data;
      // an error banner here would report a problem with the reassurance rather
      // than with anything the reader came for.
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  if (!freshness || metricIds.length === 0) return null;

  const fixer = can('integrations.manage');
  const found = currencyOf(freshness, metricIds, new Date());
  const { asOf } = found;
  const suspect = fixer && found.suspect;
  const note = fixer ? found.note : null;
  if (!asOf && !note) return null;

  return (
    <p
      className={`flex flex-wrap items-baseline gap-x-2 text-sm ${
        suspect ? 'text-warning' : 'text-content-subtle'
      } ${className}`}
    >
      {asOf && (
        <span>
          Data as of <time dateTime={asOf.toISOString()}>{agoInWords(asOf, new Date())}</time>
        </span>
      )}
      {note && <span>{note}</span>}
      {note && (
        <Link to="/integrations" className="underline hover:no-underline">
          Check the sources
        </Link>
      )}
    </p>
  );
}
