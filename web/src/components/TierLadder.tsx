import { useEffect, useState } from 'react';

import { api } from '../api';
import { formatPoints } from '../pages/pointsCopy';
import Loading from './Loading';

interface Tier {
  id: number;
  name: string;
  threshold: number;
}

interface Ladder {
  tiers: Tier[];
}

interface Suggestion {
  name: string;
  threshold: number;
  would_hold: number;
}

interface Suggested {
  suggestions: Suggestion[];
  scoring_people: number;
  minimum: number;
}

/** A rung being edited. Strings, because a half-typed number is not one. */
interface Draft {
  name: string;
  threshold: string;
}

/**
 * Setting up the ladder.
 *
 * **Typing round numbers into this form is how a ladder goes wrong**, and the
 * two ways of going wrong look nothing alike from in here: a rung too high is
 * one nobody aims at, a rung too low is one that says nothing to hold. Both
 * are obvious the moment you see what people have actually scored, so the
 * suggestion is a button rather than a document — and every rung says how many
 * people would hold it, which is the number that settles the argument.
 */
export default function TierLadder() {
  const [draft, setDraft] = useState<Draft[] | null>(null);
  const [suggested, setSuggested] = useState<Suggested | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    Promise.all([
      api<Ladder>('/api/points/tiers'),
      api<Suggested>('/api/points/tiers/suggest'),
    ])
      .then(([ladder, ideas]) => {
        setDraft(
          ladder.tiers.map((tier) => ({
            name: tier.name,
            threshold: String(tier.threshold),
          })),
        );
        setSuggested(ideas);
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load.'));
  }, []);

  async function save() {
    if (!draft) return;
    setSaving(true);
    setError(null);
    try {
      await api<Ladder>('/api/points/tiers', {
        method: 'PUT',
        body: JSON.stringify({
          tiers: draft
            .filter((row) => row.name.trim() && Number(row.threshold) > 0)
            .map((row) => ({
              name: row.name.trim(),
              threshold: Number(row.threshold),
            })),
        }),
      });
      setSaved(true);
    } catch (e) {
      // The server's own words: it knows whether two rungs collided on a name
      // or on a number, and paraphrasing loses the half that says which.
      setError(e instanceof Error ? e.message : 'Could not save.');
    } finally {
      setSaving(false);
    }
  }

  if (error && !draft) {
    return (
      <p role="alert" className="rounded-md border border-danger px-3 py-2 text-sm text-danger">
        {error}
      </p>
    );
  }
  if (!draft || !suggested) {
    return <Loading />;
  }

  const change = (index: number, patch: Partial<Draft>) => {
    setSaved(false);
    setDraft(draft.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  };

  return (
    <section className="rounded-lg border border-edge bg-surface p-6">
      <h2 className="text-h3 text-content">Tiers</h2>
      <p className="mt-1 text-sm text-content-muted">
        Held by reaching that many points <em>this season</em>. Everybody starts
        again when the season does, which is what keeps the top rung worth
        wearing.
      </p>

      {error && (
        <p role="alert" className="mt-4 rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      <Suggestions
        suggested={suggested}
        onUse={(rows) => {
          setSaved(false);
          setDraft(
            rows.map((row) => ({
              name: row.name,
              threshold: String(row.threshold),
            })),
          );
        }}
      />

      {draft.length === 0 ? (
        <p className="mt-5 text-sm text-content-muted">
          No tiers set up. Points still work without them — a ladder is
          optional in a way a season is not.
        </p>
      ) : (
        <ul className="mt-5 space-y-3">
          {draft.map((row, index) => (
            <li key={index} className="flex flex-wrap items-end gap-3">
              <label className="flex-1">
                <span className="text-xs text-content-muted">Name</span>
                <input
                  value={row.name}
                  onChange={(event) => change(index, { name: event.target.value })}
                  className="mt-1 w-full rounded-md border border-edge bg-surface px-3 py-2 text-content"
                />
              </label>
              <label className="w-32">
                <span className="text-xs text-content-muted">Points</span>
                <input
                  type="number"
                  min={1}
                  value={row.threshold}
                  onChange={(event) =>
                    change(index, { threshold: event.target.value })
                  }
                  className="mt-1 w-full rounded-md border border-edge bg-surface px-3 py-2 text-right tabular-nums text-content"
                />
              </label>
              <button
                type="button"
                onClick={() => {
                  setSaved(false);
                  setDraft(draft.filter((_, i) => i !== index));
                }}
                className="py-2 text-sm text-content-muted hover:text-danger"
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-6 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => {
            setSaved(false);
            setDraft([...draft, { name: '', threshold: '' }]);
          }}
          className="rounded-md border border-edge px-4 py-2 text-sm text-content"
        >
          Add a tier
        </button>
        <button
          type="button"
          onClick={save}
          disabled={saving}
          className="rounded-md bg-brand px-4 py-2 text-sm text-white disabled:opacity-60"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
        {saved && <span className="text-sm text-success">Saved.</span>}
      </div>
    </section>
  );
}

function Suggestions({
  suggested,
  onUse,
}: {
  suggested: Suggested;
  onUse: (rows: Suggestion[]) => void;
}) {
  if (suggested.suggestions.length === 0) {
    return (
      <p className="mt-4 rounded-md border border-edge bg-surface-hover px-3 py-2 text-sm text-content-muted">
        {suggested.scoring_people === 0
          ? 'Nobody has scored yet this season, so there is no distribution to draw tiers from.'
          : `Only ${suggested.scoring_people} ${
              suggested.scoring_people === 1 ? 'person has' : 'people have'
            } scored this season. Below ${suggested.minimum}, a suggested ladder would just be the highest score with names on it.`}
      </p>
    );
  }

  return (
    <div className="mt-4 rounded-md border border-edge bg-surface-hover p-4">
      <p className="text-sm text-content">
        Suggested from what people have scored this season
      </p>
      <ul className="mt-3 space-y-1 text-sm">
        {suggested.suggestions.map((row) => (
          <li key={row.name} className="flex justify-between gap-4">
            <span className="text-content-muted">{row.name}</span>
            <span className="tabular-nums text-content">
              {formatPoints(row.threshold)}
              <span className="ml-2 text-content-muted">
                {/* The number that settles the argument about a rung. */}
                {row.would_hold} would hold it
              </span>
            </span>
          </li>
        ))}
      </ul>
      <button
        type="button"
        onClick={() => onUse(suggested.suggestions)}
        className="mt-3 text-sm text-brand hover:underline"
      >
        Use these
      </button>
      <p className="mt-2 text-xs text-content-muted">
        Round them afterwards if you like — what matters is that you are
        rounding something real.
      </p>
    </div>
  );
}
