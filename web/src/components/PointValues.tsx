import { useEffect, useState } from 'react';

import { api } from '../api';
import { EVENT_LABELS, EVENT_NOTES, labelFor } from '../pages/pointsCopy';
import Loading from './Loading';

interface Values {
  values: Record<string, number>;
}

/**
 * What each thing is worth here.
 *
 * **Changing a price changes nothing that has already been awarded.** A ledger
 * row records what was paid at the time, and re-pricing history would mean
 * somebody's balance moving overnight for work they did last month — the
 * fastest way to stop people believing the number. The page says so, because
 * an admin lowering a value is entitled to know it will not claw anything
 * back.
 */
export default function PointValues() {
  const [values, setValues] = useState<Record<string, number> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api<Values>('/api/points/values')
      .then((body) => setValues(body.values))
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load.'));
  }, []);

  async function save() {
    if (!values) return;
    setSaving(true);
    setError(null);
    try {
      const body = await api<Values>('/api/points/values', {
        method: 'PUT',
        body: JSON.stringify({ values }),
      });
      setValues(body.values);
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save.');
    } finally {
      setSaving(false);
    }
  }

  if (error && !values) {
    return (
      <p role="alert" className="rounded-md border border-danger px-3 py-2 text-sm text-danger">
        {error}
      </p>
    );
  }
  if (!values) return <Loading />;

  // The server's own order, which is the order of `points.DEFAULTS` — biggest
  // ideas first — rather than alphabetical, which would put "Birthday" above
  // "Winning a competition".
  const rows = Object.keys(EVENT_LABELS).filter((key) => key in values);

  return (
    <section className="rounded-lg border border-edge bg-surface p-6">
      <h2 className="text-h3 text-content">What things are worth</h2>
      <p className="mt-1 text-sm text-content-muted">
        Changing these affects points awarded from now on. Nothing already
        earned moves.
      </p>

      {error && (
        <p role="alert" className="mt-4 rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      <div className="mt-5 space-y-4">
        {rows.map((key) => (
          <div key={key} className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0 flex-1">
              <label htmlFor={`points-${key}`} className="text-content">
                {labelFor(key)}
              </label>
              {EVENT_NOTES[key] && (
                <p className="mt-0.5 text-xs text-content-muted">
                  {EVENT_NOTES[key]}
                </p>
              )}
            </div>
            <input
              id={`points-${key}`}
              type="number"
              min={0}
              value={values[key]}
              onChange={(event) => {
                setSaved(false);
                setValues({
                  ...values,
                  // An empty box is 0, not NaN — which would be sent as null
                  // and refused by the server with a message about types.
                  [key]: Math.max(0, Number(event.target.value) || 0),
                });
              }}
              className="w-24 rounded-md border border-edge bg-surface px-3 py-2 text-right tabular-nums text-content"
            />
          </div>
        ))}
      </div>

      <div className="mt-6 flex items-center gap-3">
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

      <p className="mt-6 text-xs text-content-muted">
        Celebration rules carry their own value, set on the rule itself — one
        fires on every matching record, so how much it is worth depends on how
        often it will fire.
      </p>
    </section>
  );
}
