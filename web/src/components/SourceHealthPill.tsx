import { sourceHealth, type SourceStatus, type Tone } from '../pages/sourceWizard';

/**
 * One word on whether a source is working, with the sentence behind it.
 *
 * The word and the sentence come from the same call, so a pill saying "Working"
 * can never sit next to an explanation of a failure. `sourceWizard.sourceHealth`
 * decides; this only paints.
 */
const TONES: Record<Tone, string> = {
  good: 'bg-success/15 text-success',
  warn: 'bg-warning/15 text-warning',
  bad: 'bg-danger/15 text-danger',
  idle: 'bg-surface-hover text-content-muted',
};

export default function SourceHealthPill({
  source,
  now = new Date(),
  withDetail = false,
}: {
  source: SourceStatus;
  /** Passed in so a list of twenty sources judges them all against one moment. */
  now?: Date;
  withDetail?: boolean;
}) {
  const health = sourceHealth(source, now);

  return (
    <span className="inline-flex flex-wrap items-baseline gap-x-2">
      <span
        className={`shrink-0 rounded-full px-2 py-0.5 text-xs ${TONES[health.tone]}`}
      >
        {health.label}
      </span>
      {withDetail && (
        <span className="text-sm text-content-muted">{health.detail}</span>
      )}
    </span>
  );
}
