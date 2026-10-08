import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { api } from '../api';
import EmptyState from '../components/EmptyState';
import Loading from '../components/Loading';
import PageHeader from '../components/PageHeader';
import { agoInWords } from '../time';
import { toast } from '../toast';

export interface InboxItem {
  kind: string;
  /** Which item across requests — "source_quiet:12" — for putting it away. */
  key: string;
  severity: 'problem' | 'todo' | 'heads_up';
  title: string;
  detail: string | null;
  link: string;
  since: string | null;
  action: { label: string; method: string; path: string } | null;
}

const SEVERITY: Record<InboxItem['severity'], { label: string; className: string }> = {
  problem: { label: 'Problem', className: 'border-danger text-danger' },
  todo: { label: 'To do', className: 'border-warning text-warning' },
  heads_up: { label: 'Heads up', className: 'border-edge text-content-muted' },
};

/**
 * What needs an admin right now, in one place (6.2).
 *
 * Failing and late sources, people waiting in the directory, TVs that are dark
 * or showing a pairing code, a season about to end. Each lived on its own page
 * before, and was found by visiting each in turn — or by somebody on the floor
 * saying the board looked wrong.
 *
 * **Nothing to mark as read.** Every item is worked out from the data when the
 * page opens (`app/inbox.py`), so fixing the thing is how it leaves, and an
 * item can never claim something is wrong after it has been put right.
 *
 * **But "not now" is allowed** (12.2): a TV in a room closed for the weekend,
 * a feed nobody can fix till Monday. Put away, an item waits underneath until
 * what it is about changes, or until tomorrow — "not today", never "never".
 */
export default function Inbox() {
  const [items, setItems] = useState<InboxItem[] | null>(null);
  const [away, setAway] = useState<InboxItem[]>([]);
  const [showAway, setShowAway] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const found = await api<{ items: InboxItem[]; dismissed?: InboxItem[] }>('/api/inbox');
      setItems(found.items);
      setAway(found.dismissed ?? []);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load the inbox.');
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function putAway(item: InboxItem) {
    try {
      await api('/api/inbox/dismiss', { method: 'POST', body: JSON.stringify({ key: item.key }) });
      toast('Put away until it changes, or tomorrow', undefined, {
        label: 'Undo',
        run: () => void bringBack(item),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That did not work.');
    }
    await load();
    window.dispatchEvent(new Event('gg:inbox-changed'));
  }

  async function bringBack(item: InboxItem) {
    try {
      await api('/api/inbox/restore', { method: 'POST', body: JSON.stringify({ key: item.key }) });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That did not work.');
    }
    await load();
    window.dispatchEvent(new Event('gg:inbox-changed'));
  }

  async function act(item: InboxItem) {
    if (!item.action) return;
    setBusy(item.action.path);
    try {
      const done = await api<{ name?: string; channel_name?: string } | null>(item.action.path, {
        method: item.action.method,
      });
      // What happened, not "Reconnect: done" (Q2-22).
      toast(
        done?.name && done.channel_name
          ? `${done.name} is back on ${done.channel_name}`
          : `${item.action.label} — done`,
      );
      // Ask again rather than drop the row: the inbox is the data's answer,
      // and the fix may have resolved more than one item.
      await load();
      window.dispatchEvent(new Event('gg:inbox-changed'));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That did not work.');
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <PageHeader
        title="Inbox"
        description="What needs an admin right now. An item leaves once it is fixed; Not now puts one away until it changes, or until tomorrow."
      />

      {error && (
        <p role="alert" className="mb-4 rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      {items === null ? (
        !error && <Loading />
      ) : items.length === 0 ? (
        away.length > 0 ? (
          <p className="max-w-3xl rounded-lg border border-edge bg-surface px-6 py-4 text-sm text-content-muted">
            Nothing else needs you right now.
          </p>
        ) : (
          <EmptyState
            title="Nothing needs you"
            description="Every source is reading, every TV is checking in, and nobody is waiting to be placed."
          />
        )
      ) : (
        <ul className="max-w-3xl divide-y divide-edge rounded-lg border border-edge bg-surface">
          {items.map((item) => {
            const tone = SEVERITY[item.severity];
            return (
              <li key={item.key} className="flex flex-wrap items-start gap-x-4 gap-y-2 p-4">
                <span
                  className={`mt-0.5 shrink-0 rounded border px-1.5 py-0.5 text-caption uppercase tracking-wide ${tone.className}`}
                >
                  {tone.label}
                </span>
                <div className="min-w-0 flex-1 basis-64">
                  <p className="text-content">{item.title}</p>
                  {item.detail && (
                    <p className="mt-1 text-sm text-content-muted">{item.detail}</p>
                  )}
                  {item.since && (
                    <p className="mt-1 text-xs text-content-subtle">
                      Since {agoInWords(new Date(item.since))}
                    </p>
                  )}
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {item.action && (
                    <button
                      type="button"
                      onClick={() => void act(item)}
                      disabled={busy !== null}
                      className="rounded-md bg-brand px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
                    >
                      {busy === item.action.path ? 'Working…' : item.action.label}
                    </button>
                  )}
                  <Link
                    to={item.link}
                    className="rounded-md border border-edge px-3 py-1.5 text-sm text-content transition-colors hover:bg-surface-hover"
                  >
                    Open
                  </Link>
                  <button
                    type="button"
                    onClick={() => void putAway(item)}
                    title="Put away until it changes, or until tomorrow"
                    className="rounded-md px-2 py-1.5 text-sm text-content-muted transition-colors hover:bg-surface-hover hover:text-content"
                  >
                    Not now
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {/* **Listed, not lost.** Quiet, and below everything still asking. */}
      {away.length > 0 && (
        <div className="mt-6 max-w-3xl">
          <button
            type="button"
            onClick={() => setShowAway((was) => !was)}
            aria-expanded={showAway}
            className="text-sm text-content-muted hover:text-content hover:underline"
          >
            {away.length === 1 ? '1 notice was' : `${away.length} notices were`} dismissed
            {showAway ? ' · Hide' : ' · Show'}
          </button>
          {showAway && (
            <ul className="mt-2 divide-y divide-edge rounded-lg border border-edge">
              {away.map((item) => (
                <li key={item.key} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
                  <p className="min-w-0 flex-1 basis-64 text-sm text-content-muted">{item.title}</p>
                  <button
                    type="button"
                    onClick={() => void bringBack(item)}
                    className="rounded-md border border-edge px-3 py-1.5 text-sm text-content transition-colors hover:bg-surface-hover"
                  >
                    Bring back
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </>
  );
}
