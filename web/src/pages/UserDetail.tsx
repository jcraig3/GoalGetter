import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { api } from '../api';
import { Can, useAuth } from '../auth';
import ProfileFields from '../components/ProfileFields';
import PhotoPicker from '../components/PhotoPicker';
import PersonPassword from '../components/PersonPassword';
import HandoffLink from '../components/HandoffLink';
import PageHeader from '../components/PageHeader';
import Select from '../components/Select';
import GameTokens from '../components/GameTokens';
import WalkupMedia from '../components/WalkupMedia';
import { ask } from '../confirm';
import Loading from '../components/Loading';
import Breadcrumb from '../components/Breadcrumb';
import { capitalised } from '../words';
import { toast } from '../toast';
import { handoffMessage, type Delivery } from '../handoffWords';

const ROLES = ['agent', 'manager', 'admin'] as const;

interface User {
  id: number;
  full_name: string;
  email: string;
  org_role: string;
  status: string;
  team_id: number | null;
  team_name: string | null;
  hidden: boolean;
  deactivated: boolean;
  /** Two-step sign-in is set up. */
  mfa_enabled?: boolean;
  /** In the directory with SSO required (11.1). */
  must_use_sso?: boolean;
  /** Why they must: signed in with Microsoft before, or in the directory. */
  sso_reason?: 'signed_in' | 'directory' | null;
  /** Whether a reset link would have anything to reset. */
  has_password?: boolean;
  /** Has a password an admin set and not yet replaced it (11.2). */
  must_change_password?: boolean;
  /** Content hash of their photo, or null for initials. */
  photo_digest: string | null;
  has_custom_photo: boolean;
  invite_pending: boolean;
  /** Given a temporary password and never signed in. */
  awaiting_first_sign_in?: boolean;
  nickname: string;
  birthday_month: number | null;
  birthday_day: number | null;
  started_on: string | null;
  job_title: string;
  department: string;
  office_location: string;
}

interface Team {
  id: number;
  name: string;
}

interface Handoff {
  message: string;
  link: string;
}

/**
 * Everything about one person, in one place.
 *
 * **This page used to be read-only and say so**, with a line pointing back at the
 * list: *"role, team and status are set on the people list, where you can see
 * everybody at once."* That reasoning held while the list was where you set
 * things — but the list now carries search, filters and bulk actions, and per-row
 * editing was what made it unreadable at four hundred rows.
 *
 * So the split moved: **the list is for deciding about many people, this page is
 * for deciding about one.** Bulk team and role assignment live there; everything
 * that is about a single person — their role, their team, their password, their
 * access, their walk-up media — lives here, on one page, rather than split
 * between a dialog and a page depending on which it was.
 *
 * **Scope is the API's, not this page's.** Reaching somebody outside your scope
 * 404s on the request, so there is no client-side guard to keep in step with the
 * server's.
 */
