import { dayAndTime } from '../time';
import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { api } from '../api';
import { recordable } from '../recordable';
import {
  dataSources,
  type Identity,
  type Mapping,
  type Run,
  type SourceDetail,
  type SourceField,
  type TestResult,
} from '../dataSources';
import ConnectorMark from '../components/connectorMark';
import CopyField from '../components/CopyField';
import EmptyState from '../components/EmptyState';
import Field from '../components/Field';
import MappingEditor, { type MetricOption } from '../components/MappingEditor';
import PageHeader from '../components/PageHeader';
import Select from '../components/Select';
import SourceHealthPill from '../components/SourceHealthPill';
import SpreadsheetPicker from '../components/SpreadsheetPicker';
import {
  excelProvider,
  packExcelId,
  sheetsProvider,
  unpackExcelId,
} from '../components/sheetProviders';
import { BACKFILLS, INTERVALS } from './ConnectSource';
import { sourceHealth } from './sourceWizard';
import { ask } from '../confirm';
import PeoplePicker from '../components/PeoplePicker';
import type { PickPerson } from '../components/peoplePick';

/**
 * One data source: what it is, what it imports, and what it has been doing.
 *
 * The page an admin opens when something looks wrong, so it is ordered by what
 * they came for rather than by what is easiest to render: the questions it needs
 * answered first, then what it imports, then its history. The endpoint sits near
 * the top because "what was that URL again?" is the other reason to be here.
 */

type Person = PickPerson;

