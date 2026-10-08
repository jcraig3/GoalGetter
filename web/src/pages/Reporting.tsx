import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { api } from '../api';
import EmptyState from '../components/EmptyState';
import MetricValue from '../components/MetricValue';
import PageHeader from '../components/PageHeader';
import { Tab } from '../components/Tabs';
import CompetitionReportCard from '../components/CompetitionReportCard';
import ReportSchedules from '../components/ReportSchedules';
import {
  TONE_BORDER,
  TONE_TEXT,
  type Gap,
  type TrackRecord,
  gapSentence,
  hitLabel,
  stepUp,
  streakLabel,
  tone,
} from './reportingCopy';
import Loading from '../components/Loading';

interface Overview {
  total: number;
  on_pace: number;
  behind: number;
  hit: number;
  /** Null when no running goal has anything recorded yet. */
  on_pace_percent: number | null;
  not_started?: number;
  gaps: Gap[];
}

interface CompetitionRow {
  id: number;
  name: string;
  state: string;
}

type View = 'overview' | 'record' | 'competitions' | 'email';

/**
 * The reporting tab.
 *
 * **Three questions, not one dashboard.** Who needs help today, who keeps
 * missing, and whether a contest is on for a good number — a manager asks
 * exactly one of those at a time, and a page that answered all three at once
 * would be scrolled past to reach the part that was wanted.
 *
 * Nothing here is a second way to read other people's figures. Every number
 * is one the viewer could already reach by opening the goal; what the page
 * adds is the ordering and the sentence at the end.
 */
export default function Reporting() {
  const [view, setView] = useState<View>('overview');

  return (
    <>
      <PageHeader
        title="Reporting"
        description="Who needs a conversation, and what about."
      />

      <div className="mb-6 flex flex-wrap gap-2">
        <Tab active={view === 'overview'} onClick={() => setView('overview')}>
          Overview
        </Tab>
        <Tab active={view === 'record'} onClick={() => setView('record')}>
          Track record
        </Tab>
        <Tab
          active={view === 'competitions'}
          onClick={() => setView('competitions')}
        >
          Competitions
        </Tab>
        <Tab active={view === 'email'} onClick={() => setView('email')}>
          Email
        </Tab>
      </div>

      {view === 'overview' && <OverviewPanel />}
      {view === 'record' && <RecordPanel />}
      {view === 'competitions' && <CompetitionsPanel />}
      {view === 'email' && <ReportSchedules />}
    </>
  );
}

/** A load that failed, said once.
 *
 * Not `ErrorNote`, which is dismissable — dismissing this would leave an
 * empty panel that reads as "nothing to report" rather than "nothing
 * loaded", which is the more dangerous of the two on a page about who is
 * behind.
 */
function LoadError({ message }: { message: string }) {
  return (
    <p
      role="alert"
      className="rounded-md border border-danger px-3 py-2 text-sm text-danger"
    >
      {message}
    </p>
  );
}

// -- Overview ----------------------------------------------------------------

