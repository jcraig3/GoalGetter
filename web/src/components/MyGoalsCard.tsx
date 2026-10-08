import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { api } from '../api';
import GoalProgress, { type GoalLike } from './GoalProgress';

interface Goal extends GoalLike {
  id: number;
  name: string | null;
  subject_type: string;
  subject_name: string;
  period_label: string;
}

/**
 * The signed-in person's goals, and their team's.
 *
 * `?mine=true` rather than filtering client-side: an agent must not receive
 * their colleagues' targets at all, so the narrowing belongs in the query.
 */
export default function MyGoalsCard({ onEmpty }: { onEmpty?: (empty: boolean) => void } = {}) {
  const [goals, setGoals] = useState<Goal[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Told to Home, which folds three empty cards into one line (8.2).
  useEffect(() => {
    if (goals !== null) onEmpty?.(goals.length === 0);
  }, [goals, onEmpty]);

  useEffect(() => {
    // `trend=true` costs one extra query per goal, so it is asked for
    // only where a sparkline is actually drawn.
    api<Goal[]>('/api/goals?mine=true&trend=true')
      .then(setGoals)
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load goals.'));
  }, []);

  return (
    <section className="rounded-lg border border-edge bg-surface p-6">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-h3 text-content">Your goals</h2>
        <Link to="/goals" className="text-sm text-brand hover:underline">
          All goals
        </Link>
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
        <p className="mt-4 text-sm text-content-muted">
          Nothing set for you yet. Targets your manager sets for you or your team
          appear here.
        </p>
      )}

      {goals && goals.length > 0 && (
        <ul className="mt-5 space-y-5">
          {/* Capped at four: this is the dashboard's summary of them, and the
              Goals page is one click away for the rest. */}
          {goals.slice(0, 4).map((goal) => (
            <li key={goal.id}>
              <p className="mb-1 text-sm text-content">
                <Link to={`/goals/${goal.id}`} className="hover:text-brand">
                  {goal.name || goal.metric_name}
                </Link>
                <span className="text-content-subtle">
                  {' · '}
                  {goal.subject_type === 'team' ? goal.subject_name : goal.period_label}
                </span>
              </p>
              <GoalProgress goal={goal} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
