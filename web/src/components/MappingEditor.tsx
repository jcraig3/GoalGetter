import { dayAndTime } from '../time';
import { useCallback, useEffect, useRef, useState } from 'react';

import {
  dataSources,
  type Mapping,
  type PreviewRow,
  type SourceField,
} from '../dataSources';
import Field from './Field';
import Select from './Select';
import { TrashIcon } from './icons';
import { columnForMetric } from '../pages/metricSuggest';
import { suggestMapping, type DraftKey } from '../pages/sourceWizard';

/**
 * "This column means that", with the answer shown before it is committed.
 *
 * The single most useful thing in the connect flow: a mapping error appears in
 * three seconds rather than after a sync has recorded forty thousand wrong
 * numbers. The preview comes from the server, through the same code the real
 * sync uses, so what is on screen is genuinely what will happen — a
 * preview computed in the browser would be a second implementation of the
 * interesting logic, and the two would agree right up until somebody fixed a bug
 * in one of them.
 *
 * **It saves as it goes, and what it saves is switched off.** Preview needs a
 * mapping to exist server-side, so every edit is persisted; a mapping left
 * `enabled: false` imports nothing, which means an abandoned setup does no harm
 * and turning it on is a deliberate act at the end of the flow.
 */

/** The operators the API accepts, with wording an admin can act on. */
const OPS = [
  { value: 'eq', label: 'is' },
  { value: 'ne', label: 'is not' },
  { value: 'contains', label: 'contains' },
  { value: 'not_contains', label: 'does not contain' },
  { value: 'in', label: 'is one of' },
  { value: 'gt', label: 'is greater than' },
  { value: 'gte', label: 'is at least' },
  { value: 'lt', label: 'is less than' },
  { value: 'lte', label: 'is at most' },
];

export interface MetricOption {
  id: number;
  name: string;
  unit: string;
  archived: boolean;
}

/** How long to wait after a keystroke before saving and re-previewing. */
const SETTLE_MS = 600;

/** The row's id, falling back to the subject when the source has no dates. */
function rowIdFor(draft: {
  occurred_at_field: string | null;
  external_id_field: string | null;
  subject_field: string;
}): string | null {
  if (draft.external_id_field) return draft.external_id_field;
  return draft.occurred_at_field ? null : draft.subject_field || null;
}

interface Draft {
  metric_id: number;
  subject_field: string;
  occurred_at_field: string | null;
  value_field: string | null;
  external_id_field: string | null;
  multiplier: string;
  snapshot_daily: boolean;
  filters: { field: string; op: string; value: string }[];
}