export default function DataSource() {
  const { id } = useParams();
  const navigate = useNavigate();
  const sourceId = Number(id);

  const [source, setSource] = useState<SourceDetail | null>(null);
  const [fields, setFields] = useState<SourceField[]>([]);
  const [metrics, setMetrics] = useState<MetricOption[]>([]);
  const [people, setPeople] = useState<Person[]>([]);
  const [waiting, setWaiting] = useState<Identity[]>([]);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<number | null>(null);
  const [test, setTest] = useState<TestResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [detail, metricList, peopleList] = await Promise.all([
        dataSources.read(sourceId),
        api<MetricOption[]>('/api/metrics'),
        api<Person[]>('/api/users'),
      ]);
      setSource(detail);
      setMetrics(recordable(metricList));
      setPeople(peopleList);
      // Both are allowed to be empty and neither is worth failing the page for:
      // a source whose connector was removed has no columns to report, and that
      // is exactly when somebody needs to read the rest of this page.
      setFields(await dataSources.fields(sourceId).catch(() => []));
      setWaiting(await dataSources.identities(sourceId).catch(() => []));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load that source.');
    }
  }, [sourceId]);

  useEffect(() => {
    void load();
  }, [load]);

  /** Every action ends the same way: take the server's answer as the truth. */
  async function act(what: () => Promise<SourceDetail | void>) {
    setBusy(true);
    setError(null);
    try {
      const updated = await what();
      if (updated) setSource(updated);
      else await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That did not work.');
    } finally {
      setBusy(false);
    }
  }

  if (error && !source) {
    return (
      <>
        <PageHeader title="Data source" />
        <p
          role="alert"
          className="rounded-md border border-danger px-3 py-2 text-sm text-danger"
        >
          {error}
        </p>
      </>
    );
  }

  if (!source) return <PageHeader title="Data source" description="Loading…" />;

  const health = sourceHealth(source, new Date());

  return (
    <>
      <PageHeader
        title={source.name}
        description={`${source.connector_name} · imports into ${
          source.mappings.length > 0
            ? source.mappings.map((m) => m.metric_name).join(', ')
            : 'nothing yet'
        }`}
        actions={
          <>
            <Link
              to="/integrations"
              className="rounded-md px-3 py-2 text-sm text-content-muted transition-colors hover:text-content"
            >
              All integrations
            </Link>
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                void act(async () => {
                  await dataSources.syncNow(sourceId);
                })
              }
              className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
            >
              {busy ? 'Working…' : 'Sync now'}
            </button>
          </>
        }
      />

      <div className="mb-6 flex flex-wrap items-center gap-x-3 gap-y-2">
        <ConnectorMark connector={source.connector} className="size-6" />
        <SourceHealthPill source={source} withDetail />
      </div>

      {error && (
        <p
          role="alert"
          className="mb-4 rounded-md border border-danger px-3 py-2 text-sm text-danger"
        >
          {error}
        </p>
      )}

      {health.resumable && (
        <p className="mb-6 flex flex-wrap items-center gap-3 rounded-md border border-warning px-3 py-2 text-sm text-warning">
          This source is not finished, so nothing is being imported.
          <Link
            to={`/integrations/connect/${source.id}`}
            className="underline hover:no-underline"
          >
            Pick up where you left off
          </Link>
        </p>
      )}

      {/* First, because it is a question waiting on a person rather than
          information to read. */}
      {waiting.length > 0 && (
        <Quarantine
          waiting={waiting}
          people={people}
          onMap={(identityId, userId) =>
            void act(async () => {
              setWaiting(
                await dataSources.mapIdentity(sourceId, identityId, userId),
              );
            })
          }
          onIgnoreRest={() =>
            void act(async () => {
              setWaiting(await dataSources.ignoreRestOfIdentities(sourceId));
            })
          }
          onIgnore={(identityId) =>
            void act(async () => {
              setWaiting(
                await dataSources.ignoreIdentity(sourceId, identityId),
              );
            })
          }
        />
      )}

      {source.endpoint_url && (
        <Section
          title="Endpoint"
          description="Where the sending system posts its events."
        >
          <CopyField label="Address" value={source.endpoint_url} />
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button
              type="button"
              disabled={busy}
              onClick={async () => {
                if (
                  !await ask(
                    'Issue a new address? Anything still sending to the old one will stop working until it is updated.',
                  )
                ) {
                  return;
                }
                void act(() => dataSources.rotateEndpoint(sourceId));
              }}
              className="rounded-md border border-edge px-3 py-2 text-sm text-content-muted transition-colors hover:bg-surface-hover hover:text-content disabled:opacity-50"
            >
              Issue a new address
            </button>
            <p className="text-xs text-content-subtle">
              For an address that ended up somewhere it should not have. Senders
              using the old one stop working immediately — which is the point.
            </p>
          </div>
        </Section>
      )}

      <Section
        title="What it imports"
        description="One mapping per metric. Editing one changes future syncs; what it already imported stays as it is."
      >
        {source.mappings.length === 0 && !adding && (
          <EmptyState
            title="Nothing mapped yet"
            description="Until a column is pointed at a metric, this source stores what it receives and imports none of it."
          />
        )}

        <div className="space-y-4">
          {source.mappings.map((mapping) =>
            editing === mapping.id ? (
              <MappingEditor
                key={mapping.id}
                sourceId={sourceId}
                fields={fields}
                metrics={metrics}
                existing={mapping}
                onSaved={() => void load()}
                onRemoved={() =>
                  void act(async () => {
                    if (
                      !await ask(
                        'Stop importing this metric? What it has already imported stays.',
                      )
                    )
                      return;
                    setEditing(null);
                    return dataSources.removeMapping(sourceId, mapping.id);
                  })
                }
              />
            ) : (
              <MappingRow
                key={mapping.id}
                mapping={mapping}
                onEdit={() => setEditing(mapping.id)}
              />
            ),
          )}
        </div>

        {adding ? (
          <div className="mt-4">
            <MappingEditor
              sourceId={sourceId}
              fields={fields}
              metrics={metrics}
              onSaved={() => {
                setAdding(false);
                void load();
              }}
            />
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setAdding(true)}
            disabled={fields.length === 0}
            title={fields.length === 0 ? 'No columns known yet' : undefined}
            className="mt-4 rounded-md border border-edge px-3 py-2 text-sm text-content-muted transition-colors hover:bg-surface-hover hover:text-content disabled:opacity-50"
          >
            Import another metric
          </button>
        )}
      </Section>

      {/* Above the runs, because "is it pointed at the right file?" comes before
          "did the last run work?" — and a renamed tab is the commonest reason
          the answer to the second is no. */}
      {(source.connector === 'microsoft_excel' ||
        source.connector === 'google_sheets') && (
        <Workbook
          source={source}
          busy={busy}
          onSave={(changes) =>
            void act(() => dataSources.update(sourceId, changes))
          }
        />
      )}

      <Section title="Recent syncs" description="Newest first.">
        <Runs runs={source.recent_runs} mappingCount={source.mappings.length} />
      </Section>

      <Settings
        source={source}
        busy={busy}
        test={test}
        onTest={() =>
          void (async () => {
            setTest(null);
            setTest(await dataSources.test(sourceId).catch(() => null));
          })()
        }
        onSave={(changes) =>
          void act(() => dataSources.update(sourceId, changes))
        }
        onToggle={() =>
          void act(() =>
            dataSources.update(sourceId, { enabled: !source.enabled }),
          )
        }
        onArchive={() =>
          void act(async () => {
            // Spelled out rather than "are you sure": what survives is the part
            // people are actually anxious about.
            if (
              !await ask(
                `Remove ${source.name}?

` +
                  `It stops importing and leaves the list. The ` +
                  `${source.facts_written.toLocaleString()} measurements it ` +
                  `already imported stay, and keep counting on leaderboards.

` +
                  `Its endpoint stops working immediately.`,
              )
            ) {
              return;
            }
            await dataSources.archive(sourceId);
            navigate('/integrations');
          })
        }
        onRestore={() => void act(() => dataSources.restore(sourceId))}
        onDelete={() =>
          void act(async () => {
            if (
              !await ask(
                `Delete ${source.name}? It has imported nothing, so nothing is lost.`,
              )
            ) {
              return;
            }
            await dataSources.remove(sourceId);
            navigate('/integrations');
          })
        }
      />
    </>
  );
}

