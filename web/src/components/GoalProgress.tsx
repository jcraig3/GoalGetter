import MetricValue, { type MetricFormat } from './MetricValue';
import Sparkline, { type Trend } from './Sparkline';

export interface GoalLike extends MetricFormat {
  metric_name: string;
  direction: string;
  target_value: string;
  current_value: string;
  percent: number;
  attained: boolean;
  elapsed_percent: number;
  expected_percent: number | null;
  projected_value: string | null;
  status: string;
  //: Only when the caller asked for it. See `?trend=true` on /api/goals.
  trend?: Trend | null;
  /** Levels past the target, and whether each is reached this period. */
  stretch?: StretchLevel[];
  /** When the period closes. Optional so a caller without it still draws. */
  period_end?: string;
}

/**
 * Time left and what it takes, in words: "3 days left · needs 74,600 more".
 *
 * Replaces "95.5% of the period gone", which made the reader do the sum the
 * screen could have done (review §7). Calendar days, because that is how a
 * person counts down to the end of the month.
 */
export function timeLeft(goal: GoalLike, now: Date = new Date()): string | null {
  if (!goal.period_end) return null;
  const ms = new Date(goal.period_end).getTime() - now.getTime();
  if (ms <= 0) return 'Period over';
  const days = Math.ceil(ms / 86_400_000);
  return days <= 1 ? 'Last day' : `${days} days left`;
}

function isOver(goal: GoalLike, now: Date = new Date()): boolean {
  return Boolean(goal.period_end) && new Date(goal.period_end!).getTime() <= now.getTime();
}

/**
 * **How a finished period ended**, rather than its pace (Q2-13): "Finished at
 * $0 · missed by $250,000". Null while it is still running.
 */
export function finishedLine(goal: GoalLike, now: Date = new Date()) {
  if (!isOver(goal, now)) return null;
  const short = Number(goal.target_value) - Number(goal.current_value);
  const missedBy =
    !goal.attained && goal.direction !== 'lower_is_better' && Number.isFinite(short) && short > 0;
  return (
    <span>
      Finished at <MetricValue value={goal.current_value} format={goal} />
      {missedBy && (
        <>
          {' · missed by '}
          <MetricValue value={String(short)} format={goal} />
        </>
      )}
    </span>
  );
}

/** How much more reaches the target, or null when that is not the question. */
export function needsMore(goal: GoalLike): string | null {
  if (goal.attained || goal.direction === 'lower_is_better') return null;
  if (goal.period_end && new Date(goal.period_end).getTime() <= Date.now()) return null;
  const short = Number(goal.target_value) - Number(goal.current_value);
  return Number.isFinite(short) && short > 0 ? String(short) : null;
}

export interface StretchLevel {
  level: number;
  label: string;
  value: string;
  reached: boolean;
}

interface StatusStyle {
  label: string;
  tone: string;
}

/** Falls back to this for a status the server adds before the client knows it,
 *  so a new value renders neutrally rather than as an empty badge. */
const UNKNOWN: StatusStyle = {
  label: 'On track',
  tone: 'bg-surface-raised text-content-muted',
};

/** Wording and colour per status. Data, not a chain of ternaries in the JSX. */
const STATUS: Record<string, StatusStyle> = {
  hit: { label: 'Hit', tone: 'bg-success/15 text-success' },
  ahead: { label: 'Ahead', tone: 'bg-success/15 text-success' },
  on_track: { label: 'On track', tone: 'bg-surface-raised text-content-muted' },
  behind: { label: 'Behind', tone: 'bg-warning/15 text-warning' },
  missed: { label: 'Missed', tone: 'bg-danger/15 text-danger' },
  not_started: { label: 'Not started', tone: 'bg-surface-raised text-content-subtle' },
};

export function StatusBadge({ status }: { status: string }) {
  const { label, tone } = STATUS[status] ?? UNKNOWN;
  return <span className={`rounded-full px-2 py-0.5 text-xs ${tone}`}>{label}</span>;
}

/**
 * A goal's progress bar, its two numbers, and where it should be by now.
 *
 * The bar is clamped to 100% wide; the percentage beside it is not. Beating a
 * target is the point of having one, so "150%" has to be sayable — but a bar
 * rendering at 150% of its container breaks the layout it sits in.
 */
