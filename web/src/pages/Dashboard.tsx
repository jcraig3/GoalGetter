import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { api } from '../api';
import { useAuth } from '../auth';
import { CloseIcon } from '../components/icons';
import { toast } from '../toast';
import HealthCard, { type Health } from '../components/HealthCard';
import MyCompetitionsCard from '../components/MyCompetitionsCard';
import MyGoalsCard from '../components/MyGoalsCard';
import NeedsAttentionCard from '../components/NeedsAttentionCard';
import PageHeader from '../components/PageHeader';
import PlacementsCard, { type Placement } from '../components/PlacementsCard';
import SetupChecklist, { type SetupStep } from '../components/SetupChecklist';
import TeamCard from '../components/TeamCard';

interface AttentionItem {
  kind: string;
  message: string;
  count: number;
  link: string;
}

interface DashboardData {
  role: string;
  placements: Placement[];
  attention: AttentionItem[];
  /** Banners put away until they change, or tomorrow (12.2). */
  attention_dismissed?: AttentionItem[];
  health: Health | null;
  /** Admins only. */
  setup: SetupStep[] | null;
}

/**
 * The overview, arranged by what the viewer can actually do about it.
 *
 * An agent gets motivation — where they stand, and their goals. A manager gets
 * the same plus who needs them. An admin gets both plus whether data is still
 * arriving. Showing everyone everything would produce a page that answers none
 * of those: an agent cannot act on a broken sync, and an admin hunting one does
 * not want to scroll past their own call count to find it.
 *
 * One request, composed server-side. Letting the client assemble it would mean
 * asking for things it is not entitled to and handling the 403.
 */
export default function Dashboard() {
  const { user } = useAuth();
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<DashboardData>('/api/dashboard')
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load.'));
  }, []);

  useEffect(load, [load]);

  // **"Not now" for a banner** (12.2): back when it changes, or tomorrow.
  async function putAway(item: AttentionItem) {
    // Off the page at once; the reload confirms it.
    setData((was) =>
      was && {
        ...was,
        attention: was.attention.filter((a) => a.kind !== item.kind),
        attention_dismissed: [...(was.attention_dismissed ?? []), item],
      },
    );
    try {
      await api('/api/dashboard/attention/dismiss', {
        method: 'POST',
        body: JSON.stringify({ kind: item.kind }),
      });
      toast('Put away until it changes, or tomorrow', undefined, {
        label: 'Undo',
        run: () => void bringBack(item),
      });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That did not work.');
    }
    load();
  }

  async function bringBack(item: AttentionItem) {
    await api('/api/dashboard/attention/restore', {
      method: 'POST',
      body: JSON.stringify({ kind: item.kind }),
    }).catch(() => undefined);
    load();
  }

  const firstName = user?.full_name?.split(' ')[0] ?? '';

  // "Goals behind" is in the API response, but the panel below lists the
  // actual goals with the gap on each — a banner saying "3 goals are behind"
  // directly above a card naming those three is repetition, not emphasis.
  // **While setup is unfinished, the checklist speaks instead of the alarms.**
  // "350 agents are on no team" on a deployment that has not made its teams
  // yet is a step, not a warning — and the checklist already names it.
  const settingUp = (data?.setup ?? []).some((step) => !step.done);
  const [noGoals, setNoGoals] = useState<boolean | null>(null);
  const [noContests, setNoContests] = useState<boolean | null>(null);
  const nothingPersonal =
    data !== null && data !== undefined && data.placements.length === 0 && noGoals === true && noContests === true;
  const banner = settingUp
    ? []
    : (data?.attention.filter((item) => item.kind !== 'goals_behind') ?? []);
  const putAwayBanners = settingUp
    ? []
    : (data?.attention_dismissed?.filter((item) => item.kind !== 'goals_behind') ?? []);

  return (
    <>
      <PageHeader
        title={firstName ? `Welcome back, ${firstName}` : 'Home'}
        tabTitle="Home"
        description="Where things stand today."
      />

      {error && (
        <p role="alert" className="mb-4 rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      {data?.setup && <SetupChecklist steps={data.setup} />}

      {/* Only when there is something. A permanent "nothing needs attention"
          panel trains people to stop looking at the spot warnings appear in. */}
      {banner.length > 0 && (
        <ul className="mb-6 space-y-2">
          {banner.map((item) => (
            <li key={item.kind} className="flex items-stretch rounded-md border border-warning text-sm text-warning">
              {item.link ? (
                <Link
                  to={item.link}
                  className="flex flex-1 items-center gap-3 rounded-l-md px-3 py-2 transition-colors hover:bg-warning/10"
                >
                  <span className="flex-1">{item.message}</span>
                  <span aria-hidden="true">→</span>
                </Link>
              ) : (
                // Nothing this person can do from here — said, not linked.
                <p className="flex-1 px-3 py-2">{item.message}</p>
              )}
              <button
                type="button"
                onClick={() => void putAway(item)}
                aria-label={`Not now: ${item.message}`}
                title="Put away until it changes, or until tomorrow"
                className="shrink-0 rounded-r-md border-l border-warning/40 px-2 text-warning/80 transition-colors hover:bg-warning/10 hover:text-warning"
              >
                <CloseIcon />
              </button>
            </li>
          ))}
        </ul>
      )}
      {/* Listed, not lost — one quiet line, offering them back. */}
      {putAwayBanners.length > 0 && (
        <p className="-mt-3 mb-6 text-xs text-content-subtle">
          {putAwayBanners.length === 1 ? '1 notice was' : `${putAwayBanners.length} notices were`}{' '}
          dismissed ·{' '}
          <button
            type="button"
            onClick={() => putAwayBanners.forEach((item) => void bringBack(item))}
            className="underline hover:text-content"
          >
            Show {putAwayBanners.length === 1 ? 'it' : 'them'}
          </button>
        </p>
      )}

      {/* **A manager's own team first** (6.13): the board, the goals beside
          it, who needs a nudge and who has earned a word. Nothing for anybody
          with no team to manage. */}
      <TeamCard staleAbove={banner.some((item) => item.kind === 'data_stale')} />

      {/* **Three empty cards are one line** (8.2): an admin on no board, goal
          or contest had half the first screen saying so three times. The
          cards stay mounted, hidden, so they still notice when that changes. */}
      {nothingPersonal && (
        <p className="mb-6 rounded-lg border border-edge bg-surface px-6 py-4 text-sm text-content-muted">
          Nothing personal to show yet — no numbers, goals or contests of yours this period.
        </p>
      )}
      <div className={`grid gap-6 lg:grid-cols-2 ${nothingPersonal ? 'hidden' : ''}`}>
        {data && <PlacementsCard placements={data.placements} />}
        <MyGoalsCard onEmpty={setNoGoals} />
      </div>

      {/* Competitions sit directly under the goals, above the boards: a contest
          has a deadline, and something with a deadline outranks something
          without one. */}
      <div className={`grid gap-6 lg:grid-cols-2 ${nothingPersonal ? '' : 'mt-6'}`}>
        <div className={nothingPersonal ? 'hidden' : ''}>
          <MyCompetitionsCard onEmpty={setNoContests} />
        </div>
        <NeedsAttentionCard />
      </div>

      {/* The Standings card that sat here was a check on the numbers against
          the database, by its own description — not something anybody came to
          Home for (QA-40). The boards themselves are a click away. */}

      {/* Admin only, and last: operations belong below the things everyone
          else on the page came for. */}
      {data?.health && (
        <div className="mt-6">
          <HealthCard health={data.health} />
        </div>
      )}
    </>
  );
}