function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mb-10">
      <h2 className="text-h2 text-content">{title}</h2>
      {description && (
        <p className="mt-1 mb-4 text-sm text-content-muted">{description}</p>
      )}
      {!description && <div className="mb-4" />}
      {children}
    </section>
  );
}

/**
 * Names in the data that match nobody here.
 *
 * At the top of the page and impossible to miss, because every one of these is a
 * row of real performance that is not on a leaderboard yet. **Nothing was
 * dropped** — the rows stay at the source and are re-read once the question is
 * answered, which is the whole reason for asking rather than guessing.
 */
//: How many questions to render at once.
//:
//: **Not a pagination nicety — the page stopped responding without it.** Each
//: row carries a picker holding every person in the organization, so a warehouse
//: view with three hundred unmatched names and a roster of four hundred is a
//: hundred and thirty thousand option elements in one render. The list is ordered
//: by how many rows each identifier is holding up, so the first screenful is also
//: the part worth answering.
const SHOWN_AT_ONCE = 20;

function Quarantine({
  waiting,
  people,
  onMap,
  onIgnore,
  onIgnoreRest,
}: {
  waiting: Identity[];
  people: Person[];
  onMap: (identityId: number, userId: number) => void;
  onIgnore: (identityId: number) => void;
  onIgnoreRest: () => void;
}) {
  const [limit, setLimit] = useState(SHOWN_AT_ONCE);
  const [confirming, setConfirming] = useState(false);
  //: **Shut by default, because most of them need no answer.** A warehouse view
  //: with history names everybody who ever worked here, and on the day somebody
  //: connects one this panel is the largest thing on the page — three hundred
  //: rows of people who left, above the source they actually came to look at.
  //: The count is the part worth seeing; the list is there when it is wanted.
  const [openList, setOpenList] = useState(false);
  const shown = waiting.slice(0, limit);

  return (
    <section className="mb-10 rounded-lg border border-warning bg-surface p-5">
      <h2 className="text-h2 text-content">Unmatched names</h2>
      <p className="mt-1 text-sm text-content-muted">
        {waiting.length === 1 ? 'One name' : `${waiting.length} names`} in the
        incoming data {waiting.length === 1 ? 'does' : 'do'} not match anyone
        here. Their rows are waiting, not lost — assign once and the next sync
        picks them up, including everything already sent.
      </p>

      {/* **Two actions, the common one first, both labelled as verbs.** A button
          saying "None of them are people here" reads as a claim somebody has to
          agree with rather than a thing it does; "Ignore all" is the same action
          in the language every other tool uses for it.

          The escape hatch matters for the case a warehouse with history always
          produces: a view of sales going back years names everybody who ever
          worked here, and the ones who left will never match. */}
      {!confirming && (
        <div className="mt-3 flex flex-wrap gap-3">
          <button
            type="button"
            onClick={() => setOpenList((open) => !open)}
            aria-expanded={openList}
            className="rounded-md border border-edge px-3 py-2 text-sm text-content transition-colors hover:bg-surface-hover"
          >
            {openList ? 'Hide' : 'Review'}
          </button>
          <button
            type="button"
            onClick={() => setConfirming(true)}
            className="rounded-md px-3 py-2 text-sm text-content-muted transition-colors hover:text-danger"
          >
            Ignore all
          </button>
        </div>
      )}

      {confirming && (
        <div className="mt-3 rounded-md border border-danger p-3">
          <p className="text-sm font-medium text-content">
            Ignore {waiting.length} unmatched{' '}
            {waiting.length === 1 ? 'name' : 'names'}?
          </p>
          <p className="mt-1 text-sm text-content-muted">
            Their rows are skipped from now on instead of waiting. Nothing
            already imported changes, and any new name that appears later is
            still listed here — this clears today's list only.
          </p>
          <div className="mt-3 flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => {
                setConfirming(false);
                onIgnoreRest();
              }}
              className="rounded-md bg-danger px-3 py-2 text-sm font-medium text-white transition-colors hover:opacity-90"
            >
              Ignore all {waiting.length}
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              className="rounded-md px-3 py-2 text-sm text-content-muted transition-colors hover:text-content"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {openList && (
        <>
          <ul className="mt-4 max-h-96 space-y-3 overflow-y-auto pr-1">
            {shown.map((identity) => (
              <li key={identity.id} className="flex flex-wrap items-end gap-3">
                <div className="min-w-0 flex-1">
                  <p className="truncate font-mono text-sm text-content">
                    {identity.external_identifier}
                  </p>
                  <p className="text-xs text-content-subtle">
                    {identity.pending_rows}{' '}
                    {identity.pending_rows === 1 ? 'row' : 'rows'} waiting
                  </p>
                </div>
                <div className="min-w-64">
                  {/* Typed: the identifier is usually half a name already, and
                      scrolling 461 of them to match it was the slow part. */}
                  <PeoplePicker
                    label="This is"
                    people={people}
                    value={null}
                    onChange={(id) => id !== null && onMap(identity.id, id)}
                  />
                </div>
                <button
                  type="button"
                  onClick={() => onIgnore(identity.id)}
                  className="rounded-md border border-edge px-3 py-2 text-sm text-content-muted transition-colors hover:bg-surface-hover hover:text-content"
                >
                  Not a person
                </button>
              </li>
            ))}
          </ul>

          {waiting.length > shown.length && (
            <button
              type="button"
              onClick={() => setLimit((n) => n + SHOWN_AT_ONCE)}
              className="mt-4 rounded-md border border-edge px-3 py-2 text-sm text-content transition-colors hover:bg-surface-hover"
            >
              Show {Math.min(SHOWN_AT_ONCE, waiting.length - shown.length)} more
              of {waiting.length - shown.length}
            </button>
          )}
        </>
      )}

      <p className="mt-4 text-xs text-content-subtle">
        “Not a person” is for the service account a CRM owns half its records
        with. It stops being asked about, and its rows are skipped from then on.
      </p>
    </section>
  );
}

