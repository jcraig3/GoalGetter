import { useCallback, useEffect, useState } from 'react';

import { api } from '../api';
import { formatPoints } from '../pages/pointsCopy';
import type { Item, Shop } from '../pages/spendCopy';
import { ringStyle } from './ring';
import { ask } from '../confirm';
import Loading from './Loading';
import { toast } from '../toast';
import MissingHint from './MissingHint';

/**
 * Stocking the cosmetics.
 *
 * **Retire rather than delete, once anybody has bought one.** Deleting it then
 * would take it off people who paid for it — their points back without saying
 * so — so the server refuses, and this list offers Retire in its place: it
 * stops being sold and stays on everybody who has it.
 */
export default function CosmeticAdmin() {
  const [items, setItems] = useState<Item[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  const load = useCallback(() => {
    api<Shop>('/api/points/unlockables')
      .then((shop) => setItems(shop.items))
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load.'));
  }, []);

  useEffect(load, [load]);

  async function retire(item: Item, enabled: boolean) {
    setError(null);
    try {
      await api(`/api/points/unlockables/${item.id}`, {
        method: 'PATCH',
        body: JSON.stringify({
          name: item.name,
          kind: item.kind,
          value: item.value,
          price: item.price,
          enabled,
        }),
      });
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save.');
    }
  }

  async function remove(item: Item) {
    if (!await ask(`Delete "${item.name}"? Nobody has bought it yet.`)) return;
    setError(null);
    try {
      await api(`/api/points/unlockables/${item.id}`, { method: 'DELETE' });
      toast('Deleted');
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not delete.');
    }
  }

  if (!items) {
    return error ? (
      <p role="alert" className="rounded-md border border-danger px-3 py-2 text-sm text-danger">
        {error}
      </p>
    ) : (
      <Loading />
    );
  }

  return (
    <section className="rounded-lg border border-edge bg-surface p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-h3 text-content">Cosmetics</h2>
          <p className="mt-1 text-sm text-content-muted">
            Something to spend points on that other people see. Titles are
            written here rather than typed by the person wearing one, so
            nothing on the wall needs moderating.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setAdding(true)}
          className="rounded-md bg-brand px-4 py-2 text-sm text-white"
        >
          Add one
        </button>
      </div>

      {error && (
        <p role="alert" className="mt-4 rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      {adding && (
        <CosmeticForm
          onClose={() => setAdding(false)}
          onSaved={() => {
            setAdding(false);
            load();
          }}
        />
      )}

      {items.length === 0 ? (
        <p className="mt-5 text-sm text-content-muted">Nothing on sale yet.</p>
      ) : (
        <ul className="mt-5 divide-y divide-edge">
          {items.map((item) => (
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
                <p className={item.enabled ? 'text-content' : 'text-content-muted'}>
                  {item.name}
                  {!item.enabled && <span className="ml-2 text-xs">retired</span>}
                </p>
                <p className="text-sm tabular-nums text-content-muted">
                  {formatPoints(item.price)} points ·{' '}
                  {item.owners === 1 ? '1 owner' : `${item.owners} owners`}
                </p>
              </div>
              <button
                type="button"
                onClick={() => retire(item, !item.enabled)}
                className="text-sm text-content-muted hover:text-brand"
              >
                {item.enabled ? 'Retire' : 'Put back on sale'}
              </button>
              {item.owners === 0 && (
                <button
                  type="button"
                  onClick={() => remove(item)}
                  className="text-sm text-content-muted hover:text-danger"
                >
                  Delete
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function CosmeticForm({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: () => void;
}) {
  const [kind, setKind] = useState<'ring' | 'title'>('ring');
  const [name, setName] = useState('');
  const [value, setValue] = useState('#f5b301');
  const [price, setPrice] = useState('300');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await api('/api/points/unlockables', {
        method: 'POST',
        body: JSON.stringify({ name, kind, value, price: Number(price) || 0 }),
      });
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save.');
    } finally {
      setSaving(false);
    }
  }

  const input =
    'mt-1 w-full rounded-md border border-edge bg-surface px-3 py-2 text-content';

  return (
    <div className="mt-4 space-y-4 rounded-md border border-edge bg-surface-hover p-4">
      <fieldset>
        <legend className="text-sm text-content-muted">What is it?</legend>
        <div className="mt-2 flex gap-4">
          {(['ring', 'title'] as const).map((option) => (
            <label key={option} className="flex items-center gap-2 text-content">
              <input
                type="radio"
                checked={kind === option}
                onChange={() => {
                  setKind(option);
                  setValue(option === 'ring' ? '#f5b301' : '');
                }}
              />
              {option === 'ring' ? 'A ring round their face' : 'A title under their name'}
            </label>
          ))}
        </div>
      </fieldset>

      <div className="grid gap-4 sm:grid-cols-3">
        <label className="block">
          <span className="text-sm text-content-muted">Name in the list</span>
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder={kind === 'ring' ? 'Gold ring' : 'The Closer'}
            className={input}
          />
        </label>
        <label className="block">
          <span className="text-sm text-content-muted">
            {kind === 'ring' ? 'Colour' : 'Words shown'}
          </span>
          {kind === 'ring' ? (
            <input
              type="color"
              value={value}
              onChange={(event) => setValue(event.target.value)}
              className="mt-1 h-10 w-full rounded-md border border-edge bg-surface"
            />
          ) : (
            <input
              value={value}
              maxLength={40}
              onChange={(event) => setValue(event.target.value)}
              placeholder="The Closer"
              className={input}
            />
          )}
        </label>
        <label className="block">
          <span className="text-sm text-content-muted">Price in points</span>
          <input
            type="number"
            min={1}
            value={price}
            onChange={(event) => setPrice(event.target.value)}
            className={`${input} tabular-nums`}
          />
        </label>
      </div>

      {error && (
        <p role="alert" className="rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      <div className="flex gap-2">
        <button
          type="button"
          onClick={save}
          disabled={saving || !name || !value}
          className="rounded-md bg-brand px-4 py-2 text-sm text-white disabled:opacity-60"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
        <MissingHint checks={[[!name, 'Name it.'], [!value, 'Choose what it is.']]} />
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
