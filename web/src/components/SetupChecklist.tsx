import { Link } from 'react-router-dom';

export interface SetupStep {
  key: string;
  label: string;
  done: boolean;
  link: string;
  detail: string;
}

/**
 * The way from a fresh install to a working wall, for an admin.
 *
 * Home used to open on alarms — "300 people have recorded nothing", "350 on
 * no team" — with nothing saying what to do first (review §3, #4). This says
 * it, in order, and each step ticks itself from the data as the work gets done
 * anywhere in the app. Gone once everything is.
 */
export default function SetupChecklist({ steps }: { steps: SetupStep[] }) {
  const left = steps.filter((s) => !s.done).length;
  if (left === 0) return null;
  const next = steps.find((s) => !s.done);

  return (
    <section
      aria-labelledby="setup-heading"
      className="mb-6 rounded-lg border border-brand/40 bg-brand-subtle p-5"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="setup-heading" className="text-h3 text-content">
          Getting to your first wall
        </h2>
        <p className="text-sm text-content-muted">
          {steps.length - left} of {steps.length} done
        </p>
      </div>
      <ol className="mt-4 space-y-2">
        {steps.map((step, index) => (
          <li key={step.key}>
            <Link
              to={step.link}
              className={`flex items-start gap-3 rounded-md px-3 py-2 transition-colors hover:bg-surface-hover ${
                step === next ? 'bg-surface' : ''
              }`}
            >
              <span
                aria-hidden="true"
                className={`mt-0.5 grid size-5 shrink-0 place-items-center rounded-full border text-xs ${
                  step.done
                    ? 'border-success bg-success text-white'
                    : 'border-edge text-content-muted'
                }`}
              >
                {step.done ? '✓' : index + 1}
              </span>
              <span className="min-w-0 flex-1">
                <span className={`block text-sm ${step.done ? 'text-content-muted' : 'text-content'}`}>
                  {step.label}
                  <span className="sr-only">{step.done ? ' — done' : ' — to do'}</span>
                </span>
                <span className="block text-xs text-content-subtle">{step.detail}</span>
              </span>
              {step === next && (
                <span className="shrink-0 text-sm font-medium text-brand">Next →</span>
              )}
            </Link>
          </li>
        ))}
      </ol>
    </section>
  );
}