function MappingRow({
  mapping,
  onEdit,
}: {
  mapping: Mapping;
  onEdit: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-lg border border-edge bg-surface px-4 py-3">
      <div className="min-w-40 flex-1">
        <p className="font-medium text-content">{mapping.metric_name}</p>
        <p className="text-xs text-content-subtle">
          {mapping.subject_field} · {mapping.value_field ?? 'one per row'} ·{' '}
          {mapping.occurred_at_field}
          {mapping.filters.length > 0 &&
            ` · ${mapping.filters.length} ${mapping.filters.length === 1 ? 'rule' : 'rules'}`}
        </p>
      </div>
      {!mapping.enabled && (
        <span className="rounded-full bg-warning/15 px-2 py-0.5 text-xs text-warning">
          Not importing
        </span>
      )}
      <button
        type="button"
        onClick={onEdit}
        className="rounded-md border border-edge px-3 py-1.5 text-sm text-content-muted transition-colors hover:bg-surface-hover hover:text-content"
      >
        Edit
      </button>
    </div>
  );
}

const RUN_TONES: Record<string, string> = {
  ok: 'text-success',
  partial: 'text-warning',
  failed: 'text-danger',
  running: 'text-content-muted',
};

/**
 * What each sync did, in the numbers that matter.
 *
 * Five counts rather than a log line, because they answer different questions:
 * `read` says whether the source gave us anything, `written` whether it landed,
 * and the other three say where the difference went. A run where read is high
 * and written is zero is a mapping problem; one where read is zero is a
 * connection problem.
 */