export default function GoalProgress({
  goal,
  showStatus = true,
}: {
  goal: GoalLike;
  /** Off where the card already shows the status above — once is enough (QA-20). */
  showStatus?: boolean;
}) {
  const width = Math.min(goal.percent, 100);
  const lowerIsBetter = goal.direction === 'lower_is_better';
  // Never at the very edges: a marker at 0% or 100% sits half outside the bar
  // and reads as a rendering fault rather than a position.
  const marker =
    goal.expected_percent === null
      ? null
      : Math.min(Math.max(goal.expected_percent, 1), 99);

  return (
    <div>
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className="min-w-0 truncate text-content">
          <MetricValue value={goal.current_value} format={goal} bare />
          <span className="text-content-muted">
            {' '}
            {lowerIsBetter ? 'against a cap of' : 'of'}{' '}
          </span>
          <MetricValue value={goal.target_value} format={goal} />
        </span>
        <span
          className={`shrink-0 tabular-nums ${
            goal.attained ? 'text-success' : 'text-content-muted'
          }`}
        >
          {goal.percent}%
        </span>
      </div>

      <div
        className="relative mt-2 h-2 overflow-hidden rounded-full bg-surface-raised"
        role="progressbar"
        aria-valuenow={Math.round(goal.percent)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${goal.metric_name} progress`}
      >
        <div
          className={`h-full rounded-full transition-[width] duration-500 ${
            goal.attained ? 'bg-success' : 'bg-brand'
          }`}
          style={{ width: `${width}%` }}
        />
        {marker !== null && (
          // Where the bar should have reached by now. A bar alone cannot
          // distinguish "40% on the 3rd" from "40% on the 28th", and those are
          // opposite situations.
          <span
            aria-hidden="true"
            title={`Expected by today: ${goal.expected_percent}%`}
            className="absolute inset-y-0 w-0.5 bg-content-subtle"
            style={{ left: `${marker}%` }}
          />
        )}
      </div>

      {goal.trend && (
        // Under the bar rather than beside it. The bar says how far along,
        // which is one number; this says how they got there, which the bar
        // physically cannot show — a goal at 60% reached steadily and one
        // reached in a single day on the 2nd look identical above and
        // completely different here.
        //
        // The dashed rule is the target, so "will I make it" is a question
        // about whether the line is heading for it rather than arithmetic.
        <div className="mt-3">
          <Sparkline
            trend={goal.trend}
            reference={goal.trend.cumulative ? Number(goal.target_value) : undefined}
            label={`${goal.metric_name} over the period, against a target of ${goal.target_value}`}
          />
        </div>
      )}

      {/* Past the end of the bar, so not on it: the bar is the target, and a
          level is a further line beyond it. */}
      {goal.stretch && goal.stretch.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-1.5" aria-label="Stretch levels">
          {goal.stretch.map((level) => (
            <li
              key={level.level}
              className={`rounded-full px-2 py-0.5 text-xs ${
                level.reached ? 'bg-success/15 text-success' : 'bg-surface-raised text-content-muted'
              }`}
            >
              {level.reached && <span aria-hidden>✓ </span>}
              {level.label} · <MetricValue value={level.value} format={goal} />
              {level.reached && <span className="sr-only"> (reached)</span>}
            </li>
          ))}
        </ul>
      )}

      <p className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-content-subtle">
        {showStatus && <StatusBadge status={goal.status} />}
        {finishedLine(goal) ?? (
          <span>{timeLeft(goal) ?? `${goal.elapsed_percent}% of the period gone`}</span>
        )}
        {needsMore(goal) && (
          <span>
            · needs <MetricValue value={needsMore(goal)!} format={goal} /> more
          </span>
        )}
        {goal.projected_value !== null && !goal.attained && !isOver(goal) && (
          <span>
            · on pace for <MetricValue value={goal.projected_value} format={goal} />
          </span>
        )}
        {lowerIsBetter && <span>· lower is better</span>}
        {/* The line on the bar, named (8.2): it had no label or legend. */}
        {marker !== null && !goal.attained && !isOver(goal) && (
          <span className="inline-flex items-center gap-1">
            · <span aria-hidden="true" className="inline-block h-2.5 w-0.5 bg-content-subtle" /> expected by today
          </span>
        )}
        {goal.expected_percent === null && (
          // Said plainly rather than leaving a bar with no marker looking
          // unfinished. An average has no honest "should be here by now".
          <span>· averages are not paced</span>
        )}
      </p>
    </div>
  );
}
