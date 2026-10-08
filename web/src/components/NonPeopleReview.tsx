import { useEffect, useState } from 'react';

import { api } from '../api';

interface NonPerson {
  id: number;
  full_name: string;
  email: string;
  /** Why it was suggested, e.g. "a number in the name". */
  reason: string;
}

/**
 * Accounts that look like printers, rooms or shared mailboxes, for an admin to
 * hide in one go.
 *
 * **Every other number is wrong until this is done.** A directory sync brings
 * in "MFP 3100", "No Reply" and "dummy account 2" along with the people, and
 * they sit in every picker and every "recorded nothing" count (review §2 #2).
 * Hiding them was always possible, one person at a time, and nothing suggested
 * it.
 *
 * **Suggested, reviewed, then hidden** — through the People page's own bulk
 * action, so it is audited like any other hide and undone from the Hidden tab.
 * Nothing disappears because a name looked odd.
 */
export default function NonPeopleReview({ onHidden }: { onHidden: () => void | Promise<void> }) {
  const [found, setFound] = useState<NonPerson[]>([]);
  const [reviewing, setReviewing] = useState(false);
  const [chosen, setChosen] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      const next = await api<NonPerson[]>('/api/users/non-people');
      setFound(next);
      setChosen(new Set(next.map((p) => p.id)));
    } catch {
      // Advice, not a feature anybody depends on: without it the page is
      // exactly as it was.
      setFound([]);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function hide(ids: number[]) {
    if (ids.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      await api('/api/users/bulk', {
        method: 'POST',
        body: JSON.stringify({ ids, action: 'hide' }),
      });
      setReviewing(false);
      await load();
      await onHidden();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not hide them.');
    } finally {
      setBusy(false);
    }
  }

  if (found.length === 0) return null;

  const n = found.length;
  return (
    <section
      aria-label="Accounts that may not be people"
      className="mt-4 rounded-lg border border-warning/40 bg-warning/10 p-4 text-sm"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-content">
          <strong>
            {n} {n === 1 ? 'account looks' : 'accounts look'} like a device, a test account or a shared mailbox
          </strong>{' '}
          rather than a person — {n === 1 ? 'it counts' : 'they count'} in every total and
          picker until hidden.
        </p>
        <span className="flex gap-2">
          <button
            type="button"
            onClick={() => setReviewing((v) => !v)}
            className="rounded-md border border-edge bg-surface px-3 py-1.5 text-content hover:bg-surface-hover"
          >
            {reviewing ? 'Close' : 'Review'}
          </button>
          {!reviewing && (
            <button
              type="button"
              disabled={busy}
              onClick={() => void hide(found.map((p) => p.id))}
              className="rounded-md bg-brand px-3 py-1.5 font-medium text-white hover:bg-brand-hover disabled:opacity-60"
            >
              Hide all {n}
            </button>
          )}
        </span>
      </div>

      {error && (
        <p role="alert" className="mt-2 text-danger">
          {error}
        </p>
      )}

      {reviewing && (
        <div className="mt-3 space-y-3">
          <ul className="max-h-80 divide-y divide-edge overflow-y-auto rounded-md border border-edge bg-surface">
            {found.map((p) => (
              <li key={p.id}>
                <label className="flex cursor-pointer items-center gap-3 px-3 py-2">
                  <input
                    type="checkbox"
                    checked={chosen.has(p.id)}
                    onChange={() =>
                      setChosen((set) => {
                        const next = new Set(set);
                        if (next.has(p.id)) next.delete(p.id);
                        else next.add(p.id);
                        return next;
                      })
                    }
                  />
                  <span className="min-w-0 flex-1">
                    <span className="text-content">{p.full_name}</span>
                    <span className="ml-2 text-xs text-content-subtle">{p.email}</span>
                  </span>
                  <span className="shrink-0 text-xs text-content-muted">{p.reason}</span>
                </label>
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              disabled={busy || chosen.size === 0}
              onClick={() => void hide([...chosen])}
              className="rounded-md bg-brand px-3 py-1.5 font-medium text-white hover:bg-brand-hover disabled:opacity-60"
            >
              Hide {chosen.size} selected
            </button>
            <span className="text-xs text-content-muted">
              Hidden people keep their history and come back from the Hidden tab.
            </span>
          </div>
        </div>
      )}
    </section>
  );
}
