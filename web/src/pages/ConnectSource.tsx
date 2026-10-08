import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Link,
  useNavigate,
  useParams,
  useSearchParams,
} from 'react-router-dom';

import { api } from '../api';
import { recordable } from '../recordable';
import {
  dataSources,
  type ConnectorOption,
  type Mapping,
  type SourceDetail,
  type Provider,
  type SourceField,
  type TestResult,
} from '../dataSources';
import CopyField from '../components/CopyField';
import Field from '../components/Field';
import ConnectorPicker from '../components/ConnectorPicker';
import ProviderSetup from '../components/ProviderSetup';
import SpreadsheetPicker from '../components/SpreadsheetPicker';
import WarehouseSetup from '../components/WarehouseSetup';
import {
  excelProvider,
  packExcelId,
  sheetsProvider,
  unpackExcelId,
} from '../components/sheetProviders';
import { excel } from '../excel';
import { sheets } from '../sheets';
import { warehouse } from '../warehouse';
import SchemaForm from '../components/SchemaForm';
import MappingEditor, { type MetricOption } from '../components/MappingEditor';
import PageHeader from '../components/PageHeader';
import Select from '../components/Select';
import { Tab } from '../components/Tabs';
import ConnectorMark from '../components/connectorMark';
import { formFields, missing, toPayload } from './connectorForm';
import { STEPS, resumeStep } from './sourceWizard';
import {
  AGGREGATIONS,
  AGGREGATION_LABELS,
  DIRECTIONS,
  DIRECTION_LABELS,
  ROLES,
  ROLE_HINTS,
  ROLE_LABELS,
  UNITS,
  edited,
  filterClauses,
  keyFor,
  metricsFor,
  subjectFor,
  suggestFilterValues,
  suggestRoles,
  tableOf,
  type Aggregation,
  type Direction,
  type MetricEdit,
  type MetricProposal,
  type Role,
  type Unit,
} from './metricSuggest';

/**
 * Connecting a source, in five steps.
 *
 * A page rather than a modal, because step four shows ten rows of real data in a
 * table and a dialog cannot hold that without becoming its own scrolling world.
 *
 * **The source is created at step three, not at the end.** A webhook's endpoint
 * is generated server-side, so it cannot be shown until the row exists — and
 * asking somebody to fill in five steps before finding out whether the connection
 * works is the shape of wizard people abandon.
 *
 * **So an unfinished source is a draft, and a draft is nobody's problem.**
 * Everything saved along the way is switched off, so it imports nothing. Cancel
 * deletes it outright. Anything abandoned another way — a closed tab, a lost
 * browser — is swept within a day, and never appears in the sources list in the
 * meantime. Cancelled means cancelled.
 *
 * `activated_at` on the source is what makes that safe: it separates "never
 * finished" from "finished and later paused", which look identical from outside and
 * must be treated completely differently.
 */

/**
 * How often a source is read.
 *
 * **Nothing under an hour, and that is honesty rather than a limit.** The job
 * loop ticks hourly — see `JOB_INTERVAL_SECONDS` — so "every 15 minutes" was
 * never 15 minutes; it was hourly with a label that said otherwise. Offering a
 * cadence the scheduler cannot keep is worse than not offering it: somebody
 * plans around it, and the numbers are late for a reason nothing on screen
 * explains.
 *
 * **"Once" is first because it is what a new connection wants.** A source
 * otherwise starts a schedule the moment it is saved, whether or not anybody has
 * confirmed the numbers are right — free against a spreadsheet, billed by the
 * second against a warehouse. Read once, check it, then choose a rhythm.
 */
export const INTERVALS = [
  { value: '0', label: 'Once — then only when I press Sync now' },
  { value: '60', label: 'Every hour' },
  { value: '360', label: 'Every 6 hours' },
  { value: '1440', label: 'Once a day' },
  { value: '10080', label: 'Once a week' },
  { value: '43200', label: 'Once a month' },
];

export const BACKFILLS = [
  { value: '0', label: 'Nothing — start from today' },
  { value: '30', label: 'The last 30 days' },
  { value: '90', label: 'The last 90 days' },
  { value: '365', label: 'The last year' },
];

/** How often to look for the first delivery while waiting on step three. */
const POLL_MS = 3000;

