import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';

import { api } from '../api';
import { toast } from '../toast';
import { Can, useAuth } from '../auth';
import EmptyState from '../components/EmptyState';
import Field from '../components/Field';
import IconButton from '../components/IconButton';
import {
  ArchiveIcon,
  PencilIcon,
  RestoreIcon,
  RulerIcon,
  TrashIcon,
} from '../components/icons';
import PageHeader from '../components/PageHeader';
import Select from '../components/Select';
import { ArchiveTabs } from '../components/Tabs';
import { ask } from '../confirm';
import Loading from '../components/Loading';
import { singular } from '../components/MetricValue';
import { useFocusRow, useOpenFromUrl } from '../urlIntent';

interface Metric {
  id: number;
  key: string;
  name: string;
  description: string | null;
  unit: string;
  aggregation: string;
  direction: string;
  decimal_places: number;
  /** What a count is a count of, as the plural: "deals". */
  unit_label?: string | null;
  archived: boolean;
  /** For a ratio: what is divided by what. */
  numerator_metric_id?: number | null;
  denominator_metric_id?: number | null;
  /** Admins only — the sources feeding it, by name. */
  sources?: string[];
  /** A count whose numbers look like money (QA-39). */
  looks_like_amounts?: boolean;
}

const UNITS = ['count', 'currency', 'percent', 'duration'] as const;
const AGGREGATIONS = ['sum', 'count', 'avg', 'max', 'min', 'last', 'ratio'] as const;

// **Said in words, not keys** (review §9): "sum · currency (2dp) · higher" was
// the database talking.
export const AGGREGATION_LABEL: Record<string, string> = {
  sum: 'Total',
  count: 'Number of entries',
  avg: 'Average',
  max: 'Highest',
  min: 'Lowest',
  last: 'Latest',
  ratio: 'Ratio of two metrics',
};

export const UNIT_LABEL: Record<string, string> = {
  count: 'Number',
  currency: 'Money',
  percent: 'Percent',
  duration: 'Time',
};

/** "Money · 2 decimals", "Deals". */
export function unitWords(m: Pick<Metric, 'unit' | 'unit_label' | 'decimal_places'>): string {
  const base =
    m.unit === 'count' && m.unit_label
      ? m.unit_label.replace(/^./, (c) => c.toUpperCase())
      : (UNIT_LABEL[m.unit] ?? m.unit);
  if (m.decimal_places <= 0) return base;
  return `${base} · ${m.decimal_places} decimal${m.decimal_places === 1 ? '' : 's'}`;
}

// Every one of these is a real integration bug we're trying to prevent, so the
// explanation sits next to the control rather than in a doc nobody opens.
const AGGREGATION_HELP: Record<string, string> = {
  sum: 'Add the values together. Revenue, calls, deals.',
  count: 'Count the rows and ignore their values. For events with no magnitude.',
  avg: 'Mean of the values. Deal size, satisfaction score.',
  max: 'Largest single value. "Biggest deal closed."',
  min: 'Smallest single value.',
  last: 'Most recent value. For snapshots — pipeline size, quota attainment — where adding them up would be nonsense.',
  ratio:
    'One metric divided by another — close rate is deals won ÷ deals created. Worked out from those two, so it has no data of its own. A team’s rate is its total over its total, not an average of people’s rates.',
};