function Runs({
  runs,
  mappingCount,
}: {
  runs: Run[];
  /** How many mappings a row passes through, which is why the columns after
   *  "Rows read" can exceed it. */
  mappingCount: number;
}) {
  if (runs.length === 0) {
    return <p className="text-sm text-content-muted">It has not run yet.</p>;
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-edge">
      <table className="w-full min-w-[40rem] text-sm">
        <thead>
          <tr className="border-b border-edge bg-surface text-left text-xs uppercase tracking-wide text-content-subtle">
            <th className="px-3 py-2 font-normal">When</th>
            <th className="px-3 py-2 font-normal">Trigger</th>
            <th className="px-3 py-2 font-normal">Result</th>
            {/* **"Rows" and "facts" are different units and the table used to
                imply otherwise.** A row is read once and then passed through
                every mapping, so a source feeding three metrics reads 495 rows
                and produces 1,485 outcomes — correct, and unreadable as four
                columns that visibly fail to add up to the first. Saying which
                unit each column is in costs a word and settles it. */}
            <th className="px-3 py-2 font-normal">Rows read</th>
            <th className="px-3 py-2 font-normal">Facts imported</th>
            <th className="px-3 py-2 font-normal">Facts waiting</th>
            <th className="px-3 py-2 font-normal">Facts skipped</th>
            <th className="px-3 py-2 font-normal">Corrections kept</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id} className="border-b border-edge last:border-0">
              <td className="whitespace-nowrap px-3 py-2 text-content-muted">
                {dayAndTime(run.started_at)}
              </td>
              <td className="px-3 py-2 text-content-muted">{run.trigger}</td>
              <td
                className={`px-3 py-2 ${RUN_TONES[run.status] ?? 'text-content'}`}
              >
                {run.status}
                {run.error && (
                  <span className="mt-0.5 block text-xs text-content-muted">
                    {run.error}
                  </span>
                )}
              </td>
              <td
                className="px-3 py-2 text-content"
                title={
                  mappingCount > 1
                    ? `${run.rows_read} rows, each passed through ${mappingCount} mappings`
                    : undefined
                }
              >
                {run.rows_read}
                {mappingCount > 1 && (
                  <span className="text-content-subtle"> ×{mappingCount}</span>
                )}
              </td>
              <td className="px-3 py-2 text-content">{run.rows_written}</td>
              <td className="px-3 py-2 text-content-muted">
                {run.rows_quarantined}
              </td>
              <td className="px-3 py-2 text-content-muted">
                {run.rows_skipped}
              </td>
              {/* `conflicts` is the count of facts a human corrected and the sync
                  left alone. Labelled "Kept" because that is what happened to
                  the correction, and it is a rule worth being visible. */}
              <td className="px-3 py-2 text-content-muted">{run.conflicts}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The settings, and the three ways to stop.
 *
 * Named for what each does to the data rather than to the row, because that is
 * the question somebody actually has:
 *
 *   **Pause**   stops it syncing. Everything else stays, including the credential,
 *               so resuming is one click.
 *   **Remove**  disconnects it and takes it out of the list. The numbers it
 *               imported stay and keep counting.
 *   **Delete**  only offered before it has imported anything, because a fact that
 *               cannot say where it came from is a fact nobody can audit.
 *
 * The settings above them are editable here and nowhere else: renaming a source
 * or changing how often it runs should not mean deleting and reconnecting it.
 */
/**
 * Which workbook and tab this source reads, changeable in place.
 *
 * **The hole this fills.** Settings edited the name, the interval and the
 * backfill; the workbook lived only in the wizard's Configure step, and a
 * finished source resumes past that step. So "the tab got renamed" or "we moved
 * to a new sheet" had no fix short of deleting the source and adding it again —
 * which throws away the column mapping *and* the facts, because
 * `metric_fact.data_source_id` points here.
 *
 * Re-pointing is a real thing to want and a cheap thing to allow: the mapping is
 * by column name, so the same columns in a new file keep working. Changing it
 * writes `config` and nothing else, so the facts already imported stay exactly
 * where they are.
 */
function Workbook({
  source,
  busy,
  onSave,
}: {
  source: SourceDetail;
  busy: boolean;
  onSave: (changes: Record<string, unknown>) => void;
}) {
  const config = (source.config ?? {}) as Record<string, unknown>;
  const isExcel = source.connector === 'microsoft_excel';

  // Both vocabularies in one shape, written back into whichever keys this
  // connector stores them under. The picker itself knows about neither.
  const [picked, setPicked] = useState({
    drive_id: String(config.drive_id ?? ''),
    item_id: String(config.item_id ?? ''),
    spreadsheet_id: String(config.spreadsheet_id ?? ''),
    file_name: String(config.file_name ?? ''),
    tab: String(config.worksheet ?? config.tab ?? ''),
  });
  const [headerRow, setHeaderRow] = useState(String(config.header_row ?? 1));
  const [editing, setEditing] = useState(false);

  // Reset whenever the source reloads, so a save that the server changed — or
  // refused — leaves the form showing what is actually stored.
  useEffect(() => {
    const held = (source.config ?? {}) as Record<string, unknown>;
    setPicked({
      drive_id: String(held.drive_id ?? ''),
      item_id: String(held.item_id ?? ''),
      spreadsheet_id: String(held.spreadsheet_id ?? ''),
      file_name: String(held.file_name ?? ''),
      tab: String(held.worksheet ?? held.tab ?? ''),
    });
    setHeaderRow(String(held.header_row ?? 1));
    setEditing(false);
  }, [source.config]);

  const stored = {
    file: String(config.file_name ?? ''),
    sheet: String(config.worksheet ?? config.tab ?? ''),
    row: String(config.header_row ?? 1),
  };
  const dirty =
    picked.drive_id !== String(config.drive_id ?? '') ||
    picked.item_id !== String(config.item_id ?? '') ||
    picked.spreadsheet_id !== String(config.spreadsheet_id ?? '') ||
    picked.tab !== stored.sheet ||
    headerRow !== stored.row;

  return (
    <Section
      title="Workbook"
      description="Which file and tab this reads. Changing it keeps the column mapping and everything already imported."
    >
      {!editing ? (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border border-edge bg-surface p-4">
          <span aria-hidden className="shrink-0 text-content-subtle">
            ▤
          </span>
          <div className="min-w-40 flex-1">
            <p className="text-sm text-content">
              {stored.file || 'A workbook chosen before the picker existed'}
            </p>
            <p className="text-xs text-content-subtle">
              {stored.sheet ? `“${stored.sheet}” tab` : 'first tab'} · headers
              in row {stored.row}
            </p>
          </div>
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="shrink-0 rounded-md border border-edge px-3 py-2 text-sm text-content transition-colors hover:bg-surface-hover"
          >
            Change
          </button>
        </div>
      ) : (
        <div className="rounded-lg border border-edge bg-surface p-4">
          <SpreadsheetPicker
            provider={
              isExcel ? excelProvider(source.id) : sheetsProvider(source.id)
            }
            fileId={
              isExcel
                ? packExcelId(picked.drive_id, picked.item_id)
                : picked.spreadsheet_id
            }
            fileName={picked.file_name}
            fileUrl={String(config.file_url ?? config.spreadsheet_id ?? '')}
            tab={picked.tab}
            onPick={(file) =>
              setPicked((p) => ({
                ...p,
                ...(isExcel
                  ? unpackExcelId(file?.id ?? '')
                  : { spreadsheet_id: file?.id ?? '' }),
                file_name: file?.name ?? '',
                // A new file means the old tab name is about to be wrong, and a
                // stale one is worse than none: it reads as chosen.
                tab: '',
              }))
            }
            onTab={(name) => setPicked((p) => ({ ...p, tab: name }))}
          />

          <div className="mt-4 max-w-xs">
            <Select
              label="Which row holds the column names"
              value={headerRow}
              onChange={setHeaderRow}
              options={[1, 2, 3, 4, 5].map((n) => ({
                value: String(n),
                label: String(n),
              }))}
              hint="Usually 1. Higher if the sheet has a title above the table."
            />
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-edge pt-4">
            <button
              type="button"
              onClick={() =>
                onSave({
                  config: {
                    ...config,
                    ...(isExcel
                      ? {
                          drive_id: picked.drive_id,
                          item_id: picked.item_id,
                          worksheet: picked.tab,
                        }
                      : {
                          spreadsheet_id: picked.spreadsheet_id,
                          tab: picked.tab,
                        }),
                    file_name: picked.file_name,
                    header_row: Number(headerRow) || 1,
                  },
                })
              }
              disabled={busy || !dirty || !picked.tab}
              className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
            >
              {busy ? 'Saving…' : 'Save'}
            </button>
            <button
              type="button"
              onClick={() => setEditing(false)}
              className="rounded-md border border-edge px-4 py-2 text-sm text-content-muted transition-colors hover:bg-surface-hover hover:text-content"
            >
              Cancel
            </button>
            {/* Said next to the button rather than left as a disabled mystery. */}
            {!picked.tab && (
              <span className="text-xs text-content-subtle">
                Choose a worksheet to save.
              </span>
            )}
          </div>
        </div>
      )}
    </Section>
  );
}

function Settings({
  source,
  busy,
  test,
  onTest,
  onSave,
  onToggle,
  onArchive,
  onRestore,
  onDelete,
}: {
  source: SourceDetail;
  busy: boolean;
  test: TestResult | null;
  onTest: () => void;
  onSave: (changes: Record<string, unknown>) => void;
  onToggle: () => void;
  onArchive: () => void;
  onRestore: () => void;
  onDelete: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(source.name);
  const [interval, setInterval] = useState(String(source.interval_minutes));
  const [backfill, setBackfill] = useState(String(source.backfill_days));

  // Reset from the server's answer whenever it changes, so cancelling an edit or
  // saving one both leave the fields showing what is actually stored.
  useEffect(() => {
    setName(source.name);
    setInterval(String(source.interval_minutes));
    setBackfill(String(source.backfill_days));
  }, [source.name, source.interval_minutes, source.backfill_days]);

  return (
    <section className="mb-10 rounded-lg border border-edge bg-surface p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="text-h2 text-content">Settings</h2>
        <button
          type="button"
          onClick={() => setEditing((was) => !was)}
          className="text-sm text-content-muted underline transition-colors hover:text-content"
        >
          {editing ? 'Cancel' : 'Edit'}
        </button>
      </div>

      {editing ? (
        <form
          className="mt-4 space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            onSave({
              name: name.trim(),
              interval_minutes: Number(interval),
              backfill_days: Number(backfill),
            });
            setEditing(false);
          }}
        >
          <Field
            label="Name"
            value={name}
            onChange={setName}
            maxLength={120}
            hint="Only for you. It appears wherever this source is mentioned."
          />
          <Select
            label="How often to check"
            value={interval}
            onChange={setInterval}
            options={INTERVALS}
          />
          <Select
            label="How much history to import"
            value={backfill}
            onChange={setBackfill}
            options={BACKFILLS}
            hint="Applies to future syncs. What has already been imported stays as it is."
          />
          <button
            type="submit"
            disabled={busy || !name.trim()}
            className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
          >
            {busy ? 'Saving…' : 'Save settings'}
          </button>
        </form>
      ) : (
        <dl className="mt-4 grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
          <Pair term="Checked">
            {source.interval_minutes === 0
              ? 'Once — then only when somebody presses Sync now'
              : `Every ${source.interval_minutes} minutes`}
          </Pair>
          <Pair term="History imported">
            {source.backfill_days === 0
              ? 'From connection onwards'
              : `${source.backfill_days} days`}
          </Pair>
          <Pair term="Next run">
            {source.archived
              ? 'Removed — it will not run'
              : source.next_run_at
                ? dayAndTime(source.next_run_at)
                : 'As soon as possible'}
          </Pair>
          <Pair term="Measurements recorded">
            {source.facts_written.toLocaleString()}
          </Pair>
        </dl>
      )}

      {test && (
        <p
          role="alert"
          className={`mt-4 rounded-md border px-3 py-2 text-sm ${
            test.ok
              ? 'border-success text-success'
              : 'border-danger text-danger'
          }`}
        >
          {test.detail}
        </p>
      )}

      <div className="mt-5 flex flex-wrap items-center gap-3 border-t border-edge pt-5">
        {source.archived ? (
          <button
            type="button"
            onClick={onRestore}
            disabled={busy}
            className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
          >
            Restore this source
          </button>
        ) : (
          <>
            <button
              type="button"
              onClick={onTest}
              className="rounded-md border border-edge px-3 py-2 text-sm text-content-muted transition-colors hover:bg-surface-hover hover:text-content"
            >
              Test connection
            </button>
            <button
              type="button"
              onClick={onToggle}
              disabled={busy}
              className="rounded-md border border-edge px-3 py-2 text-sm text-content-muted transition-colors hover:bg-surface-hover hover:text-content disabled:opacity-50"
            >
              {source.enabled ? 'Pause syncing' : 'Resume syncing'}
            </button>

            {/* Which of the two is offered depends only on whether anything was
                imported, so there is never a button that cannot work. */}
            {source.facts_written > 0 ? (
              <button
                type="button"
                onClick={onArchive}
                disabled={busy}
                className="ml-auto rounded-md border border-edge px-3 py-2 text-sm text-danger transition-colors hover:bg-danger/10 disabled:opacity-50"
              >
                Remove integration
              </button>
            ) : (
              <button
                type="button"
                onClick={onDelete}
                disabled={busy}
                className="ml-auto rounded-md border border-edge px-3 py-2 text-sm text-danger transition-colors hover:bg-danger/10 disabled:opacity-50"
              >
                Delete
              </button>
            )}
          </>
        )}
      </div>

      <p className="mt-2 text-xs text-content-subtle">
        {source.archived
          ? 'Restoring brings back its history and its mappings. It will need reconnecting before it can sync again.'
          : source.facts_written > 0
            ? `Removing disconnects it and takes it out of the list. The ${source.facts_written.toLocaleString()} measurements it imported stay, and keep counting on leaderboards — the plumbing goes, the numbers do not.`
            : 'It has imported nothing, so deleting leaves nothing behind.'}
      </p>
    </section>
  );
}

function Pair({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3">
      <dt className="w-44 shrink-0 text-content-muted">{term}</dt>
      <dd className="min-w-0 text-content">{children}</dd>
    </div>
  );
}
