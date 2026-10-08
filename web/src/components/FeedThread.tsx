import { useState, type FormEvent } from 'react';

import { api } from '../api';
import { useAuth } from '../auth';
import { UNDO_TOAST_MS, toast } from '../toast';
import { agoInWords } from '../time';
import Avatar from './Avatar';
import PersonLink from './PersonLink';

export interface Reaction {
  reaction: string;
  count: number;
  mine: boolean;
  names: string[];
}

export interface FeedComment {
  id: number;
  body: string;
  created_at: string;
  author_id: number;
  author_name: string;
  author_photo_digest: string | null;
}

interface Thread {
  reactions: Reaction[];
  comments: FeedComment[];
}

/** The reactions on offer, in the server's order. See `models/feed.py`. */
export const REACTIONS: { key: string; emoji: string; label: string }[] = [
  { key: 'clap', emoji: '👏', label: 'Applause' },
  { key: 'fire', emoji: '🔥', label: 'On fire' },
  { key: 'party', emoji: '🎉', label: 'Celebrate' },
  { key: 'muscle', emoji: '💪', label: 'Strong' },
  { key: 'heart', emoji: '❤️', label: 'Love it' },
];

const EMOJI = Object.fromEntries(REACTIONS.map((r) => [r.key, r]));

/** "Ann, Bob and 3 others" — for the tooltip on a reaction. */
export function whoReacted(names: string[]): string {
  if (names.length <= 3) {
    return names.length <= 1 ? names.join('') : `${names.slice(0, -1).join(', ')} and ${names.at(-1)}`;
  }
  const others = names.length - 2;
  return `${names.slice(0, 2).join(', ')} and ${others} others`;
}

/**
 * **Reactions and comments under a feed entry** (6.15).
 *
 * A shout-out nobody can answer is a notice; the floor clapping and saying
 * "nobody deserved it more" is what makes it recognition. Reactions are a
 * small fixed set, counted at a glance; comments fold away until somebody
 * opens them, so a long feed stays a feed.
 */
