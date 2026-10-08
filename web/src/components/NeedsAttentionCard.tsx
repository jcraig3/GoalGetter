import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { api } from '../api';
import MetricValue from './MetricValue';
import { StatusBadge } from './GoalProgress';

interface Goal {
  id: number;
  name: string | null;
  metric_name: string;
  unit: string;
  decimal_places: number;
  subject_name: string;
  period_label: string;
  current_value: string;
  target_value: string;
  percent: number;
  expected_percent: number | null;
  status: string;
}

/**
 * Goals behind pace or already missed.
 *
 * Filtered by the server (`?needs_attention=true`), not in the browser: an
 * agent must not receive their colleagues' goals in order to hide them, and
 * "behind" depends on today's date against a period resolved in the
 * organization's timezone — which the client would have to reimplement.
 */
export default function NeedsAttentionCard() {
  const [goals, setGoals] = useState<Goal[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Goal[]>('/api/goals?needs_attention=true')
      .then(setGoals)
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load.'));
  }, []);

  return (
    <section className="rounded-lg border border-edge bg-surface p-6">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-h3 text-content">Needs attention</h2>
        {goals && goals.length > 0 && (
          <span className="rounded-full bg-warning/15 px-2 py-0.5 text-xs text-warning">
            {goals.length}
          </span>
        )}
      </div>

      {error && (
        <p role="alert" className="mt-4 text-sm text-danger">
          {error}
        </p>
      )}

      {goals === null && !error && (
        <p className="mt-4 text-sm text-content-muted">Loading…</p>
      )}

      {goals?.length === 0 && (
        // Not an empty state to apologise for — it is the good outcome, and
        // saying so is more useful than a blank panel.
        <p className="mt-4 text-sm text-content-muted">
          Nothing is behind right now.
        </p>
      )}

      {goals && goals.length > 0 && (
        <>
          <ul className="mt-4 divide-y divide-edge">
            {goals.slice(0, 5).map((goal) => (
              <li key={goal.id} className="flex items-center gap-3 py-2.5 text-sm">
                <div className="min-w-0 flex-1">
                  {/* To the goal: this list is a list of things to do something
                      about, and the doing starts on its page (review §7). */}
                  <Link
                    to={`/goals/${goal.id}`}
                    className="block truncate text-content hover:text-brand hover:underline"
                  >
                    {goal.name || goal.metric_name}
                  </Link>
                  <p className="truncate text-xs text-content-subtle">
                    {goal.subject_name} · {goal.period_label}
                  </p>
                </div>
                <span className="shrink-0 text-right text-xs text-content-muted">
                  <MetricValue value={goal.current_value} format={goal} bare />
                  {' / '}
                  <MetricValue value={goal.target_value} format={goal} />
                  {goal.status === 'missed' ? (
                    // Over: how far short, not "100% behind pace" (Q2-13).
                    Number(goal.target_value) > Number(goal.current_value) && (
                      <span className="block text-content-subtle">
                        missed by{' '}
                        <MetricValue
                          value={String(Number(goal.target_value) - Number(goal.current_value))}
                          format={goal}
                        />
                      </span>
                    )
                  ) : goal.expected_percent !== null && (
                    // The gap is the actionable number, not the raw percentage.
                    <span className="block text-content-subtle">
                      {/* Not "points": that word belongs to the points
                          economy now, and this is a share of the target. */}
                      {Math.round(goal.expected_percent - goal.percent)}% behind pace
                    </span>
                  )}
                </span>
                <StatusBadge status={goal.status} />
              </li>
            ))}
          </ul>
          {goals.length > 5 && (
            <Link to="/goals" className="mt-3 inline-block text-sm text-brand hover:underline">
              {goals.length - 5} more
            </Link>
          )}
        </>
      )}
    </section>
  );
}
