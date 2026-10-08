import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { api } from '../api';
import { useAuth } from '../auth';
import { toast } from '../toast';
import { useRefreshNotifications } from '../notifications';
import { RecogniseForm } from '../pages/Achievements';
import Avatar from './Avatar';
import { StatusBadge } from './GoalProgress';
import MetricValue, { type MetricFormat } from './MetricValue';
import { MedalIcon } from './icons';
import PersonLink from './PersonLink';

interface TeamGoal {
  goal_id: number;
  target: string;
  percent: number;
  expected_percent: number | null;
  status: string;
}

interface Member {
  user_id: number;
  name: string;
  photo_digest: string | null;
  value: string;
  rank: number;
  goal: TeamGoal | null;
  quiet_days: number | null;
  is_me: boolean;
}

export interface Note {
  user_id: number;
  name: string;
  kind: 'behind' | 'missed' | 'quiet' | 'hit' | 'leading' | 'team_quiet';
  value: string | null;
  target: string | null;
  expected: string | null;
  days: number | null;
}

export interface TeamHome {
  team_id: number;
  team_name: string;
  metrics: { id: number; name: string; recorded: number }[];
  metric_id: number | null;
  metric_name: string;
  unit: string;
  decimal_places: number;
  unit_label: string | null;
  direction: string;
  period_type: string;
  period_label: string;
  members: Member[];
  nudges: Note[];
  shout_outs: Note[];
}

const PERIODS = [
  { value: 'day', label: 'Today' },
  { value: 'week', label: 'This week' },
  { value: 'month', label: 'This month' },
  { value: 'quarter', label: 'This quarter' },
];

const METRIC_KEY = 'gg:team-metric';
const PERIOD_KEY = 'gg:team-period';

/** The period before, as the offer to show it says it. */
const LAST: Record<string, string> = {
  day: 'yesterday',
  week: 'last week',
  month: 'last month',
  quarter: 'last quarter',
};

/** Nobody has a number yet: every value zero or missing. */
export function nothingYet(members: { value: string | number | null }[]): boolean {
  return members.length > 0 && members.every((m) => !Number(m.value ?? 0));
}

function remembered(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function remember(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // A private window: remembered for this visit only.
  }
}

/** How many nudges show before "and N more" — a list of twenty is a report,
 *  not something to act on before lunch. */
const NUDGES_SHOWN = 6;

/** The board's first page. A big team is a long list, and a home page is not
 *  the place to scroll it — "Show all" is there for when it is wanted. */
const BOARD_SHOWN = 10;

/**
 * **A manager's own team, on their home page** (6.13).
 *
 * The board for the team on one metric, each person's goal beside their
 * number, who needs a nudge and why, and who has earned a word — with
 * "Recognise" right there, so noticing and saying so are one click apart.
 *
 * The server sends null for anybody with no team to manage, and then this
 * draws nothing.
 */
