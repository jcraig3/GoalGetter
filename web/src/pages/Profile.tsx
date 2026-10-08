import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { api, ApiError } from '../api';
import { useAuth } from '../auth';
import { toast } from '../toast';
import { agoInWords, dayMonth } from '../time';
import { useDocumentTitle } from '../documentTitle';
import Avatar from '../components/Avatar';
import EmptyState from '../components/EmptyState';
import GiveBadge from '../components/GiveBadge';
import GoalProgress, { type GoalLike } from '../components/GoalProgress';
import Loading from '../components/Loading';
import MetricValue from '../components/MetricValue';
import { BadgeMark } from '../components/badgeMarks';
import { RecogniseForm } from './Achievements';
import { ringStyle } from '../components/ring';
import { formatPoints, ordinal } from './pointsCopy';

interface Person {
  id: number;
  name: string;
  photo_digest: string | null;
  job_title: string | null;
  team_name: string | null;
  office_name: string | null;
  ring: string | null;
  title: string | null;
}

interface Season {
  name: string;
  points: number;
  rank: number | null;
  of: number;
  tier: string | null;
  next_tier: string | null;
  to_next_tier: number | null;
}

interface Badge {
  badge_id: number;
  name: string;
  icon: string;
  reason: string;
  earned_at: string;
  times: number;
}

interface Win {
  id: number;
  occasion: string;
  title: string;
  body: string | null;
  figure: string | null;
  from_name: string | null;
  created_at: string;
}

interface NumberRow {
  board_id: number;
  board_name: string;
  metric_name: string;
  period_label: string;
  value: string;
  unit: string;
  decimal_places: number;
  unit_label: string | null;
  rank: number;
  of: number;
  movement: number | null;
}

interface Profile {
  person: Person;
  is_me: boolean;
  season: Season | null;
  badges: Badge[];
  wins: Win[];
  private: {
    goals: (GoalLike & { id: number; name: string | null; period_label: string })[];
    numbers: NumberRow[];
    streak_days: number | null;
  } | null;
  /** Board places for a viewer without the private half (P4-12): the place, never the number. */
  places?: { board_id: number; board_name: string; period_label: string; rank: number; of: number }[];
  can: { recognise: boolean; give_badge: boolean; edit: string | null };
}

/**
 * A person's profile (Phase 9).
 *
 * **One column, and only what there is**: a section with nothing in it is not
 * drawn, so a new starter's profile is short rather than a page of "none".
 *
 * **The same page for everyone, narrowed by the server.** Badges, wins and
 * points come to anybody in the organization; goals and numbers only to the
 * person and those who manage them — `private` is simply absent otherwise.
 * Every button here is one this viewer can use: the server says which.
 */