export default function MappingEditor({
  sourceId,
  fields,
  metrics,
  existing,
  onSaved,
  onRemoved,
}: {
  sourceId: number;
  fields: SourceField[];
  metrics: MetricOption[];
  /** Absent when adding. Present when editing one already saved. */
  existing?: Mapping;
  onSaved: (mapping: Mapping) => void;
  onRemoved?: () => void;
}) {
  const importable = metrics.filter((m) => !m.archived);
  const suggestion = suggestMapping(fields);

  const [draft, setDraft] = useState<Draft>(() =>
    existing
      ? {
          metric_id: existing.metric_id,
          subject_field: existing.subject_field,
          occurred_at_field: existing.occurred_at_field,
          value_field: existing.value_field,
          external_id_field: existing.external_id_field,
          multiplier: existing.multiplier,
          snapshot_daily: existing.snapshot_daily ?? false,
          filters: existing.filters ?? [],
        }
      : {
          metric_id: importable[0]?.id ?? 0,
          ...suggestion.draft,
          // **A dateless source is identified by its subject, until told
          // otherwise.** Such a source has one row per person, so the person is
          // what identifies the row — and a row id is mandatory there, so
          // starting empty opens a form that cannot be saved without saying that
          // the answer is already on screen.
          external_id_field: rowIdFor(suggestion.draft),
          multiplier: '1',
          // One row per person — the row's id *is* the person — means a running
          // total, which is the shape that loses its history without a figure
          // kept per day. See `SourceMapping.snapshot_daily`.
          snapshot_daily:
            !suggestion.draft.occurred_at_field &&
            !!suggestion.draft.subject_field &&
            rowIdFor(suggestion.draft) === suggestion.draft.subject_field,
          filters: [],
        },
  );

  const [mappingId, setMappingId] = useState<number | null>(
    existing?.id ?? null,
  );
  const [preview, setPreview] = useState<PreviewRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Held in a ref rather than state: it changes on every keystroke and nothing
  // renders from it, so putting it in state would re-render the whole editor
  // twice per character for no visible reason.
  const timer = useRef<number | null>(null);

  const body = useCallback(
    () => ({
      metric_id: draft.metric_id,
      subject_field: draft.subject_field,
      occurred_at_field: draft.occurred_at_field,
      value_field: draft.value_field || null,
      external_id_field: draft.external_id_field || null,
      multiplier: draft.multiplier || '1',
      snapshot_daily: draft.snapshot_daily,
      // Half-typed rows are dropped rather than sent: the API refuses a filter
      // with no field, and a red error while somebody is mid-thought is noise.
      filters: draft.filters.filter((f) => f.field && f.value),
      // Off until the flow says otherwise. See the note at the top.
      ...(existing ? {} : { enabled: false }),
    }),
    [draft, existing],
  );

  // A date column is no longer part of being ready: empty is a real answer,
  // meaning the fact is dated by when its number last changed.
  //
  // **A row id takes its place when it is.** That rule needs to find the fact
  // written last time and compare; with nothing to find it by, every read inserts
  // a new fact instead, so the totals multiply and the date is always today.
  const ready =
    draft.metric_id > 0 &&
    !!draft.subject_field &&
    (!!draft.occurred_at_field || !!draft.external_id_field);

  /** Save, then preview. One after the other because preview needs the id. */
  const saveAndPreview = useCallback(async () => {
    if (!ready) return;
    setBusy(true);
    setError(null);
    try {
      const source = mappingId
        ? await dataSources.editMapping(sourceId, mappingId, body())
        : await dataSources.addMapping(sourceId, body());

      // The API returns the whole source, so the mapping is found rather than
      // assumed — on a create there is no id to have guessed.
      const saved = mappingId
        ? source.mappings.find((m) => m.id === mappingId)
        : source.mappings.find((m) => m.metric_id === draft.metric_id);
      if (!saved) throw new Error('Saved, but the mapping came back missing.');

      setMappingId(saved.id);
      onSaved(saved);
      setPreview(await dataSources.preview(sourceId, saved.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save that mapping.');
    } finally {
      setBusy(false);
    }
  }, [body, draft.metric_id, mappingId, onSaved, ready, sourceId]);

  // Debounced, and deliberately not on mount for a mapping being edited: opening
  // an existing mapping should not rewrite it before anything is touched.
  const [touched, setTouched] = useState(!existing);
  useEffect(() => {
    if (!touched) return;
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => void saveAndPreview(), SETTLE_MS);
    return () => {
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [draft, saveAndPreview, touched]);

  function set<K extends keyof Draft>(key: K, value: Draft[K]) {
    setTouched(true);
    setDraft((d) => ({ ...d, [key]: value }));
  }

  //: Why the value column says what it says, when it was filled in by choosing a
  //: metric rather than typed.
  const matched = importable.find((m) => m.id === draft.metric_id)?.name ?? '';

  const columns = [{ value: '', label: '— none —' }].concat(
    fields.map((f) => ({ value: f.name, label: `${f.name}  (${f.kind})` })),
  );
  const required = fields.map((f) => ({
    value: f.name,
    label: `${f.name}  (${f.kind})`,
  }));

  /** The reason under a picker, but only while it still holds the guess. */
  const why = (key: DraftKey, current: string | null) =>
    existing || (suggestion.draft[key] ?? '') !== (current ?? '')
      ? undefined
      : suggestion.reasons[key];

  return (
    <div className="rounded-lg border border-edge bg-surface p-5">
      <div className="grid gap-4 sm:grid-cols-2">
        <Select
          label="Import into which metric"
          value={String(draft.metric_id)}
          onChange={(v) => {
            // **Picking the metric fills in what it measures.** Metrics made
            // from this source are named after their columns, so the answer to
            // "which column is that?" is in the name somebody just chose —
            // asking again is the same question twice. Left alone when nothing
            // matches, because a wrong column is a leaderboard measuring the
            // wrong thing and an empty picker at least asks visibly.
            const id = Number(v);
            const chosen = importable.find((m) => m.id === id);
            const column = chosen ? columnForMetric(chosen.name, fields) : null;
            setTouched(true);
            setDraft((d) => ({
              ...d,
              metric_id: id,
              ...(column ? { value_field: column } : {}),
            }));
          }}
          options={importable.map((m) => ({
            value: String(m.id),
            label: m.name,
          }))}
          hint={
            existing
              ? 'Fixed once saved — the facts it imported belong to this metric.'
              : 'Where these numbers will appear on leaderboards and goals.'
          }
        />
        <Select
          label="Who it belongs to"
          value={draft.subject_field}
          onChange={(v) => set('subject_field', v)}
          options={required}
          hint={why('subject_field', draft.subject_field)}
        />
        {/* **Optional, because plenty of sources have no date to give.** A
            pre-aggregated view — one row per person, a number that moves — is
            the shape every leaderboard tool before this one asks for. Left
            empty, the fact is dated by when its number last changed. */}
        <Select
          label="When it happened"
          value={draft.occurred_at_field ?? ''}
          onChange={(v) => set('occurred_at_field', v || null)}
          options={columns}
          hint={
            why('occurred_at_field', draft.occurred_at_field) ??
            (draft.occurred_at_field
              ? undefined
              : 'No date column: each row is dated when its number last changed, and keeps that date until it changes again.')
          }
        />
        <Select
          label="The amount"
          value={draft.value_field ?? ''}
          onChange={(v) => set('value_field', v || null)}
          options={columns}
          hint={
            why('value_field', draft.value_field) ??
            (draft.value_field
              ? draft.value_field === columnForMetric(matched, fields)
                ? `Matched to “${matched}”.`
                : undefined
              : 'Each row counts as one.')
          }
        />
        <Select
          label="The source’s id for the row"
          value={draft.external_id_field ?? ''}
          onChange={(v) => set('external_id_field', v || null)}
          options={columns}
          // **The requirement outranks the suggestion.** `why` returns the
          // detector's reasoning while the draft still holds what it guessed —
          // which is exactly the state a dateless mapping starts in, so the one
          // line saying this field is now mandatory was never once displayed.
          hint={
            !draft.occurred_at_field && !draft.external_id_field
              ? 'Required here, because there is no date column: this is what lets a row be recognised between reads instead of imported again.'
              : (why('external_id_field', draft.external_id_field) ??
                'Needed unless the source supplies its own. Without it the same row is imported again every time it is read.')
          }
        />
        <Field
          label="Multiply by"
          value={draft.multiplier}
          onChange={(v) => set('multiplier', v)}
          numeric={{ decimals: 6, min: 0 }}
          hint="For units that differ — 0.01 turns cents into pounds."
        />
      </div>

      {/* **Only offered where it means something.** A source that supplies its
          own dates already has history; this is for the shape that does not, and
          on a row-per-event source it would turn one sale into one a day. */}
      {!draft.occurred_at_field && (
        <label className="mt-4 flex items-start gap-3 text-sm text-content">
          <input
            type="checkbox"
            checked={draft.snapshot_daily}
            onChange={(e) => set('snapshot_daily', e.target.checked)}
            className="mt-0.5"
          />
          <span>
            Keep a figure for each day
            <span className="block text-xs text-content-muted">
              This source has no dates, so by default each row holds only its
              latest number and yesterday's is overwritten. Tick this if each
              row is a running total for one person — a week then becomes the
              sum of seven days. Leave it clear if each row is a single thing
              that happened, or one of them becomes one a day.
            </span>
          </span>
        </label>
      )}

      <Filters
        rows={draft.filters}
        fields={fields}
        onChange={(rows) => set('filters', rows)}
      />

      {error && (
        <p
          role="alert"
          className="mt-4 rounded-md border border-danger px-3 py-2 text-sm text-danger"
        >
          {error}
        </p>
      )}

      <Preview rows={preview} busy={busy} ready={!!ready} />

      {onRemoved && mappingId && (
        <div className="mt-4 flex justify-end border-t border-edge pt-4">
          <button
            type="button"
            onClick={onRemoved}
            className="text-sm text-danger hover:underline"
          >
            Stop importing this metric
          </button>
        </div>
      )}
    </div>
  );
}

/**
 * Only rows matching every filter are imported.
 *
 * Deliberately not an expression language. "Stage is Closed Won" covers what
 * people actually need, reads the same to whoever inherits it, and cannot be
 * written wrong in a way that silently matches nothing.
 */
function Filters({
  rows,
  fields,
  onChange,
}: {
  rows: { field: string; op: string; value: string }[];
  fields: SourceField[];
  onChange: (rows: { field: string; op: string; value: string }[]) => void;
}) {
  return (
    <div className="mt-5 border-t border-edge pt-5">
      <p className="text-sm text-content-muted">Only import rows where…</p>

      {rows.length === 0 && (
        <p className="mt-1 text-xs text-content-subtle">
          Nothing set, so every row is imported. Add a rule to import only
          closed deals, one office, or one product.
        </p>
      )}

      <div className="mt-3 space-y-2">
        {rows.map((row, index) => (
          <div key={index} className="flex flex-wrap items-end gap-2">
            <div className="min-w-40 flex-1">
              <Select
                label="Column"
                value={row.field}
                onChange={(v) =>
                  onChange(
                    rows.map((r, i) => (i === index ? { ...r, field: v } : r)),
                  )
                }
                options={fields.map((f) => ({ value: f.name, label: f.name }))}
              />
            </div>
            <div className="min-w-36">
              <Select
                label="Test"
                value={row.op}
                onChange={(v) =>
                  onChange(
                    rows.map((r, i) => (i === index ? { ...r, op: v } : r)),
                  )
                }
                options={OPS}
              />
            </div>
            <div className="min-w-40 flex-1">
              <Field
                label="Value"
                value={row.value}
                onChange={(v) =>
                  onChange(
                    rows.map((r, i) => (i === index ? { ...r, value: v } : r)),
                  )
                }
                hint={
                  row.op === 'in'
                    ? 'Separate alternatives with commas.'
                    : undefined
                }
              />
            </div>
            <button
              type="button"
              aria-label="Remove this rule"
              onClick={() => onChange(rows.filter((_, i) => i !== index))}
              className="rounded-md border border-edge p-2 text-content-muted transition-colors hover:bg-surface-hover hover:text-danger"
            >
              <TrashIcon className="size-4" />
            </button>
          </div>
        ))}
      </div>

      <button
        type="button"
        onClick={() =>
          onChange([
            ...rows,
            { field: fields[0]?.name ?? '', op: 'eq', value: '' },
          ])
        }
        className="mt-3 rounded-md border border-edge px-3 py-1.5 text-sm text-content-muted transition-colors hover:bg-surface-hover hover:text-content"
      >
        Add a rule
      </button>
    </div>
  );
}

const OUTCOMES: Record<
  PreviewRow['outcome'],
  { label: string; className: string }
> = {
  written: { label: 'Imported', className: 'text-success' },
  quarantined: { label: 'Waiting', className: 'text-warning' },
  skipped: { label: 'Skipped', className: 'text-content-subtle' },
  error: { label: 'Problem', className: 'text-danger' },
};

/**
 * Ten real rows, as the facts they would become.
 *
 * Outcomes are named for what happens rather than for the internal status:
 * "Waiting" says the row is held pending a decision, where "quarantined" reads
 * like something went wrong. Nothing here is written — previewing is safe to do
 * repeatedly, which is the point of it being live.
 */
function Preview({
  rows,
  busy,
  ready,
}: {
  rows: PreviewRow[] | null;
  busy: boolean;
  ready: boolean;
}) {
  if (!ready) {
    return (
      <p className="mt-5 rounded-md border border-dashed border-edge px-3 py-4 text-sm text-content-muted">
        {/* No date column here either: empty is a real answer, so demanding one
            before showing a preview withholds the preview from exactly the
            sources that most need checking. */}
        Choose a metric and a person column to see what this would import.
      </p>
    );
  }

  if (rows === null) {
    return (
      <p className="mt-5 rounded-md border border-dashed border-edge px-3 py-4 text-sm text-content-muted">
        {busy ? 'Working out what this would import…' : 'No preview yet.'}
      </p>
    );
  }

  if (rows.length === 0) {
    return (
      <p className="mt-5 rounded-md border border-warning px-3 py-3 text-sm text-warning">
        Nothing to preview. The source has no rows in its window yet — send it
        some data and this will fill in.
      </p>
    );
  }

  return (
    <div className="mt-5">
      <p className="mb-2 text-sm text-content-muted">
        The most recent {rows.length} {rows.length === 1 ? 'row' : 'rows'}, as
        they would be imported{busy && ' — updating…'}
      </p>
      {/* Its own scroller: a source with twenty columns must not push the page
          sideways. */}
      <div className="overflow-x-auto rounded-md border border-edge">
        <table className="w-full min-w-[36rem] text-sm">
          <thead>
            <tr className="border-b border-edge bg-bg text-left text-xs uppercase tracking-wide text-content-subtle">
              <th className="px-3 py-2 font-normal">Outcome</th>
              <th className="px-3 py-2 font-normal">Who</th>
              <th className="px-3 py-2 font-normal">Amount</th>
              <th className="px-3 py-2 font-normal">When</th>
              <th className="px-3 py-2 font-normal">Why</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => {
              const outcome = OUTCOMES[row.outcome];
              return (
                <tr key={index} className="border-b border-edge last:border-0">
                  <td
                    className={`px-3 py-2 whitespace-nowrap ${outcome.className}`}
                  >
                    {outcome.label}
                  </td>
                  <td className="px-3 py-2 text-content">
                    {row.subject_name ?? '—'}
                  </td>
                  <td className="px-3 py-2 text-content">{row.value ?? '—'}</td>
                  <td className="px-3 py-2 whitespace-nowrap text-content-muted">
                    {row.occurred_at
                      ? dayAndTime(row.occurred_at)
                      : '—'}
                  </td>
                  <td className="px-3 py-2 text-content-muted">
                    {row.detail ?? ''}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