export default function FeedThread({
  entryId,
  reactions: initialReactions,
  comments: initialComments,
}: {
  entryId: number;
  reactions: Reaction[];
  comments: FeedComment[];
}) {
  const { user, can } = useAuth();
  const [thread, setThread] = useState<Thread>({
    reactions: initialReactions,
    comments: initialComments,
  });
  const [picking, setPicking] = useState(false);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function react(reaction: string) {
    setPicking(false);
    setError(null);
    try {
      setThread(
        await api<Thread>(`/api/feed/${entryId}/reactions`, {
          method: 'POST',
          body: JSON.stringify({ reaction }),
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not react.');
    }
  }

  async function comment(event: FormEvent) {
    event.preventDefault();
    if (!draft.trim()) return;
    setBusy(true);
    setError(null);
    try {
      setThread(
        await api<Thread>(`/api/feed/${entryId}/comments`, {
          method: 'POST',
          body: JSON.stringify({ body: draft }),
        }),
      );
      setDraft('');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not post that.');
    } finally {
      setBusy(false);
    }
  }

  /**
   * **Gone at once, deleted a moment later** (7.5, Q2-17): the comment
   * disappears, a toast offers Undo for as long as it shows, and only then is
   * it deleted — so Undo needs nothing from the server at all.
   */
  function remove(id: number) {
    setError(null);
    const removed = thread.comments.find((c) => c.id === id);
    if (!removed) return;
    setThread((was) => ({ ...was, comments: was.comments.filter((c) => c.id !== id) }));
    let undone = false;
    const timer = window.setTimeout(() => {
      if (undone) return;
      api<Thread>(`/api/feed/comments/${id}`, { method: 'DELETE' })
        .then(setThread)
        .catch((e) => setError(e instanceof Error ? e.message : 'Could not remove that.'));
    }, UNDO_TOAST_MS);
    toast('Comment removed', undefined, {
      label: 'Undo',
      run: () => {
        undone = true;
        window.clearTimeout(timer);
        setThread((was) => ({
          ...was,
          comments: [...was.comments, removed].sort((a, b) => a.id - b.id),
        }));
      },
    });
  }

  const count = thread.comments.length;
  const chip =
    'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand';

  return (
    <div className="mt-2">
      <div className="flex flex-wrap items-center gap-1.5">
        {thread.reactions.map((r) => (
          <button
            key={r.reaction}
            type="button"
            aria-pressed={r.mine}
            aria-label={`${EMOJI[r.reaction]?.label ?? r.reaction}: ${whoReacted(r.names)}`}
            title={whoReacted(r.names)}
            onClick={() => void react(r.reaction)}
            className={`${chip} ${
              r.mine
                ? 'border-brand bg-brand/10 text-content'
                : 'border-edge text-content-muted hover:bg-surface-hover'
            }`}
          >
            <span aria-hidden="true">{EMOJI[r.reaction]?.emoji ?? r.reaction}</span>
            <span className="tabular-nums">{r.count}</span>
          </button>
        ))}

        {/* One toggle that says whether it is open (Q2-27), and the choices
            after it while it is. */}
        <button
          type="button"
          onClick={() => setPicking((was) => !was)}
          aria-label="Add a reaction"
          aria-expanded={picking}
          className={`${chip} border-edge text-content-subtle hover:bg-surface-hover hover:text-content`}
        >
          <span aria-hidden="true">☺</span>+
        </button>
        {picking && (
          <span className="inline-flex gap-0.5 rounded-full border border-edge px-1 py-0.5" role="group" aria-label="React">
            {REACTIONS.map((r) => (
              <button
                key={r.key}
                type="button"
                aria-label={r.label}
                title={r.label}
                onClick={() => void react(r.key)}
                className="rounded-full px-1 text-sm transition-transform hover:scale-125 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand"
              >
                {r.emoji}
              </button>
            ))}
          </span>
        )}

        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          className="ml-1 text-xs text-content-muted hover:text-content hover:underline"
        >
          {count === 0 ? 'Comment' : `${count} comment${count === 1 ? '' : 's'}`}
        </button>
      </div>

      {open && (
        <div className="mt-3 space-y-3 border-l-2 border-edge pl-3">
          {thread.comments.map((c) => (
            <div key={c.id} className="flex items-start gap-2">
              <Avatar name={c.author_name} digest={c.author_photo_digest} />
              <div className="min-w-0 flex-1">
                <p className="text-sm text-content">
                  <PersonLink id={c.author_id} className="font-medium">
                    {c.author_name}
                  </PersonLink>{' '}
                  {c.body}
                </p>
                <p className="text-xs text-content-subtle">
                  {agoInWords(new Date(c.created_at))}
                  {(c.author_id === user?.id || can('org.settings.edit')) && (
                    <>
                      {' · '}
                      <button
                        type="button"
                        onClick={() => remove(c.id)}
                        className="hover:text-danger hover:underline"
                      >
                        Remove comment
                      </button>
                    </>
                  )}
                </p>
              </div>
            </div>
          ))}
          <form onSubmit={comment} className="flex gap-2">
            <label htmlFor={`comment-${entryId}`} className="sr-only">
              Add a comment
            </label>
            <input
              id={`comment-${entryId}`}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              maxLength={300}
              placeholder="Add a comment…"
              className="min-w-0 flex-1 rounded-md border border-edge bg-bg px-3 py-1.5 text-sm text-content outline-none placeholder:text-content-subtle focus:border-brand"
            />
            <button
              type="submit"
              disabled={busy || !draft.trim()}
              className="shrink-0 rounded-md bg-brand px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
            >
              Post
            </button>
          </form>
        </div>
      )}

      {error && (
        <p role="alert" className="mt-2 text-xs text-danger">
          {error}
        </p>
      )}
    </div>
  );
}
