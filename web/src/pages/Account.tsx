import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { api } from '../api';
import { useAuth } from '../auth';
import PhotoPicker from '../components/PhotoPicker';
import ChangePassword from '../components/ChangePassword';
import TwoStepSettings from '../components/TwoStepSettings';
import NotificationPreferences from '../components/NotificationPreferences';
import ProfileFields from '../components/ProfileFields';
import PageHeader from '../components/PageHeader';
import GameTokens from '../components/GameTokens';
import WalkupMedia from '../components/WalkupMedia';
import { LogoutIcon } from '../components/icons';

interface Team {
  id: number;
  name: string;
}

/**
 * Everything about the signed-in person, in one place.
 *
 * Kept off the dashboard on purpose: the home page answers "how are we doing?"
 * and this answers "who am I and what are my settings?". Mixing them means the
 * first screen everyone sees is half occupied by details each person already
 * knows about themselves.
 */
export default function Account() {
  const { user, logout, refresh } = useAuth();
  // "#two-step" from Settings' "Set it up now" (8.4): the router does not
  // scroll to a hash on its own.
  useEffect(() => {
    if (!window.location.hash) return;
    const timer = window.setTimeout(
      () => document.getElementById(window.location.hash.slice(1))?.scrollIntoView?.({ block: 'start' }),
      300,
    );
    return () => window.clearTimeout(timer);
  }, []);
  const [teamName, setTeamName] = useState<string | null>(null);
  // Held locally so the new face appears the moment it uploads, rather than
  // after the session reloads.
  const [digest, setDigest] = useState<string | null>(
    user?.photo_digest ?? null,
  );
  const hasCustom = user?.has_custom_photo ?? false;

  useEffect(() => {
    if (user?.team_id == null) return;
    // /api/auth/me returns team_id but not the name — it is the id every other
    // caller needs. One extra request on a rarely-visited page is cheaper than
    // widening a response every request pays for.
    api<Team[]>('/api/teams')
      .then((teams) =>
        setTeamName(teams.find((t) => t.id === user.team_id)?.name ?? null),
      )
      .catch(() => setTeamName(null));
  }, [user?.team_id]);

  return (
    <>
      <PageHeader
        title="Your account"
        description="Your details, sign-in, and what you hear about."
        actions={
          // What colleagues see of you (9.2) — this page is what you change.
          <Link
            to="/people/me"
            className="rounded-md border border-edge px-3 py-2 text-sm text-content hover:bg-surface-hover"
          >
            View your profile
          </Link>
        }
      />

      <section className="max-w-xl rounded-lg border border-edge bg-surface p-6">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-4">
          {user && (
            <PhotoPicker
              userId={user.id}
              name={user.full_name}
              digest={digest}
              // Whether "use the default" would do anything. Known by asking:
              // the account's own record says which of the two slots is filled.
              hasCustom={hasCustom}
              onChanged={(next) => {
                setDigest(next);
                void refresh();
              }}
            />
          )}
          <div className="min-w-0">
            <p className="truncate text-h3 text-content">{user?.full_name}</p>
            <p className="truncate text-sm text-content-muted">{user?.email}</p>
          </div>
        </div>

        <dl className="mt-6 space-y-2 border-t border-edge pt-6 text-sm">
          <Row
            label="Role"
            value={(user?.org_role ?? '').replace(/^./, (c) => c.toUpperCase())}
          />
          <Row
            label="Team"
            value={user?.team_id == null ? 'Not on a team' : (teamName ?? '…')}
            // Being on no team means missing from every team leaderboard, which
            // is worth surfacing rather than showing an empty cell.
            warn={user?.team_id == null}
          />
        </dl>

        <p className="mt-4 text-xs text-content-muted">
          Your role and team are set by an administrator.
        </p>

        {/* **Yours, unlike the two above it.** Role and team are decisions
            about where you sit that somebody else makes; this is a decision
            about you. */}
        {user && (
          <div className="mt-6 border-t border-edge pt-6">
            <ProfileFields
              userId={user.id}
              profile={{
                nickname: user.nickname,
                birthday_month: user.birthday_month,
                birthday_day: user.birthday_day,
              }}
              onSaved={() => void refresh()}
            />
          </div>
        )}

        {/* Both are about a password, and somebody who only signs in with
            Microsoft has none to change or to protect (QA-33). */}
        {user?.has_password === false ? (
          <p className="rounded-md border border-edge px-4 py-3 text-sm text-content-muted">
            You sign in with Microsoft, so your password and two-step sign-in
            are managed there, not here.
          </p>
        ) : (
          <>
            <ChangePassword />
            {/* The target of Settings' "Set it up now" (8.4). */}
            <div id="two-step" className="scroll-mt-24">
              <TwoStepSettings />
            </div>
          </>
        )}

        <NotificationPreferences />

        <WalkupMedia />
        <GameTokens />

        {/* Last, and the only red control on the page. Sign out is not
            dangerous — nothing is lost — but it is the one action here that
            ends what you were doing, and it now lives on a page you have to
            navigate to rather than a button beside every screen. */}
        <div className="mt-6 border-t border-edge pt-6">
          <button
            onClick={() => void logout()}
            className="flex items-center gap-2 rounded-md border border-danger px-4 py-2 text-sm font-medium text-danger transition-colors hover:bg-danger hover:text-white"
          >
            <LogoutIcon className="size-4" />
            Sign out
          </button>
          <p className="mt-2 text-xs text-content-muted">
            Ends this session only. Other devices stay signed in.
          </p>
        </div>
      </section>
    </>
  );
}

function Row({
  label,
  value,
  warn,
}: {
  label: string;
  value: string;
  warn?: boolean;
}) {
  return (
    <div className="flex justify-between gap-4 border-b border-edge pb-2 last:border-0">
      <dt className="text-content-muted">{label}</dt>
      <dd className={warn ? 'text-warning' : 'text-content'}>{value}</dd>
    </div>
  );
}
