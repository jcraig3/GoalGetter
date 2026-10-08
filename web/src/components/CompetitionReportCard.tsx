import { useEffect, useState } from 'react';

import { api } from '../api';
import MetricValue from './MetricValue';
import {
  TONE_TEXT,
  type CompetitionReport,
  type Run,
  basisLabel,
  deltaLabel,
} from '../pages/reportingCopy';
import Loading from './Loading';

/**
 * One contest, read against the settled contests before it.
 *
 * **The bars are past results; the line is this one's forecast.** Nothing
 * stores what an earlier contest was predicted to reach part-way through, and
 * inventing that retrospectively would be drawing a number nobody ever saw. So
 * the honest comparison is this run's prediction against what past runs
 * actually finished at, and the card says which is which rather than leaving
 * a reader to assume.
 */
export default function CompetitionReportCard({
  competitionId,
  heading,
}: {
  competitionId: number;
  /** Instead of the contest's name, where the page is already titled with it. */
  heading?: string;
}) {
  const [report, setReport] = useState<CompetitionReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setReport(null);
    setError(null);
    api<CompetitionReport>(`/api/reporting/competitions/${competitionId}`)
      .then(setReport)
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load.'));
  }, [competitionId]);

  if (error) return <LoadError message={error} />;
  if (!report) return <Loading />;

  const format = {
    unit: report.unit,
    decimal_places: report.decimal_places,
    unit_label: report.unit_label,
  };
  const comparisons = [
    { label: 'vs previous', delta: report.vs_previous },
    { label: 'vs first', delta: report.vs_first },
    { label: 'vs best ever', delta: report.vs_high },
  ]
    .map((row) => ({ ...row, said: deltaLabel(row.delta, report) }))
    .filter((row) => row.said !== null);

  return (
    <section className="rounded-lg border border-edge bg-surface p-6">
      <h2 className="text-h3 text-content">{heading ?? report.name}</h2>
      <p className="mt-1 text-sm text-content-muted">
        {report.metric_name} · {report.elapsed_percent}% of the window gone
      </p>

      <div className="mt-5 grid gap-5 sm:grid-cols-2">
        <div>
          <p className="text-sm text-content-muted">
            {report.leader_name ? `Leading · ${report.leader_name}` : 'Leading'}
          </p>
          <p className="mt-0.5 text-h2 tabular-nums text-content">
            {report.leader_value === null ? (
              <span className="text-h3 text-content-muted">No scores yet</span>
            ) : (
              <MetricValue value={report.leader_value} format={format} />
            )}
          </p>
        </div>

        <div>
          <p className="text-sm text-content-muted">{basisLabel(report)}</p>
          <p className="mt-0.5 text-h2 tabular-nums text-content">
            {report.basis === null ? (
              report.too_early ? (
                <span className="text-content-muted">Too early to call</span>
              ) : (
                '—'
              )
            ) : (
              <MetricValue value={report.basis} format={format} />
            )}
          </p>
        </div>
      </div>

      {comparisons.length > 0 && (
        <dl className="mt-5 flex flex-wrap gap-x-8 gap-y-3 text-sm">
          {comparisons.map((row) => (
            <div key={row.label}>
              <dt className="text-content-muted">{row.label}</dt>
              <dd className={`mt-0.5 tabular-nums ${TONE_TEXT[row.said!.tone]}`}>
                {row.said!.text}
              </dd>
            </div>
          ))}
        </dl>
      )}

      {report.runs.length > 0 ? (
        <div className="mt-6">
          <h3 className="text-sm font-medium text-content">Comparable contests</h3>
          <p className="mt-1 text-xs text-content-muted">
            Settled contests on the same metric, oldest first. Each is named,
            so it is clear what is being compared.
          </p>
          <ul className="mt-3 space-y-2">
            {report.runs.map((run) => (
              <RunRow
                key={run.competition_id}
                run={run}
                format={format}
                best={run.value === report.all_time_high}
              />
            ))}
          </ul>
        </div>
      ) : (
        <p className="mt-6 text-sm text-content-muted">
          Nothing to compare it against yet. A contest on the same metric shows
          up here once it has been settled.
        </p>
      )}
    </section>
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

function RunRow({
  run,
  format,
  best,
}: {
  run: Run;
  format: { unit: string; decimal_places: number };
  best: boolean;
}) {
  return (
    <li className="flex flex-wrap items-baseline justify-between gap-x-4 text-sm">
      <span className="text-content">
        {run.name}
        <span className="text-content-muted"> · {run.winner_name}</span>
        {best && <span className="ml-2 text-xs text-success">best</span>}
      </span>
      <span className="tabular-nums text-content-muted">
        <MetricValue value={run.value} format={format} />
      </span>
    </li>
  );
}
