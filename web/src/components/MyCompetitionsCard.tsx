import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { api } from '../api';
import {
  phaseOf,
  remaining,
  statusLine,
  tickInterval,
  type Phase,
} from '../pages/competitionClock';
import type { Competition } from '../pages/Competitions';

/**
 * Contests the signed-in person is competing in.
 *
 * On the dashboard because a competition has a **deadline**, and the whole point
 * of one is the urgency. Having to navigate to another page to find out how long
 * is left is the wrong way round — a goal can wait to be looked up, a contest
 * ending on Friday cannot.
 *
 * `?mine=true` rather than filtering here: the narrowing is a scope decision and
 * belongs in the query, the same as `MyGoalsCard`.
 */
export default function MyCompetitionsCard({
  onEmpty,
}: { onEmpty?: (empty: boolean) => void } = {}) {
  const [competitions, setCompetitions] = useState<Competition[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    api<Competition[]>('/api/competitions?mine=true')
      .then(setCompetitions)
      .catch((e) =>
        setError(e instanceof Error ? e.message : 'Could not load competitions.'),
      );
  }, []);

  // Anything a person is still competing in, or waiting on the result of. A
  // settled contest from March is history and belongs on the Competitions page.
  const live = (competitions ?? []).filter((competition) =>
    (['upcoming', 'running', 'provisional'] as Phase[]).includes(phaseOf(competition)),
  );

  // Told to Home, which folds three empty cards into one line (8.2).
  const empty = competitions === null ? null : live.length === 0;
  useEffect(() => {
    if (empty !== null) onEmpty?.(empty);
  }, [empty, onEmpty]);

  // Tick at the rate the nearest deadline deserves — per second in the last hour,
  // every ten minutes for something a week out.
  const soonest = live.reduce((best, competition) => {
    const phase = phaseOf(competition);
    const at =
      phase === 'upcoming'
        ? competition.starts_at
        : phase === 'provisional'
          ? competition.settles_at
          : competition.ends_at;
    return Math.min(best, remaining(at, now));
  }, Number.POSITIVE_INFINITY);
  const interval = tickInterval(Number.isFinite(soonest) ? soonest : 0);

  useEffect(() => {
    if (live.length === 0) return;
    const timer = setInterval(() => setNow(new Date()), interval);
    return () => clearInterval(timer);
  }, [interval, live.length]);

  return (
    <section className="rounded-lg border border-edge bg-surface p-6">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-h3 text-content">Your competitions</h2>
        <Link to="/competitions" className="text-sm text-brand hover:underline">
          All competitions
        </Link>
      </div>

      {error && (
        <p role="alert" className="mt-4 text-sm text-danger">
          {error}
        </p>
      )}

      {competitions === null && !error && (
        <p className="mt-4 text-sm text-content-muted">Loading…</p>
      )}

      {competitions !== null && live.length === 0 && (
        <p className="mt-4 text-sm text-content-muted">
          You are not in a contest right now. Ones you are entered in appear here
          with a countdown.
        </p>
      )}

      {live.length > 0 && (
        <ul className="mt-5 space-y-4">
          {/* Capped at three. This is the summary; the page is one click away. */}
          {live.slice(0, 3).map((competition) => (
            <li key={competition.id}>
              <p className="text-sm text-content">
                <Link
                  to={`/competitions/${competition.id}`}
                  className="hover:text-brand"
                >
                  {competition.name}
                </Link>
                <span className="text-content-subtle">
                  {' · '}
                  {competition.metric_name}
                </span>
              </p>
              <p
                className={`mt-0.5 text-sm ${
                  phaseOf(competition) === 'provisional'
                    ? 'text-warning'
                    : 'text-content-muted'
                }`}
              >
                {statusLine(competition, now)}
              </p>
              {competition.prize && (
                <p className="mt-0.5 truncate text-xs text-content-subtle">
                  {competition.prize}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