export default function UserDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user: me, can } = useAuth();
  const [person, setPerson] = useState<User | null>(null);
  const [teams, setTeams] = useState<Team[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [handoff, setHandoff] = useState<Handoff | null>(null);

  const load = useCallback(async () => {
    try {
      // Just this person (P4-16), whichever roster they are on: unhiding
      // somebody is a decision made while looking at them, not from a list
      // they are not on. It used to load all 480 to find one.
      const [found, t] = await Promise.all([
        api<User>(`/api/users/${id}`).catch(() => null),
        api<Team[]>('/api/teams').catch(() => [] as Team[]),
      ]);
      if (!found) {
        setError('That person is not in your scope, or no longer exists.');
        return;
      }
      setPerson(found);
      setTeams(t);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load.');
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  async function patch(body: Record<string, unknown>) {
    setError(null);
    try {
      setPerson(
        await api<User>(`/api/users/${id}`, {
          method: 'PATCH',
          body: JSON.stringify(body),
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save that.');
      // Reload rather than leave the form showing a value the server refused.
      void load();
    }
  }

  async function act(action: string, confirmText?: string, confirmLabel?: string) {
    // The button says what it does (P5-9): "Suspend", not "Continue".
    if (confirmText && !(await ask(confirmText, confirmLabel ? { confirmLabel, danger: true } : {}))) return;
    setError(null);
    try {
      await api(`/api/users/${id}/${action}`, { method: 'POST' });
      // What happened, said (P4-10): "Let them back in" changed nothing on
      // screen but a button's label.
      const name = person?.full_name ?? 'They';
      const said: Record<string, string> = {
        reactivate: `${name} can sign in again`,
        suspend: `${name} is suspended and signed out`,
        hide: `${name} is hidden`,
        unhide: `${name} is back on the roster`,
      };
      if (said[action]) toast(said[action]);
      // Hiding takes them off the roster, so going back to a list they are not
      // on is the honest destination.
      if (action === 'hide') navigate('/users');
      else await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : `Could not ${action}.`);
    }
  }

  if (error && !person) {
    return (
      <>
        <Back />
        <p
          role="alert"
          className="rounded-md border border-danger px-3 py-2 text-sm text-danger"
        >
          {error}
        </p>
      </>
    );
  }

  if (!person) return <Loading />;

  const isMe = person.id === me?.id;

  return (
    <>
      <Back here={person.full_name} />
      <PageHeader
        title={person.full_name}
        description={person.email}
        actions={
          // What colleagues see of them (9.4); this page is what you change.
          <Link
            to={`/people/${person.id}`}
            className="rounded-md border border-edge px-3 py-2 text-sm text-content hover:bg-surface-hover"
          >
            View profile
          </Link>
        }
      />

      {error && (
        <p
          role="alert"
          className="mb-4 rounded-md border border-danger px-3 py-2 text-sm text-danger"
        >
          {error}
        </p>
      )}

      {handoff && (
        <div className="mb-4 max-w-xl">
          <HandoffLink
            message={handoff.message}
            link={handoff.link}
            onDismiss={() => setHandoff(null)}
          />
        </div>
      )}

      {/* **Two columns on a wide screen** (review §7): who they are and what
          they can do on the left, what plays and moves for them on the right.
          One long column put the walk-up clip a long scroll below the name. */}
      <div className="grid items-start gap-6 xl:grid-cols-2">
      <section className="rounded-lg border border-edge bg-surface p-6">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-4">
          {/* **Editable here, because most of these people never sign in.** The
              directory created their account, so "they can upload their own" is
              not an answer for the majority — somebody has to be able to do it
              for them. */}
          <Can do="users.edit_photo">
            <PhotoPicker
              userId={person.id}
              name={person.full_name}
              digest={person.photo_digest}
              hasCustom={person.has_custom_photo}
              onChanged={() => void load()}
            />
          </Can>
          <div className="min-w-0">
            <p className="truncate text-h3 text-content">{person.full_name}</p>
            <p className="truncate text-sm text-content-muted">
              {person.email}
            </p>
            {(person.hidden || person.deactivated) && (
              <span className="mt-1 inline-block rounded-full bg-surface-raised px-2 py-0.5 text-xs text-content-muted">
                {person.hidden ? 'hidden' : 'deactivated'}
              </span>
            )}
          </div>
        </div>

        {/* **Beside the photograph's rule, not the directory's.** A nickname
            is theirs, and most of these people never sign in — so somebody has
            to be able to set it for them, exactly as with a face. */}
        <Can do="users.edit_photo">
          <div className="mt-6 border-t border-edge pt-6">
            <ProfileFields
              userId={person.id}
              profile={{
                nickname: person.nickname,
                birthday_month: person.birthday_month,
                birthday_day: person.birthday_day,
              }}
              onSaved={() => void load()}
            />
          </div>
        </Can>

        {/* What the directory says they do. Read-only on purpose: the sync owns
            these, so an edit here is a change the next sync silently undoes. */}
        {(person.job_title || person.department || person.office_location) && (
          <dl className="mt-6 space-y-2 border-t border-edge pt-6 text-sm">
            {person.job_title && <Row label="Title" value={person.job_title} />}
            {person.department && (
              <Row label="Department" value={person.department} />
            )}
            {person.office_location && (
              <Row label="Office" value={person.office_location} />
            )}
          </dl>
        )}

        <div className="mt-6 space-y-4 border-t border-edge pt-6">
          {can('users.assign_team') ? (
            <Select
              label="Team"
              value={person.team_id === null ? '' : String(person.team_id)}
              onChange={(v) =>
                void patch({ team_id: v === '' ? null : Number(v) })
              }
              options={[
                { value: '', label: 'No team' },
                ...teams.map((t) => ({ value: String(t.id), label: t.name })),
              ]}
            />
          ) : (
            <Row
              label="Team"
              value={person.team_name ?? 'Not on a team'}
              warn={!person.team_id}
            />
          )}

          {/* **A company fact, so it sits with team and role.** When somebody
              joined is not theirs to invent, and it is what "three years
              today" counts from. */}
          {can('users.assign_team') && (
            <div>
              <label
                htmlFor="started-on"
                className="block text-sm text-content-muted"
              >
                Started on
              </label>
              <input
                id="started-on"
                type="date"
                value={person.started_on ?? ''}
                onChange={(e) =>
                  void patch({ started_on: e.target.value || null })
                }
                className="mt-1 w-full rounded-md border border-edge bg-bg px-3 py-2 text-sm text-content outline-none focus:border-brand"
              />
              <p className="mt-1 text-xs text-content-subtle">
                Optional. Marks a work anniversary each year — on the Friday
                before, when it falls on a weekend.
              </p>
            </div>
          )}

          {/* Your own role is never editable here. Demoting yourself is a lockout
              nobody intends, and the bulk path refuses it for the same reason. */}
          {can('users.manage_roles') && !isMe ? (
            <Select
              label="Role"
              value={person.org_role}
              onChange={(v) => void patch({ org_role: v })}
              options={ROLES.map((r) => ({ value: r, label: capitalised(r) }))}
            />
          ) : (
            <Row label="Role" value={capitalised(person.org_role)} />
          )}

          <Row
            label="Status"
            value={
              person.hidden
                ? 'Hidden'
                : person.deactivated
                  ? 'Deactivated — turned off in your directory'
                  : // Before anything about invitations (P4-2): a locked-out
                    // person read as "Invited — has not signed in".
                    person.status === 'suspended'
                    ? 'Suspended — cannot sign in'
                    : person.awaiting_first_sign_in
                    ? 'Invited — has not signed in with the password you set'
                    : person.invite_pending
                      ? 'Invited — has not opened their link'
                      : capitalised(person.status)
            }
          />
        </div>

        {/* **Only for somebody actually waiting on one.** People from the
            directory sync arrive active and sign in with the work account they
            already have — there is nothing to invite them to. This is for
            accounts an admin typed in by hand. */}
        {person.invite_pending && can('users.invite') && (
          <div className="mt-6 border-t border-edge pt-6">
            <p className="text-sm text-content">Invitation</p>
            <p className="mt-1 text-sm text-content-muted">
              They have never signed in. Resending produces a fresh link — the
              previous one stops working.
            </p>
            <button
              type="button"
              onClick={() =>
                void (async () => {
                  try {
                    const r = await api<{ invite_link: string } & Delivery>(
                      `/api/users/${person.id}/resend-invite`,
                      { method: 'POST' },
                    );
                    setHandoff({
                      message: handoffMessage(
                        'invitation',
                        { name: person.full_name, email: person.email },
                        r,
                      ),
                      link: r.invite_link,
                    });
                  } catch (e) {
                    setError(
                      e instanceof Error ? e.message : 'Could not resend.',
                    );
                  }
                })()
              }
              className="mt-3 rounded-md border border-edge px-3 py-2 text-sm text-content transition-colors hover:bg-surface-hover"
            >
              Resend invitation
            </button>
          </div>
        )}

        {can('users.reset_password') && !person.hidden && (
          <PersonPassword
            person={person}
            isMe={person.id === me?.id}
            onHandoff={setHandoff}
            onError={setError}
            onChanged={() => void load()}
          />
        )}

        {/* **For somebody who lost their phone and their recovery codes.** They
            sign in with their password next time, and set up again if it is
            required. A separate block: nothing about editing them changes. */}
        {can('users.reset_password') && person.mfa_enabled && (
          <div className="mt-6 border-t border-edge pt-6">
            <p className="text-sm text-content">Two-step sign-in</p>
            <p className="mt-1 text-sm text-content-muted">
              On. If they have lost their authenticator and their recovery codes, reset it.
            </p>
            <button
              type="button"
              onClick={() =>
                void (async () => {
                  if (
                    !await ask(
                      `Reset two-step sign-in for ${person.full_name}?\n\n` +
                        'Their password alone signs them in until they set it up again.',
                    )
                  ) {
                    return;
                  }
                  try {
                    await api(`/api/auth/mfa/${person.id}/reset`, { method: 'POST' });
                    await load();
                  } catch (e) {
                    setError(e instanceof Error ? e.message : 'Could not reset it.');
                  }
                })()
              }
              className="mt-3 rounded-md border border-edge px-3 py-2 text-sm text-content transition-colors hover:bg-surface-hover"
            >
              Reset two-step sign-in
            </button>
          </div>
        )}

        {can('users.suspend') && !isMe && (
          <div className="mt-6 border-t border-edge pt-6">
            <p className="text-sm text-content">Access</p>
            <div className="mt-3 flex flex-wrap gap-3">
              {person.hidden ? (
                <button
                  type="button"
                  onClick={() => void act('unhide')}
                  className="rounded-md border border-edge px-3 py-2 text-sm text-content transition-colors hover:bg-surface-hover"
                >
                  Unhide
                </button>
              ) : (
                <>
                  <button
                    type="button"
                    onClick={() =>
                      void act(
                        person.status === 'suspended'
                          ? 'reactivate'
                          : 'suspend',
                        person.status === 'suspended'
                          ? undefined
                          : `Suspend ${person.full_name}? They will be signed out immediately and cannot sign back in.`,
                        'Suspend',
                      )
                    }
                    className="rounded-md border border-edge px-3 py-2 text-sm text-content transition-colors hover:bg-surface-hover"
                  >
                    {person.status === 'suspended'
                      ? 'Let them back in'
                      : 'Suspend'}
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      void act(
                        'hide',
                        `Hide ${person.full_name}? They come off every leaderboard and lose access. Their history is kept and their numbers still count toward their team — one click brings them back.`,
                        'Hide',
                      )
                    }
                    className="rounded-md border border-danger px-3 py-2 text-sm text-danger transition-colors hover:bg-danger/10"
                  >
                    Hide
                  </button>
                </>
              )}
            </div>
          </div>
        )}

      </section>

      <section className="rounded-lg border border-edge bg-surface p-6 [&>div:first-child]:mt-0 [&>div:first-child]:border-t-0 [&>div:first-child]:pt-0">
        <WalkupMedia userId={isMe ? undefined : person.id} />
        <GameTokens userId={isMe ? undefined : person.id} />

        {/* Said plainly, because setting somebody else's music is the kind of
            thing that should not be a surprise to them. */}
        {!isMe && (
          <p className="mt-4 text-xs text-content-subtle">
            Changes you make here are recorded against your name.
          </p>
        )}
      </section>
      </div>
    </>
  );
}

function Back({ here }: { here?: string }) {
  return <Breadcrumb parent={{ to: '/users', label: 'Users' }} here={here} />;
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