function OverviewPanel() {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Overview>('/api/reporting/overview')
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load.'));
  }, []);

  if (error) return <LoadError message={error} />;
  if (!data) return <Loading />;

  if (data.total === 0) {
    return (
      <EmptyState
        title="No goals are running"
        description="Once somebody has a target in a period that has started, this is where you will see who is on for it."
        action={
          <Link className="text-sm text-brand hover:underline" to="/goals">
            Go to goals
          </Link>
        }
      />
    );
  }

  // Too early to tell is not a percentage (Q2-10).
  const headline = data.on_pace_percent === null ? 'neutral' : tone(data.on_pace_percent);

  return (
    <div className="space-y-6">
      <section
        className={`rounded-lg border bg-surface p-6 ${TONE_BORDER[headline]}`}
      >
        <p className="text-sm text-content-muted">On pace</p>
        <p className={`mt-1 text-h1 tabular-nums ${TONE_TEXT[headline]}`}>
          {data.on_pace_percent === null ? 'Too early to tell' : `${data.on_pace_percent}%`}
        </p>
        <dl className="mt-5 flex flex-wrap gap-x-8 gap-y-3 text-sm">
          <Chip label="Already hit" value={data.hit} tone="text-success" />
          <Chip label="On track" value={data.on_pace} tone="text-content" />
          <Chip label="Behind" value={data.behind} tone="text-danger" />
          {(data.not_started ?? 0) > 0 && (
            <Chip label="Nothing yet" value={data.not_started ?? 0} tone="text-content-muted" />
          )}
          <Chip label="Goals running" value={data.total} tone="text-content-muted" />
        </dl>
      </section>

      {/* Only when there is something. A permanent "nobody is behind" panel
          trains people to stop looking at the spot warnings appear in. */}
      {data.gaps.length > 0 && (
        <section className="rounded-lg border border-edge bg-surface p-6">
          <h2 className="text-h3 text-content">What is missing</h2>
          <p className="mt-1 text-sm text-content-muted">
            Furthest off the pace first, and what closing it would take.
          </p>

          <ul className="mt-5 divide-y divide-edge">
            {data.gaps.map((gap) => (
              <GapRow key={gap.goal_id} gap={gap} />
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function Chip({
  label,
  value,
  tone: colour,
}: {
  label: string;
  value: number;
  tone: string;
}) {
  return (
    <div>
      <dt className="text-content-muted">{label}</dt>
      <dd className={`mt-0.5 text-h3 tabular-nums ${colour}`}>{value}</dd>
    </div>
  );
}

function GapRow({ gap }: { gap: Gap }) {
  const multiple = stepUp(gap);
  const format = { unit: gap.unit, decimal_places: gap.decimal_places, unit_label: gap.unit_label };

  return (
    <li className="py-4 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <Link
          to={`/goals/${gap.goal_id}`}
          className="text-content hover:underline"
        >
          <span className="font-medium">{gap.subject_name}</span>
          <span className="text-content-muted"> · {gap.goal_name}</span>
        </Link>
        <p className="text-sm tabular-nums text-content-muted">
          <MetricValue value={gap.current} format={format} bare /> of{' '}
          <MetricValue value={gap.target} format={format} />
        </p>
      </div>

      <p className="mt-1 text-sm text-content">{gapSentence(gap)}</p>

      {/* Only when the change is large enough to be the point. "1.1x" is
          noise next to the sentence that already said the two rates. */}
      {multiple !== null && multiple >= 1.5 && (
        <p className="mt-1 text-xs text-warning">
          That is {multiple}× the rate so far.
        </p>
      )}
    </li>
  );
}

// -- Track record ------------------------------------------------------------

function RecordPanel() {
  const [rows, setRows] = useState<TrackRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<TrackRecord[]>('/api/reporting/records')
      .then(setRows)
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load.'));
  }, []);

  if (error) return <LoadError message={error} />;
  if (!rows) return <Loading />;

  if (rows.length === 0) {
    return (
      <EmptyState
        title="Nothing has a track record yet"
        description="A goal on a repeating period builds one as each period finishes. A one-off date range has no periods before it to compare."
      />
    );
  }

  return (
    <section className="rounded-lg border border-edge bg-surface p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-h3 text-content">Track record</h2>
          <p className="mt-1 text-sm text-content-muted">
            How often each goal has been met in the periods before this one,
            measured against today&rsquo;s target.
          </p>
        </div>
        {/* A plain link, not a fetch: the browser downloads it with the
            session cookie, so nothing here has to hold a file in memory. */}
        <a
          href="/api/reporting/records.csv"
          className="text-sm text-brand hover:underline"
        >
          Download CSV
        </a>
      </div>

      <ul className="mt-5 divide-y divide-edge">
        {rows.map((record) => (
          <RecordRow key={record.goal_id} record={record} />
        ))}
      </ul>
    </section>
  );
}

function RecordRow({ record }: { record: TrackRecord }) {
  const colour = tone(record.hit_rate);
  const streak = streakLabel(record);

  return (
    <li className="py-4 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <Link
          to={`/goals/${record.goal_id}`}
          className="text-content hover:underline"
        >
          <span className="font-medium">{record.subject_name}</span>
          <span className="text-content-muted"> · {record.goal_name}</span>
        </Link>
        <p className="text-sm tabular-nums">
          {record.considered === 0 ? (
            // Nothing to count yet: a new goal for somebody new (Q2-7).
            <span className="text-content-muted">No history yet</span>
          ) : (
            <>
              <span className={TONE_TEXT[colour]}>{record.hit_rate}%</span>
              <span className="text-content-muted"> · {hitLabel(record)}</span>
            </>
          )}
        </p>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-2">
        {record.seasons.map((season) => (
          <span
            key={season.label}
            title={
              season.counted === false
                ? `${season.label}: before this goal`
                : `${season.label}: ${season.value}`
            }
            className={`rounded px-1.5 py-0.5 text-xs tabular-nums ${
              season.counted === false
                ? 'border border-dashed border-edge text-content-subtle'
                : season.met_target
                  ? 'bg-success/15 text-success'
                  : 'bg-surface-hover text-content-muted'
            }`}
          >
            {season.label}
          </span>
        ))}
        {streak && (
          <span className="text-xs text-content-muted">{streak}</span>
        )}
      </div>
    </li>
  );
}

// -- Competitions ------------------------------------------------------------

function CompetitionsPanel() {
  const [list, setList] = useState<CompetitionRow[] | null>(null);
  const [chosen, setChosen] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<CompetitionRow[]>('/api/competitions')
      .then((rows) => {
        setList(rows);
        // Land on something rather than an empty frame with a picker in it.
        // A contest that is running is the one somebody came here about; a
        // finished one is the fallback, because its report still reads.
        const running = rows.find((row) => row.state === 'active');
        setChosen((running ?? rows[0])?.id ?? null);
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load.'));
  }, []);

  if (error) return <LoadError message={error} />;
  if (!list) return <Loading />;

  if (list.length === 0) {
    return (
      <EmptyState
        title="No competitions yet"
        description="Once one has run, this is where you will see whether the next is on for a better number."
        action={
          <Link className="text-sm text-brand hover:underline" to="/competitions">
            Go to competitions
          </Link>
        }
      />
    );
  }

  return (
    <div className="space-y-6">
      <label className="block max-w-sm">
        <span className="text-sm text-content-muted">Competition</span>
        <select
          value={chosen ?? ''}
          onChange={(event) => setChosen(Number(event.target.value))}
          className="mt-1 w-full rounded-md border border-edge bg-surface px-3 py-2 text-content"
        >
          {list.map((row) => (
            <option key={row.id} value={row.id}>
              {row.name}
            </option>
          ))}
        </select>
      </label>

      {chosen !== null && <CompetitionReportCard competitionId={chosen} />}
    </div>
  );
}
