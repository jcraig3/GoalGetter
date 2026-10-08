import { useEffect, useState } from 'react';

import { api } from '../api';
import { dayAndTime } from '../time';
import { type Details, extras, kindLabel, knowMetricNames, targetWord, what } from './activityWords';

interface Entry {
  id: number;
  action: string;
  actor_email: string | null;
  target_email: string | null;
  /** Who, by name (P3-19); the address when the account is gone. */
  actor_name?: string | null;
  target_name?: string | null;
  // Either {from, to} for a change, or a scalar for context.
  details: Details;
  occurred_at: string;
}

/**
 * Read-only view of the audit log.
 *
 * On the Settings page rather than its own nav item: it is consulted when
 * something looks wrong, not daily, and a permanent link for a rarely-used
 * page is exactly the clutter we're avoiding.
 */
export default function ActivityLog() {
  const [entries, setEntries] = useState<Entry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // **Who, what and when** (8.4): fifty rows of everything was the only view.
  const [person, setPerson] = useState('');
  const [kind, setKind] = useState('');
  const [since, setSince] = useState('');
  const [until, setUntil] = useState('');
  const [kinds, setKinds] = useState<string[]>([]);
  const filtered = Boolean(person.trim() || kind || since || until);

  useEffect(() => {
    api<string[]>('/api/audit/kinds')
      .then(setKinds)
      .catch(() => setKinds([]));
    // So a row says "Sales Feed Amount Today", not its key (P3-19).
    api<{ key: string; name: string }[]>('/api/metrics?include_archived=true')
      .then(knowMetricNames)
      .catch(() => {});
  }, []);

  useEffect(() => {
    const query = new URLSearchParams({ limit: '50' });
    if (person.trim()) query.set('person', person.trim());
    if (kind) query.set('kind', kind);
    if (since) query.set('since', since);
    if (until) query.set('until', until);
    let stale = false;
    // A moment after typing stops, not on every key.
    const timer = window.setTimeout(() => {
      api<Entry[]>(`/api/audit?${query}`)
        .then((found) => !stale && setEntries(found))
        .catch((e) =>
          !stale && setError(e instanceof Error ? e.message : 'Could not load activity.'),
        );
    }, 200);
    return () => {
      stale = true;
      window.clearTimeout(timer);
    };
  }, [person, kind, since, until]);

  return (
    <section className="mt-8 max-w-3xl rounded-lg border border-edge bg-surface p-6">
      <h2 className="font-medium text-content">Recent activity</h2>
      <p className="mt-1 text-sm text-content-muted">
        What was changed and by whom, newest first. Each record is written with
        the change itself, so this cannot drift from what actually happened.
      </p>

      {error && (
        <p role="alert" className="mt-4 text-sm text-danger">
          {error}
        </p>
      )}

      <div className="mt-4 grid gap-3 sm:grid-cols-4">
        <label className="text-xs text-content-muted sm:col-span-2">
          Person
          <input
            type="search"
            value={person}
            onChange={(e) => setPerson(e.target.value)}
            placeholder="Who did it, or who it was done to"
            className="mt-1 block w-full rounded-md border border-edge bg-bg px-3 py-1.5 text-sm text-content outline-none focus:border-brand"
          />
        </label>
        <label className="text-xs text-content-muted sm:col-span-2">
          Kind
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            className="mt-1 block w-full rounded-md border border-edge bg-bg px-3 py-1.5 text-sm text-content"
          >
            <option value="">Everything</option>
            {kinds.map((k) => (
              <option key={k} value={k}>
                {kindLabel(k)}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-content-muted">
          From
          <input
            type="date"
            value={since}
            onChange={(e) => setSince(e.target.value)}
            className="mt-1 block w-full rounded-md border border-edge bg-bg px-3 py-1.5 text-sm text-content"
          />
        </label>
        <label className="text-xs text-content-muted">
          To
          <input
            type="date"
            value={until}
            onChange={(e) => setUntil(e.target.value)}
            className="mt-1 block w-full rounded-md border border-edge bg-bg px-3 py-1.5 text-sm text-content"
          />
        </label>
        {filtered && (
          <button
            type="button"
            onClick={() => {
              setPerson('');
              setKind('');
              setSince('');
              setUntil('');
            }}
            className="self-end justify-self-start text-sm text-brand hover:underline"
          >
            Clear
          </button>
        )}
      </div>

      {entries === null && !error && (
        <p className="mt-4 text-sm text-content-muted">Loading…</p>
      )}

      {entries?.length === 0 && (
        <p className="mt-4 text-sm text-content-muted">
          {filtered
            ? 'Nothing matches. Clear the filters to see everything.'
            : 'Nothing yet. Invitations, role changes, and suspensions appear here.'}
        </p>
      )}

      {entries && entries.length > 0 && (
        // **Scrolls in place rather than growing the page.** A deployment a
        // year in fills all fifty rows, and the export below it should not
        // end up a long scroll away. Focusable, so the list can be scrolled
        // from the keyboard too.
        <ul
          tabIndex={0}
          aria-label="Recent activity"
          className="mt-4 max-h-96 divide-y divide-edge overflow-y-auto pr-2 text-sm"
        >
          {entries.map((entry) => (
            <li key={entry.id} className="flex flex-wrap gap-x-2 py-2.5">
              {/* A sentence (review §9): "jayden@… changed the running contest
                  “QA2 sprint” · The end moved from …". */}
              <span className="text-content">
                {entry.actor_name ?? entry.actor_email ?? 'A deleted account'}{' '}
                <span className="text-content-muted">{what(entry.action, entry.details)}</span>
                {/* Not the name twice when somebody acted on themselves (P4-13):
                    "QA4 Agent chose their own password QA4 Agent". */}
                {(entry.target_name || entry.target_email) && entry.target_email !== entry.actor_email
                  ? ` ${targetWord(entry.action)}${entry.target_name ?? entry.target_email}`
                  : ''}
              </span>
              <Change details={entry.details} hasTarget={entry.target_email !== null} />
              <time
                dateTime={entry.occurred_at}
                className="ml-auto shrink-0 text-content-subtle"
              >
                {/* Rendered in the reader's local timezone. The organization
                    timezone governs when a *day* starts for leaderboards; an
                    audit entry is a point in time, and the person reading it
                    wants it in theirs. */}
                {dayAndTime(entry.occurred_at)}
              </time>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Change({ details, hasTarget }: { details: Details; hasTarget: boolean }) {
  const parts = extras(details, hasTarget);
  if (parts.length === 0) return null;
  return <span className="text-content-subtle">· {parts.join(' · ')}</span>;
}