export default function Metrics() {
  const { can } = useAuth();
  const [metrics, setMetrics] = useState<Metric[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<Metric | null>(null);
  const [showArchived, setShowArchived] = useState(false);
  useOpenFromUrl('new', () => setCreating(true));
  useFocusRow(metrics !== null);

  const load = useCallback(async () => {
    try {
      const all = await api<Metric[]>(
        `/api/metrics?include_archived=${showArchived}`,
      );
      // A tab is its own list. `include_archived` means "both", which would show
      // live metrics under Archived.
      setMetrics(all.filter((m) => m.archived === showArchived));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load metrics.');
    }
  }, [showArchived]);

  useEffect(() => {
    void load();
  }, [load]);

  async function act(metric: Metric, action: string) {
    setError(null);
    try {
      await api(`/api/metrics/${metric.id}/${action}`, { method: 'POST' });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : `Could not ${action}.`);
    }
  }

  async function remove(metric: Metric) {
    if (
      !await ask(
        `Delete "${metric.name}" permanently? Archive instead if it has ever been measured — archiving keeps its history readable.`,
      )
    )
      return;
    setError(null);
    try {
      await api(`/api/metrics/${metric.id}`, { method: 'DELETE' });
      toast('Metric deleted');
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not delete.');
    }
  }

  async function seedDefaults() {
    setError(null);
    try {
      await api('/api/metrics/seed-defaults', { method: 'POST' });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not restore defaults.');
    }
  }


  return (
    <>
      <PageHeader
        title="Metrics"
        description="What this organization measures. Everything else — goals, leaderboards, competitions — ranks one of these."
        actions={
          <Can do="metrics.manage">
            <Link
              to="/corrections"
              className="mr-2 rounded-md border border-edge px-3 py-2 text-sm text-content-muted transition-colors hover:bg-surface-hover hover:text-content"
            >
              Corrections
            </Link>
            <button
              type="button"
              // **One button, one meaning** (8.3): it read "New metric" while an
              // edit form was open, then became a purple "Cancel" — a primary
              // button whose primary act was to throw away the form. Now it is
              // always "New metric", resting while a form is open; the form has
              // its own Cancel.
              onClick={() => setCreating(true)}
              disabled={creating || editing !== null}
              className="rounded-md bg-brand px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
            >
              New metric
            </button>
          </Can>
        }
      />

      {error && (
        <p role="alert" className="mb-4 rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      {(creating || editing) && (
        <MetricForm
          metric={editing}
          choices={(metrics ?? []).filter((m) => m.aggregation !== 'ratio' && m.id !== editing?.id)}
          onCancel={() => {
            setCreating(false);
            setEditing(null);
          }}
          onSaved={async () => {
            toast(editing ? 'Metric saved' : 'Metric created');
            setError(null);
            setCreating(false);
            setEditing(null);
            await load();
          }}
          onError={setError}
        />
      )}

      <ArchiveTabs showArchived={showArchived} onChange={setShowArchived} />

      {metrics === null ? (
        <Loading />
      ) : metrics.length === 0 && showArchived ? (
        <EmptyState
          title="Nothing archived"
          description="An archived metric keeps every measurement it has ever taken and stops appearing in pickers. Archive rather than delete once something has been measured — deleting is refused for exactly that reason."
        />
      ) : metrics.length === 0 ? (
        <EmptyState
          title="No metrics yet"
          description="A fresh install ships with eight common ones. Restore them, or define your own."
          action={
            can('metrics.manage') ? (
              <button
                onClick={() => void seedDefaults()}
                className="rounded-md bg-brand px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover"
              >
                Restore default metrics
              </button>
            ) : undefined
          }
        />
      ) : (
        <>
          <div className="mt-2 overflow-x-auto rounded-lg border border-edge bg-surface">
            <table className="gg-stack w-full text-sm">
              <thead>
                <tr className="border-b border-edge text-left text-caption uppercase tracking-wide text-content-subtle">
                  <th className="px-4 py-3 font-medium">Metric</th>
                  <th className="px-4 py-3 font-medium whitespace-nowrap">Adds up as</th>
                  <th className="px-4 py-3 font-medium">Unit</th>
                  <th className="px-4 py-3 font-medium">Direction</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody>
                {(metrics ?? []).map((m) => (
                  <tr
                    key={m.id}
                    id={`row-${m.id}`}
                    className={`border-b border-edge last:border-0 ${
                      m.archived ? 'opacity-50' : ''
                    }`}
                  >
                    <td data-primary className="px-4 py-3 text-content">
                      {m.name}
                      {/* "Created from <source>." is what connecting a source
                          writes; the line below says it better. */}
                      {m.description &&
                        !(m.sources?.length && /^Created from .*\.$/.test(m.description)) && (
                        <span className="block text-xs text-content-muted">
                          {m.description}
                        </span>
                      )}
                      {/* Where its numbers come from, by the source's own name,
                          rather than a column of internal keys (review §7).
                          The key is still on the edit form, where it is needed. */}
                      {m.sources && m.sources.length > 0 && (
                        <span className="block text-xs text-content-subtle">
                          From {m.sources.join(', ')}
                        </span>
                      )}
                      {m.looks_like_amounts && (
                        <span className="mt-1 block text-xs text-warning">
                          These look like amounts, not a count — should the unit be
                          Money, or the mapping read a different column?
                        </span>
                      )}
                    </td>
                    <td data-label="Adds up as" className="px-4 py-3 whitespace-nowrap text-content-muted">
                      {m.aggregation === 'ratio' ? (
                        <>
                          Ratio
                          <span className="block text-xs">
                            {nameOf(metrics, m.numerator_metric_id)} ÷{' '}
                            {nameOf(metrics, m.denominator_metric_id)}
                          </span>
                        </>
                      ) : (
                        (AGGREGATION_LABEL[m.aggregation] ?? m.aggregation)
                      )}
                    </td>
                    <td data-label="Unit" className="px-4 py-3 whitespace-nowrap text-content-muted">
                      {unitWords(m)}
                    </td>
                    <td data-label="Direction" className="px-4 py-3 whitespace-nowrap text-content-muted">
                      {m.direction === 'higher_is_better' ? 'Higher is better' : 'Lower is better'}
                    </td>
                    <td data-actions className="px-4 py-3">
                      <div className="flex justify-end gap-1">
                        <Can do="metrics.manage">
                          {m.archived ? (
                            <>
                              <IconButton
                                label="Restore"
                                icon={<RestoreIcon className="size-4" />}
                                onClick={() => void act(m, 'restore')}
                              />
                              <IconButton
                                label="Delete"
                                icon={<TrashIcon className="size-4" />}
                                danger
                                onClick={() => void remove(m)}
                              />
                            </>
                          ) : (
                            <>
                              <IconButton
                                label="Edit"
                                icon={<PencilIcon className="size-4" />}
                                onClick={() => {
                                  setCreating(false);
                                  setEditing(m);
                                }}
                              />
                              {/* Corrections, filtered to this metric. The jump
                                  people actually want from here is "fix a number
                                  for *this*", and arriving at an unfiltered list
                                  means picking the metric again. */}
                              <IconButton
                                label={`Corrections for ${m.name}`}
                                icon={<RulerIcon className="size-4" />}
                                to={`/corrections?metric=${m.id}`}
                              />
                              <IconButton
                                label="Archive"
                                icon={<ArchiveIcon className="size-4" />}
                                onClick={() => void act(m, 'archive')}
                              />
                            </>
                          )}
                        </Can>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}

function nameOf(metrics: Metric[] | null, id: number | null | undefined): string {
  return metrics?.find((m) => m.id === id)?.name ?? 'an archived metric';
}

function MetricForm({
  metric,
  choices,
  onCancel,
  onSaved,
  onError,
}: {
  metric: Metric | null;
  /** What a ratio can be built from: recorded metrics, not other ratios. */
  choices: Metric[];
  onCancel: () => void;
  onSaved: () => Promise<void>;
  onError: (message: string | null) => void;
}) {
  const isEdit = metric !== null;

  const [name, setName] = useState(metric?.name ?? '');
  const [key, setKey] = useState(metric?.key ?? '');
  const [description, setDescription] = useState(metric?.description ?? '');
  const [unit, setUnit] = useState(metric?.unit ?? 'count');
  const [aggregation, setAggregation] = useState(metric?.aggregation ?? 'sum');
  const [direction, setDirection] = useState(metric?.direction ?? 'higher_is_better');
  const [decimals, setDecimals] = useState(metric?.decimal_places ?? 0);
  const [unitLabel, setUnitLabel] = useState(metric?.unit_label ?? '');
  const [numerator, setNumerator] = useState(String(metric?.numerator_metric_id ?? ''));
  const [denominator, setDenominator] = useState(String(metric?.denominator_metric_id ?? ''));
  const isRatio = aggregation === 'ratio';
  const [busy, setBusy] = useState(false);
  // A name or key already taken, said on its own field (8.3) rather than in a
  // banner at the top of the page.
  const [nameTaken, setNameTaken] = useState<string | null>(null);
  const [keyTaken, setKeyTaken] = useState<string | null>(null);
  // Once the admin edits the key by hand, stop overwriting it from the name.
  const [keyTouched, setKeyTouched] = useState(isEdit);

  function onName(value: string) {
    setName(value);
    setNameTaken(null);
    if (!keyTouched) setKey(slug(value));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    // A failure from last time is not true of this attempt (QA-4).
    onError(null);
    setNameTaken(null);
    setKeyTaken(null);
    try {
      const body = {
        name,
        description: description || null,
        unit,
        aggregation,
        direction,
        decimal_places: decimals,
        // Only a count has one; switching away from count clears it.
        unit_label: unit === 'count' ? unitLabel.trim() || null : null,
        ...(isRatio
          ? { numerator_metric_id: Number(numerator), denominator_metric_id: Number(denominator) }
          : {}),
      };
      if (isEdit) {
        await api(`/api/metrics/${metric.id}`, {
          method: 'PATCH',
          body: JSON.stringify(body),
        });
      } else {
        await api('/api/metrics', {
          method: 'POST',
          body: JSON.stringify({ ...body, key }),
        });
      }
      await onSaved();
    } catch (e) {
      const said = e instanceof Error ? e.message : 'Could not save the metric.';
      if (said.startsWith('There is already a metric called')) setNameTaken(said);
      else if (said.includes('with the key')) setKeyTaken(said);
      else onError(said);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="mb-6 max-w-2xl rounded-lg border border-edge bg-surface p-6">
      <h2 className="mb-4 font-medium text-content">
        {isEdit ? `Edit ${metric.name}` : 'New metric'}
      </h2>

      <Field label="Name" value={name} onChange={onName} invalid={nameTaken !== null} />
      {nameTaken && (
        <p role="alert" className="mt-1 text-xs text-danger">
          {nameTaken}
        </p>
      )}

      {isEdit ? (
        <p className="mt-4 text-sm text-content-muted">
          Key <code className="rounded bg-bg px-1.5 py-0.5 text-xs">{metric.key}</code>{' '}
          — permanent. Connectors, saved import mappings, and goals all reference
          it, so renaming would break them silently.
        </p>
      ) : (
        <div className="mt-4">
          {/* Mirrors KEY_PATTERN on the server. Typing a capital or a
              space simply does not land, rather than being accepted and
              rejected on submit. */}
          <Field
            label="Key"
            value={key}
            onChange={(v) => {
              setKeyTouched(true);
              setKey(v);
              setKeyTaken(null);
            }}
            allow={/^[a-z][a-z0-9_]*$/}
            maxLength={64}
            invalid={keyTaken !== null || (key !== '' && !KEY_PATTERN.test(key))}
          />
          {keyTaken && (
            <p role="alert" className="mt-1 text-xs text-danger">
              {keyTaken}
            </p>
          )}
          <p className="mt-1 text-xs text-content-muted">
            How connectors and spreadsheet imports will refer to this metric.
            Lowercase, underscores, permanent once created.
          </p>
        </div>
      )}

      <div className="mt-4">
        <Field
          label="Description"
          value={description}
          onChange={setDescription}
          required={false}
          hint="Optional. Shown under the name wherever this metric appears."
        />
      </div>

      <div className="mt-6 grid gap-4 border-t border-edge pt-6 sm:grid-cols-2">
        <Select
          label="How values add up"
          value={aggregation}
          onChange={setAggregation}
          options={AGGREGATIONS.map((a) => ({ value: a, label: AGGREGATION_LABEL[a] ?? a }))}
          hint={AGGREGATION_HELP[aggregation]}
        />
        {isRatio && (
          <div className="grid gap-4 sm:col-span-2 sm:grid-cols-2">
            <Select
              label="Divide"
              value={numerator}
              onChange={setNumerator}
              options={[
                { value: '', label: 'Choose a metric' },
                ...choices.map((m) => ({ value: String(m.id), label: m.name })),
              ]}
              hint="What is counted — deals won."
            />
            <Select
              label="By"
              value={denominator}
              onChange={setDenominator}
              options={[
                { value: '', label: 'Choose a metric' },
                ...choices.map((m) => ({ value: String(m.id), label: m.name })),
              ]}
              hint="What it is out of — deals created. Nobody with none of these gets a rate."
            />
            <p className="text-xs text-content-subtle sm:col-span-2">
              Set the unit to percent to show 7 of 20 as 35%.
            </p>
          </div>
        )}
        <Select
          label="Unit"
          value={unit}
          onChange={setUnit}
          options={UNITS.map((u) => ({ value: u, label: UNIT_LABEL[u] ?? u }))}
        />
        {/* **What a count is a count of** (§8): money carries its "$" and a
            percentage its "%", and a count said nothing. "48,210 deals". */}
        {unit === 'count' && (
          <Field
            label="Counts of"
            value={unitLabel}
            onChange={setUnitLabel}
            required={false}
            maxLength={32}
            placeholder="deals"
            hint={`The plural, shown after the number: "12 ${unitLabel.trim() || 'deals'}", and "1 ${singular(unitLabel.trim() || 'deals')}". Leave empty for a bare number.`}
          />
        )}
        <Select
          label="Better when the number is"
          value={direction}
          onChange={setDirection}
          options={[
            { value: 'higher_is_better', label: 'Higher' },
            { value: 'lower_is_better', label: 'Lower' },
          ]}
          hint="Response time is better lower. Getting this wrong makes the leaderboard celebrate the worst performer."
        />
        <Select
          label="Decimal places"
          value={String(decimals)}
          onChange={(v) => setDecimals(Number(v))}
          options={[0, 1, 2, 3, 4].map((d) => ({ value: String(d), label: String(d) }))}
        />
      </div>

      {isEdit && (
        <p className="mt-6 rounded-md border border-warning px-3 py-2 text-sm text-warning">
          Changing how values add up, or the unit, reinterprets every number already
          recorded — the same data will report a different number. The change is
          written to the activity log.
        </p>
      )}

      <div className="mt-6 flex items-center gap-3">
        <button
          type="submit"
          disabled={
            busy ||
            !name ||
            (!isEdit && !KEY_PATTERN.test(key)) ||
            (isRatio && (!numerator || !denominator || numerator === denominator))
          }
          className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
        >
          {busy ? 'Saving…' : isEdit ? 'Save changes' : 'Create metric'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md border border-edge px-4 py-2 text-sm text-content-muted transition-colors hover:bg-surface-hover hover:text-content"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

/** Matches the server's KEY_PATTERN exactly. */
const KEY_PATTERN = /^[a-z][a-z0-9_]{1,63}$/;

/**
 * "Meetings Booked" → "meetings_booked".
 *
 * The leading-character strip matters: KEY_PATTERN requires a letter first, so
 * "1st Call Attempt" would otherwise auto-fill "1st_call_attempt" and be
 * refused with a 422 the admin did nothing to cause.
 */
function slug(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^[^a-z]+/, '')
    .replace(/_+$/, '')
    .slice(0, 64);
}


