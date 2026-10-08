import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';

import { api } from '../api';
import { useAuth } from '../auth';
import { toast } from '../toast';
import { GoalForm, type Goal as EditableGoal } from './Goals';
import DataCurrency from '../components/DataCurrency';
import EmptyState from '../components/EmptyState';
import GoalProgress, { StatusBadge, type GoalLike } from '../components/GoalProgress';
import MetricValue from '../components/MetricValue';
import PageHeader from '../components/PageHeader';
import ShowOnTv from '../components/ShowOnTv';
import { RepeatIcon } from '../components/icons';
import Loading from '../components/Loading';
import Breadcrumb from '../components/Breadcrumb';
import { repeatTag } from './goalWords';
import { archiveQuestion } from '../wallUse';
import { ask } from '../confirm';

interface Goal extends GoalLike {
  id: number;
  name: string | null;
  metric_id: number;
  subject_type: string;
  subject_name: string;
  period_label: string;
  period_type: string;
  archived: boolean;
  recurring: boolean;
  spawned_from_goal_id: number | null;
}

interface Contributor {
  user_id: number;
  full_name: string;
  value: string;
  rank: number;
}

/** "No earlier months". */
const PERIOD_WORD: Record<string, string> = {
  day: 'days',
  week: 'weeks',
  month: 'months',
  quarter: 'quarters',
  year: 'years',
};

interface PastPeriod {
  label: string;
  value: string;
  met_target: boolean;
}

interface Detail {
  goal: Goal;
  contributors: Contributor[];
  history: PastPeriod[];
}

/**
 * One goal, in enough depth to act on it.
 *
 * The list already answers "how far along". This page exists for the two
 * questions a card physically cannot fit:
 *
 *   who   — which people make up a team's number
 *   was the target ever realistic — which only earlier periods can say
 *
 * One request. The three answers all describe the same period, and letting the
 * client assemble them would mean three round trips that could disagree about
 * which one.
 */
