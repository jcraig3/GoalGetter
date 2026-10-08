import { Link } from 'react-router-dom';
import { useCallback, useEffect, useState } from 'react';

import { api } from '../api';
import UploadToLibrary from './UploadToLibrary';
import { type Badge, termsLabel } from '../pages/badgesCopy';
import { ASSET_PREFIX, BADGE_MARKS, BadgeMark, type BadgeMarkKey } from './badgeMarks';
import { ask } from '../confirm';
import Loading from './Loading';
import { toast } from '../toast';
import { useFocusRow } from '../urlIntent';

interface Rule {
  id: number;
  name: string;
}

/**
 * Defining badges.
 *
 * Two kinds, and the choice between them is the first thing on the form
 * because everything else depends on it: a badge an admin pins on by hand, or
 * one counted from an achievement rule firing enough times in a window.
 *
 * **Deleting one takes its history with it**, so every row shows how many
 * people hold it, and the confirmation repeats the number. Somebody who wants
 * a badge to stop being earned without erasing what people already have
 * should switch it to "given by hand" and simply stop giving it.
 */
export default function BadgeAdmin() {
  const [rows, setRows] = useState<Badge[] | null>(null);
  const [rules, setRules] = useState<Rule[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Badge | 'new' | null>(null);
  useFocusRow(rows !== null);

  const load = useCallback(() => {
    Promise.all([
      api<Badge[]>('/api/points/badges'),
      api<Rule[]>('/api/achievement-rules'),
    ])
      .then(([badges, found]) => {
        setRows(badges);
        setRules(found);
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load.'));
  }, []);

  useEffect(load, [load]);

  async function remove(badge: Badge) {
    const who =
      badge.holders === 0
        ? 'Nobody holds it yet.'
        : `${badge.holders} ${badge.holders === 1 ? 'person holds' : 'people hold'} it, and will lose it.`;
    // Points it paid stay — the season's record (7.5, as decided).
    if (!await ask(`Delete "${badge.name}"? ${who} Points it already paid stay.`)) return;
    try {
      await api(`/api/points/badges/${badge.id}`, { method: 'DELETE' });
      toast('Badge deleted');
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not delete.');
    }
  }

  if (error && !rows) {
    return (
      <p role="alert" className="rounded-md border border-danger px-3 py-2 text-sm text-danger">
        {error}
      </p>
    );
  }
  if (!rows) return <Loading />;

  return (
    <section className="rounded-lg border border-edge bg-surface p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-h3 text-content">Badges</h2>
          <p className="mt-1 text-sm text-content-muted">
            Badges stay when a season ends. Points and tiers start again; a
            badge for what somebody did in March is still theirs in December.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setEditing('new')}
          className="rounded-md bg-brand px-4 py-2 text-sm text-white"
        >
          Add a badge
        </button>
      </div>

      {error && (
        <p role="alert" className="mt-4 rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      {editing === 'new' && (
        <BadgeForm
          rules={rules}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            load();
          }}
        />
      )}

      {rows.length === 0 ? (
        <p className="mt-5 text-sm text-content-muted">
          No badges yet.
        </p>
      ) : (
        <ul className="mt-5 divide-y divide-edge">
          {rows.map((badge) => (
            <li key={badge.id} id={`row-${badge.id}`} className="py-4 first:pt-0 last:pb-0">
              <div className="flex flex-wrap items-center gap-3">
                <span className="text-brand">
                  <BadgeMark icon={badge.icon} />
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-content">{badge.name}</p>
                  <p className="text-sm text-content-muted">
                    {termsLabel(badge)}
                    {badge.points > 0 && ` · pays ${badge.points} points`}
                    {' · '}
                    {badge.holders === 1 ? '1 holder' : `${badge.holders} holders`}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setEditing(badge)}
                  className="text-sm text-content-muted hover:text-brand"
                >
                  Edit
                </button>
                <button
                  type="button"
                  onClick={() => remove(badge)}
                  className="text-sm text-content-muted hover:text-danger"
                >
                  Delete
                </button>
              </div>

              {editing !== 'new' && editing?.id === badge.id && (
                <BadgeForm
                  badge={badge}
                  rules={rules}
                  onClose={() => setEditing(null)}
                  onSaved={() => {
                    setEditing(null);
                    load();
                  }}
                />
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function BadgeForm({
  badge,
  rules,
  onClose,
  onSaved,
}: {
  badge?: Badge;
  rules: Rule[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(badge?.name ?? '');
  const [description, setDescription] = useState(badge?.description ?? '');
  const [kind, setKind] = useState<'manual' | 'count'>(badge?.kind ?? 'manual');
  const [icon, setIcon] = useState<string>(badge?.icon ?? 'medal');
  const [points, setPoints] = useState(String(badge?.points ?? 0));
  const [ruleId, setRuleId] = useState(String(badge?.achievement_rule_id ?? ''));
  const [threshold, setThreshold] = useState(String(badge?.threshold ?? 3));
  const [countedOver, setCountedOver] = useState(badge?.counted_over ?? 'month');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await api(badge ? `/api/points/badges/${badge.id}` : '/api/points/badges', {
        method: badge ? 'PATCH' : 'POST',
        body: JSON.stringify({
          name,
          description,
          kind,
          icon,
          points: Number(points) || 0,
          ...(kind === 'count'
            ? {
                achievement_rule_id: Number(ruleId) || null,
                threshold: Number(threshold) || null,
                counted_over: countedOver,
              }
            : {}),
        }),
      });
      // Said, as every other save is (Q2-22).
      toast(badge ? 'Badge saved' : `${name} created`);
      onSaved();
    } catch (e) {
      // The server's words: it says which rule was broken — no rule chosen,
      // no number, a name already taken — and a paraphrase would lose that.
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
        <legend className="text-sm text-content-muted">How is it earned?</legend>
        <div className="mt-2 flex flex-wrap gap-4">
          <label className="flex items-center gap-2 text-content">
            <input
              type="radio"
              checked={kind === 'manual'}
              onChange={() => setKind('manual')}
            />
            Given by hand
          </label>
          <label className="flex items-center gap-2 text-content">
            <input
              type="radio"
              checked={kind === 'count'}
              onChange={() => setKind('count')}
            />
            When a celebration rule fires enough times
          </label>
        </div>
      </fieldset>

      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block">
          <span className="text-sm text-content-muted">Name</span>
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Closer"
            className={input}
          />
        </label>
        <label className="block">
          <span className="text-sm text-content-muted">Points when earned</span>
          <input
            type="number"
            min={0}
            value={points}
            onChange={(event) => setPoints(event.target.value)}
            className={`${input} tabular-nums`}
          />
        </label>
      </div>

      <label className="block">
        <span className="text-sm text-content-muted">What it is for</span>
        <input
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          placeholder="Three big deals in a month"
          className={input}
        />
        <span className="mt-1 block text-xs text-content-muted">
          Shown to people who have not got it yet, which is most of what a
          badge does on a page.
        </span>
      </label>

      {kind === 'count' && (
        <div className="grid gap-4 sm:grid-cols-3">
          <label className="block sm:col-span-1">
            <span className="text-sm text-content-muted">Achievement</span>
            <select
              value={ruleId}
              onChange={(event) => setRuleId(event.target.value)}
              className={input}
            >
              <option value="">Choose one…</option>
              {rules.map((rule) => (
                <option key={rule.id} value={rule.id}>
                  {rule.name}
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="text-sm text-content-muted">Times</span>
            <input
              type="number"
              min={1}
              value={threshold}
              onChange={(event) => setThreshold(event.target.value)}
              className={`${input} tabular-nums`}
            />
          </label>
          <label className="block">
            <span className="text-sm text-content-muted">Within</span>
            <select
              value={countedOver}
              onChange={(event) => setCountedOver(event.target.value)}
              className={input}
            >
              <option value="week">A week</option>
              <option value="month">A month</option>
              <option value="season">A season</option>
            </select>
          </label>
        </div>
      )}

      {kind === 'count' && rules.length === 0 && (
        <p className="text-sm text-warning">
          A counted badge counts a celebration rule, and there are none yet.{' '}
          <Link to="/celebrations" className="underline">
            Make one under Celebrations
          </Link>{' '}
          first.
        </p>
      )}

      <fieldset>
        <legend className="text-sm text-content-muted">Art</legend>
        <div className="mt-2 grid grid-cols-[repeat(auto-fill,minmax(4.5rem,1fr))] gap-2">
          {(Object.keys(BADGE_MARKS) as BadgeMarkKey[]).map((key) => (
            <button
              key={key}
              type="button"
              onClick={() => setIcon(key)}
              aria-pressed={icon === key}
              aria-label={BADGE_MARKS[key].label}
              title={BADGE_MARKS[key].label}
              className={`flex flex-col items-center gap-1 rounded-md border p-2 text-xs transition-colors ${
                icon === key
                  ? 'border-brand bg-brand-subtle text-content'
                  : 'border-edge text-content-muted hover:bg-surface-hover hover:text-content'
              }`}
            >
              <BadgeMark icon={key} className="h-11 w-11" />
              <span className="line-clamp-2 w-full text-center leading-tight">{BADGE_MARKS[key].label}</span>
            </button>
          ))}
        </div>
        {/* **Or the organization's own** (6.5): any picture in Assets. Art
            with a transparent background looks best, and is kept that way. */}
        <OwnArt icon={icon} onPick={setIcon} />
      </fieldset>

      {error && (
        <p role="alert" className="rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      <div className="flex gap-2">
        <button
          type="button"
          onClick={save}
          disabled={saving || !name}
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

/** Pictures from Organization → Assets, offered as a badge's art. */
function OwnArt({ icon, onPick }: { icon: string; onPick: (icon: string) => void }) {
  const [images, setImages] = useState<{ digest: string; name: string | null }[] | null>(null);

  useEffect(() => {
    api<{ digest: string; name: string | null; kind: string }[]>('/api/assets')
      .then((all) => setImages(all.filter((a) => a.kind === 'image')))
      .catch(() => setImages([]));
  }, []);

  return (
    <div className="mt-3">
      <p className="text-xs text-content-subtle">
        Or your own, from{' '}
        <Link to="/library" className="underline">
          Assets
        </Link>
        {images && images.length === 0 && ' — add a picture there first'}.
      </p>
      {images && (
        <div className="mt-2 flex flex-wrap gap-2">
          {/* Or from this computer, into the library (Phase 27). */}
          <UploadToLibrary
            onUploaded={(file) => {
              if (file.kind !== 'image') return;
              setImages((all) => [{ digest: file.digest, name: file.name }, ...(all ?? [])]);
              onPick(`${ASSET_PREFIX}${file.digest}`);
            }}
          />
          {images.map((image) => {
            const value = `${ASSET_PREFIX}${image.digest}`;
            return (
              <button
                key={image.digest}
                type="button"
                onClick={() => onPick(value)}
                aria-pressed={icon === value}
                aria-label={image.name ?? 'Uploaded picture'}
                title={image.name ?? undefined}
                className={`rounded-md border p-1.5 transition-colors ${
                  icon === value ? 'border-brand bg-brand-subtle' : 'border-edge hover:bg-surface-hover'
                }`}
              >
                <BadgeMark icon={value} className="h-11 w-11" />
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