export default function ProfilePage() {
  const { id } = useParams();
  const { user, can } = useAuth();
  const personId = id === 'me' ? user?.id : Number(id);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recognising, setRecognising] = useState(false);
  const [giving, setGiving] = useState(false);
  // Not the last person's name over "not available" (P3-5).
  useDocumentTitle(missing ? 'Profile not available' : profile?.person.name);

  const load = useCallback(() => {
    if (!personId) return;
    api<Profile>(`/api/people/${personId}`)
      .then((found) => {
        setProfile(found);
        setMissing(false);
      })
      .catch((e) => {
        if (e instanceof ApiError && e.status === 404) setMissing(true);
        else setError(e instanceof Error ? e.message : 'Could not load this profile.');
      });
  }, [personId]);

  useEffect(load, [load]);

  if (missing) {
    return (
      <EmptyState
        title="This profile isn’t available"
        description="They may have left, or your organization keeps profiles to the people who manage them."
      />
    );
  }
  if (error) {
    return (
      <p role="alert" className="rounded-md border border-danger px-3 py-2 text-sm text-danger">
        {error}
      </p>
    );
  }
  if (!profile) return <Loading />;

  const { person, season, badges, wins } = profile;
  const first = person.name.split(' ')[0];
  // The office only when it says something the team did not ("Metropolis Sales
  // Team · Metropolis Sales Team" where an office is named for its one team).
  const about = [
    person.job_title,
    person.team_name,
    person.office_name !== person.team_name ? person.office_name : null,
  ]
    .filter(Boolean)
    .join(' · ');

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      {/* Who they are, and what you can do about it. */}
      <section className="flex flex-wrap items-center gap-5 rounded-lg border border-edge bg-surface p-6">
        <Face person={person} />
        <div className="min-w-0 flex-1">
          <h1 className="text-h1 text-content">{person.name}</h1>
          {about && <p className="mt-1 text-content-muted">{about}</p>}
          {(season?.tier || person.title) && (
            <p className="mt-2 flex flex-wrap gap-2 text-xs">
              {season?.tier && (
                <span className="rounded-full bg-gold/15 px-2.5 py-1 text-gold">{season.tier} tier</span>
              )}
              {person.title && (
                <span className="rounded-full bg-brand-subtle px-2.5 py-1 text-content">{person.title}</span>
              )}
            </p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          {profile.can.recognise && (
            <button
              type="button"
              onClick={() => setRecognising(true)}
              className="rounded-md bg-brand px-3 py-2 text-sm font-medium text-white hover:bg-brand-hover"
            >
              Recognise
            </button>
          )}
          {profile.can.give_badge && (
            <button
              type="button"
              onClick={() => setGiving(true)}
              className="rounded-md border border-edge px-3 py-2 text-sm text-content hover:bg-surface-hover"
            >
              Give a badge
            </button>
          )}
          {profile.can.edit && (
            <Link
              to={profile.can.edit}
              className="rounded-md border border-edge px-3 py-2 text-sm text-content hover:bg-surface-hover"
            >
              {profile.is_me ? 'Edit your details' : 'Edit'}
            </Link>
          )}
        </div>
      </section>

      {season && (
        <Section title="This season" aside={season.name}>
          <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            <Stat label="Points" value={formatPoints(season.points)} />
            <Stat
              label="Place"
              value={season.rank ? `${ordinal(season.rank)} of ${season.of}` : 'Not ranked yet'}
            />
            {season.next_tier && season.to_next_tier !== null && (
              <Stat label={`To ${season.next_tier}`} value={formatPoints(season.to_next_tier)} />
            )}
          </dl>
        </Section>
      )}

      {badges.length > 0 && (
        <Section title="Badges" aside={String(badges.length)}>
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {badges.map((badge) => (
              <li
                key={badge.badge_id}
                className="flex flex-col items-center rounded-md border border-edge px-3 py-4 text-center"
                title={badge.reason || undefined}
              >
                <BadgeMark icon={badge.icon} className="h-12 w-12" />
                <span className="mt-2 line-clamp-2 text-sm leading-tight text-content">{badge.name}</span>
                <span className="mt-1 text-xs text-content-subtle">
                  {dayMonth(badge.earned_at)}
                  {badge.times > 1 && ` · ×${badge.times}`}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {wins.length > 0 && (
        <Section title="Recent wins">
          <ul className="divide-y divide-edge">
            {wins.map((win) => (
              <li key={win.id} className="flex items-baseline gap-4 py-3">
                <div className="min-w-0 flex-1">
                  <p className="text-caption uppercase tracking-wide text-brand">{win.occasion}</p>
                  <p className="text-content">
                    {win.title}
                    {win.from_name && <span className="text-content-muted"> — from {win.from_name}</span>}
                  </p>
                </div>
                {win.figure && (
                  <span className="shrink-0 font-semibold tabular-nums text-content">{win.figure}</span>
                )}
                <span className="shrink-0 text-xs text-content-subtle">
                  {agoInWords(new Date(win.created_at))}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {/* **Where they stand, without the numbers** (P4-12): the boards this
          viewer can open show both already; the profile shows the place and
          keeps the number on the private half. */}
      {profile.places && profile.places.length > 0 && (
        <Section title="On the boards">
          <ul className="divide-y divide-edge">
            {profile.places.map((place) => (
              <li key={place.board_id} className="flex items-baseline justify-between gap-4 py-3">
                <span className="min-w-0 text-content">
                  {can('leaderboards.view') ? (
                    <Link to={`/leaderboards/${place.board_id}`} className="hover:underline">
                      {place.board_name}
                    </Link>
                  ) : (
                    place.board_name
                  )}
                  <span className="text-content-muted"> · {place.period_label}</span>
                </span>
                <span className="shrink-0 text-content">
                  {ordinal(place.rank)} <span className="text-content-muted">of {place.of}</span>
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {!season && badges.length === 0 && wins.length === 0 && !profile.private && !profile.places?.length && (
        <EmptyState
          title={profile.is_me ? 'Nothing here yet' : `Nothing to show for ${first} yet`}
          description="Badges, wins and shout-outs appear here as they are earned."
        />
      )}

      {profile.private && (
        <Private
          data={profile.private}
          note={
            profile.is_me
              ? 'Only you, your managers and admins see this.'
              : `Only ${first}, their managers and admins see this.`
          }
          canOpenBoards={can('leaderboards.view')}
        />
      )}

      {recognising && (
        <RecogniseForm
          userId={person.id}
          onClose={() => setRecognising(false)}
          onSent={async () => {
            setRecognising(false);
            toast(`${first} recognised`);
            load();
          }}
          onError={(message) => message && setError(message)}
        />
      )}
      {giving && (
        <GiveBadge
          userId={person.id}
          onClose={() => setGiving(false)}
          onGiven={() => {
            setGiving(false);
            toast(`Badge given to ${first}`);
            load();
          }}
        />
      )}
    </div>
  );
}

/** The private half: goals and numbers, under a line saying who sees it. */
function Private({
  data,
  note,
  canOpenBoards,
}: {
  data: NonNullable<Profile['private']>;
  note: string;
  canOpenBoards: boolean;
}) {
  const nothing = data.goals.length === 0 && data.numbers.length === 0;
  return (
    <section aria-label="Private" className="rounded-lg border border-dashed border-edge p-6">
      <p className="flex items-center gap-2 text-xs text-content-subtle">
        <span aria-hidden="true">🔒</span>
        {note}
      </p>

      {nothing && <p className="mt-4 text-sm text-content-muted">No goals or numbers this period yet.</p>}

      {data.goals.length > 0 && (
        <div className="mt-5">
          <h2 className="text-h3 text-content">Goals</h2>
          <ul className="mt-3 space-y-5">
            {data.goals.map((goal) => (
              <li key={goal.id}>
                <p className="mb-1 text-sm text-content">
                  <Link to={`/goals/${goal.id}`} className="hover:text-brand">
                    {goal.name || goal.metric_name}
                  </Link>
                  <span className="text-content-subtle"> · {goal.period_label}</span>
                </p>
                <GoalProgress goal={goal} />
              </li>
            ))}
          </ul>
        </div>
      )}

      {data.numbers.length > 0 && (
        <div className="mt-6">
          <div className="flex items-baseline justify-between gap-3">
            <h2 className="text-h3 text-content">Numbers</h2>
            {data.streak_days && (
              <span className="text-xs text-content-muted">{data.streak_days}-day streak</span>
            )}
          </div>
          <ul className="mt-3 divide-y divide-edge">
            {data.numbers.map((row) => (
              <li key={row.board_id} className="flex flex-wrap items-baseline gap-x-4 gap-y-1 py-3">
                <div className="min-w-0 flex-1">
                  <p className="text-content">
                    {canOpenBoards ? (
                      <Link to={`/leaderboards/${row.board_id}`} className="hover:text-brand">
                        {row.board_name}
                      </Link>
                    ) : (
                      row.board_name
                    )}
                  </p>
                  <p className="text-xs text-content-subtle">
                    {row.metric_name} · {row.period_label}
                  </p>
                </div>
                <MetricValue
                  value={row.value}
                  format={{ unit: row.unit, decimal_places: row.decimal_places, unit_label: row.unit_label }}
                  className="font-semibold tabular-nums text-content"
                />
                <span className="text-sm text-content-muted">
                  {ordinal(row.rank)} of {row.of}
                  {row.movement !== null && row.movement !== 0 && (
                    <span className={row.movement > 0 ? 'text-success' : 'text-danger'}>
                      {' '}
                      {row.movement > 0 ? `▲${row.movement}` : `▼${-row.movement}`}
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function Section({ title, aside, children }: { title: string; aside?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-edge bg-surface p-6">
      <div className="mb-4 flex items-baseline justify-between gap-3">
        <h2 className="text-h3 text-content">{title}</h2>
        {aside && <span className="text-sm text-content-subtle">{aside}</span>}
      </div>
      {children}
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs text-content-muted">{label}</dt>
      <dd className="mt-1 text-h2 tabular-nums text-content">{value}</dd>
    </div>
  );
}

/** Their photo, large, with the ring they wear; their initials without one. */
function Face({ person }: { person: Person }) {
  if (person.photo_digest) {
    return (
      <img
        src={`/api/images/${person.photo_digest}`}
        alt=""
        className="size-20 shrink-0 rounded-full object-cover"
        style={ringStyle(person.ring, '3px', '3px')}
      />
    );
  }
  return (
    <span className="shrink-0 [&>*]:size-20 [&>*]:text-2xl">
      <Avatar name={person.name} digest={null} size="lg" />
    </span>
  );
}