export default function ConnectSource() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [params] = useSearchParams();

  const [step, setStep] = useState(1);
  const [connectors, setConnectors] = useState<ConnectorOption[]>([]);
  const [metrics, setMetrics] = useState<MetricOption[]>([]);
  const [source, setSource] = useState<SourceDetail | null>(null);
  const [fields, setFields] = useState<SourceField[]>([]);
  const [mapping, setMapping] = useState<Mapping | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Defaults until a source exists to hold them, then editable behind the
  // "Name and schedule" disclosure on the connect step.
  const [name, setName] = useState('');
  const [interval, setInterval] = useState('60');
  const [backfill, setBackfill] = useState('90');

  useEffect(() => {
    Promise.all([dataSources.connectors(), api<MetricOption[]>('/api/metrics')])
      .then(([available, m]) => {
        setConnectors(available);
        setMetrics(recordable(m));

        // Arrived from a connector card on the Integrations page, so the first
        // question is already answered — asking it again would be a step that
        // exists only to be clicked through. Validated against the registry
        // rather than trusted, since it came out of a URL.
        const asked = params.get('connector');
        const match = asked && available.find((c) => c.key === asked);
        if (match && !id) {
          // Arrived from a connector card, so the first question is answered.
          // Creating straight away means the card is genuinely one click to a
          // connect screen rather than one click to another question.
          void create(match.key, available);
        }
      })
      .catch((e) =>
        setError(e instanceof Error ? e.message : 'Could not load.'),
      );
  }, [id, params]);

  // Resuming an abandoned setup: fetch what exists and open on the first step
  // that still needs an answer, rather than making somebody retype four things.
  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    void (async () => {
      try {
        const existing = await dataSources.read(Number(id));
        const discovered = existing.credentials_set
          ? await dataSources.fields(existing.id).catch(() => [])
          : [];
        if (cancelled) return;
        setSource(existing);
        setName(existing.name);
        setInterval(String(existing.interval_minutes));
        setBackfill(String(existing.backfill_days));
        setFields(discovered);
        setMapping(existing.mappings[0] ?? null);
        setStep(
          resumeStep({
            credentialsSet: existing.credentials_set,
            hasFields: discovered.length > 0,
            mappingCount: existing.mappings.length,
          }),
        );
      } catch (e) {
        if (!cancelled)
          setError(
            e instanceof Error ? e.message : 'Could not load that source.',
          );
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id]);

  async function create(
    key: string,
    catalogue: ConnectorOption[] = connectors,
  ) {
    setBusy(true);
    setError(null);
    // **The catalogue is passed in, not read from state, and that is the fix.**
    // One caller is inside the `.then` that populates `connectors` — arriving
    // from a connector card on the Integrations page — where the state is still
    // `[]` because React has not re-rendered yet. So the lookup missed, the name
    // fell through to the connector's internal key, and every source created
    // that way was called `microsoft_excel`. Which then became the name of every
    // metric proposed from it.
    const label = catalogue.find((c) => c.key === key)?.display_name ?? key;
    setName(label);
    try {
      const made = await dataSources.create({
        name: label,
        connector: key,
        interval_minutes: Number(interval),
        backfill_days: Number(backfill),
      });
      setSource(made);
      setStep(2);
      // The URL now names the source, so a reload or a closed tab resumes here
      // instead of starting over with a second half-built source.
      navigate(`/integrations/connect/${made.id}`, { replace: true });
    } catch (e) {
      setError(
        e instanceof Error ? e.message : 'Could not create that source.',
      );
    } finally {
      setBusy(false);
    }
  }

  /**
   * Cancel: cancelled means cancelled.
   *
   * The source has to exist from step three onwards — a webhook's endpoint is
   * generated server-side and cannot be shown before the row does — so backing out
   * leaves something behind unless it is cleaned up here. Deleting is safe because
   * an unfinished source has imported nothing: its mapping, if it has one, was
   * saved switched off.
   *
   * Only ever a draft. Reaching this page for a source somebody already finished
   * happens when they are re-connecting it, and Cancel there must leave it alone.
   */
  async function abandon() {
    if (source && !source.activated) {
      // A failure here is not worth blocking on: the sweep collects abandoned
      // drafts within a day anyway, and refusing to navigate away from a Cancel
      // button would be a strange thing to do to somebody.
      await dataSources.remove(source.id).catch(() => undefined);
    }
    navigate('/integrations');
  }

  /** Ask what columns the source has. Empty is a normal answer, not a failure. */
  const look = useCallback(async () => {
    if (!source) return [];
    const found = await dataSources.fields(source.id).catch(() => []);
    setFields(found);
    return found;
  }, [source]);

  async function finish() {
    if (!source || source.mappings.length === 0) return;
    setBusy(true);
    setError(null);
    try {
      // The moment data starts flowing: every mapping is switched on, then the
      // source is run once so the finished page shows real numbers rather than a
      // promise of them.
      //
      // **All of them, not the one the editor happened to be showing.** Creating
      // metrics from the columns makes several mappings at once; turning on only
      // the last one visited left the rest set up and silent.
      for (const each of source.mappings) {
        await dataSources.editMapping(source.id, each.id, {
          metric_id: each.metric_id,
          subject_field: each.subject_field,
          occurred_at_field: each.occurred_at_field,
          value_field: each.value_field,
          external_id_field: each.external_id_field,
          multiplier: each.multiplier,
          filters: each.filters,
          enabled: true,
        });
      }
      await dataSources.syncNow(source.id);
      navigate(`/integrations/sources/${source.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not finish setting up.');
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Connect a data source"
        description="Where your performance numbers come from."
        actions={
          <button
            type="button"
            onClick={() => void abandon()}
            className="rounded-md px-3 py-2 text-sm text-content-muted transition-colors hover:text-content"
          >
            Cancel
          </button>
        }
      />

      <Steps current={step} />

      {error && (
        <p
          role="alert"
          className="mb-4 rounded-md border border-danger px-3 py-2 text-sm text-danger"
        >
          {error}
        </p>
      )}

      {step === 1 && (
        <ChooseConnector
          connectors={connectors}
          busy={busy}
          // Straight to connecting. The name and the schedule used to be a screen
          // of their own here, asked before anybody knew whether the connection
          // even worked — they have sensible defaults, they are editable on the
          // source's own page, and they are behind Advanced on the next step for
          // anyone who wants them now.
          onChoose={(key) => void create(key)}
        />
      )}

      {step === 2 && source && (
        <Connect
          source={source}
          connector={connectors.find((c) => c.key === source.connector) ?? null}
          fields={fields}
          name={name}
          onName={setName}
          interval={interval}
          onInterval={setInterval}
          backfill={backfill}
          onBackfill={setBackfill}
          onLook={look}
          onSaved={setSource}
          onBack={() => setStep(1)}
          onNext={() => setStep(3)}
        />
      )}

      {step === 3 && source && (
        <MapIt
          source={source}
          fields={fields}
          metrics={metrics}
          mapping={mapping}
          busy={busy}
          connectorName={
            connectors.find((c) => c.key === source.connector)?.display_name ??
            ''
          }
          onMapped={(saved) => {
            setMapping(saved);
            // **Only when it is one the source has not heard of.** The editor
            // autosaves on a debounce, so refetching on every save would be a
            // request per pause in typing; a mapping that is new is the one case
            // the list above cannot already render.
            if (saved && !source.mappings.some((m) => m.id === saved.id)) {
              void dataSources.read(source.id).then(setSource);
            }
          }}
          onMetrics={async () => {
            // Both, and in this order: the metrics list is what unlocks the
            // editor, and the source carries the mappings that were created
            // alongside them — showing one without the other would render an
            // editor with nothing selected over a source that is already wired.
            const [all, fresh] = await Promise.all([
              api<MetricOption[]>('/api/metrics'),
              dataSources.read(source.id),
            ]);
            setMetrics(recordable(all));
            setSource(fresh);
            setMapping(fresh.mappings[0] ?? null);
            // **The mapping work is done at this point.** Each metric was
            // created with its mapping alongside it, so dropping back into the
            // editor offers to do again what has just been done — and shows one
            // of the three that were made.
            if (fresh.mappings.length > 0) setStep(4);
          }}
          onBack={() => setStep(2)}
          onFinish={() => setStep(4)}
        />
      )}

      {step === 4 && source && (
        <Review
          source={source}
          busy={busy}
          onBack={() => setStep(3)}
          onFinish={() => void finish()}
        />
      )}
    </>
  );
}

/**
 * Where you are, out of how many.
 *
 * Numbered and named. "Step 3 of 5" is the thing that stops a multi-step form
 * feeling endless, and naming them means somebody who came back after lunch can
 * see what is left without reading the whole page.
 */
function Steps({ current }: { current: number }) {
  return (
    <ol className="mb-6 flex flex-wrap gap-2" aria-label="Progress">
      {STEPS.map((label, index) => {
        const number = index + 1;
        const state =
          number === current ? 'current' : number < current ? 'done' : 'todo';
        return (
          <li
            key={label}
            aria-current={state === 'current' ? 'step' : undefined}
            className={`flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm ${
              state === 'current'
                ? 'border-brand text-content'
                : state === 'done'
                  ? 'border-edge text-content-muted'
                  : 'border-edge text-content-subtle'
            }`}
          >
            <span
              className={`grid size-5 shrink-0 place-items-center rounded-full text-xs ${
                state === 'todo'
                  ? 'bg-surface-hover text-content-subtle'
                  : 'bg-brand text-white'
              }`}
            >
              {state === 'done' ? '✓' : number}
            </span>
            {label}
          </li>
        );
      })}
    </ol>
  );
}

function ChooseConnector({
  connectors,
  busy,
  onChoose,
}: {
  connectors: ConnectorOption[];
  busy: boolean;
  onChoose: (key: string) => void;
}) {
  return (
    <section>
      <h2 className="text-h2 text-content">What are you connecting?</h2>
      <p className="mt-1 mb-4 text-sm text-content-muted">
        Search if you know what you are looking for. Not on the list is not a
        dead end — a webhook works with anything that can send an HTTP request,
        and the API connector with anything that has one.
      </p>

      {/* Buttons rather than links: this step creates the source in place, so
          there is no address to navigate to yet. */}
      <ConnectorPicker
        connectors={connectors}
        onChoose={onChoose}
        disabled={busy}
      />
    </section>
  );
}

/**
 * The step that has to be effortless.
 *
 * For a webhook: one URL to copy, and this page watching for the first delivery.
 * "Send one event and watch it arrive" is what turns a configuration screen into
 * something somebody trusts — and it is why the mapping step has real column
 * names to suggest from rather than an empty form.
 */
function Connect({
  source,
  connector,
  fields,
  name,
  onName,
  interval,
  onInterval,
  backfill,
  onBackfill,
  onLook,
  onSaved,
  onBack,
  onNext,
}: {
  source: SourceDetail;
  connector: ConnectorOption | null;
  fields: SourceField[];
  name: string;
  onName: (value: string) => void;
  interval: string;
  onInterval: (value: string) => void;
  backfill: string;
  onBackfill: (value: string) => void;
  onLook: () => Promise<SourceField[]>;
  onSaved: (source: SourceDetail) => void;
  onBack: () => void;
  onNext: () => void;
}) {
  // The name and the schedule, which used to be a screen of their own. Behind a
  // disclosure because they have sensible defaults, are editable on the source's
  // own page afterwards, and asking about them before the connection is proven is
  // asking somebody to guess.
  const basics = (
    <details className="mt-6">
      <summary className="cursor-pointer text-sm text-content-muted transition-colors hover:text-content">
        Name and schedule
      </summary>
      <div className="mt-4 space-y-4 border-l-2 border-edge pl-4">
        <Field
          label="Name"
          value={name}
          onChange={onName}
          maxLength={120}
          hint="Only for you. It appears wherever this source is mentioned."
        />
        <Select
          label="How often to check"
          value={interval}
          onChange={onInterval}
          options={INTERVALS}
        />
        <Select
          label="How much history to import"
          value={backfill}
          onChange={onBackfill}
          options={BACKFILLS}
          hint="Imported once, on the first sync."
        />
      </div>
    </details>
  );

  // Saved on the way out rather than behind a button of their own: leaving this
  // step is the natural moment, and a second Save is a second thing to forget.
  const advance = async () => {
    await dataSources
      .update(source.id, {
        name: name.trim() || source.name,
        interval_minutes: Number(interval),
        backfill_days: Number(backfill),
      })
      .then(onSaved)
      .catch(() => undefined);
    onNext();
  };
  // Two shapes of connecting, and the connector says which. A webhook is an
  // address to paste somewhere and then wait on; anything that fetches is a form
  // and a Test button. Branching on `receives` rather than on whether an endpoint
  // URL happens to be present, which is also empty for a receiving source whose
  // token has not been generated.
  if (connector && !connector.receives) {
    return (
      <Configure
        source={source}
        connector={connector}
        fields={fields}
        basics={basics}
        name={name}
        onName={onName}
        onLook={onLook}
        onSaved={onSaved}
        onBack={onBack}
        onNext={() => void advance()}
      />
    );
  }

  return (
    <ReceiveEvents
      source={source}
      fields={fields}
      basics={basics}
      onLook={onLook}
      onBack={onBack}
      onNext={() => void advance()}
    />
  );
}

/**
 * Connecting something GoalGetter reaches out to.
 *
 * Settings, then credentials, then Test — in that order because Test is the only
 * one that tells you anything and it cannot say anything useful until the other
 * two are filled in. Saving happens *on* Test rather than behind its own button:
 * two buttons where one must be pressed before the other is a sequence people get
 * wrong, and there is nothing to lose by storing settings that turn out not to
 * work.
 */
function Configure({
  source,
  connector,
  fields,
  basics,
  name,
  onName,
  onLook,
  onSaved,
  onBack,
  onNext,
}: {
  source: SourceDetail;
  connector: ConnectorOption;
  fields: SourceField[];
  basics: React.ReactNode;
  /** The source's name, so choosing a workbook can replace a placeholder one. */
  name: string;
  onName: (value: string) => void;
  onLook: () => Promise<SourceField[]>;
  onSaved: (source: SourceDetail) => void;
  onBack: () => void;
  onNext: () => void;
}) {
  // **Excel is configured by pointing at a file, not by describing one.** The
  // picker owns the ids, the workbook name, the link and the worksheet — all
  // marked `hidden` in the schema, so `formFields` drops them and what is left is
  // the one question a person genuinely answers: which row holds the headers.
  // **One picker, two providers.** They differ in three requests and two nouns;
  // everything the reader touches is the same component. See `sheetProviders`.
  const isExcel = connector.key === 'microsoft_excel';
  const isSheets = connector.key === 'google_sheets';
  const picks = isExcel || isSheets;

  // A warehouse is the same story as a spreadsheet account: six answers that
  // belong to the deployment rather than to this query. Shown in place the first
  // time it is needed, and gone once saved.
  const isWarehouse = connector.key === 'snowflake';

  /**
   * Whether the source's name is still ours to choose.
   *
   * Asked twice — once when a file is picked, once when a tab is — and the
   * second time is the harder question, because by then the name may be one this
   * component set a moment ago. So anything we could have generated counts as
   * untouched; only something a person typed is an answer to respect.
   */
  const untouchedName = () => {
    const held = name.trim();
    if (!held || held === connector.display_name || held === connector.key)
      return true;
    const book = picked.file_name.replace(/\.xlsx?$|\.xlsm$/i, '');
    return Boolean(book) && (held === book || held.startsWith(`${book} — `));
  };

  const settingFields = formFields(connector.config_schema, source.config);
  // **Empty for a warehouse, because the credential is not this source's.**
  // `SqlSecrets` carries a username, a password and a private key — every one of
  // them answered once on the connection above. Rendering them here would ask
  // for the key again per query, and store a second copy that
  // `oauth.ensure_fresh` then ignores.
  const secretFields = isWarehouse
    ? []
    : formFields(connector.credential_schema);

  const [settings, setSettings] = useState<Record<string, string>>(() =>
    Object.fromEntries(settingFields.map((f) => [f.name, f.initial])),
  );

  // What the picker holds, kept beside the generic form rather than inside it —
  // these are set by choosing, never by typing.
  // Held in the picker's own vocabulary — one id, one tab — and written back
  // into whichever config keys the connector uses at save time.
  const [picked, setPicked] = useState(() => ({
    id: isExcel
      ? packExcelId(
          String(source.config?.drive_id ?? ''),
          String(source.config?.item_id ?? ''),
        )
      : String(source.config?.spreadsheet_id ?? ''),
    file_name: String(source.config?.file_name ?? ''),
    tab: String(source.config?.worksheet ?? source.config?.tab ?? ''),
  }));

  /** The picked file and tab, in the keys this connector stores them under. */
  const pickedConfig = () =>
    isExcel
      ? {
          ...unpackExcelId(picked.id),
          file_name: picked.file_name,
          worksheet: picked.tab,
        }
      : {
          spreadsheet_id: picked.id,
          file_name: picked.file_name,
          tab: picked.tab,
        };

  // Whether an account is signed in for spreadsheets. When one is, this source
  // needs no sign-in of its own and the button below would be asking for a second
  // credential nobody uses — see `oauth.ensure_fresh`.
  const [shared, setShared] = useState<{
    connected: boolean;
    connected_as: string;
  } | null>(null);
  useEffect(() => {
    if (isExcel) {
      excel
        .status()
        .then(setShared)
        .catch(() => setShared(null));
    } else if (isSheets) {
      sheets
        .status()
        .then(setShared)
        .catch(() => setShared(null));
    } else if (isWarehouse) {
      warehouse
        .read()
        .then((w) =>
          setShared({
            connected: w.connected,
            connected_as: `${w.account} as ${w.username}`,
          }),
        )
        .catch(() => setShared(null));
    }
  }, [isExcel, isSheets, isWarehouse]);
  const [secrets, setSecrets] = useState<Record<string, string>>(() =>
    Object.fromEntries(secretFields.map((f) => [f.name, f.initial])),
  );
  const [result, setResult] = useState<TestResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // **What was true when the check passed.** Without this, confirming against
  // one worksheet and then choosing another left the panel showing the first
  // sheet's columns under the word "confirmed" — the most convincing possible way
  // to be wrong. Comparing the settings themselves rather than counting edits, so
  // typing a change and undoing it leaves the confirmation standing.
  const [confirmedWith, setConfirmedWith] = useState<string | null>(null);
  const current = JSON.stringify({ settings, picked });
  const stale = confirmedWith !== null && confirmedWith !== current;

  const notFilledIn = missing(settingFields, settings);
  // **Columns, not a green tick, are what "confirmed" means here.** A connector
  // can authenticate against the right account and still be pointed at an empty
  // sheet, and the next step has nothing to work with either way — so the thing
  // that opens Continue is the thing the next step needs.
  const arrived = fields.length > 0 && !stale;
  // **Nothing is reported while the check is still running.** `saveAndTest` sets
  // the result before it re-reads the columns, so for the moment between those
  // two there was a result and no columns — which is exactly the shape of a
  // failure, and the panel flashed "Could not read it" in red on its way to
  // going green. A check in progress has no verdict yet, and should say so.
  const failed = !busy && result !== null && !arrived && !stale;

  async function saveAndTest() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const body = {
        ...toPayload(settingFields, settings),
        ...(picks ? pickedConfig() : {}),
      };

      // **Name a warehouse query after the table it reads.** The spreadsheet
      // equivalent of naming a source after its worksheet: without it a source is
      // called "Snowflake" and its metrics come out as "Rows" and "Rows Amount".
      // Only while the name is still ours to choose — see `untouchedName`.
      if (isWarehouse && untouchedName()) {
        const named = tableOf(
          String((body as Record<string, unknown>).query ?? ''),
        );
        if (named) onName(named);
      }

      const saved = await dataSources.update(source.id, { config: body });
      // Only what was typed. Sending every field would blank a stored password
      // with an empty string on a second visit — the API merges what it is given,
      // and giving it nothing for a field is how "leave that one alone" is said.
      const typed = Object.fromEntries(
        Object.entries(secrets).filter(([, value]) => value !== ''),
      );
      onSaved(
        Object.keys(typed).length > 0
          ? await dataSources.setCredentials(source.id, typed)
          : saved,
      );
      const outcome = await dataSources.test(source.id);
      setResult(outcome);
      const discovered = await onLook();
      // Recorded only when it actually worked. Marking the settings confirmed
      // after a failure would let Continue open on the next unrelated keystroke.
      if (outcome.ok && discovered.length > 0) setConfirmedWith(current);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save that.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="max-w-2xl">
      <h2 className="text-h2 text-content">Connect it</h2>
      <p className="mt-1 mb-4 text-sm text-content-muted">
        Where {connector.display_name} lives, and an account that can read it.
        Nothing is imported yet — this only proves the connection works.
      </p>

      {/* The route through the other product, in that product's own menu names.
          Above the form rather than spread across the hints beside each box: a
          four-step journey told one sentence at a time, next to the field each
          sentence ends at, is a journey nobody follows. What each box *means*
          stays on the box. */}
      {connector.setup_steps.length > 0 && (
        <div className="mb-6 rounded-lg border border-edge bg-surface p-4">
          <p className="text-sm font-medium text-content">
            Getting the details for {connector.display_name}
          </p>
          <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm text-content-muted">
            {connector.setup_steps.map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
        </div>
      )}

      {/* **Above the form, because the query cannot be tested without it.** The
          same placement `ProviderSetup` takes in this step for an OAuth
          connector: the once-per-deployment job, shown in place the first time it
          is needed rather than sending somebody to another page and back. */}
      {isWarehouse && (
        <div className="mb-6">
          {/* **Neutral, because this block is usually already satisfied.** It
              said "First, connect the warehouse", which sat directly above a line
              reading "Connected to … as …" — an instruction to do the thing that
              had visibly been done, on the screen somebody reaches only after
              doing it. */}
          <p className="mb-2 text-sm font-medium text-content">
            Warehouse connection
          </p>
          <WarehouseSetup
            compact
            onConnected={(w) =>
              setShared({
                connected: w.connected,
                connected_as: `${w.account} as ${w.username}`,
              })
            }
          />
        </div>
      )}

      {picks && (
        <div className="mb-6">
          <SpreadsheetPicker
            provider={
              isExcel ? excelProvider(source.id) : sheetsProvider(source.id)
            }
            fileId={picked.id}
            fileName={picked.file_name}
            fileUrl={String(
              source.config?.file_url ?? source.config?.spreadsheet_id ?? '',
            )}
            tab={picked.tab}
            onPick={(file) => {
              setPicked((p) => ({
                ...p,
                id: file?.id ?? '',
                file_name: file?.name ?? '',
                // A new file means the old tab name is about to be wrong, and a
                // stale one is worse than none: it reads as chosen.
                tab: '',
              }));
              if (file && untouchedName()) {
                onName(file.name.replace(/\.xlsx?$|\.xlsm$/i, ''));
              }
            }}
            onTab={(sheet) => {
              setPicked((p) => ({ ...p, tab: sheet }));
              // **The tab is what distinguishes siblings.** One file with a tab
              // per team produces several sources, and naming them all after the
              // file gives a list of identical rows.
              if (untouchedName() && sheet) {
                const book = picked.file_name.replace(/\.xlsx?$|\.xlsm$/i, '');
                onName(
                  !book || book.toLowerCase() === sheet.toLowerCase()
                    ? sheet
                    : `${book} — ${sheet}`,
                );
              }
            }}
          />
        </div>
      )}

      <SchemaForm
        fields={settingFields}
        values={settings}
        onChange={(name, value) =>
          setSettings((s) => ({ ...s, [name]: value }))
        }
      />

      {/* **Not shown when there is nothing to sign in for.** Excel reads as one
          account for the whole deployment, so once that is connected a per-source
          button would mint a second credential that `oauth.ensure_fresh` then
          ignores — a step that appears to matter and does not. */}
      {connector.oauth && !isWarehouse && !(picks && shared?.connected) && (
        <SignIn
          sourceId={source.id}
          provider={connector.oauth.provider}
          providerName={connector.oauth.provider_name}
          connected={source.credentials_set}
          onDone={onLook}
        />
      )}

      {(picks || isWarehouse) && shared?.connected && (
        <p className="mt-4 rounded-md border border-success bg-success/5 px-3 py-2 text-sm text-content">
          <span aria-hidden>✓ </span>Reading as{' '}
          <strong>{shared.connected_as || 'the connected account'}</strong> — no
          sign-in needed here.
        </p>
      )}

      {/* A connector that signs in has a button; its credential fields exist for
          the unusual case and are tucked behind a disclosure rather than shown as
          a co-equal option. Two full sections asking for the same thing two ways is
          the reader working out which one applies to them, every time. */}
      {secretFields.length > 0 &&
        (connector.oauth ? (
          <details className="mt-4">
            <summary className="cursor-pointer text-sm text-content-muted transition-colors hover:text-content">
              Not on {connector.oauth.provider_name} Workspace? Use a service
              account instead
            </summary>
            <div className="mt-4 border-l-2 border-edge pl-4">
              <SchemaForm
                fields={secretFields}
                values={secrets}
                onChange={(name, value) =>
                  setSecrets((s) => ({ ...s, [name]: value }))
                }
                secret
              />
              <p className="mt-2 text-xs text-content-subtle">
                Stored encrypted and never shown again. Leave it empty to keep
                what is already saved.
              </p>
            </div>
          </details>
        ) : (
          <div className="mt-6 border-t border-edge pt-6">
            <p className="mb-4 text-sm text-content">Sign-in details</p>
            <SchemaForm
              fields={secretFields}
              values={secrets}
              onChange={(name, value) =>
                setSecrets((s) => ({ ...s, [name]: value }))
              }
              secret
            />
            <p className="mt-2 text-xs text-content-subtle">
              Stored encrypted and never shown again. Leave a field empty to
              keep what is already saved.
            </p>
          </div>
        ))}

      {error && (
        <p
          role="alert"
          className="mt-4 rounded-md border border-danger px-3 py-2 text-sm text-danger"
        >
          {error}
        </p>
      )}

      {/* **The step that was a button nobody knew was required.**
          *Save and test* sat quietly below the form in the same grey as
          everything else, and Continue carried a sentence explaining why it was
          shut. Two problems with that: the explanation was where you look only
          after being confused, and the one control that mattered looked optional.

          Now it is a panel with a state, and the state does the explaining. While
          it is unchecked this holds the only brand-coloured button on screen, so
          the eye goes to it without being told; once it succeeds the emphasis
          moves to Continue and this becomes a quiet *Check again*. The proof is
          the columns themselves — naming them is what shows the connection
          reached the right sheet, which "Connected" alone never did. */}
      <div
        className={`mt-6 rounded-lg border p-4 transition-colors ${
          busy
            ? 'border-edge bg-surface'
            : arrived
              ? 'border-success bg-success/5'
              : failed
                ? 'border-danger'
                : 'border-edge bg-surface'
        }`}
      >
        <div className="flex flex-wrap items-center gap-3">
          <span
            aria-hidden
            className={`grid size-6 shrink-0 place-items-center rounded-full text-xs ${
              busy
                ? 'bg-surface-hover text-content-subtle'
                : arrived
                  ? 'bg-success/20 text-success'
                  : failed
                    ? 'bg-danger/15 text-danger'
                    : 'bg-surface-hover text-content-subtle'
            }`}
          >
            {busy ? '·' : arrived ? '✓' : failed ? '!' : '·'}
          </span>

          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium text-content">
              {busy
                ? 'Checking…'
                : arrived
                  ? 'Connection confirmed'
                  : failed
                    ? 'Could not read it'
                    : stale
                      ? 'Confirm it again'
                      : 'Confirm the connection'}
            </p>
            <p className="text-sm text-content-muted">
              {busy
                ? 'Saving these settings and reading the source once.'
                : arrived
                  ? `${fields.length} ${fields.length === 1 ? 'column' : 'columns'}: ${fields
                      .map((f) => f.name)
                      .join(', ')}`
                  : stale
                    ? 'Something changed since the last check.'
                    : notFilledIn.length > 0
                      ? `Still needed: ${notFilledIn.join(', ')}.`
                      : 'Saves these settings and reads the source once.'}
            </p>
          </div>

          <button
            type="button"
            onClick={() => void saveAndTest()}
            disabled={busy || notFilledIn.length > 0}
            className={`shrink-0 rounded-md px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
              arrived
                ? 'border border-edge text-content-muted hover:bg-surface-hover hover:text-content'
                : 'bg-brand text-white hover:bg-brand-hover'
            }`}
          >
            {busy
              ? 'Checking…'
              : arrived
                ? 'Check again'
                : 'Confirm connection'}
          </button>
        </div>

        {/* Only when something went wrong, or when it worked and the columns are
            not the whole story. A success message repeating what the line above
            already says is a message that trains people to skip messages. */}
        {result && !arrived && !busy && (
          <div
            role="alert"
            className={`mt-3 border-t pt-3 text-sm ${
              result.ok
                ? 'border-edge text-content-muted'
                : 'border-danger/40 text-danger'
            }`}
          >
            <p className="whitespace-pre-wrap">{result.detail}</p>
            {/* Whatever the connector thought worth confirming — the server
                version, the columns it saw. Connected on its own does not say
                whether they reached the database they meant. */}
            {Object.entries(result.info).map(([key, value]) =>
              value ? (
                <p key={key} className="mt-1 text-xs text-content-subtle">
                  {key}: {value}
                </p>
              ) : null,
            )}
          </div>
        )}
      </div>

      {basics}

      <Buttons
        onBack={onBack}
        onNext={onNext}
        nextLabel="Continue"
        nextDisabled={!arrived}
      />
    </section>
  );
}

/**
 * The sign-in button, and the popup it opens.
 *
 * **The two-click moment.** A popup rather than navigating away, so the wizard is
 * still sitting here when they come back — the callback closes its own window and
 * posts the outcome across.
 *
 * Three things have to be handled and all three happen in practice: the popup
 * finishing, the popup being closed without finishing, and the popup never opening
 * because a browser blocked it.
 */
function SignIn({
  sourceId,
  provider,
  providerName,
  connected,
  onDone,
}: {
  sourceId: number;
  provider: string;
  providerName: string;
  connected: boolean;
  onDone: () => Promise<unknown>;
}) {
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  // Whether this deployment has registered an app with the provider yet. Fetched
  // here rather than passed down, because it is the only thing on the page that
  // needs it and it changes the moment somebody fills the form in below.
  const [registration, setRegistration] = useState<Provider | null | undefined>(
    undefined,
  );

  useEffect(() => {
    dataSources
      .providers()
      .then((all) =>
        setRegistration(all.find((p) => p.provider === provider) ?? null),
      )
      .catch(() => setRegistration(null));
  }, [provider]);

  // The registration step, shown in place the first time it is needed rather than
  // sending somebody to another page and back. It disappears for good once saved,
  // because it is a once-per-deployment job and not part of connecting a source.
  if (registration && !registration.client_secret_set) {
    return (
      <div className="mt-6 border-t border-edge pt-6">
        <p className="mb-3 text-sm text-content">
          First, register GoalGetter with {providerName}
        </p>
        <ProviderSetup
          provider={registration}
          compact
          onSaved={(saved) => setRegistration(saved)}
        />
      </div>
    );
  }

  async function start() {
    setBusy(true);
    setProblem(null);
    try {
      const { url } = await dataSources.authorize(sourceId);
      const popup = window.open(url, 'gg_oauth', 'width=520,height=680');

      if (!popup) {
        // Blocked. Navigating is a worse experience but a working one, and the
        // callback handles both — so this is a fallback rather than a dead end.
        window.location.assign(url);
        return;
      }

      // Two ways this ends, and whichever happens first wins.
      const finished = await new Promise<string | null>((resolve) => {
        function onMessage(event: MessageEvent) {
          // Only our own origin, and only our own message. A popup on a page can
          // receive anything anybody sends it.
          if (event.origin !== window.location.origin) return;
          if (event.data?.source !== 'goalgetter-oauth') return;
          cleanup();
          resolve(event.data.result?.error ?? null);
        }

        // Closing the window is how somebody says no. Without this the button
        // would sit on "Waiting…" for ever.
        const watch = window.setInterval(() => {
          if (popup.closed) {
            cleanup();
            resolve(null);
          }
        }, 500);

        function cleanup() {
          window.clearInterval(watch);
          window.removeEventListener('message', onMessage);
        }

        window.addEventListener('message', onMessage);
      });

      if (finished) setProblem(finished);
      await onDone();
    } catch (e) {
      setProblem(
        e instanceof Error ? e.message : 'Could not start that sign-in.',
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-6 border-t border-edge pt-6">
      <button
        type="button"
        onClick={() => void start()}
        disabled={busy}
        className="flex items-center gap-3 rounded-md border border-edge bg-surface px-4 py-2.5 text-sm font-medium text-content transition-colors hover:bg-surface-hover disabled:opacity-50"
      >
        <ConnectorMark connector={provider} className="size-5" />
        {busy
          ? 'Waiting for the sign-in window…'
          : connected
            ? `Sign in to ${providerName} again`
            : `Sign in with ${providerName}`}
      </button>

      <p className="mt-2 text-xs text-content-subtle">
        {connected
          ? 'Already connected. Signing in again replaces the stored access — useful if it was set up by somebody who has since left.'
          : `Opens a ${providerName} window. GoalGetter never sees your password.`}
      </p>

      {problem && (
        <p
          role="alert"
          className="mt-3 rounded-md border border-danger px-3 py-2 text-sm text-danger"
        >
          {problem}
        </p>
      )}
    </div>
  );
}

function ReceiveEvents({
  source,
  fields,
  basics,
  onLook,
  onBack,
  onNext,
}: {
  source: SourceDetail;
  fields: SourceField[];
  basics: React.ReactNode;
  onLook: () => Promise<SourceField[]>;
  onBack: () => void;
  onNext: () => void;
}) {
  const [waiting, setWaiting] = useState(fields.length === 0);
  const arrived = fields.length > 0;

  // Held in a ref so the interval callback always sees the current value without
  // the effect having to be torn down and rebuilt on every tick.
  const stop = useRef(false);
  useEffect(() => {
    stop.current = arrived;
  }, [arrived]);

  useEffect(() => {
    if (!waiting) return;
    const handle = window.setInterval(() => {
      if (stop.current) return;
      void onLook();
    }, POLL_MS);
    return () => window.clearInterval(handle);
  }, [onLook, waiting]);

  useEffect(() => {
    if (arrived) setWaiting(false);
  }, [arrived]);

  return (
    <section className="max-w-2xl">
      <h2 className="text-h2 text-content">Connect it</h2>

      {source.endpoint_url ? (
        <>
          <p className="mt-1 mb-4 text-sm text-content-muted">
            Paste this address into whatever is sending the data, then send one
            event. This page will notice when it arrives.
          </p>
          <CopyField
            label="Your endpoint"
            value={source.endpoint_url}
            hint="Anyone with this address can send data to this source. Treat it like a password."
          />

          <div className="mt-5 rounded-lg border border-edge bg-surface p-4">
            <p className="text-sm text-content">What to send</p>
            <p className="mt-1 text-sm text-content-muted">
              A POST with a JSON body — one event, or a list of them under{' '}
              <code className="text-content">events</code>. Any field names you
              like; you will say what they mean on the next step.
            </p>
            <pre className="mt-3 overflow-x-auto rounded-md border border-edge bg-bg p-3 text-xs text-content-muted">
              {`{
  "event_id": "deal-1042",
  "owner": "sam@example.com",
  "amount": 2500,
  "closed_at": "${new Date().toISOString().slice(0, 10)}"
}`}
            </pre>
          </div>
        </>
      ) : (
        <p className="mt-1 mb-4 text-sm text-content-muted">
          This source has no credentials yet. Add them on its own page, then
          come back to finish mapping.
        </p>
      )}

      <div
        className={`mt-5 rounded-md border px-3 py-3 text-sm ${
          arrived
            ? 'border-success text-success'
            : 'border-edge text-content-muted'
        }`}
      >
        {arrived ? (
          <>
            Received — {fields.length}{' '}
            {fields.length === 1 ? 'column' : 'columns'}:{' '}
            <span className="text-content">
              {fields.map((f) => f.name).join(', ')}
            </span>
          </>
        ) : (
          <span className="flex items-center gap-2">
            <span
              aria-hidden
              className="inline-block size-2 animate-pulse rounded-full bg-content-subtle"
            />
            Waiting for the first event…
            <button
              type="button"
              onClick={() => void onLook()}
              className="ml-auto text-content-muted underline hover:text-content"
            >
              Check now
            </button>
          </span>
        )}
      </div>

      {basics}

      <Buttons
        onBack={onBack}
        onNext={onNext}
        nextLabel="Continue"
        nextDisabled={!arrived}
        // Said plainly rather than leaving a dead button to be puzzled over.
        note={
          arrived
            ? undefined
            : 'Continue opens once something has arrived — the next step needs real column names to work from.'
        }
      />
    </section>
  );
}

/**
 * What arrived, what it means, and what to measure — one panel, in that order.
 *
 * **What used to be here was a wall.** "There are no metrics to import into yet —
 * create one first, then come back" sent somebody to a form asking for a key, a
 * unit, an aggregation and a direction about data they were looking at on the
 * previous screen.
 *
 * **What replaced it was right and looked wrong.** Six columns went in, two
 * metrics came out, and nothing was said about the other four — so a reader saw
 * *Closed Deals* and *Closed Deals Amount*, matched them against `deal_id`,
 * `rep_email`, `closed_date`, `amount`, `stage`, `region`, and reasonably
 * concluded detection had failed. It had not: four columns were consumed by a
 * mapping that was not on screen yet, and the names came from the worksheet. All
 * of that was true and none of it was visible.
 *
 * So the panel now leads with the columns. Every one is listed, every one says
 * what it is for, and — the part that also answers "can I fix it by hand?" — every
 * one is a dropdown. Reading a guess and correcting a guess are the same control,
 * because a separate advanced-mapping screen would be a second answer to the same
 * question and the two would disagree the first time either changed.
 *
 * **And it fixes a number that was quietly wrong.** A `stage` column holding
 * three words sat unused, so a metric named *Closed Deals* counted the lost ones
 * too — 120 rows against 97 real ones, and revenue overstated by a fifth. A
 * filter is the fix and nobody reaches for one they were never offered.
 */
function SuggestMetrics({
  source,
  fields,
  connectorName,
  onCreated,
}: {
  source: SourceDetail;
  fields: SourceField[];
  /** What this connector is called, so a source still named after it is ignored. */
  connectorName: string;
  /** Refetch metrics and the source, so the mapping editor appears filled in. */
  onCreated: () => Promise<unknown>;
}) {
  const subject = subjectFor(
    source.config as Record<string, unknown> | undefined,
    source.name,
    connectorName,
  );
  const taken = source.mappings.map((m) => keyFor(m.metric_name));

  // Detected once, then owned by the reader. Keyed off the column names so that
  // re-discovering the same sheet does not throw away a correction.
  const detected = useMemo(() => suggestRoles(fields), [fields]);
  const [roles, setRoles] = useState<Record<string, Role>>(detected);
  const [filters, setFilters] = useState<Record<string, string>>(() =>
    suggestFilterValues(fields, detected),
  );
  useEffect(() => {
    setRoles(detected);
    setFilters(suggestFilterValues(fields, detected));
  }, [detected, fields]);

  // **A sparse overlay, not a copy.** Changing a column role rebuilds every
  // proposal from scratch; holding edited copies would mean either losing a name
  // somebody just chose or freezing the metrics against the columns. Keyed by the
  // proposal's own key, so only what was actually changed survives.
  const [edits, setEdits] = useState<Record<string, MetricEdit>>({});
  const [dropped, setDropped] = useState<Set<string>>(new Set());
  //: Taken off the list altogether, as opposed to `dropped`, which is a tick box
  //: somebody can change their mind about. Detection rebuilds proposals from the
  //: columns on every role change, so "I do not want this one" has to be
  //: remembered somewhere or it comes straight back.
  const [removed, setRemoved] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<string | null>(null);
  //: Metrics somebody added that detection did not propose. Held as proposals so
  //: everything below treats them identically.
  const [extra, setExtra] = useState<MetricProposal[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const proposals = [
    ...metricsFor(fields, roles, { subject, taken }),
    ...extra,
  ].filter((p) => !removed.has(p.key));
  const picked = proposals.filter((p) => !dropped.has(p.key));
  const clauses = filterClauses(roles, filters);

  //: The columns a metric can measure: anything marked as one, plus the option
  //: of measuring nothing and counting rows instead.
  const measurable = fields.filter((f) => roles[f.name] === 'measure');

  /** Off the list entirely — the tick box is for changing your mind. */
  function remove(key: string) {
    setRemoved((current) => new Set(current).add(key));
    setExtra((current) => current.filter((p) => p.key !== key));
    setOpen((current) => (current === key ? null : current));
  }

  const change = (key: string, patch: MetricEdit) =>
    setEdits((current) => ({
      ...current,
      [key]: { ...current[key], ...patch },
    }));

  const chosen = (role: Role) =>
    fields.filter((f) => roles[f.name] === role).map((f) => f.name);
  // **A date is no longer required.** Empty means the fact is dated by when its
  // number last changed — the rule that lets a pre-aggregated view map at all.
  //
  // A dateless mapping still needs a row id, so that the rule can find the fact
  // written last time and compare. But demanding a separate *column* for it was
  // an unsatisfiable question: a view with one row per person identifies its rows
  // by that person, and this panel gives each column exactly one role — so the
  // email was already spoken for as the subject and nothing could ever be
  // offered as the id.
  //
  // The subject is the answer in that case, and `rowId` says so rather than
  // blocking. A source with genuinely many rows per person and no date cannot be
  // told apart by anything anyway, which is a problem with the source.
  const rowId =
    chosen('id')[0] ??
    (chosen('date').length === 0 ? chosen('subject')[0] : null) ??
    null;
  const missing = [
    chosen('subject').length === 0 ? 'who a row belongs to' : '',
  ].filter(Boolean);
  // A filter somebody turned on but never answered would be `eq ''`, which
  // matches nothing and produces an empty leaderboard rather than an error.
  const unanswered = fields
    .filter((f) => roles[f.name] === 'filter' && !(filters[f.name] ?? ''))
    .map((f) => f.name);

  const blocked =
    missing.length > 0 || unanswered.length > 0 || picked.length === 0;

  /** The one line under a metric that says exactly what it will count. */
  function describe(proposal: MetricProposal): string {
    const it = edited(proposal, edits[proposal.key]);
    const base = it.value_field
      ? `${AGGREGATION_LABELS[it.aggregation]}: ${it.value_field}`
      : it.aggregation === 'count'
        ? 'Count the rows'
        : 'One per row';
    if (clauses.length === 0) return `${base}.`;
    const where = clauses
      .map((c) => `${c.field} is “${c.value}”`)
      .join(' and ');
    return `${base}, where ${where}.`;
  }

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const subjectField = chosen('subject')[0];
      const dateField = chosen('date')[0] ?? null;
      if (!subjectField) return;

      for (const proposal of picked) {
        const it = edited(proposal, edits[proposal.key]);
        const metric = await api<{ id: number }>('/api/metrics', {
          method: 'POST',
          body: JSON.stringify({
            key: it.key,
            name: it.name,
            unit: it.unit,
            aggregation: it.aggregation,
            direction: it.direction,
            decimal_places: it.decimal_places,
            description: `Created from ${source.name}.`,
          }),
        });
        await dataSources.addMapping(source.id, {
          metric_id: metric.id,
          subject_field: subjectField,
          occurred_at_field: dateField,
          external_id_field: rowId,
          // **One row per person is the shape that needs snapshotting**, and it
          // is detectable: if the thing identifying a row *is* the person, there
          // is one row each and its number is a running total. A row identified
          // by anything else — a deal id, a ticket number — is an event, where
          // dating by day would turn one sale into one a day.
          //
          // An earlier version of this called the two shapes indistinguishable
          // and left the choice to the reader. They are not; this is the signal.
          snapshot_daily: !dateField && rowId === subjectField,
          value_field: it.value_field,
          filters: clauses,
        });
      }
      await onCreated();
    } catch (e) {
      // Partial failure is possible and worth saying so: the loop may have
      // created some before failing, and silently retrying would double them.
      setError(
        (e instanceof Error ? e.message : 'Could not create those.') +
          ' Anything already created is kept — untick it and try the rest.',
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      {/* 1 — every column, and what it is for. Leading with this because it is
          the answer to "did it read my sheet properly?", which is the question
          somebody actually has at this moment. */}
      <div className="rounded-lg border border-edge bg-surface p-4">
        <p className="text-sm font-medium text-content">
          What arrived, and what each column is for
        </p>
        <p className="mt-1 text-sm text-content-muted">
          Worked out from the names and the values. Change any of it — this is
          also where you say what a column means when the guess is wrong.
        </p>

        <ul className="mt-4 divide-y divide-edge rounded-md border border-edge">
          {fields.map((f) => {
            const role = roles[f.name] ?? 'ignore';
            return (
              <li
                key={f.name}
                className="flex flex-wrap items-center gap-3 px-3 py-2"
              >
                <span className="min-w-40 flex-1">
                  <span className="block truncate font-mono text-sm text-content">
                    {f.name}
                  </span>
                  <span className="block truncate text-xs text-content-subtle">
                    {f.samples[0] ?? '—'}
                  </span>
                </span>

                <select
                  aria-label={`What ${f.name} is for`}
                  value={role}
                  onChange={(e) =>
                    setRoles((r) => ({
                      ...r,
                      [f.name]: e.target.value as Role,
                    }))
                  }
                  className={`shrink-0 rounded-md border bg-bg px-2 py-1 text-sm outline-none focus:border-brand ${
                    role === 'ignore'
                      ? 'border-edge text-content-subtle'
                      : 'border-edge text-content'
                  }`}
                >
                  {ROLES.map((each) => (
                    <option key={each} value={each}>
                      {ROLE_LABELS[each]}
                    </option>
                  ))}
                </select>

                {/* The value, beside the role that needs it rather than in a
                    section of its own — "only rows where stage is X" is one
                    sentence and reads as one row. */}
                {role === 'filter' && (
                  <select
                    aria-label={`Which ${f.name} to keep`}
                    value={filters[f.name] ?? ''}
                    onChange={(e) =>
                      setFilters((v) => ({ ...v, [f.name]: e.target.value }))
                    }
                    className={`shrink-0 rounded-md border bg-bg px-2 py-1 text-sm outline-none focus:border-brand ${
                      filters[f.name]
                        ? 'border-edge text-content'
                        : 'border-warning text-warning'
                    }`}
                  >
                    <option value="">choose a value…</option>
                    {(f.values ?? []).map((v) => (
                      <option key={v} value={v}>
                        {v}
                      </option>
                    ))}
                  </select>
                )}
              </li>
            );
          })}
        </ul>

        <p className="mt-2 text-xs text-content-subtle">
          {ROLE_HINTS.subject} {ROLE_HINTS.date}
        </p>
      </div>

      {/* 2 — what that adds up to. */}
      <div className="rounded-lg border border-edge bg-surface p-4">
        <p className="text-sm font-medium text-content">Metrics to create</p>
        <p className="mt-1 text-sm text-content-muted">
          {subject
            ? `Named after “${subject}”, because a column called amount cannot say whether you call it revenue, premium or commission. Rename freely.`
            : 'Rename these — a column called amount cannot say whether you call it revenue, premium or commission.'}
        </p>

        {proposals.length === 0 ? (
          <p className="mt-4 rounded-md border border-warning px-3 py-2 text-sm text-warning">
            Nothing to measure yet. Mark at least one column as{' '}
            <strong>{ROLE_LABELS.measure}</strong>, or leave them all and this
            still counts one per row.
          </p>
        ) : (
          <ul className="mt-4 space-y-2">
            {proposals.map((proposal) => (
              <li
                key={proposal.key}
                className="rounded-md border border-edge px-3 py-2"
              >
                <div className="flex flex-wrap items-center gap-3">
                  <input
                    type="checkbox"
                    checked={!dropped.has(proposal.key)}
                    onChange={(e) =>
                      setDropped((current) => {
                        const next = new Set(current);
                        if (e.target.checked) next.delete(proposal.key);
                        else next.add(proposal.key);
                        return next;
                      })
                    }
                    aria-label={`Create ${proposal.name}`}
                    className="size-4 shrink-0 accent-[var(--gg-brand)]"
                  />
                  <span className="min-w-40 flex-1">
                    <input
                      aria-label={`Name for ${proposal.name}`}
                      value={edits[proposal.key]?.name ?? proposal.name}
                      onChange={(e) =>
                        change(proposal.key, { name: e.target.value })
                      }
                      maxLength={120}
                      className="w-full rounded-md border border-edge bg-bg px-2 py-1 text-sm text-content outline-none focus:border-brand"
                    />
                    {/* **The sentence that would have caught the wrong number.**
                        "One per row, where stage is Closed Won" is checkable at a
                        glance; "One per row" beside a metric called Closed Deals
                        is not. */}
                    <span className="mt-1 block text-xs text-content-subtle">
                      {describe(proposal)}
                    </span>
                  </span>
                  <span className="shrink-0 rounded-full bg-surface-hover px-2 py-0.5 text-xs text-content-muted">
                    {edited(proposal, edits[proposal.key]).unit}
                  </span>
                  {/* **Collapsed by default, and that is the whole reason it can
                      exist.** The summary above is right most of the time; five
                      dropdowns per metric on first sight is the wall this panel
                      was built to remove. Open is where you go when it is wrong. */}
                  <button
                    type="button"
                    onClick={() =>
                      setOpen((current) =>
                        current === proposal.key ? null : proposal.key,
                      )
                    }
                    aria-expanded={open === proposal.key}
                    className="shrink-0 text-xs text-brand hover:underline"
                  >
                    {open === proposal.key ? 'Done' : 'Edit'}
                  </button>
                </div>

                {open === proposal.key && (
                  <div className="mt-3 grid gap-3 border-t border-edge pt-3 sm:grid-cols-2">
                    {/* "What data it connects to", which is the question the
                        summary line answers and this one changes. The options are
                        the columns marked as measures above, so the two panels
                        cannot disagree about what is measurable. */}
                    <Select
                      label="Measures"
                      value={
                        edited(proposal, edits[proposal.key]).value_field ?? ''
                      }
                      onChange={(v) =>
                        change(proposal.key, {
                          value_field: v === '' ? null : v,
                        })
                      }
                      options={[
                        { value: '', label: 'Nothing — one per row' },
                        ...measurable.map((f) => ({
                          value: f.name,
                          label: f.name,
                        })),
                      ]}
                      hint={
                        measurable.length === 0
                          ? 'Mark a column as “Measure it” above to offer more here.'
                          : undefined
                      }
                    />
                    <Select
                      label="Combine by"
                      value={edited(proposal, edits[proposal.key]).aggregation}
                      onChange={(v) =>
                        change(proposal.key, { aggregation: v as Aggregation })
                      }
                      options={AGGREGATIONS.map((a) => ({
                        value: a,
                        label: AGGREGATION_LABELS[a],
                      }))}
                    />
                    <Select
                      label="Unit"
                      value={edited(proposal, edits[proposal.key]).unit}
                      onChange={(v) =>
                        change(proposal.key, { unit: v as Unit })
                      }
                      options={UNITS.map((u) => ({ value: u, label: u }))}
                    />
                    <Select
                      label="Better when"
                      value={edited(proposal, edits[proposal.key]).direction}
                      onChange={(v) =>
                        change(proposal.key, { direction: v as Direction })
                      }
                      options={DIRECTIONS.map((d) => ({
                        value: d,
                        label: DIRECTION_LABELS[d],
                      }))}
                    />
                    {/* A choice rather than a number box: the API accepts 0 to
                        4, and a box that takes 7 and fails on save is a worse
                        control than one that cannot express it. */}
                    <Select
                      label="Decimal places"
                      value={String(
                        edited(proposal, edits[proposal.key]).decimal_places,
                      )}
                      onChange={(v) =>
                        change(proposal.key, { decimal_places: Number(v) })
                      }
                      options={[0, 1, 2, 3, 4].map((n) => ({
                        value: String(n),
                        label: String(n),
                      }))}
                    />

                    {/* **Distinct from unticking it.** The tick box says "not
                        this time" and can be changed back; this says "stop
                        offering it", which matters on a wide view where a dozen
                        proposals bury the three somebody wants. */}
                    <div className="border-t border-edge pt-3 sm:col-span-2">
                      <button
                        type="button"
                        onClick={() => remove(proposal.key)}
                        className="text-xs text-content-muted underline transition-colors hover:text-danger"
                      >
                        Remove from the list
                      </button>
                    </div>
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}

        {/* **Said out loud, because it was inferred rather than chosen.** With no
            date the fact is dated by when its number last changed, which means
            recognising the same row between reads — and here that is the person.
            Silently picking a column that decides whether totals update or
            multiply is not something to leave unsaid. */}
        {chosen('date').length === 0 && rowId && (
          <p className="mt-3 text-sm text-content-muted">
            No date column, so each row is dated when its number last changed.
            Rows are recognised between reads by <strong>{rowId}</strong> — mark
            a different column “{ROLE_LABELS.id}” above to use that instead.
          </p>
        )}

        {error && (
          <p
            role="alert"
            className="mt-3 rounded-md border border-danger px-3 py-2 text-sm text-danger"
          >
            {error}
          </p>
        )}

        {/* Said plainly and next to the button, rather than as a disabled button
            somebody has to guess at. */}
        {(missing.length > 0 || unanswered.length > 0) && (
          <p className="mt-3 rounded-md border border-warning px-3 py-2 text-sm text-warning">
            {missing.length > 0 && (
              <>
                Nothing says {missing.join(' or ')}.{' '}
                {missing.length > 1 ? 'Both are' : 'That is'} needed before
                anything can be measured.
              </>
            )}
            {missing.length > 0 && unanswered.length > 0 && ' '}
            {unanswered.length > 0 && (
              <>
                Choose which value of <strong>{unanswered.join(', ')}</strong>{' '}
                to keep, or set it to “{ROLE_LABELS.ignore}”.
              </>
            )}
          </p>
        )}

        {/* **Not limited to what was detected.** Detection proposes a count and
            one metric per numeric column; a deployment that wants a second cut of
            the same column — average deal size beside total revenue — had no way
            to say so without leaving the wizard. */}
        <button
          type="button"
          onClick={() => {
            const key = `custom_${extra.length + 1}`;
            setExtra((current) => [
              ...current,
              {
                key,
                name: subject ? `${subject} — new metric` : 'New metric',
                unit: 'count',
                aggregation: 'sum',
                decimal_places: 0,
                value_field: measurable[0]?.name ?? null,
                why: 'Added by hand.',
              },
            ]);
            setOpen(key);
          }}
          className="mt-3 text-sm text-brand hover:underline"
        >
          + Add another metric
        </button>

        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => void create()}
            disabled={busy || blocked}
            className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
          >
            {busy
              ? 'Creating…'
              : `Create ${picked.length} ${picked.length === 1 ? 'metric' : 'metrics'}`}
          </button>
          <Link
            to="/metrics"
            className="text-sm text-content-muted underline transition-colors hover:text-content"
          >
            Or make one by hand
          </Link>
        </div>
      </div>
    </div>
  );
}

/**
 * The last step: say what the columns mean, then turn it on.
 *
 * **Two steps merged into one**, because the second was a summary of the first.
 * The mapping editor already shows ten real rows as the facts they would become —
 * that *is* the confirmation, and a screen restating it in prose was a click
 * charged for nothing.
 */
function MapIt({
  source,
  fields,
  metrics,
  mapping,
  busy,
  connectorName,
  onMapped,
  onMetrics,
  onBack,
  onFinish,
}: {
  source: SourceDetail;
  fields: SourceField[];
  metrics: MetricOption[];
  mapping: Mapping | null;
  busy: boolean;
  /** What this connector is called, so a source still named after it is ignored. */
  connectorName: string;
  /** `null` starts a blank editor, for mapping a second metric. */
  onMapped: (mapping: Mapping | null) => void;
  /** Refetch metrics and the source after some were created from the columns. */
  onMetrics: () => Promise<unknown>;
  onBack: () => void;
  onFinish: () => void;
}) {
  const importable = metrics.filter((m) => !m.archived);

  /**
   * Feed a metric that exists, or make one out of these columns.
   *
   * **It used to be neither — it was whichever the deployment's age implied.**
   * The proposal UI appeared only when the org had no metrics at all, so it was
   * reachable on day one and never again. Connect a source whose columns match
   * nothing you already measure, and the only offer was a dropdown of metrics
   * that are all wrong, with no route to the screen that would have built the
   * right one. The way through was to abandon the wizard, create a metric
   * elsewhere, and come back.
   *
   * Both are now always on offer. The default still follows what is there,
   * because it is right far more often than not: nothing to add to means make
   * one, and otherwise most sources genuinely are feeding something that exists.
   */
  const [mode, setMode] = useState<'existing' | 'new'>(
    importable.length === 0 ? 'new' : 'existing',
  );

  return (
    <section>
      <h2 className="text-h2 text-content">Say what the columns mean</h2>
      <p className="mt-1 mb-4 text-sm text-content-muted">
        Filled in from what your source actually sent. Change anything that
        looks wrong — the table underneath updates as you go, and nothing is
        imported until you turn it on.
      </p>

      {/* Only a choice when there is something to choose between. With no
          metrics yet, "add to an existing metric" is a tab onto an empty
          dropdown. */}
      {importable.length > 0 && (
        <div className="mb-4 flex flex-wrap gap-2">
          <Tab active={mode === 'existing'} onClick={() => setMode('existing')}>
            Add to an existing metric
          </Tab>
          <Tab active={mode === 'new'} onClick={() => setMode('new')}>
            Create a metric from this data
          </Tab>
        </div>
      )}

      {/* **What is already mapped, because a source can feed several metrics.**
          The editor shows one mapping at a time, so without this list the second
          and third were invisible — and there was no way back to them, or on to a
          fourth. Creating metrics from the columns has always made several at
          once; mapping to metrics that already exist could only ever make one. */}
      {mode === 'existing' && source.mappings.length > 0 && (
        <ul className="mb-4 divide-y divide-edge rounded-lg border border-edge bg-surface">
          {source.mappings.map((m) => (
            <li
              key={m.id}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2"
            >
              <span className="min-w-40 flex-1 text-sm text-content">
                {m.metric_name}
                <span className="ml-2 text-xs text-content-subtle">
                  {m.value_field ? m.value_field : 'one per row'}
                </span>
              </span>
              {mapping?.id === m.id ? (
                <span className="shrink-0 text-xs text-content-subtle">
                  editing
                </span>
              ) : (
                <button
                  type="button"
                  onClick={() => onMapped(m)}
                  className="shrink-0 text-xs text-brand hover:underline"
                >
                  Edit
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {mode === 'new' ? (
        <SuggestMetrics
          source={source}
          fields={fields}
          connectorName={connectorName}
          onCreated={async () => {
            const result = await onMetrics();
            // What was just built is now an existing metric with a mapping
            // already pointing at it — so show that, rather than the proposal
            // screen offering to build it a second time.
            setMode('existing');
            return result;
          }}
        />
      ) : (
        <>
          <MappingEditor
            // **Remounted per mapping.** The draft is seeded once from
            // `existing`, so switching to another mapping — or to a blank one —
            // without a new key would leave the previous one's columns on screen
            // under the new one's name.
            key={mapping?.id ?? 'new'}
            sourceId={source.id}
            fields={fields}
            metrics={metrics}
            existing={mapping ?? undefined}
            onSaved={onMapped}
          />

          {mapping && (
            <button
              type="button"
              onClick={() => onMapped(null)}
              className="mt-3 rounded-md border border-edge px-3 py-2 text-sm text-content transition-colors hover:bg-surface-hover"
            >
              Add another metric
            </button>
          )}
        </>
      )}

      {mapping && (
        <p className="mt-4 text-sm text-content-muted">
          Turning it on imports{' '}
          {source.backfill_days === 0
            ? 'from now on'
            : `the last ${source.backfill_days} days`}
          , then checks{' '}
          {source.interval_minutes === 0
            ? 'only when you press Sync now'
            : `every ${source.interval_minutes} minutes`}
          {source.endpoint_url ? ', plus whenever an event arrives' : ''}. If
          some names in the data do not match anyone here, those rows wait for
          you to say who they are rather than being guessed at.
        </p>
      )}

      <Buttons
        onBack={onBack}
        onNext={onFinish}
        nextLabel="Review"
        nextDisabled={source.mappings.length === 0 || busy}
        note={
          source.mappings.length === 0
            ? 'Ready once a mapping saves cleanly.'
            : undefined
        }
      />
    </section>
  );
}

/**
 * Everything about to start importing, before anything does.
 *
 * **One line per mapping, because there can be several.** Creating metrics from
 * the columns makes one per metric, and the mapping editor shows a single one at
 * a time — so the step before this could truthfully say "ready" while two of the
 * three things about to run had never been on screen.
 *
 * Nothing here is editable. It is the last look, and a screen that invites
 * changes is a screen somebody has to re-check afterwards; Back is one click.
 */
function Review({
  source,
  busy,
  onBack,
  onFinish,
}: {
  source: SourceDetail;
  busy: boolean;
  onBack: () => void;
  onFinish: () => void;
}) {
  const every = source.mappings.length;

  return (
    <section>
      <h2 className="text-h2 text-content">Ready to turn on</h2>
      <p className="mt-1 mb-4 text-sm text-content-muted">
        {every === 1 ? 'One metric' : `${every} metrics`} will start filling
        from <strong>{source.name}</strong>. Nothing has been imported yet.
      </p>

      <ul className="divide-y divide-edge rounded-lg border border-edge bg-surface">
        {source.mappings.map((m) => (
          <li key={m.id} className="px-4 py-3">
            <p className="font-medium text-content">{m.metric_name}</p>
            <p className="mt-1 text-sm text-content-muted">
              {m.value_field
                ? `Adds up “${m.value_field}”`
                : 'Counts one per row'}
              , per person from “{m.subject_field}”
              {m.occurred_at_field
                ? `, dated by “${m.occurred_at_field}”`
                : ', dated when the number last changes'}
              {Number(m.multiplier) !== 1 ? `, times ${m.multiplier}` : ''}.
            </p>
            {m.filters.length > 0 && (
              <p className="mt-1 text-sm text-content-muted">
                Only rows where{' '}
                {m.filters
                  .map((f) => `${f.field} is “${f.value}”`)
                  .join(' and ')}
                .
              </p>
            )}
          </li>
        ))}
      </ul>

      <p className="mt-4 text-sm text-content-muted">
        Turning it on imports{' '}
        {source.backfill_days === 0
          ? 'from now on'
          : `the last ${source.backfill_days} days`}
        , then checks{' '}
        {source.interval_minutes === 0
          ? 'only when you press Sync now'
          : `every ${source.interval_minutes} minutes`}
        {source.endpoint_url ? ', plus whenever an event arrives' : ''}. If some
        names in the data do not match anyone here, those rows wait for you to
        say who they are rather than being guessed at.
      </p>

      <Buttons
        onBack={onBack}
        onNext={onFinish}
        nextLabel={busy ? 'Starting…' : 'Turn it on and sync now'}
        nextDisabled={busy || every === 0}
      />
    </section>
  );
}

function Buttons({
  onBack,
  onNext,
  nextLabel,
  nextDisabled,
  note,
}: {
  onBack: () => void;
  onNext: () => void;
  nextLabel: string;
  nextDisabled?: boolean;
  note?: string;
}) {
  return (
    <div className="mt-6">
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={onBack}
          className="rounded-md border border-edge px-4 py-2 text-sm text-content-muted transition-colors hover:bg-surface-hover hover:text-content"
        >
          Back
        </button>
        <button
          type="button"
          onClick={onNext}
          disabled={nextDisabled}
          className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-40"
        >
          {nextLabel}
        </button>
      </div>
      {note && <p className="mt-2 text-xs text-content-subtle">{note}</p>}
    </div>
  );
}
