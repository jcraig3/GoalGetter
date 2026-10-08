import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { api } from '../api';
import { toast } from '../toast';
import { recordable } from '../recordable';
import { Can } from '../auth';
import EmptyState from '../components/EmptyState';
import Field from '../components/Field';
import IconButton from '../components/IconButton';
import { PencilIcon, TrashIcon } from '../components/icons';
import MetricValue from '../components/MetricValue';
import PageHeader from '../components/PageHeader';
import Select from '../components/Select';
import { ask } from '../confirm';
import Loading from '../components/Loading';
import PeoplePicker from '../components/PeoplePicker';
import type { PickPerson } from '../components/peoplePick';
import FilterFold from '../components/FilterFold';

interface Metric {
  id: number;
  key: string;
  name: string;
  unit: string;
  decimal_places: number;
}

type Person = PickPerson;

interface Fact {
  id: number;
  metric_definition_id: number;
  metric_name: string;
  metric_key: string;
  unit: string;
  decimal_places: number;
  subject_user_id: number;
  subject_name: string;
  team_id: number | null;
  team_name: string | null;
  value: string;
  occurred_at: string;
  source_type: string;
  corrected: boolean;
  corrected_at: string | null;
}

/** "2026-08-12T15:00:00Z" → "2026-08-12", for a date input. */
function toDateInput(iso: string): string {
  return new Date(iso).toISOString().slice(0, 10);
}

