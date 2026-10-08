import { useEffect, useState } from 'react';

import { api } from '../api';
import MetricValue from './MetricValue';

interface PastPeriod {
  label: string;
  value: string;
  start: string;
}

interface Preview {
  subject_name: string;
  metric_name: string;
  unit: string;
  decimal_places: number;
  direction: string;
  history: PastPeriod[];
  average: string | null;
  best: string | null;
  suggested_target: string | null;
}

/**
 * What this subject has actually done, shown while a target is being chosen.
 *
 * A target set with no reference to history is a guess, and a guess is either
 * trivially met or plainly impossible — both of which stop anyone taking the
 * number seriously.
 */
export default function GoalPreview({
  metricId,
  subjectType,
  subjectId,
  periodType,
  target,
  onUseSuggestion,
}: {
  metricId: string;
  subjectType: 'user' | 'team' | 'organization';
  subjectId: string;
  periodType: string;
  target: string;
  onUseSuggestion: (value: string) => void;
}) {
  const [preview, setPreview] = useState<Preview | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    // An organization goal names nobody, so waiting for a subject id would
    // mean the history panel never appears for the one goal most worth
    // arguing a number for.
    if (!metricId) return;
    if (subjectType !== 'organization' && !subjectId) return;

    // A custom range has no previous range to compare against, so the endpoint
    // refuses it — asking would be a guaranteed 422.
    if (periodType === 'custom') {
      setPreview(null);
      return;
    }

    // Guards against an out-of-order response overwriting a newer one when
    // someone changes the metric twice quickly.
    let current = true;
    setLoading(true);

    api<Preview>('/api/goals/preview', {
      method: 'POST',
      body: JSON.stringify({
        metric_id: Number(metricId),
        subject_type: subjectType,
        subject_id:
          subjectType === 'organization' ? null : Number(subjectId),
        period_type: periodType,
      }),
    })
      .then((result) => current && setPreview(result))
      // Silent: this is an aid, not the task. A failed preview must not stop
      // someone setting a goal.
      .catch(() => current && setPreview(null))
      .finally(() => current && setLoading(false));

    return () => {
      current = false;
    };
  }, [metricId, subjectType, subjectId, periodType]);

  if (loading && !preview) {
    return <p className="text-xs text-content-subtle">Checking recent history…</p>;
  }
  if (!preview) return null;

  const values = preview.history.map((h) => Number(h.value));
  const peak = Math.max(...values, 1);
  const measured = values.filter((v) => v !== 0);

  if (measured.length === 0) {
    return (
      // Said rather than hidden: "no history" is itself the useful answer when
      // someone is wondering why there is no suggestion.
      <p className="rounded-md border border-edge bg-bg px-3 py-2 text-xs text-content-muted">
        No recorded history for {preview.subject_name} on {preview.metric_name}
        {' '}yet, so there is nothing to base a target on.
      </p>
    );
  }

  return (
    <div className="rounded-md border border-edge bg-bg p-3">
      <p className="text-xs text-content-muted">
        {preview.subject_name} · last {preview.history.length} periods
      </p>

      {/* Bars rather than a chart library: six values with no axes, tooltips,
          or interaction to speak of. A charting dependency would be ~60KB to
          draw six rectangles. */}
      <div className="mt-2 flex items-end gap-1" style={{ height: '2.5rem' }}>
        {preview.history.map((period) => {
          const value = Number(period.value);
          return (
            <div
              key={period.start}
              title={`${period.label}: ${period.value}`}
              className="flex-1 rounded-sm bg-brand/40"
              style={{
                // A floor of 2px so an empty period is visibly empty rather
                // than absent — a gap in the row reads as a rendering fault.
                height: `${Math.max((value / peak) * 100, 4)}%`,
                opacity: value === 0 ? 0.3 : 1,
              }}
            />
          );
        })}
      </div>

      <div className="mt-2 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-xs text-content-muted">
        <span>
          average{' '}
          <MetricValue
            value={preview.average ?? '0'}
            format={preview}
            className="text-content"
          />
        </span>
        <span>
          best{' '}
          <MetricValue
            value={preview.best ?? '0'}
            format={preview}
            className="text-content"
          />
        </span>
        {preview.suggested_target && (
          <button
            type="button"
            onClick={() => onUseSuggestion(String(Number(preview.suggested_target)))}
            className="ml-auto rounded-md border border-edge px-2 py-1 text-xs text-content-muted transition-colors hover:bg-surface-hover hover:text-content"
          >
            Use{' '}
            <MetricValue value={preview.suggested_target} format={preview} />
          </button>
        )}
      </div>

      <Assessment preview={preview} target={target} />
    </div>
  );
}

/**
 * Whether the typed target is worth setting.
 *
 * Phrased as an observation, never a refusal — a stretch target above anything
 * previously achieved is a legitimate thing to set on purpose, and so is an
 * easy one for someone returning from leave.
 */
function Assessment({ preview, target }: { preview: Preview; target: string }) {
  const value = Number(target);
  if (!target || !Number.isFinite(value) || value <= 0) return null;

  const average = Number(preview.average);
  const best = Number(preview.best);
  const lowerIsBetter = preview.direction === 'lower_is_better';

  const tooEasy = lowerIsBetter ? value >= average : value <= average;
  const beyondBest = lowerIsBetter ? value < best : value > best;

  if (tooEasy) {
    return (
      <p className="mt-2 text-xs text-warning">
        At or {lowerIsBetter ? 'above' : 'below'} the recent average — most
        periods would already have met this.
      </p>
    );
  }
  if (beyondBest) {
    return (
      <p className="mt-2 text-xs text-warning">
        Beyond the best of the last {preview.history.length} periods. Fine as a
        stretch, worth a second look otherwise.
      </p>
    );
  }
  return (
    <p className="mt-2 text-xs text-success">
      Between the recent average and the best period.
    </p>
  );
}