export default function GoalDetail() {
  const { id } = useParams();
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const { can } = useAuth();

  const load = useCallback(() => {
    api<Detail>(`/api/goals/${id}`)
      .then(setDetail)
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load this goal.'));
  }, [id]);

  useEffect(load, [load]);

  // **On the goal's own page** (review §7). Changing a goal meant going back
  // to the list to find its card again.
  async function setArchived(archived: boolean) {
    // Wall-aware, as delete is (P3-2): asked only when a TV would lose it.
    if (archived && detail) {
      const g = detail.goal;
      const question = await archiveQuestion('goal', g.id, g.name || `${g.subject_name} — ${g.metric_name}`);
      if (question && !(await ask(question, { confirmLabel: 'Archive' }))) return;
    }
    try {
      await api(`/api/goals/${id}/${archived ? 'archive' : 'restore'}`, { method: 'POST' });
      toast(
        archived ? 'Goal archived' : 'Goal restored',
        undefined,
        archived ? { label: 'Undo', run: () => void setArchived(false) } : undefined,
      );
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not change that.');
    }
  }

  if (error) {
    return (
      <>
        <Back />
        <p role="alert" className="rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      </>
    );
  }

  if (!detail) return <Loading />;

  const { goal, contributors, history } = detail;

  return (
    <>
      <Back here={goal.name || `${goal.subject_name} — ${goal.metric_name}`} />
      <PageHeader
        // Who and what, as the breadcrumb says it — the metric alone named
        // a page that was about one person (Q2-24).
        title={goal.name || `${goal.subject_name} — ${goal.metric_name}`}
        description={`${goal.subject_name} · ${goal.period_label}${
          goal.name ? ` · ${goal.metric_name}` : ''
        }`}
        actions={
          <div className="flex items-center gap-2">
            {(goal.recurring || goal.spawned_from_goal_id !== null) && (
              <span
                className="inline-flex items-center gap-1 text-xs text-content-subtle"
                title={repeatTag(goal).title}
              >
                <RepeatIcon className="size-4" />
                {repeatTag(goal).label}
              </span>
            )}
            <StatusBadge status={goal.status} />
            {can('integrations.manage') && !goal.archived && (
              <ShowOnTv
                kind="goal"
                id={goal.id}
                name={goal.name || `${goal.subject_name} — ${goal.metric_name}`}
              />
            )}
            {can('goals.manage') && (
              <>
                {!goal.archived && (
                  <button
                    type="button"
                    onClick={() => setEditing(true)}
                    className="rounded-md border border-edge px-3 py-1.5 text-sm text-content hover:bg-surface-hover"
                  >
                    Edit
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => void setArchived(!goal.archived)}
                  className="rounded-md border border-edge px-3 py-1.5 text-sm text-content-muted hover:bg-surface-hover hover:text-content"
                >
                  {goal.archived ? 'Restore' : 'Archive'}
                </button>
              </>
            )}
          </div>
        }
      />

      {editing && (
        <GoalForm
          goal={goal as unknown as EditableGoal}
          onClose={() => setEditing(false)}
          onSaved={async () => {
            toast('Goal saved');
            setEditing(false);
            load();
          }}
        />
      )}

      {/* A goal is judged on these numbers, so whether they are current is not a
          footnote for the person being judged. */}
      <DataCurrency metricIds={[goal.metric_id]} className="mb-4" />

      {goal.archived && (
        <p className="mb-6 rounded-md border border-dashed border-edge px-3 py-2 text-sm text-content-muted">
          This goal is archived. It is kept so that "you hit 4 of 5 goals last
          quarter" can still be answered.
        </p>
      )}

      {/* Progress first and full width: it is the thing the page is named
          after, and everything below explains it. */}
      <section className="rounded-lg border border-edge bg-surface p-6">
        <GoalProgress goal={goal} />
      </section>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Contributors contributors={contributors} goal={goal} />
        <History history={history} goal={goal} />
      </div>
    </>
  );
}

function Back({ here }: { here?: string }) {
  return <Breadcrumb parent={{ to: '/goals', label: 'Goals' }} here={here} />;
}

/** Who made up a team's number. */
function Contributors({
  contributors,
  goal,
}: {
  contributors: Contributor[];
  goal: Goal;
}) {
  if (goal.subject_type !== 'team') return null;

  return (
    <section className="rounded-lg border border-edge bg-surface p-6">
      <h2 className="text-h3 text-content">Who is contributing</h2>
      <p className="mt-1 text-sm text-content-muted">
        The people behind this team's number, this period.
      </p>

      {contributors.length === 0 ? (
        <p className="mt-4 text-sm text-content-muted">
          Nothing recorded for this team yet.
        </p>
      ) : (
        <ol className="mt-4 space-y-2">
          {contributors.map((person) => (
            <li key={person.user_id} className="flex items-baseline gap-3 text-sm">
              <span className="w-6 shrink-0 tabular-nums text-content-subtle">
                {person.rank}
              </span>
              <span className="min-w-0 flex-1 truncate text-content">
                {person.full_name}
              </span>
              <MetricValue
                value={person.value}
                format={goal}
                className="shrink-0 tabular-nums text-content-muted"
              />
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

/** Earlier periods, as bars against the current target. */
function History({ history, goal }: { history: PastPeriod[]; goal: Goal }) {
  // **An empty axis said nothing** (8.2): no periods before, or periods with
  // no numbers in them, are both said in words.
  const word = PERIOD_WORD[goal.period_type] ?? 'periods';
  if (history.length === 0 || history.every((h) => !Number(h.value))) {
    return (
      <section className="rounded-lg border border-edge bg-surface p-6">
        <h2 className="text-h3 text-content">Before this</h2>
        <EmptyState
          title={goal.period_type === 'custom' ? 'No earlier periods' : `No earlier ${word}`}
          description={
            goal.period_type === 'custom'
              ? 'A custom date range has no defined period before it, so there is nothing to compare against.'
              : history.length === 0
                ? `This is its first. Earlier ${word} appear here once there are some.`
                : `Nothing was recorded in the ${word} before this one.`
          }
        />
      </section>
    );
  }

  const target = Number(goal.target_value);
  // Scaled to include the target, so a bar that clears the line is visibly
  // over it. Scaling to the tallest bar alone would put the target wherever it
  // happened to fall and make two periods look comparable when they are not.
  const ceiling = Math.max(target, ...history.map((h) => Number(h.value))) || 1;

  return (
    <section className="rounded-lg border border-edge bg-surface p-6">
      <h2 className="text-h3 text-content">Before this</h2>
      <p className="mt-1 text-sm text-content-muted">
        The same measure over earlier periods, against{' '}
        <span className="text-content">today's</span> target of{' '}
        <MetricValue value={goal.target_value} format={goal} />.
      </p>

      <div className="relative mt-6 flex h-32 items-end gap-2">
        {/* The target as one line across the whole row. Most of these periods
            had no goal at all, and a recurring goal's copies could each have
            carried a different target — so one line is the only comparison
            that stays consistent from bar to bar. */}
        <div
          aria-hidden="true"
          className="absolute inset-x-0 border-t border-dashed border-content-subtle"
          style={{ bottom: `${(target / ceiling) * 100}%` }}
        />
        {/* **A full-height column per period**, so a bar's percentage has a
            height to be a share of — inside an auto-height box every bar
            computed to nothing and the chart was an empty axis (P3-6). */}
        {history.map((period) => (
          <div key={period.label} className="flex h-full min-w-0 flex-1 items-end">
            <div
              className={`w-full rounded-t transition-[height] ${
                period.met_target ? 'bg-success' : 'bg-brand/50'
              }`}
              // A zero is a hairline, not nothing: "nothing recorded" is a
              // value, and a gap reads as missing data.
              style={{ height: `max(2px, ${(Number(period.value) / ceiling) * 100}%)` }}
              title={`${period.label}: ${period.value}`}
            />
          </div>
        ))}
      </div>

      <div className="mt-2 flex gap-2">
        {history.map((period) => (
          <p
            key={period.label}
            className="min-w-0 flex-1 truncate text-center text-xs text-content-subtle"
            title={period.label}
          >
            {/* Just enough to place it. The full label is in the tooltip, and
                six wrapped month names would be wider than the chart. */}
            {period.label.split(' ')[0]?.slice(0, 3)}
          </p>
        ))}
      </div>
    </section>
  );
}