export default function Corrections() {
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [people, setPeople] = useState<Person[]>([]);
  const [facts, setFacts] = useState<Fact[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<Fact | null>(null);

  // Arrives pre-filtered from the Metrics page's per-metric jump. Without this,
  // "fix a number for Calls Made" landed on an unfiltered list and made you pick
  // the metric again — which is the step you had already taken.
  const [params, setParams] = useSearchParams();
  const [metricFilter, setMetricFilter] = useState(params.get('metric') ?? '');
  const [personFilter, setPersonFilter] = useState('');
  // A day range, and pages: only the newest hundred could be seen at all
  // (review §7).
  const [since, setSince] = useState('');
  const [until, setUntil] = useState('');
  const [more, setMore] = useState(false);

  const query = useCallback(
    (offset: number) => {
      const q = new URLSearchParams();
      if (metricFilter) q.set('metric_id', metricFilter);
      if (personFilter) q.set('subject_user_id', personFilter);
      if (since) q.set('since', since);
      if (until) q.set('until', until);
      q.set('limit', String(PAGE));
      if (offset) q.set('offset', String(offset));
      return `/api/metric-facts?${q}`;
    },
    [metricFilter, personFilter, since, until],
  );

  const load = useCallback(async () => {
    try {
      const first = await api<Fact[]>(query(0));
      setFacts(first);
      setMore(first.length === PAGE);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load entries.');
    }
  }, [query]);

  async function loadMore() {
    try {
      const next = await api<Fact[]>(query(facts?.length ?? 0));
      setFacts((current) => [...(current ?? []), ...next]);
      setMore(next.length === PAGE);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load more.');
    }
  }

  // The filter is the URL. A pre-filtered arrival that silently loses its filter
  // on the next interaction is worse than never having one.
  function changeMetricFilter(value: string) {
    setMetricFilter(value);
    if (value) setParams({ metric: value }, { replace: true });
    else setParams({}, { replace: true });
  }

  useEffect(() => {
    Promise.all([api<Metric[]>('/api/metrics'), api<Person[]>('/api/users')])
      .then(([m, p]) => {
        setMetrics(recordable(m));
        setPeople(p);
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load.'));
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function remove(fact: Fact) {
    if (
      !await ask(
        `Delete this entry permanently?\n\n${fact.subject_name} · ${fact.metric_name} · ${fact.value} on ${toDateInput(fact.occurred_at)}\n\nTotals that include it will drop. The deletion is recorded in the activity log.`,
      )
    )
      return;
    setError(null);
    try {
      await api(`/api/metric-facts/${fact.id}`, { method: 'DELETE' });
      toast('Entry deleted');
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not delete.');
    }
  }

  return (
    <>
      <PageHeader
        title="Corrections"
        description="Fix a bad number. Not a data-entry workflow — production data comes from integrations."
        actions={
          <>
            {/* The way back. Arriving here from a metric and having no route home
                but the browser button is the kind of dead end that makes a tool
                feel like a series of pages rather than one product. */}
            <Can do="metrics.manage">
              <Link
                to="/metrics"
                className="mr-2 rounded-md border border-edge px-3 py-2 text-sm text-content-muted transition-colors hover:bg-surface-hover hover:text-content"
              >
                ← Metrics
              </Link>
            </Can>
          <button
            onClick={() => {
              if (adding || editing) {
                setAdding(false);
                setEditing(null);
              } else {
                setAdding(true);
              }
            }}
            className="rounded-md bg-brand px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover"
          >
            {adding || editing ? 'Cancel' : 'Add an entry'}
          </button>
          </>
        }
      />

      {/* Stated up front, because a correction tool used as a data-entry tool
          is how a leaderboard stops being believed. */}
      <p className="mb-6 rounded-md border border-warning px-3 py-2 text-sm text-warning">
        Everything recorded here is marked as entered by hand and stays visibly
        marked wherever it appears. Every entry, edit, and deletion is written
        to the activity log with your name on it.
      </p>

      {error && (
        <p role="alert" className="mb-4 rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      {(adding || editing) && (
        <EntryForm
          fact={editing}
          metrics={metrics}
          people={people}
          onCancel={() => {
            setAdding(false);
            setEditing(null);
          }}
          onSaved={async () => {
            toast(editing ? 'Correction saved' : 'Correction recorded');
            setError(null);
            setAdding(false);
            setEditing(null);
            await load();
          }}
          onError={setError}
        />
      )}

      <div className="mb-4 flex flex-wrap gap-2">
        <FilterFold active={[metricFilter, since, until].filter(Boolean).length}>
        <Picker
          label="Metric"
          value={metricFilter}
          onChange={changeMetricFilter}
          options={[
            { value: '', label: 'All metrics' },
            ...metrics.map((m) => ({ value: String(m.id), label: m.name })),
          ]}
        />
        <Field label="From" type="date" value={since} onChange={setSince} required={false} />
        <Field label="To" type="date" value={until} onChange={setUntil} required={false} />
        </FilterFold>
        <div className="w-full sm:w-72">
          <PeoplePicker
            label="Person"
            people={people}
            value={personFilter ? Number(personFilter) : null}
            onChange={(id) => setPersonFilter(id === null ? '' : String(id))}
            placeholder="Everyone — type to narrow"
          />
        </div>
      </div>

      {facts === null ? (
        <Loading />
      ) : facts.length === 0 ? (
        <EmptyState
          title="No entries"
          description="Nothing recorded for this filter. Generated demo data appears here too — it is marked as imported, not hand-entered."
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-edge bg-surface">
          <table className="gg-stack w-full text-sm">
            <thead>
              <tr className="border-b border-edge text-left text-caption uppercase tracking-wide text-content-subtle">
                <th className="px-4 py-3 font-medium">Date</th>
                <th className="px-4 py-3 font-medium">Person</th>
                <th className="px-4 py-3 font-medium">Metric</th>
                <th className="px-4 py-3 text-right font-medium">Value</th>
                <th className="px-4 py-3 font-medium">Source</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody>
              {facts.map((fact) => (
                <tr key={fact.id} className="border-b border-edge last:border-0">
                  <td data-label="Date" className="px-4 py-3 tabular-nums text-content-muted">
                    {toDateInput(fact.occurred_at)}
                  </td>
                  <td data-primary className="px-4 py-3 text-content">
                    {fact.subject_name}
                    <span className="block text-xs text-content-subtle">
                      {fact.team_name ?? 'unassigned'}
                    </span>
                  </td>
                  <td data-label="Metric" className="px-4 py-3 text-content-muted">{fact.metric_name}</td>
                  <td data-label="Value" className="px-4 py-3 text-right text-content">
                    <MetricValue value={fact.value} format={fact} />
                  </td>
                  <td data-label="Source" className="px-4 py-3">
                    <SourceBadge fact={fact} />
                  </td>
                  <td data-actions className="px-4 py-3">
                    <div className="flex justify-end gap-1">
                      <IconButton
                        label="Edit"
                        icon={<PencilIcon className="size-4" />}
                        onClick={() => {
                          setAdding(false);
                          setEditing(fact);
                        }}
                      />
                      <IconButton
                        label="Delete"
                        icon={<TrashIcon className="size-4" />}
                        danger
                        onClick={() => void remove(fact)}
                      />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {more && (
        <button
          type="button"
          onClick={() => void loadMore()}
          className="mt-3 rounded-md border border-edge px-3 py-1.5 text-sm text-content hover:bg-surface-hover"
        >
          Show {PAGE} more
        </button>
      )}

      <p className="mt-4 text-sm text-content-muted">
        Looking for what a metric measures? That is on the{' '}
        <Link to="/metrics" className="text-brand hover:underline">
          Metrics
        </Link>{' '}
        page.
      </p>
    </>
  );
}

/**
 * Where a number came from.
 *
 * The distinction the whole feature exists to preserve: a hand-keyed figure
 * must never be indistinguishable from a synced one, or nobody can answer
 * "did someone edit this?" — which is the question that decides whether the
 * leaderboard gets believed.
 */
function SourceBadge({ fact }: { fact: Fact }) {
  if (fact.corrected) {
    return (
      <span className="rounded-full border border-warning px-2 py-0.5 text-xs text-warning">
        {fact.source_type === 'manual' ? 'entered by hand' : 'edited by hand'}
      </span>
    );
  }
  return (
    <span className="text-xs text-content-subtle">
      {SOURCE_WORDS[fact.source_type] ?? fact.source_type}
    </span>
  );
}

/** Where a row came from, in words rather than the stored value. */
const SOURCE_WORDS: Record<string, string> = {
  connector: 'synced',
  import: 'imported',
  manual: 'entered by hand',
};

/** Rows per page. */
const PAGE = 100;

function EntryForm({
  fact,
  metrics,
  people,
  onCancel,
  onSaved,
  onError,
}: {
  fact: Fact | null;
  metrics: Metric[];
  people: Person[];
  onCancel: () => void;
  onSaved: () => Promise<void>;
  onError: (message: string | null) => void;
}) {
  const isEdit = fact !== null;

  const [metricId, setMetricId] = useState(
    String(fact?.metric_definition_id ?? metrics[0]?.id ?? ''),
  );
  // Nobody until chosen. It used to default to whoever sorted first, so a
  // hurried correction could land on the wrong person without them choosing.
  const [personId, setPersonId] = useState<number | null>(fact?.subject_user_id ?? null);
  const [value, setValue] = useState(fact ? String(Number(fact.value)) : '');
  const [date, setDate] = useState(
    fact ? toDateInput(fact.occurred_at) : new Date().toISOString().slice(0, 10),
  );
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    // A failure from last time is not true of this attempt (QA-4).
    onError(null);
    try {
      // Midday rather than midnight. A date-only input has no time, and
      // midnight sits on a period boundary — one timezone conversion either
      // way and the entry lands in the wrong day. Midday is unambiguous
      // everywhere.
      const occurred_at = new Date(`${date}T12:00:00`).toISOString();

      if (isEdit) {
        await api(`/api/metric-facts/${fact.id}`, {
          method: 'PATCH',
          body: JSON.stringify({ value, occurred_at }),
        });
      } else {
        await api('/api/metric-facts', {
          method: 'POST',
          body: JSON.stringify({
            metric_id: Number(metricId),
            subject_user_id: personId,
            value,
            occurred_at,
          }),
        });
      }
      await onSaved();
    } catch (e) {
      onError(e instanceof Error ? e.message : 'Could not save the entry.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="mb-6 max-w-2xl rounded-lg border border-edge bg-surface p-6">
      <h2 className="mb-4 font-medium text-content">
        {isEdit ? 'Edit entry' : 'New entry'}
      </h2>

      <div className="grid gap-4 sm:grid-cols-2">
        <Select
          label="Metric"
          value={metricId}
          onChange={setMetricId}
          disabled={isEdit}
          options={metrics.map((m) => ({ value: String(m.id), label: m.name }))}
        />
        {isEdit ? (
          <p className="text-sm">
            <span className="block text-content-muted">Person</span>
            <span className="text-content">{fact?.subject_name}</span>
          </p>
        ) : (
          <PeoplePicker label="Person" people={people} value={personId} onChange={setPersonId} />
        )}
        {/* Negatives allowed: a refund reducing revenue, or reversing a
            double-counted deal, is a legitimate correction. Four decimals to
            match the column. */}
        <Field
          label="Value"
          value={value}
          onChange={setValue}
          numeric={{ decimals: 4, allowNegative: true }}
        />
        <Field label="Date" value={date} onChange={setDate} type="date" />
      </div>

      {isEdit && fact?.source_type === 'connector' && (
        // Said because the worry is reasonable and the answer is reassuring:
        // a sync never overwrites a corrected row (see `sync._upsert`).
        <p className="mt-4 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-content">
          This number came from a sync. Your change is kept — later syncs leave a
          corrected row alone, and count the disagreement on the source&rsquo;s page.
        </p>
      )}

      {isEdit && (
        <p className="mt-4 text-sm text-content-muted">
          {/* Explained rather than silently disabled — a control that does
              nothing with no reason given reads as a bug. */}
          The metric and person cannot be changed. Moving an entry to someone
          else is a delete and a new entry, not a correction, and recording it
          as one would leave a misleading trail.
        </p>
      )}

      <div className="mt-6 flex items-center gap-3">
        <button
          type="submit"
          disabled={busy || personId === null || value === '' || value === '-' || !date}
          className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
        >
          {busy ? 'Saving…' : isEdit ? 'Save change' : 'Record entry'}
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

/**
 * A compact inline filter, distinct from the labelled `Select` in components/.
 *
 * No visible label — the placeholder option carries the meaning ("All metrics"),
 * and a form label above a filter bar would double its height for no gain. Kept
 * local for that reason rather than folded into the shared component.
 */
function Picker({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <select
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="rounded-md border border-edge bg-bg px-2 py-1 text-sm text-content outline-none focus:border-brand"
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

