import { Link } from 'react-router-dom';
import { daysAgo } from '../time';

export interface Health {
  /** Each source and its newest row (P3-3). */
  sources?: { name: string; newest: string | null; read_once: boolean; quiet: boolean }[];
  last_fact_at: string | null;
  facts_last_7_days: number;
  active_people: number;
  people_without_a_team: number;
  metrics_without_data: number;
  displays_offline: number;
  /** Sources whose last run failed outright. */
  sources_failing: number;
  /** Sources that were due to run and did not — usually the scheduler, not them. */
  sources_overdue: number;
  /** The most recent failure's own words, so the card can say what broke. */
  source_error: string | null;
}

/** How long ago, in words somebody can act on. */
function freshness(iso: string | null): { text: string; tone: string } {
  if (!iso) return { text: 'no data recorded yet', tone: 'text-warning' };

  const hours = (Date.now() - new Date(iso).getTime()) / 3_600_000;
  if (hours < 24) return { text: 'today', tone: 'text-success' };
  if (hours < 48) return { text: 'yesterday', tone: 'text-content-muted' };

  // Rounded down, like everywhere else — see `time.ts`.
  const days = daysAgo(new Date(iso));
  // Three days of silence is the shape of a sync that has stopped, which is
  // exactly the failure this panel exists to make visible.
  return {
    text: `${days} days ago`,
    tone: days >= 3 ? 'text-warning' : 'text-content-muted',
  };
}

/**
 * Is the data underneath everything else still arriving?
 *
 * A leaderboard showing three-day-old figures because a sync has been failing
 * looks exactly like one showing current figures. Silently stale data is the
 * fastest way to lose trust in the tool, so the staleness needs to be visible
 * somewhere an admin actually looks.
 */
export default function HealthCard({ health }: { health: Health }) {
  const fresh = freshness(health.last_fact_at);

  return (
    <section className="rounded-lg border border-edge bg-surface p-6">
      <h2 className="text-h3 text-content">System health</h2>
      <p className="mt-1 text-sm text-content-muted">
        Whether data is still arriving, and what is not wired up.
      </p>

      {/* **By source, in the banner's words** (P3-3): "11 days ago" with no
          source beside it was a third story next to the banner's "Thu 3 Sep". */}
      {health.sources && health.sources.length > 0 && (
        <ul className="mt-5 space-y-1 text-sm">
          {health.sources.map((s) => (
            <li key={s.name} className={s.quiet ? 'text-warning' : 'text-content-muted'}>
              <span className="text-content">{s.name}</span> —{' '}
              {s.newest === null
                ? 'nothing read yet'
                : s.read_once
                  ? `read once, newest row ${s.newest}`
                  : s.quiet
                    ? `no new rows since ${s.newest}`
                    : `newest row ${s.newest}`}
            </li>
          ))}
        </ul>
      )}

      <dl className="mt-5 grid gap-4 sm:grid-cols-2">
        {!health.sources?.length && (
          <Stat label="Data last recorded" value={fresh.text} tone={fresh.tone} />
        )}
        <Stat
          label="Recorded this week"
          value={health.facts_last_7_days.toLocaleString()}
          tone={health.facts_last_7_days === 0 ? 'text-warning' : 'text-content'}
        />
        <Stat label="Active people" value={String(health.active_people)} tone="text-content" />
        <Stat
          label="TVs offline"
          value={String(health.displays_offline)}
          tone={health.displays_offline > 0 ? 'text-warning' : 'text-content'}
          link={health.displays_offline > 0 ? '/channels' : undefined}
        />
      </dl>

      {/* **A broken sync is invisible on a leaderboard** — it looks exactly like a
          quiet week. `metrics with no data` was the closest thing here before and
          is not the same question: a metric fed by two sources still has recent
          data when one of them has been failing for a week. */}
      {(health.sources_failing > 0 || health.sources_overdue > 0) && (
        <div className="mt-5 border-t border-edge pt-4 text-sm">
          {health.sources_failing > 0 && (
            <p className="text-content-muted">
              <Link to="/integrations" className="text-danger hover:underline">
                {health.sources_failing}{' '}
                {health.sources_failing === 1 ? 'source is' : 'sources are'} failing
              </Link>
              {health.source_error && (
                // The provider's own words. "Something went wrong" sends somebody
                // hunting; "the credential was refused" tells them where to go.
                <> — {health.source_error}</>
              )}
            </p>
          )}
          {health.sources_overdue > 0 && (
            <p className="mt-2 text-content-muted">
              <Link to="/integrations" className="text-warning hover:underline">
                {health.sources_overdue} overdue
              </Link>{' '}
              — due to check and did not. Usually the background job rather than the
              source itself.
            </p>
          )}
        </div>
      )}

      {/* People on no team are not repeated here: the banner above says it,
          or the setup checklist while setup is unfinished (review §4). */}
      {health.metrics_without_data > 0 && (
        <ul className="mt-5 space-y-2 border-t border-edge pt-4 text-sm">
          {health.metrics_without_data > 0 && (
            <li className="text-content-muted">
              <Link to="/metrics" className="text-warning hover:underline">
                {health.metrics_without_data} metrics with no data
              </Link>{' '}
              — nothing is feeding them yet.
            </li>
          )}
        </ul>
      )}
    </section>
  );
}

function Stat({
  label,
  value,
  tone,
  link,
}: {
  label: string;
  value: string;
  tone: string;
  link?: string;
}) {
  const body = <span className={`text-xl ${tone}`}>{value}</span>;
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-content-subtle">{label}</dt>
      <dd className="mt-1">
        {link ? (
          <Link to={link} className="hover:underline">
            {body}
          </Link>
        ) : (
          body
        )}
      </dd>
    </div>
  );
}
