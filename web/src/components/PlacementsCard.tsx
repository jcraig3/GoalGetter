import { Link } from 'react-router-dom';

import MetricValue from './MetricValue';
import Sparkline, { type Trend } from './Sparkline';

export interface Placement {
  board_id: number;
  board_name: string;
  metric_name: string;
  unit: string;
  decimal_places: number;
  period_label: string;
  rank: number;
  total_entrants: number;
  value: string;
  movement: number | null;
  trend: Trend;
}

/**
 * Where the viewer stands on every board they can open.
 *
 * The one panel on the page that is about them rather than about the work —
 * and the reason a leaderboard product is worth opening in the morning.
 */
export default function PlacementsCard({ placements }: { placements: Placement[] }) {
  return (
    <section className="rounded-lg border border-edge bg-surface p-6">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-h3 text-content">Where you stand</h2>
        <Link to="/leaderboards" className="text-sm text-brand hover:underline">
          All boards
        </Link>
      </div>

      {placements.length === 0 ? (
        <p className="mt-4 text-sm text-content-muted">
          You are not on any board yet. Once data is recorded against you, your
          position appears here.
        </p>
      ) : (
        <ul className="mt-4 space-y-3">
          {placements.slice(0, 5).map((placement) => (
            <li key={placement.board_id} className="flex items-center gap-4">
              {/* The rank first and large: it is the number the panel exists
                  for, and everything else is context for it. */}
              <span
                className={`w-12 shrink-0 text-2xl font-semibold tabular-nums ${
                  placement.rank === 1
                    ? 'text-gold'
                    : placement.rank === 2
                      ? 'text-silver'
                      : placement.rank === 3
                        ? 'text-bronze'
                        : 'text-content-muted'
                }`}
              >
                {placement.rank}
              </span>

              <div className="min-w-0 flex-1">
                <Link
                  to={`/leaderboards/${placement.board_id}`}
                  className="block truncate text-sm text-content hover:text-brand"
                >
                  {placement.board_name}
                </Link>
                <p className="truncate text-xs text-content-subtle">
                  of {placement.total_entrants} · {placement.period_label}
                </p>
              </div>

              {placement.movement !== null && placement.movement !== 0 && (
                <span
                  className={`shrink-0 text-xs ${
                    placement.movement > 0 ? 'text-success' : 'text-danger'
                  }`}
                  title={`${placement.movement > 0 ? 'Up' : 'Down'} ${Math.abs(
                    placement.movement,
                  )} since last period`}
                >
                  {placement.movement > 0 ? '▲' : '▼'} {Math.abs(placement.movement)}
                </span>
              )}

              {/* Between the movement arrow and the figure, because it
                  explains both: the arrow says the direction and the number
                  says where it ended, and this is the bit in between. */}
              <div className="hidden w-20 shrink-0 sm:block">
                <Sparkline
                  trend={placement.trend}
                  label={`${placement.metric_name} over ${placement.period_label}`}
                />
              </div>

              <MetricValue
                value={placement.value}
                format={placement}
                className="shrink-0 text-sm text-content-muted"
              />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
