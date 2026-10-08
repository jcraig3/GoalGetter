import { useCallback, useEffect, useState } from 'react';

import { api } from '../api';
import { formatPoints } from '../pages/pointsCopy';
import { type Item, type Shop as ShopData, shortBy } from '../pages/spendCopy';
import { ringStyle } from './ring';
import Loading from './Loading';

/**
 * Cosmetics: rings and titles, bought with points.
 *
 * **Spending here never moves anybody on the table**, and the page says so,
 * because it is the one worry that would stop somebody pressing Buy. What is
 * spent comes out of the wallet — earned in every season, less what has been
 * spent — and the season table keeps ranking what was earned.
 */
export default function Shop({ onChange }: { onChange?: () => void }) {
  const [shop, setShop] = useState<ShopData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  const load = useCallback(() => {
    api<ShopData>('/api/points/unlockables')
      .then(setShop)
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load.'));
  }, []);

  useEffect(load, [load]);

  async function act(item: Item, verb: 'buy' | 'wear' | 'take-off') {
    setBusy(item.id);
    setError(null);
    try {
      setShop(
        await api<ShopData>(`/api/points/unlockables/${item.id}/${verb}`, {
          method: 'POST',
        }),
      );
      onChange?.();
    } catch (e) {
      // The server's own words — it says how many points short, which is the
      // half of "not enough" somebody can do something about.
      setError(e instanceof Error ? e.message : 'Could not do that.');
    } finally {
      setBusy(null);
    }
  }

  if (error && !shop) {
    return (
      <p role="alert" className="rounded-md border border-danger px-3 py-2 text-sm text-danger">
        {error}
      </p>
    );
  }
  if (!shop) return <Loading />;

  const rings = shop.items.filter((item) => item.kind === 'ring');
  const titles = shop.items.filter((item) => item.kind === 'title');

  return (
    <section className="rounded-lg border border-edge bg-surface p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-4">
        <h2 className="text-h3 text-content">Cosmetics</h2>
        <p className="text-sm text-content-muted">
          <span className="tabular-nums text-content">{formatPoints(shop.wallet)}</span>{' '}
          to spend
        </p>
      </div>
      <p className="mt-1 text-sm text-content-muted">
        Spending never moves you on the season table. A ring goes round your
        face everywhere it appears, the wall included.
      </p>

      {error && (
        <p role="alert" className="mt-4 rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      {shop.items.length === 0 ? (
        <p className="mt-5 text-sm text-content-muted">Nothing to buy yet.</p>
      ) : (
        <div className="mt-5 space-y-6">
          {rings.length > 0 && (
            <Group title="Rings" items={rings} wallet={shop.wallet} busy={busy} onAct={act} />
          )}
          {titles.length > 0 && (
            <Group title="Titles" items={titles} wallet={shop.wallet} busy={busy} onAct={act} />
          )}
        </div>
      )}
    </section>
  );
}

function Group({
  title,
  items,
  wallet,
  busy,
  onAct,
}: {
  title: string;
  items: Item[];
  wallet: number;
  busy: number | null;
  onAct: (item: Item, verb: 'buy' | 'wear' | 'take-off') => void;
}) {
  return (
    <div>
      <h3 className="text-sm text-content-muted">{title}</h3>
      <ul className="mt-2 divide-y divide-edge">
        {items.map((item) => {
          const short = shortBy(wallet, item.price);
          return (
            <li key={item.id} className="flex flex-wrap items-center gap-3 py-3">
              {item.kind === 'ring' ? (
                <span
                  aria-hidden="true"
                  style={ringStyle(item.value, '3px', '3px')}
                  className="size-8 shrink-0 rounded-full bg-surface-hover"
                />
              ) : (
                <span className="shrink-0 rounded bg-brand-subtle px-2 py-0.5 text-sm text-content">
                  {item.value}
                </span>
              )}
              <div className="min-w-0 flex-1">
                <p className="text-content">
                  {item.name}
                  {!item.enabled && (
                    <span className="ml-2 text-xs text-content-muted">retired</span>
                  )}
                </p>
                <p className="text-sm tabular-nums text-content-muted">
                  {item.owned ? 'Yours' : `${formatPoints(item.price)} points`}
                </p>
              </div>

              {item.owned ? (
                <button
                  type="button"
                  disabled={busy === item.id}
                  onClick={() => onAct(item, item.equipped ? 'take-off' : 'wear')}
                  aria-pressed={item.equipped}
                  className={`rounded-md px-3 py-1.5 text-sm disabled:opacity-60 ${
                    item.equipped
                      ? 'bg-brand-subtle text-content'
                      : 'border border-edge text-content hover:border-brand'
                  }`}
                >
                  {item.equipped ? 'Wearing' : 'Wear'}
                </button>
              ) : (
                <button
                  type="button"
                  disabled={busy === item.id || short > 0 || !item.enabled}
                  onClick={() => onAct(item, 'buy')}
                  // Says how far short rather than just greying out: a
                  // disabled button with no reason is a puzzle.
                  title={short > 0 ? `${formatPoints(short)} more to go` : undefined}
                  className="rounded-md bg-brand px-3 py-1.5 text-sm text-white disabled:opacity-50"
                >
                  {short > 0 ? `${formatPoints(short)} short` : 'Buy'}
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
