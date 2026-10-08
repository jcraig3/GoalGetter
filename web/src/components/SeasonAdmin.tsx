import { useCallback, useEffect, useState } from 'react';

import { api } from '../api';
import {
  type Season,
  seasonWindow,
  timeLeftLabel,
} from '../pages/pointsCopy';
import Loading from './Loading';
import MissingHint from './MissingHint';

/**
 * Setting up the seasons.
 *
 * **The one control in the economy that has to exist before anybody needs
 * it.** The first award opens a season on its own — aligned to the fiscal
 * quarter, so nothing has to be configured for points to work — but an
 * organization that wants its own calendar has to be able to draw one, and to
 * draw the *next* one before the current one runs out. A season that lapses
 * silently is a scoreboard that stops.
 */
export default function SeasonAdmin() {
  const [rows, setRows] = useState<Season[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  const load = useCallback(() => {
    api<Season[]>('/api/points/seasons')
      .then(setRows)
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load.'));
  }, []);

  useEffect(load, [load]);

  if (error && !rows) {
    return (
      <p role="alert" className="rounded-md border border-danger px-3 py-2 text-sm text-danger">
        {error}
      </p>
    );
  }
  if (!rows) return <Loading />;

  const today = new Date().toISOString().slice(0, 10);
  const running = rows.find(
    (row) => row.starts_on <= today && row.ends_on >= today,
  );
  const next = rows.find((row) => row.starts_on > today);

  return (
    <section className="rounded-lg border border-edge bg-surface p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-h3 text-content">Seasons</h2>
          <p className="mt-1 text-sm text-content-muted">
            Points reset when a season ends. That is what keeps the table worth
            looking at — a total that only ever grows cannot be caught up with.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="rounded-md bg-brand px-4 py-2 text-sm text-white"
        >
          Add a season
        </button>
      </div>

      {/* The gap worth warning about: a season ending with nothing after it.
          Nobody notices until the day the scoreboard stops. */}
      {running && !next && (
        <p className="mt-4 rounded-md border border-warning px-3 py-2 text-sm text-warning">
          Nothing is set up after {running.name}. Points carry on being awarded
          into a new season opened automatically, named after the quarter it
          falls in.
        </p>
      )}

      {rows.length === 0 ? (
        <p className="mt-5 text-sm text-content-muted">
          No seasons yet. The first points awarded will open one covering the
          current quarter.
        </p>
      ) : (
        <ul className="mt-5 divide-y divide-edge">
          {rows.map((season) => (
            <SeasonRow
              key={season.id}
              season={season}
              running={season.id === running?.id}
              onSaved={load}
            />
          ))}
        </ul>
      )}

      {adding && (
        <SeasonForm
          onClose={() => setAdding(false)}
          onSaved={() => {
            setAdding(false);
            load();
          }}
        />
      )}
    </section>
  );
}

function SeasonRow({
  season,
  running,
  onSaved,
}: {
  season: Season;
  running: boolean;
  onSaved: () => void;
}) {
  const [editing, setEditing] = useState(false);

  return (
    <li className="py-4 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <p className="text-content">
          {season.name}
          {running && (
            <span className="ml-2 rounded bg-success/15 px-1.5 py-0.5 text-xs text-success">
              running
            </span>
          )}
        </p>
        <button
          type="button"
          onClick={() => setEditing(true)}
          className="text-sm text-content-muted hover:text-brand"
        >
          Edit
        </button>
      </div>
      <p className="mt-0.5 text-sm text-content-muted">
        {seasonWindow(season)} · {timeLeftLabel(season)}
      </p>

      {editing && (
        <SeasonForm
          season={season}
          onClose={() => setEditing(false)}
          onSaved={() => {
            setEditing(false);
            onSaved();
          }}
        />
      )}
    </li>
  );
}

function SeasonForm({
  season,
  onClose,
  onSaved,
}: {
  season?: Season;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(season?.name ?? '');
  const [startsOn, setStartsOn] = useState(season?.starts_on ?? '');
  const [endsOn, setEndsOn] = useState(season?.ends_on ?? '');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await api(
        season ? `/api/points/seasons/${season.id}` : '/api/points/seasons',
        {
          method: season ? 'PATCH' : 'POST',
          body: JSON.stringify({
            name,
            starts_on: startsOn,
            ends_on: endsOn,
          }),
        },
      );
      onSaved();
    } catch (e) {
      // The server's own words. It knows why — overlapping dates, or awards
      // already outside the new window — and paraphrasing here would lose the
      // half that says what to do about it.
      setError(e instanceof Error ? e.message : 'Could not save.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mt-4 rounded-md border border-edge bg-surface-hover p-4">
      <div className="grid gap-4 sm:grid-cols-3">
        <label className="block">
          <span className="text-sm text-content-muted">Name</span>
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Q1 2028"
            className="mt-1 w-full rounded-md border border-edge bg-surface px-3 py-2 text-content"
          />
        </label>
        <label className="block">
          <span className="text-sm text-content-muted">Starts</span>
          <input
            type="date"
            value={startsOn}
            onChange={(event) => setStartsOn(event.target.value)}
            className="mt-1 w-full rounded-md border border-edge bg-surface px-3 py-2 text-content"
          />
        </label>
        <label className="block">
          <span className="text-sm text-content-muted">Ends</span>
          <input
            type="date"
            value={endsOn}
            onChange={(event) => setEndsOn(event.target.value)}
            className="mt-1 w-full rounded-md border border-edge bg-surface px-3 py-2 text-content"
          />
        </label>
      </div>

      <p className="mt-2 text-xs text-content-muted">
        The last day counts. A season runs through the date you give here.
      </p>

      {error && (
        <p role="alert" className="mt-3 rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      <div className="mt-4 flex gap-2">
        <button
          type="button"
          onClick={save}
          disabled={saving || !name || !startsOn || !endsOn}
          className="rounded-md bg-brand px-4 py-2 text-sm text-white disabled:opacity-60"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
        <MissingHint checks={[[!name, 'Name the season.'], [!startsOn || !endsOn, 'Choose when it starts and ends.']]} />
        <button
          type="button"
          onClick={onClose}
          className="rounded-md px-4 py-2 text-sm text-content-muted hover:text-content"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
