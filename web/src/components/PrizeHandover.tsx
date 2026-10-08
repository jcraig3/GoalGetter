import { dayMonth } from '../time';
import { useCallback, useEffect, useState } from 'react';

import { api } from '../api';
import type { Spin } from '../pages/spendCopy';

/**
 * Real prizes won on the wheel and not yet handed over.
 *
 * **A real prize with no list behind it is a promise that gets forgotten on a
 * Friday afternoon** — and a wheel that pays out things nobody receives is
 * worse than no wheel. So every real win lands here, oldest first, for
 * whoever can see the winner: usually their manager, standing near their
 * desk.
 *
 * Renders nothing when the list is empty, so a manager with nothing to hand
 * over is not shown a panel telling them so.
 */
export default function PrizeHandover() {
  const [rows, setRows] = useState<Spin[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<Spin[]>('/api/points/wheel/waiting')
      .then(setRows)
      .catch(() => setRows([]));
  }, []);

  useEffect(load, [load]);

  async function given(spin: Spin) {
    setError(null);
    try {
      await api(`/api/points/wheel/spins/${spin.id}/given`, { method: 'POST' });
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save.');
    }
  }

  if (rows.length === 0) return null;

  return (
    <section className="rounded-lg border border-warning bg-surface p-6">
      <h2 className="text-h3 text-content">Prizes to hand over</h2>
      <p className="mt-1 text-sm text-content-muted">
        Won on the prize wheel, oldest first.
      </p>
      {error && (
        <p role="alert" className="mt-3 rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}
      <ul className="mt-4 divide-y divide-edge">
        {rows.map((spin) => (
          <li key={spin.id} className="flex flex-wrap items-center gap-3 py-3">
            <div className="min-w-0 flex-1">
              <p className="text-content">
                {spin.winner_name} · {spin.label}
              </p>
              <p className="text-sm text-content-muted">
                Won {dayMonth(spin.created_at)}
              </p>
            </div>
            <button
              type="button"
              onClick={() => given(spin)}
              className="rounded-md border border-edge px-3 py-1.5 text-sm text-content hover:border-brand"
            >
              Mark handed over
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
