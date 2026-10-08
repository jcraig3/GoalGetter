import { dayMonth } from '../time';
import { useCallback, useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { api } from '../api';
import { Can, useAuth } from '../auth';
import { useRefreshNotifications } from '../notifications';
import { toast } from '../toast';
import Avatar from '../components/Avatar';
import EmptyState from '../components/EmptyState';
import PageHeader from '../components/PageHeader';
import { Tab } from '../components/Tabs';
import PointValues from '../components/PointValues';
import BadgeAdmin from '../components/BadgeAdmin';
import CosmeticAdmin from '../components/CosmeticAdmin';
import PrizeHandover from '../components/PrizeHandover';
import PrizeWheel from '../components/PrizeWheel';
import Shop from '../components/Shop';
import WheelAdmin from '../components/WheelAdmin';
import BadgeShelf from '../components/BadgeShelf';
import GiveBadge from '../components/GiveBadge';
import SeasonAdmin from '../components/SeasonAdmin';
import TierLadder from '../components/TierLadder';
import {
  type Award,
  type Season,
  type Standing,
  elapsedPercent,
  formatPoints,
  gapToNext,
  labelFor,
  ordinal,
  seasonWindow,
  signed,
  timeLeftLabel,
  toNextLabel,
} from './pointsCopy';
import Loading from '../components/Loading';
import PersonLink from '../components/PersonLink';

interface Table {
  season: Season | null;
  standings: Standing[];
}

interface Me {
  season: Season | null;
  points: number;
  rank: number | null;
  lifetime: number;
  statement: Award[];
  tier: string | null;
  next_tier: string | null;
  to_next_tier: number | null;
  /** What can be spent — a different number from `points` on purpose. */
  wallet: number;
  ring: string | null;
  title: string | null;
}

type View =
  | 'table'
  | 'spend'
  | 'seasons'
  | 'tiers'
  | 'badges'
  | 'cosmetics'
  | 'wheel'
  | 'values';

/**
 * The points economy.
 *
 * **The season clock is not decoration.** An account this product was measured
 * against had its top dozen reps sitting at 165K–178K against a 100K top tier,
 * with lifetime points equal to reward points because nothing was ever spent:
 * the number went up forever and had stopped meaning anything. Every screen
 * here is built to keep that from happening — the season name and what is left
 * of it sit above the table, and the number people are ranked on is this
 * season's, never the lifetime one.
 */
export default function Points({ setup = false }: { setup?: boolean }) {
  // **Two pages from one component.** Somebody checking their own balance
  // had eight tabs to read past, six of them settings they could not change
  // (review §7). The player's page is `/points`; the economy's settings are
  // `/points/setup`, for admins.
  const [view, setView] = useState<View>(setup ? 'seasons' : 'table');
  // `/points/setup?tab=badges` lands on its tab — the "Give a badge" link
  // with no badges set up, and the palette's badges (7.9).
  const [params] = useSearchParams();
  const asked = params.get('tab');
  useEffect(() => {
    if (setup && asked === 'badges') setView('badges');
  }, [setup, asked]);
  const [giving, setGiving] = useState(false);
  // Bumped after a badge is given, so the shelf below re-reads without
  // the whole page reloading.
  const [given, setGiven] = useState(0);
  const refreshBell = useRefreshNotifications();

  return (
    <>
      <PageHeader
        title={setup ? 'Points setup' : 'Points'}
        description={
          setup
            ? 'Seasons, tiers, badges, what can be bought, the wheel, and what everything is worth.'
            : 'Earned this season, and what you can spend it on.'
        }
        actions={
          // `recognition.send`, not an admin capability: a badge pinned on
          // by hand is recognition — the durable kind — and belongs with the
          // people allowed to recognise. See `GiveBadge`.
          <Can do="recognition.send">
            <button
              type="button"
              onClick={() => setGiving(true)}
              className="rounded-md border border-edge px-4 py-2 text-sm text-content hover:border-brand"
            >
              Give a badge
            </button>
          </Can>
        }
      />

      <div className="mb-6 flex flex-wrap items-center gap-2">
        {!setup && (
          <>
            <Tab active={view === 'table'} onClick={() => setView('table')}>
              This season
            </Tab>
            <Tab active={view === 'spend'} onClick={() => setView('spend')}>
              Spend
            </Tab>
            <Can do="org.settings.edit">
              <Link to="/points/setup" className="ml-auto text-sm text-brand hover:underline">
                Points setup →
              </Link>
            </Can>
          </>
        )}
        {setup && (
        <Can do="org.settings.edit">
          <Tab active={view === 'seasons'} onClick={() => setView('seasons')}>
            Seasons
          </Tab>
          <Tab active={view === 'tiers'} onClick={() => setView('tiers')}>
            Tiers
          </Tab>
          <Tab active={view === 'badges'} onClick={() => setView('badges')}>
            Badges
          </Tab>
          <Tab active={view === 'cosmetics'} onClick={() => setView('cosmetics')}>
            Cosmetics
          </Tab>
          <Tab active={view === 'wheel'} onClick={() => setView('wheel')}>
            Wheel
          </Tab>
          <Tab active={view === 'values'} onClick={() => setView('values')}>
            What things are worth
          </Tab>
        </Can>
        )}
      </div>

      {view === 'table' && <TablePanel shelfKey={given} />}
      {view === 'seasons' && <SeasonAdmin />}
      {view === 'tiers' && <TierLadder />}
      {/* Keyed on the same count as the shelf: a badge given from the header
          has to show in its holders here, not after a reload (QA-10). */}
      {view === 'badges' && <BadgeAdmin key={given} />}
      {view === 'cosmetics' && <CosmeticAdmin />}
      {view === 'wheel' && <WheelAdmin />}
      {view === 'spend' && (
        <div className="space-y-6">
          <Can do="wheel.hand_over">
            <PrizeHandover />
          </Can>
          <Shop />
          <PrizeWheel />
        </div>
      )}
      {view === 'values' && <PointValues />}

      {giving && (
        <GiveBadge
          onClose={() => setGiving(false)}
          onGiven={() => {
            toast('Badge given');
            refreshBell();
            setGiving(false);
            setGiven((n) => n + 1);
          }}
        />
      )}
    </>
  );
}

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

function TablePanel({ shelfKey }: { shelfKey: number }) {
  const { user } = useAuth();
  const [table, setTable] = useState<Table | null>(null);
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    Promise.all([
      api<Table>('/api/points/standings'),
      api<Me>('/api/points/me'),
    ])
      .then(([board, mine]) => {
        setTable(board);
        setMe(mine);
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load.'));
  }, []);

  useEffect(load, [load]);

  if (error) return <LoadError message={error} />;
  if (!table || !me) return <Loading />;

  if (!table.season) {
    return (
      <EmptyState
        title="The season has not started"
        description="Points are awarded for hitting goals, winning competitions and being recognised. The first one awarded opens the first season."
      />
    );
  }

  const gap = user ? gapToNext(table.standings, user.id) : null;

  return (
    <div className="space-y-6">
      <SeasonBanner season={table.season} />

      <section className="rounded-lg border border-edge bg-surface p-6">
        <p className="text-sm text-content-muted">You have</p>
        {/* One sentence to a screen reader. As two spans side by side, "10"
            and "1st" were read as "101st" (QA-22). */}
        <p className="mt-1 text-h1 tabular-nums text-content">
          <span className="sr-only">
            {formatPoints(me.points)} points,{' '}
            {me.rank ? `${ordinal(me.rank)} place` : 'unranked'}
          </span>
          <span aria-hidden="true">{formatPoints(me.points)}</span>
          <span aria-hidden="true" className="ml-2 text-h3 text-content-muted">
            {me.rank ? ordinal(me.rank) : 'unranked'}
          </span>
        </p>

        {/* A different number from the one above, and labelled so it cannot
            be mistaken for it: this is what can be spent, across every
            season, and spending it never moves the rank beside the balance. */}
        <p className="mt-2 text-sm text-content-muted">
          <span className="tabular-nums text-content">{formatPoints(me.wallet)}</span>{' '}
          to spend
          {me.title && (
            <span className="ml-3 rounded bg-brand-subtle px-2 py-0.5 text-content">
              {me.title}
            </span>
          )}
        </p>

        {me.tier && (
          <p className="mt-3">
            <span className="rounded bg-brand-subtle px-2 py-1 text-sm text-content">
              {me.tier}
            </span>
          </p>
        )}

        {/* What it would take to move up. The badge above rewards what already
            happened; this is the reason to do something this week. */}
        {toNextLabel(me.to_next_tier, me.next_tier) && (
          <p className="mt-2 text-sm text-content">
            {toNextLabel(me.to_next_tier, me.next_tier)}.
          </p>
        )}

        {/* The gap to the *next* place, not to first — the same argument the
            competition standings make. "240 behind 4th" is something somebody
            can do this week. */}
        {gap && (
          <p className="mt-2 text-sm text-content-muted">
            {formatPoints(gap.points)} behind {ordinal(gap.rank)}.
          </p>
        )}
        {me.rank === 1 && (
          <p className="mt-2 text-sm text-success">Leading the season.</p>
        )}
      </section>

      {table.standings.length > 0 ? (
        <section className="rounded-lg border border-edge bg-surface p-6">
          <h2 className="text-h3 text-content">Season table</h2>
          <ul className="mt-4 divide-y divide-edge">
            {table.standings.map((row) => (
              <li
                key={row.user_id}
                className={`flex items-center gap-3 py-3 first:pt-0 last:pb-0 ${
                  row.user_id === user?.id ? 'font-medium text-content' : ''
                }`}
              >
                <span className="w-8 shrink-0 tabular-nums text-content-muted">
                  {row.rank}
                </span>
                <Avatar name={row.name} ring={row.ring} />
                <span className="min-w-0 flex-1 truncate text-content">
                  <PersonLink id={row.user_id}>{row.name}</PersonLink>
                  {row.tier && (
                    <span className="ml-2 text-xs text-content-muted">
                      {row.tier}
                    </span>
                  )}
                </span>
                <span className="tabular-nums text-content">
                  {formatPoints(row.points)}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : (
        <EmptyState
          title="Nobody has scored yet this season"
          description="Points arrive when somebody hits a goal, wins a competition, or is recognised."
        />
      )}

      <Statement awards={me.statement} lifetime={me.lifetime} />

      {/* Below the season, not inside it: badges survive the reset, so
          they are not about where anybody stands this season. */}
      <BadgeShelf key={shelfKey} />
    </div>
  );
}

function SeasonBanner({ season }: { season: Season }) {
  const gone = elapsedPercent(season);

  return (
    <section className="rounded-lg border border-edge bg-surface p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="text-h3 text-content">{season.name}</h2>
        <p className="text-sm text-content-muted">{timeLeftLabel(season)}</p>
      </div>
      <p className="mt-1 text-sm text-content-muted">{seasonWindow(season)}</p>

      <div
        className="mt-4 h-2 overflow-hidden rounded-full bg-surface-hover"
        role="progressbar"
        aria-valuenow={Math.round(gone)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Season elapsed"
      >
        <div className="h-full bg-brand" style={{ width: `${gone}%` }} />
      </div>
    </section>
  );
}

function Statement({
  awards,
  lifetime,
}: {
  awards: Award[];
  lifetime: number;
}) {
  if (awards.length === 0) return null;

  return (
    <section className="rounded-lg border border-edge bg-surface p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4">
        <h2 className="text-h3 text-content">Where yours came from</h2>
        {/* A career total, shown here and nowhere that ranks anybody. The
            moment it becomes the scoreboard, the scoreboard is unwinnable
            again for everybody who joined last year. */}
        <p className="text-sm text-content-muted">
          {formatPoints(lifetime)} all time
        </p>
      </div>

      <ul className="mt-4 divide-y divide-edge">
        {awards.map((award) => (
          <li
            key={award.id}
            className="flex items-baseline gap-3 py-3 first:pt-0 last:pb-0"
          >
            <span
              className={`w-16 shrink-0 tabular-nums ${
                award.points < 0 ? 'text-danger' : 'text-success'
              }`}
            >
              {signed(award.points)}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-content">{award.reason}</span>
              <span className="text-xs text-content-muted">
                {labelFor(award.event_key)} ·{' '}
                {dayMonth(award.created_at)}
              </span>
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