export default function TeamCard({
  staleAbove = false,
}: {
  /** Home's banner already says which source stopped, and since when (P3-3). */
  staleAbove?: boolean;
} = {}) {
  const [home, setHome] = useState<TeamHome | null | undefined>(undefined);
  const [metricId, setMetricId] = useState<string>(() => remembered(METRIC_KEY) ?? '');
  const [period, setPeriod] = useState<string>(() => remembered(PERIOD_KEY) ?? 'month');
  const [error, setError] = useState<string | null>(null);
  const [recognising, setRecognising] = useState<number | null>(null);
  const [allNudges, setAllNudges] = useState(false);
  const [allMembers, setAllMembers] = useState(false);
  // **A period with nothing in it yet says so** (8.2) — ten "– $0.00" rows
  // said it ten times — and offers the one before when that had numbers.
  const [previous, setPrevious] = useState(false);
  const [lastHadNumbers, setLastHadNumbers] = useState(false);
  const refreshBell = useRefreshNotifications();
  const { can } = useAuth();

  const load = useCallback(() => {
    const query = new URLSearchParams({ period_type: period });
    if (metricId) query.set('metric_id', metricId);
    if (previous) query.set('previous', 'true');
    api<TeamHome | null>(`/api/dashboard/team?${query}`)
      .then((found) => {
        setHome(found);
        // Only worth offering the last period when it had something in it.
        if (found && !previous && nothingYet(found.members)) {
          query.set('previous', 'true');
          api<TeamHome | null>(`/api/dashboard/team?${query}`)
            .then((last) => setLastHadNumbers(Boolean(last && !nothingYet(last.members))))
            .catch(() => setLastHadNumbers(false));
        } else if (!previous) {
          setLastHadNumbers(false);
        }
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load your team.'));
  }, [metricId, period, previous]);

  useEffect(load, [load]);

  if (home === null) return null;
  if (home === undefined) {
    return error ? (
      <section className="rounded-lg border border-edge bg-surface p-6">
        <p role="alert" className="text-sm text-danger">{error}</p>
      </section>
    ) : null;
  }

  const format: MetricFormat = {
    unit: home.unit,
    decimal_places: home.decimal_places,
    unit_label: home.unit_label,
  };
  const nudges = allNudges ? home.nudges : home.nudges.slice(0, NUDGES_SHOWN);
  const members = allMembers ? home.members : home.members.slice(0, BOARD_SHOWN);

  return (
    <section className="mb-6 rounded-lg border border-edge bg-surface p-6" aria-labelledby="team-card">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="team-card" className="text-h3 text-content">
          Your team <span className="text-content-muted">· {home.team_name}</span>
        </h2>
        <div className="flex flex-wrap gap-2">
          <label className="sr-only" htmlFor="team-metric">Metric</label>
          <select
            id="team-metric"
            value={String(home.metric_id ?? '')}
            onChange={(e) => {
              setMetricId(e.target.value);
              remember(METRIC_KEY, e.target.value);
            }}
            className="rounded-md border border-edge bg-bg px-2 py-1 text-sm text-content outline-none focus:border-brand"
          >
            {home.metrics.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </select>
          <label className="sr-only" htmlFor="team-period">Period</label>
          <select
            id="team-period"
            // Says the period on show (P3-12): "September 2026" while last
            // month is up, not "This month" beside last month's numbers.
            value={previous ? 'previous' : period}
            onChange={(e) => {
              if (e.target.value === 'previous') return;
              setPeriod(e.target.value);
              setPrevious(false);
              remember(PERIOD_KEY, e.target.value);
            }}
            className="rounded-md border border-edge bg-bg px-2 py-1 text-sm text-content outline-none focus:border-brand"
          >
            {previous && <option value="previous">{home.period_label}</option>}
            {PERIODS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="mt-5 grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        {/* The board, with each person's goal beside their number. */}
        <div>
        {previous && (
          <p className="mb-2 flex flex-wrap items-center gap-2 px-2 text-sm text-content-muted">
            Showing {home.period_label}.
            <button type="button" onClick={() => setPrevious(false)} className="text-brand hover:underline">
              Back to now
            </button>
          </p>
        )}
        {!previous && nothingYet(home.members) ? (
          <div className="rounded-md border border-dashed border-edge px-4 py-6 text-center text-sm text-content-muted">
            <p>No numbers for {home.period_label} yet.</p>
            {lastHadNumbers && (
              <button
                type="button"
                onClick={() => setPrevious(true)}
                className="mt-2 text-brand hover:underline"
              >
                Show {LAST[period] ?? 'the last period'}
              </button>
            )}
          </div>
        ) : (
        <ol className="space-y-1" aria-label={`${home.team_name} on ${home.metric_name}`}>
          {members.map((member) => (
            <li
              key={member.user_id}
              className="group flex items-center gap-3 rounded-md px-2 py-2 hover:bg-surface-hover"
            >
              <span className="w-6 shrink-0 text-right text-sm tabular-nums text-content-subtle">
                {member.rank || '–'}
              </span>
              <Avatar name={member.name} digest={member.photo_digest} />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm text-content">
                  <PersonLink id={member.user_id}>{member.name}</PersonLink>
                  {member.is_me && <span className="ml-2 text-xs text-content-subtle">you</span>}
                </p>
                {member.goal && <GoalLine goal={member.goal} format={format} />}
              </div>
              <MetricValue
                value={member.value}
                format={format}
                className="shrink-0 text-sm font-medium tabular-nums text-content"
              />
              {member.is_me ? (
                // The button's room, kept, so every figure lines up (7.1).
                <span
                  aria-hidden="true"
                  className="invisible shrink-0 rounded-md border px-2 py-1 text-xs"
                >
                  <MedalIcon className="size-4 sm:hidden" />
                  <span className="hidden sm:inline">Recognise</span>
                </span>
              ) : (
                <button
                  type="button"
                  onClick={() => setRecognising(member.user_id)}
                  aria-label={`Recognise ${member.name}`}
                  className="shrink-0 rounded-md border border-edge px-2 py-1 text-xs text-content-muted transition-colors hover:bg-surface-hover hover:text-content sm:opacity-0 sm:group-hover:opacity-100 sm:focus-visible:opacity-100"
                >
                  {/* An icon on a phone, where the word pushed the button out
                      of its card (Q2-19). Named either way, by the label. */}
                  <MedalIcon className="size-4 sm:hidden" />
                  <span className="hidden sm:inline">Recognise</span>
                </button>
              )}
            </li>
          ))}
        </ol>
        )}
        {!(!previous && nothingYet(home.members)) && home.members.length > BOARD_SHOWN && (
          <button
            type="button"
            onClick={() => setAllMembers((v) => !v)}
            className="mt-2 px-2 text-sm text-brand hover:underline"
          >
            {allMembers ? 'Show the top 10' : `Show all ${home.members.length}`}
          </button>
        )}
        </div>

        <div className="space-y-6">
          {home.shout_outs.length > 0 && (
            <div>
              <h3 className="text-sm font-medium text-content">Worth a word</h3>
              <ul className="mt-2 space-y-2">
                {home.shout_outs.map((note) => (
                  <li key={`${note.kind}-${note.user_id}`} className="flex items-start gap-3 text-sm">
                    <span className="min-w-0 flex-1">
                      <PersonLink id={note.user_id} className="text-content">{note.name}</PersonLink>{' '}
                      <span className="text-content-muted">
                        <NoteWords note={note} metric={home.metric_name} format={format} past={previous} />
                      </span>
                    </span>
                    <button
                      type="button"
                      onClick={() => setRecognising(note.user_id)}
                      className="shrink-0 rounded-md bg-brand px-2 py-1 text-xs font-medium text-white transition-colors hover:bg-brand-hover"
                    >
                      Recognise
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div>
            <h3 className="text-sm font-medium text-content">Who needs a nudge</h3>
            {home.nudges.length === 0 ? (
              <p className="mt-2 text-sm text-content-muted">
                Nobody — everyone is on pace and recording.
              </p>
            ) : (
              <ul className="mt-2 space-y-2">
                {nudges.map((note) =>
                  note.kind === 'team_quiet' ? (
                    // The whole team at once: the feed, not the people.
                    <li key="team_quiet" className="rounded-md border border-warning px-3 py-2 text-sm text-warning">
                      Nothing recorded for {note.value === null ? '' : Number(note.value)} of the team
                      {note.days !== null && <> in {note.days} days</>}
                      {staleAbove ? (
                        // The banner above names the source and its date
                        // already (P3-3): not a second date and a second link.
                        <> — see “No new numbers” above.</>
                      ) : (
                        <>
                          {' '}— the data may have stopped arriving.{' '}
                          {can('integrations.manage') && (
                            <Link to="/integrations" className="underline">
                              Check the integrations
                            </Link>
                          )}
                        </>
                      )}
                    </li>
                  ) : (
                  <li key={`${note.kind}-${note.user_id}`} className="text-sm">
                    <PersonLink id={note.user_id} className="text-content">{note.name}</PersonLink>{' '}
                    <span className={note.kind === 'quiet' ? 'text-content-muted' : 'text-warning'}>
                      <NoteWords note={note} metric={home.metric_name} format={format} past={previous} />
                    </span>
                  </li>
                  ),
                )}
                {home.nudges.length > NUDGES_SHOWN && (
                  <li>
                    <button
                      type="button"
                      onClick={() => setAllNudges((v) => !v)}
                      className="text-sm text-brand hover:underline"
                    >
                      {allNudges ? 'Show fewer' : `and ${home.nudges.length - NUDGES_SHOWN} more`}
                    </button>
                  </li>
                )}
              </ul>
            )}
          </div>
        </div>
      </div>

      {recognising !== null && (
        <RecogniseForm
          userId={recognising}
          onClose={() => setRecognising(null)}
          onSent={async () => {
            toast('Recognition sent');
            refreshBell();
            setRecognising(null);
          }}
          onError={(message) => message && toast(message)}
        />
      )}
    </section>
  );
}

/** Under a name: how far along their goal is, and whether that is on pace. */
function GoalLine({ goal, format }: { goal: TeamGoal; format: MetricFormat }) {
  return (
    <div className="mt-1 flex items-center gap-2">
      <div className="relative h-1.5 w-24 shrink-0 overflow-hidden rounded-full bg-surface-raised">
        <div
          className={`h-full rounded-full ${
            goal.status === 'hit' || goal.status === 'ahead'
              ? 'bg-success'
              : goal.status === 'behind'
                ? 'bg-warning'
                : goal.status === 'missed'
                  ? 'bg-danger'
                  : 'bg-brand'
          }`}
          style={{ width: `${Math.min(100, goal.percent)}%` }}
        />
      </div>
      <span className="truncate text-xs text-content-subtle">
        of <MetricValue value={goal.target} format={format} /> goal
      </span>
      <StatusBadge status={goal.status} />
    </div>
  );
}

/** Why somebody is listed, in words, with the figures written as everywhere else. */
export function NoteWords({
  note,
  metric,
  format,
  past = false,
}: {
  note: Note;
  metric: string;
  format: MetricFormat;
  /** Last period, shown on request: said as what happened (P3-12). */
  past?: boolean;
}) {
  const figure = (value: string | null) => <MetricValue value={value ?? 0} format={format} />;
  switch (note.kind) {
    case 'behind':
      return past ? (
        <>
          finished behind on {metric}: {figure(note.value)} of {figure(note.target)}
        </>
      ) : (
        <>
          is behind on {metric}: {figure(note.value)} of {figure(note.target)}
          {note.expected !== null && <>, {figure(note.expected)} expected by now</>}
        </>
      );
    case 'missed':
      return (
        <>
          missed their {metric} goal: {figure(note.value)} of {figure(note.target)}
        </>
      );
    case 'quiet':
      if (past) return <>recorded nothing</>;
      return note.days === null ? (
        <>hasn&rsquo;t recorded anything yet</>
      ) : (
        <>hasn&rsquo;t recorded anything in {note.days} days</>
      );
    case 'hit':
      return <>hit their {metric} goal with {figure(note.value)}</>;
    case 'leading':
      return past ? (
        <>led the team on {metric} with {figure(note.value)}</>
      ) : (
        <>is leading the team on {metric} with {figure(note.value)}</>
      );
    default:
      return null;
  }
}
