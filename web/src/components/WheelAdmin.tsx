import { useCallback, useEffect, useState } from 'react';

import { api } from '../api';
import { formatPoints } from '../pages/pointsCopy';
import { type Prize, type Wheel, chanceLabel } from '../pages/spendCopy';
import { ask } from '../confirm';
import Loading from './Loading';
import { toast } from '../toast';

/**
 * Stocking the prize wheel.
 *
 * **It will not let the wheel print points.** A wheel whose average payout
 * reaches the price of a spin lets somebody spin forever and only ever gain,
 * so any change that would do that — a bigger points segment, a cheaper spin,
 * deleting a miss — is refused with the sum spelled out. The expected payout
 * is shown here the whole time, beside the price, so nobody has to find out
 * by being refused.
 */
export default function WheelAdmin() {
  const [wheel, setWheel] = useState<Wheel | null>(null);
  const [prizes, setPrizes] = useState<Prize[] | null>(null);
  const [cost, setCost] = useState('100');
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  const load = useCallback(() => {
    Promise.all([
      api<Wheel>('/api/points/wheel'),
      api<Prize[]>('/api/points/wheel/prizes'),
    ])
      .then(([found, stock]) => {
        setWheel(found);
        setPrizes(stock);
        setCost(String(found.spin_cost));
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load.'));
  }, []);

  useEffect(load, [load]);

  async function saveWheel(enabled: boolean) {
    setError(null);
    try {
      setWheel(
        await api<Wheel>('/api/points/wheel', {
          method: 'PUT',
          body: JSON.stringify({ spin_cost: Number(cost) || 0, enabled }),
        }),
      );
    } catch (e) {
      // The server says why in full — including the sum, when it is the
      // payout that is the problem.
      setError(e instanceof Error ? e.message : 'Could not save.');
    }
  }

  async function removePrize(prize: Prize) {
    if (!await ask(`Take "${prize.label}" off the wheel?`)) return;
    setError(null);
    try {
      await api(`/api/points/wheel/prizes/${prize.id}`, { method: 'DELETE' });
      toast('Prize taken off the wheel');
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not delete.');
    }
  }

  if (!wheel || !prizes) {
    return error ? (
      <p role="alert" className="rounded-md border border-danger px-3 py-2 text-sm text-danger">
        {error}
      </p>
    ) : (
      <Loading />
    );
  }

  const inDraw = prizes.filter(
    (p) => p.enabled && (p.stock === null || p.stock > 0),
  );
  const totalWeight = inDraw.reduce((sum, p) => sum + p.weight, 0);
  const payout = totalWeight
    ? inDraw.reduce((sum, p) => sum + p.points * p.weight, 0) / totalWeight
    : 0;
  const chanceOf = (prize: Prize) =>
    totalWeight && inDraw.includes(prize) ? prize.weight / totalWeight : 0;

  return (
    <section className="rounded-lg border border-edge bg-surface p-6">
      <h2 className="text-h3 text-content">Prize wheel</h2>
      <p className="mt-1 text-sm text-content-muted">
        People spend points to spin. Winnings go into what they can spend, and
        never onto the season table — a lucky spin should not climb it.
      </p>

      {error && (
        <p role="alert" className="mt-4 rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      <div className="mt-5 flex flex-wrap items-end gap-4">
        <label className="block">
          <span className="text-sm text-content-muted">Cost of a spin</span>
          <input
            type="number"
            min={1}
            value={cost}
            onChange={(event) => setCost(event.target.value)}
            className="mt-1 w-32 rounded-md border border-edge bg-surface px-3 py-2 text-right tabular-nums text-content"
          />
        </label>
        <button
          type="button"
          onClick={() => saveWheel(wheel.enabled)}
          className="rounded-md border border-edge px-4 py-2 text-sm text-content"
        >
          Save price
        </button>
        <button
          type="button"
          onClick={() => saveWheel(!wheel.enabled)}
          className="rounded-md bg-brand px-4 py-2 text-sm text-white"
        >
          {wheel.enabled ? 'Switch off' : 'Switch on'}
        </button>
        <p className="text-sm text-content-muted">
          Pays back{' '}
          <span className="tabular-nums text-content">{formatPoints(Math.round(payout))}</span>{' '}
          points a spin on average
        </p>
      </div>

      <div className="mt-6 flex items-center justify-between">
        <h3 className="text-sm text-content-muted">On the wheel</h3>
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="text-sm text-brand hover:underline"
        >
          Add a segment
        </button>
      </div>

      {adding && (
        <PrizeForm
          onClose={() => setAdding(false)}
          onSaved={() => {
            setAdding(false);
            load();
          }}
          onError={setError}
        />
      )}

      {prizes.length === 0 ? (
        <p className="mt-3 text-sm text-content-muted">
          Nothing yet. A wheel needs at least one segment before it can be
          switched on.
        </p>
      ) : (
        <ul className="mt-3 divide-y divide-edge">
          {prizes.map((prize) => (
            <li key={prize.id} className="flex flex-wrap items-center gap-3 py-3 text-sm">
              <div className="min-w-0 flex-1">
                <p className="text-content">{prize.label}</p>
                <p className="text-content-muted">
                  {prize.kind === 'points'
                    ? `${formatPoints(prize.points)} points`
                    : prize.kind === 'prize'
                      ? prize.stock === null
                        ? 'A real prize'
                        : `A real prize · ${prize.stock} left`
                      : 'A miss'}
                  {' · weight '}
                  {prize.weight}
                </p>
              </div>
              <span className="tabular-nums text-content-muted">
                {chanceOf(prize) ? chanceLabel(chanceOf(prize)) : 'not in the draw'}
              </span>
              <button
                type="button"
                onClick={() => removePrize(prize)}
                className="text-content-muted hover:text-danger"
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function PrizeForm({
  onClose,
  onSaved,
  onError,
}: {
  onClose: () => void;
  onSaved: () => void;
  onError: (message: string | null) => void;
}) {
  const [kind, setKind] = useState<'points' | 'prize' | 'nothing'>('prize');
  const [label, setLabel] = useState('');
  const [points, setPoints] = useState('50');
  const [weight, setWeight] = useState('1');
  const [stock, setStock] = useState('');
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    onError(null);
    try {
      await api('/api/points/wheel/prizes', {
        method: 'POST',
        body: JSON.stringify({
          label,
          kind,
          points: kind === 'points' ? Number(points) || 0 : 0,
          weight: Number(weight) || 1,
          stock: kind === 'prize' && stock !== '' ? Number(stock) : null,
        }),
      });
      onSaved();
    } catch (e) {
      onError(e instanceof Error ? e.message : 'Could not save.');
    } finally {
      setSaving(false);
    }
  }

  const input =
    'mt-1 w-full rounded-md border border-edge bg-surface px-3 py-2 text-content';

  return (
    <div className="mt-3 space-y-4 rounded-md border border-edge bg-surface-hover p-4">
      <fieldset>
        <legend className="text-sm text-content-muted">What does it give?</legend>
        <div className="mt-2 flex flex-wrap gap-4">
          {(
            [
              ['prize', 'Something real'],
              ['points', 'Points'],
              ['nothing', 'Nothing — a miss'],
            ] as const
          ).map(([value, text]) => (
            <label key={value} className="flex items-center gap-2 text-content">
              <input type="radio" checked={kind === value} onChange={() => setKind(value)} />
              {text}
            </label>
          ))}
        </div>
      </fieldset>

      <div className="grid gap-4 sm:grid-cols-4">
        <label className="block sm:col-span-2">
          <span className="text-sm text-content-muted">What it says</span>
          <input
            value={label}
            maxLength={60}
            onChange={(event) => setLabel(event.target.value)}
            placeholder={
              kind === 'prize' ? 'Long lunch' : kind === 'points' ? '+50' : 'So close'
            }
            className={input}
          />
        </label>
        {kind === 'points' && (
          <label className="block">
            <span className="text-sm text-content-muted">Points</span>
            <input
              type="number"
              min={1}
              value={points}
              onChange={(event) => setPoints(event.target.value)}
              className={`${input} tabular-nums`}
            />
          </label>
        )}
        {kind === 'prize' && (
          <label className="block">
            <span className="text-sm text-content-muted">How many (blank = no limit)</span>
            <input
              type="number"
              min={0}
              value={stock}
              onChange={(event) => setStock(event.target.value)}
              className={`${input} tabular-nums`}
            />
          </label>
        )}
        <label className="block">
          <span className="text-sm text-content-muted">Weight</span>
          <input
            type="number"
            min={1}
            value={weight}
            onChange={(event) => setWeight(event.target.value)}
            className={`${input} tabular-nums`}
          />
        </label>
      </div>
      <p className="text-xs text-content-muted">
        A weight rather than a percentage, so adding a segment never means
        re-balancing all the others by hand. The chance each one comes up is
        worked out from the weights and shown to people before they spin.
      </p>

      <div className="flex gap-2">
        <button
          type="button"
          onClick={save}
          disabled={saving || !label}
          className="rounded-md bg-brand px-4 py-2 text-sm text-white disabled:opacity-60"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
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
