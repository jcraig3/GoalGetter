import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';

import { api } from '../api';
import { Can, useAuth } from '../auth';
import EmptyState from '../components/EmptyState';
import Field from '../components/Field';
import HandoffLink from '../components/HandoffLink';
import NonPeopleReview from '../components/NonPeopleReview';
import Avatar from '../components/Avatar';
import PageHeader from '../components/PageHeader';
import IconButton from '../components/IconButton';
import Combobox from '../components/Combobox';
import Select from '../components/Select';
import { Tab } from '../components/Tabs';
import TemporaryPasswordField from '../components/TemporaryPasswordField';
import { passwordProblem } from '../passwordRule';
import { handoffMessage, type Delivery } from '../handoffWords';
import { directory, type DirectoryStatus } from '../directory';
import DirectoryPanel from './DirectoryPanel';
import {
  apply as applyFilters,
  isNarrowed,
  NO_FILTERS,
  NO_TEAM,
  optionsFor,
  type Filters,
} from './peopleFilter';

/** Rows drawn at a time. */
const PAGE_SIZE = 50;
import { badge } from './directorySync';
import { PencilIcon } from '../components/icons';
import { ask } from '../confirm';
import Loading from '../components/Loading';
import MissingHint from '../components/MissingHint';
import FilterFold from '../components/FilterFold';
import { useOpenFromUrl } from '../urlIntent';
import { capitalised } from '../words';

interface User {
  id: number;
  email: string;
  full_name: string;
  org_role: string;
  status: string;
  last_login_at: string | null;
  invite_pending: boolean;
  /** Given a temporary password and never signed in: still invited, to the eye. */
  awaiting_first_sign_in?: boolean;
  team_id: number | null;
  team_name: string | null;
  //: Which roster they are on. `hidden` is a decision an admin made; the sync
  //: never writes it. `deactivated` is the directory reporting the account
  //: turned off, and it reverses itself when the directory does.
  hidden: boolean;
  deactivated: boolean;
  /** Content hash of their photo, or null for initials. */
  photo_digest: string | null;
  //: What the directory said, when it said anything. Empty for anybody invited
  //: by hand, which is also what "any" means to the filters.
  job_title: string;
  department: string;
  office_location: string;
}

/**
 * The three rosters, and which one somebody is on.
 *
 * **Three because there are three reasons somebody is not on the active list**,
 * and lumping them together loses the only thing worth knowing: whether a person
 * did this or your directory did.
 *
 * **Hidden wins when somebody is both**, matching the server. An admin hid them
 * on purpose, and that decision is what should be shown and undone — a person
 * sitting only on Deactivated could be re-enabled upstream and quietly reappear
 * on a board they were hidden from.
 */
const ROSTERS = ['active', 'hidden', 'deactivated'] as const;
type Roster = (typeof ROSTERS)[number];

function rosterOf(user: User): Roster {
  if (user.hidden) return 'hidden';
  if (user.deactivated) return 'deactivated';
  return 'active';
}

/** What each roster is for, said once so the tabs and the empty states agree. */
const ROSTER_COPY: Record<
  Roster,
  { tab: string; empty: string; blurb: string }
> = {
  active: { tab: 'Active', empty: 'Nobody here yet', blurb: '' },
  hidden: {
    tab: 'Hidden',
    empty: 'Nobody is hidden',
    blurb:
      'Hidden on purpose. They keep their history and their numbers still count toward their team, but they appear on no leaderboard, dashboard or wall display. The directory sync will not bring them back — only Unhide will.',
  },
  deactivated: {
    tab: 'Deactivated',
    empty: 'Nobody has been switched off',
    blurb:
      'Turned off in your directory, not here. Their account was disabled upstream, so the sync switched it off. Re-enabling it in your directory brings them back on its own — reactivate here only if you want them back sooner.',
  },
};

interface Team {
  id: number;
  name: string;
}

interface InviteResult extends Delivery {
  user: User;
  /** Null when they were given a temporary password instead (11.2). */
  invite_link: string | null;
}

/** Either kind of single-use link, ready to hand over. */
interface Handoff {
  message: string;
  link: string;
}

const ROLES = ['agent', 'manager', 'admin'] as const;

export default function Users() {
  const { user: me, can } = useAuth();

  const [users, setUsers] = useState<User[] | null>(null);
  const [teams, setTeams] = useState<Team[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [inviting, setInviting] = useState(false);
  const [handoff, setHandoff] = useState<Handoff | null>(null);
  useOpenFromUrl('invite', () => setInviting(true));

  //: Narrowing the roster. Client-side over the whole list — see
  //: `peopleFilter.ts` for why there is no pagination behind it.
  // Seeded from the address, so a link from Home — "350 agents on no team" —
  // opens on exactly those people rather than all of them (review §7).
  const [searchParams] = useSearchParams();
  const [filters, setFilters] = useState<Filters>(() => ({
    ...NO_FILTERS,
    team: searchParams.get('team') === 'none' ? NO_TEAM : (searchParams.get('team') ?? ''),
    role: searchParams.get('role') ?? '',
  }));
  // Fifty at a time: 450 rows at once was a page to scroll, not to read.
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [selecting, setSelecting] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());

  // Which half of the page is showing. Still two toggle buttons rather than two
  // routes — it is the same subject, who is in here, seen two ways — but the
  // choice now lives in the query string.
  //
  // **Because somewhere else needs to link straight at it.** The Integrations
  // panel offers "choose who syncs and how they are placed", and landing that on
  // the people list leaves somebody to find the right tab themselves, having just
  // been told they were being taken to it. Replacing rather than pushing, so the
  // back button leaves the page instead of walking back through tabs.
  const [params, setParams] = useSearchParams();
  const showing: 'people' | 'directory' =
    params.get('tab') === 'directory' ? 'directory' : 'people';
  const setShowing = (next: 'people' | 'directory') =>
    setParams(
      (current) => {
        const updated = new URLSearchParams(current);
        // The default stays out of the URL, so the plain /users is the people
        // list rather than a redirect to a decorated version of itself.
        if (next === 'people') updated.delete('tab');
        else updated.set('tab', next);
        return updated;
      },
      { replace: true },
    );

  //: Which roster. **Sub-tabs rather than checkboxes**, because these are three
  //: different lists rather than extra rows in one — each has its own actions,
  //: its own count, and nothing useful to say interleaved with the others.
  //:
  //: Three because there are three reasons somebody is not on the active list,
  //: and lumping them together loses the only thing worth knowing. *Hidden* is a
  //: decision an admin made and can undo. *Deactivated* is the directory
  //: reporting the account turned off, which reverses itself when the directory
  //: changes its mind — nobody here did it, and nobody here has to undo it.
  //:
  //: In the query string, like the tab above it, so it can be linked and so the
  //: back button behaves.
  const roster: Roster =
    ROSTERS.find((r) => r === params.get('roster')) ?? 'active';
  const setRoster = (next: Roster) =>
    setParams(
      (current) => {
        const updated = new URLSearchParams(current);
        // The default stays out of the URL, so plain /users is the roster rather
        // than a redirect to a decorated version of itself.
        if (next === 'active') updated.delete('roster');
        else updated.set('roster', next);
        return updated;
      },
      { replace: true },
    );

  //: One list, used by the count, by "select all shown" and by the table — so
  //: those three can never disagree about who is on screen, which is what would
  //: make a bulk action hit somebody nobody could see.
  //:
  //: **Declared below `roster`, and that is not cosmetic.** These sat above it
  //: once, which is a temporal dead zone TypeScript cannot see: the reference is
  //: inside the `filter` callback rather than in the same scope, so the compiler
  //: assumes it might run later. It does not — `filter` calls it immediately —
  //: and the page rendered blank.
  //:
  //: The server already filtered to this roster; this is belt and braces for the
  //: moment between switching tabs and the fetch landing, when `users` still
  //: holds the previous roster.
  const roll = (users ?? []).filter((u) => rosterOf(u) === roster);
  const shown = applyFilters(roll, filters);

  // Read once so the tab can carry a count. `null` until it loads, and absent
  // entirely for a deployment with no directory — most of them.
  const [sync, setSync] = useState<DirectoryStatus | null>(null);

  useEffect(() => {
    directory
      .status()
      .then(setSync)
      // Silent on purpose: an agent-shaped 403, or a build with no directory at
      // all, is not an error worth putting a red box on the users page for.
      .catch(() => setSync(null));
  }, []);

  // A manager may move people, but only onto their own team — the API returns
  // 403 for anything else. Offering the full list and letting the save fail
  // would be a worse control than offering only what will work.
  const assignable = can('teams.manage')
    ? teams
    : teams.filter((t) => t.id === me?.team_id);

  const load = useCallback(async () => {
    try {
      // Both in parallel — the team list is needed to render the dropdown on
      // every row, so fetching it after the users would just add a round trip.
      const [u, t] = await Promise.all([
        api<User[]>(`/api/users?roster=${roster}`),
        api<Team[]>('/api/teams'),
      ]);
      setUsers(u);
      setTeams(t);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load users.');
    }
  }, [roster]);

  // Selection is of people, and no two rosters share an action — an unhide
  // aimed at somebody who is no longer on screen is the one way this could do
  // damage quietly.
  useEffect(() => {
    setSelected(new Set());
    setSelecting(false);
  }, [roster]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <>
      <PageHeader
        title="Users"
        description="Invite people and manage their access."
        actions={
          <Can do="users.invite">
            <button
              onClick={() => setInviting((v) => !v)}
              className="rounded-md bg-brand px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover"
            >
              {inviting ? 'Cancel' : 'Invite someone'}
            </button>
          </Can>
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

      {inviting && (
        <InviteForm
          canChooseRole={can('users.manage_roles')}
          canSetPassword={can('users.reset_password')}
          onDone={async (result, password) => {
            setHandoff(
              result.invite_link === null
                ? {
                    message: `${result.user.full_name} is set up. Hand them this password — they choose their own when they sign in.`,
                    link: password,
                  }
                : {
                    message: handoffMessage(
                      'invitation',
                      { name: result.user.full_name, email: result.user.email },
                      result,
                    ),
                    link: result.invite_link,
                  },
            );
            setInviting(false);
            await load();
          }}
          onError={setError}
        />
      )}

      {handoff && (
        <HandoffLink
          message={handoff.message}
          link={handoff.link}
          onDismiss={() => setHandoff(null)}
        />
      )}

      {/* Admins only: hiding is theirs, and the suggestion is about everyone. */}
      {me?.org_role === 'admin' && <NonPeopleReview onHidden={load} />}

      {/* Only for somebody who could act on it. An agent seeing a tab that 403s
          is worse than an agent not knowing it exists. */}
      {sync !== null && (
        <div className="mt-4 flex flex-wrap gap-1">
          <Tab
            active={showing === 'people'}
            onClick={() => setShowing('people')}
          >
            People
          </Tab>
          <Tab
            active={showing === 'directory'}
            onClick={() => setShowing('directory')}
          >
            Directory sync
            {badge(sync) !== null && (
              <span className="ml-2 rounded-full bg-warning/15 px-1.5 py-0.5 text-xs text-warning">
                {badge(sync)}
              </span>
            )}
          </Tab>
        </div>
      )}

      {showing === 'directory' && sync !== null && (
        <DirectoryPanel
          teams={teams.map((t) => ({ id: t.id, name: t.name }))}
          onPeopleChanged={() => {
            void load();
            directory
              .status()
              .then(setSync)
              .catch(() => undefined);
          }}
        />
      )}

      {showing === 'people' &&
        (users === null ? (
          <Loading />
        ) : (
          <>
            {/* Nested one level under the page's own tabs, and styled quieter for
              it: two rows of equally loud tabs would read as two questions of
              equal weight, when the second is a corner of the first.

              **Always rendered once loading is done, even for an empty roster.**
              There used to be a `users.length === 0` branch above this that
              replaced the whole block with "No users yet" — fine while the server
              returned everybody and the roster was a client-side filter, and a
              dead end the moment it stopped: opening Hidden with nobody in it
              removed the tabs, so there was no way back to Active except editing
              the URL. An empty roster is a normal state of a working page, not
              an empty page. */}
            <div className="mt-6 flex gap-1 border-b border-edge">
              {ROSTERS.map((each) => (
                <RosterTab
                  key={each}
                  active={roster === each}
                  onClick={() => setRoster(each)}
                >
                  {ROSTER_COPY[each].tab}
                </RosterTab>
              ))}
            </div>

            {/* Said on the roster it applies to rather than in a tooltip, because
              the difference between these two is the whole reason there are two
              tabs — and it is the difference between "somebody decided this" and
              "your directory did this". */}
            {ROSTER_COPY[roster].blurb && (
              <p className="mt-3 max-w-3xl text-sm text-content-muted">
                {ROSTER_COPY[roster].blurb}
              </p>
            )}

            <PeopleToolbar
              people={roll}
              filters={filters}
              onFilters={(next) => {
                setFilters(next);
                setLimit(PAGE_SIZE);
                // Selection is of *people*, not of rows — but a selection that
                // survives a filter change is a bulk action on people somebody can
                // no longer see, which is the one way this feature could do real
                // damage quietly.
                setSelected(new Set());
              }}
              selecting={selecting}
              onSelecting={(on) => {
                setSelecting(on);
                if (!on) setSelected(new Set());
              }}
              shown={shown.length}
            />

            {selecting && (
              <BulkBar
                ids={[...selected]}
                allShown={
                  shown.length > 0 && shown.every((u) => selected.has(u.id))
                }
                onSelectAll={(on) =>
                  setSelected(on ? new Set(shown.map((u) => u.id)) : new Set())
                }
                onDone={() => {
                  setSelected(new Set());
                  void load();
                }}
                roster={roster}
                teams={assignable}
              />
            )}

            {shown.length === 0 ? (
              <div className="mt-6">
                <EmptyState
                  title={
                    isNarrowed(filters)
                      ? 'Nobody matches'
                      : ROSTER_COPY[roster].empty
                  }
                  description={
                    isNarrowed(filters)
                      ? 'Clear the filters, or search for somebody else.'
                      : roster === 'active'
                        ? 'Invite somebody, or sync them from your directory.'
                        : 'An empty list here is the good outcome.'
                  }
                />
              </div>
            ) : (
              <div className="mt-4 overflow-x-auto rounded-lg border border-edge bg-surface">
                <table className="gg-stack w-full text-sm">
                  <thead>
                    <tr className="border-b border-edge text-left text-caption uppercase tracking-wide text-content-subtle">
                      {selecting && <th className="w-10 px-4 py-3" />}
                      <th className="px-4 py-3 font-medium">Name</th>
                      <th className="px-4 py-3 font-medium">Title</th>
                      <th className="px-4 py-3 font-medium">Department</th>
                      <th className="px-4 py-3 font-medium">Team</th>
                      <th className="px-4 py-3 font-medium">Role</th>
                      <th className="px-4 py-3 font-medium">Status</th>
                      <th className="px-4 py-3" />
                    </tr>
                  </thead>
                  <tbody>
                    {shown.slice(0, limit).map((u) => (
                      <tr
                        key={u.id}
                        className={`border-b border-edge last:border-0 ${
                          u.hidden || u.deactivated ? 'opacity-60' : ''
                        }`}
                      >
                        {selecting && (
                          <td data-primary className="px-4 py-3">
                            <input
                              type="checkbox"
                              aria-label={`Select ${u.full_name}`}
                              checked={selected.has(u.id)}
                              onChange={(e) =>
                                setSelected((current) => {
                                  const next = new Set(current);
                                  if (e.target.checked) next.add(u.id);
                                  else next.delete(u.id);
                                  return next;
                                })
                              }
                              className="size-4 accent-[var(--gg-brand)]"
                            />
                          </td>
                        )}
                        <td data-primary className="px-4 py-3">
                          {/* **The avatar is always there, photo or not.** Showing
                            one only for people who have a photograph makes the
                            names jag left and right down the column, and turns
                            "no photo" into something the layout announces. The
                            initials occupy the same circle. */}
                          <div className="flex items-center gap-3">
                            <Avatar
                              name={u.full_name}
                              digest={u.photo_digest}
                            />
                            <div className="min-w-0">
                              <p className="truncate text-content">
                                {u.full_name}
                              </p>
                              <p className="truncate text-xs text-content-subtle">
                                {u.email}
                              </p>
                            </div>
                          </div>
                        </td>
                        <td data-label="Title" className="px-4 py-3 text-content-muted">
                          {u.job_title || '—'}
                        </td>
                        <td data-label="Department" className="px-4 py-3 text-content-muted">
                          {u.department || '—'}
                        </td>
                        <td data-label="Team" className="px-4 py-3">
                          {/* Muted, not orange. Hundreds of people on no team
                              is a list, not an alarm — warning colour is kept
                              for things somebody has to act on (review §5). */}
                          <span
                            className={
                              u.team_name
                                ? 'text-content-muted'
                                : 'italic text-content-subtle'
                            }
                          >
                            {u.team_name ?? 'No team'}
                          </span>
                        </td>
                        <td data-label="Role" className="px-4 py-3 text-content-muted">
                          {capitalised(u.org_role)}
                        </td>
                        <td data-label="Status" className="px-4 py-3">
                          {/* Hidden first, because it is the decision somebody
                            made and outranks whatever the directory reports. */}
                          <StatusBadge
                            status={
                              u.hidden
                                ? 'hidden'
                                : u.deactivated
                                  ? 'deactivated'
                                  : u.status === 'suspended'
                                    ? 'suspended'
                                    : u.invite_pending || u.awaiting_first_sign_in
                                    ? 'invited'
                                    : u.status
                            }
                          />
                        </td>
                        <td data-actions className="px-4 py-3">
                          <div className="flex items-center justify-end gap-1">
                            {/* One button, and only one. Resending an invitation
                              lives in the editor with everything else somebody
                              does to one person — on a list of four hundred it
                              was four hundred mail icons. */}
                            {/* **A link again, as it was.** The dialog that briefly
                              replaced this held half of what somebody wants when
                              they open a person — role and team but not walk-up
                              media — so opening one meant guessing which half you
                              would get. Everything about one person is on one
                              page now. */}
                            <IconButton
                              label={`Edit ${u.full_name}`}
                              icon={<PencilIcon className="size-4" />}
                              to={`/users/${u.id}`}
                            />
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {shown.length > limit && (
              <div className="mt-3 flex items-center gap-3 text-sm">
                <span className="text-content-muted">
                  Showing {limit} of {shown.length}
                </span>
                <button
                  type="button"
                  onClick={() => setLimit((n) => n + PAGE_SIZE)}
                  className="rounded-md border border-edge px-3 py-1.5 text-content hover:bg-surface-hover"
                >
                  Show {Math.min(PAGE_SIZE, shown.length - limit)} more
                </button>
                <button
                  type="button"
                  onClick={() => setLimit(shown.length)}
                  className="text-content-muted hover:text-content"
                >
                  Show all
                </button>
              </div>
            )}
          </>
        ))}
    </>
  );
}

function StatusBadge({ status }: { status: string }) {
  const style =
    status === 'active'
      ? 'bg-success/15 text-success'
      : status === 'invited'
        ? 'bg-warning/15 text-warning'
        : // Hidden and deactivated both read as "not participating", which is the
          // honest grouping: one is a decision and the other is a fact, and the
          // tab somebody is standing on already says which.
          'bg-surface-raised text-content-muted';
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs ${style}`}>
      {capitalised(status)}
    </span>
  );
}

function InviteForm({
  canChooseRole,
  canSetPassword,
  onDone,
  onError,
}: {
  canChooseRole: boolean;
  /** Admins may set a temporary password instead of sending a link (11.2). */
  canSetPassword: boolean;
  onDone: (result: InviteResult, password: string) => void | Promise<void>;
  onError: (message: string) => void;
}) {
  const [email, setEmail] = useState('');
  const [fullName, setFullName] = useState('');
  const [role, setRole] = useState<string>('agent');
  const [how, setHow] = useState<'link' | 'password'>('link');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const byPassword = canSetPassword && how === 'password';

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    onError('');
    try {
      const result = await api<InviteResult>('/api/users/invite', {
        method: 'POST',
        body: JSON.stringify({
          email,
          full_name: fullName,
          org_role: role,
          ...(byPassword ? { temporary_password: password } : {}),
        }),
      });
      setEmail('');
      setFullName('');
      setPassword('');
      await onDone(result, password);
    } catch (err) {
      onError(
        err instanceof Error ? err.message : 'Could not send invitation.',
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={submit}
      className="mt-2 rounded-lg border border-edge bg-surface p-6"
    >
      <div className="grid gap-4 sm:grid-cols-3">
        <Field
          label="Full name"
          value={fullName}
          onChange={setFullName}
          autoFocus
        />
        <Field label="Email" type="email" value={email} onChange={setEmail} />
        <div>
          <label htmlFor="role" className="block text-sm text-content-muted">
            Role
          </label>
          <select
            id="role"
            value={role}
            onChange={(e) => setRole(e.target.value)}
            className="mt-1 w-full rounded-md border border-edge bg-bg px-3 py-2 text-content outline-none focus:border-brand"
          >
            {/* A manager may only invite agents. Enforced by the API too — this
                just avoids offering an option that would be rejected. */}
            {(canChooseRole ? ROLES : (['agent'] as const)).map((r) => (
              <option key={r} value={r}>
                {capitalised(r)}
              </option>
            ))}
          </select>
        </div>
      </div>
      {/* **Two ways in** (11.2): a link they open themselves, or a password
          you hand them — for somebody standing next to you, or a deployment
          with no mail server. Admins only. */}
      {canSetPassword && (
        <fieldset className="mt-4">
          <legend className="text-sm text-content-muted">How they get in</legend>
          <div className="mt-1 flex flex-wrap gap-4 text-sm text-content">
            <label className="flex items-center gap-2">
              <input type="radio" name="how" checked={how === 'link'} onChange={() => setHow('link')} />
              Send a link to set their password
            </label>
            <label className="flex items-center gap-2">
              <input
                type="radio"
                name="how"
                checked={how === 'password'}
                onChange={() => setHow('password')}
              />
              Set a temporary password
            </label>
          </div>
        </fieldset>
      )}
      {byPassword && (
        <div className="mt-4 max-w-sm">
          <TemporaryPasswordField value={password} onChange={setPassword} />
        </div>
      )}
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          type="submit"
          disabled={
            busy || !email || !fullName || (byPassword && (!password || passwordProblem(password) !== null))
          }
          className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
        >
          {busy ? 'Creating…' : byPassword ? 'Create account' : 'Create invitation'}
        </button>
        <MissingHint
          checks={[
            [!fullName, 'Enter their name.'],
            [!email, 'Enter their email.'],
            [byPassword && !password, 'Enter a temporary password, or suggest one.'],
          ]}
        />
      </div>
      {!byPassword && (
        <p className="mt-2 text-xs text-content-muted">
          They choose their own password from the link — you never set it for
          them.
        </p>
      )}
    </form>
  );
}

/**
 * Narrowing the roster, and acting on several people at once.
 *
 * **Client-side over the whole list.** An organization is hundreds of people, so
 * one fetch makes the filters instant and the counts honest — "12 of 574" needs
 * no round trip, and *select all shown* means exactly what it says rather than
 * "all on this page". The same choice the product this was modelled on made.
 *
 * **Select mode is a toggle, not always-on.** Checkboxes down the side of every
 * row, permanently, make a list read like a form to be filled in. Pressing
 * *Select* is one click and it earns the clutter for as long as it is wanted.
 */
function PeopleToolbar({
  people,
  filters,
  onFilters,
  selecting,
  onSelecting,
  shown,
}: {
  /** The roster on screen, for building dropdowns from values somebody has. */
  people: User[];
  filters: Filters;
  onFilters: (next: Filters) => void;
  selecting: boolean;
  onSelecting: (on: boolean) => void;
  /** How many survive the filters, for the count beside the search. */
  shown: number;
}) {
  const set = <K extends keyof Filters>(key: K, value: Filters[K]) =>
    onFilters({ ...filters, [key]: value });

  return (
    <div className="mt-6 flex flex-wrap items-end gap-3">
      <div className="min-w-52 flex-1">
        <Field
          label="Search"
          value={filters.search}
          onChange={(v) => set('search', v)}
          placeholder="Name or email"
        />
      </div>

      <FilterFold
        active={
          [filters.job_title, filters.department, filters.team, filters.role, filters.office_location]
            .filter(Boolean).length
        }
      >
      {/* **Searchable, like the sync rules' condition boxes.** A tenant of six
          hundred has forty job titles, and a plain select is a scroll rather than
          a question. Each option carries its headcount, so "how much will this
          narrow it" is answered before the click.

          Typeable for the same reason as there: what somebody types that matches
          nothing is worth saying so about, rather than silently offering them the
          nearest thing. */}
      <div className="min-w-44">
        <Combobox
          label="Job title"
          value={filters.job_title}
          onChange={(v) => set('job_title', v)}
          options={optionsFor(people, 'job_title')}
          placeholder="Any title"
        />
      </div>
      <div className="min-w-44">
        <Combobox
          label="Department"
          value={filters.department}
          onChange={(v) => set('department', v)}
          options={optionsFor(people, 'department')}
          placeholder="Any department"
        />
      </div>
      <div className="min-w-40">
        <Select
          label="Team"
          value={filters.team}
          onChange={(v) => set('team', v)}
          options={[
            { value: '', label: 'Any team' },
            { value: NO_TEAM, label: 'No team' },
            ...[...new Set(people.map((p) => p.team_name).filter((t): t is string => !!t))]
              .sort()
              .map((t) => ({ value: t, label: t })),
          ]}
        />
      </div>
      <div className="min-w-32">
        <Select
          label="Role"
          value={filters.role}
          onChange={(v) => set('role', v)}
          options={[
            { value: '', label: 'Any role' },
            { value: 'agent', label: 'Agent' },
            { value: 'manager', label: 'Manager' },
            { value: 'admin', label: 'Admin' },
          ]}
        />
      </div>
      <div className="min-w-44">
        <Combobox
          label="Office"
          value={filters.office_location}
          onChange={(v) => set('office_location', v)}
          options={optionsFor(people, 'office_location')}
          placeholder="Any office"
        />
      </div>
      </FilterFold>

      <div className="flex items-center gap-2">
        {isNarrowed(filters) && (
          <button
            type="button"
            onClick={() => onFilters(NO_FILTERS)}
            className="rounded-md px-3 py-2 text-sm text-content-muted transition-colors hover:text-content"
          >
            Clear ({shown})
          </button>
        )}
        <button
          type="button"
          onClick={() => onSelecting(!selecting)}
          className={`rounded-md border px-3 py-2 text-sm transition-colors ${
            selecting
              ? 'border-brand text-brand'
              : 'border-edge text-content-muted hover:text-content'
          }`}
        >
          {selecting ? 'Done' : 'Select'}
        </button>
      </div>
    </div>
  );
}

/**
 * What to do with the people who are ticked.
 *
 * **Only ever archive and restore.** Role and team are per-person decisions —
 * "make these two hundred managers" is not a thing anybody means — and suspend
 * duplicates archive closely enough that offering both here would be offering a
 * choice nobody can make confidently. See the discussion note in the message
 * accompanying this change.
 *
 * The count is in the button, because "Hide" beside a selection of two hundred
 * is the one place a mis-click is expensive.
 */
function BulkBar({
  ids,
  allShown,
  onSelectAll,
  onDone,
  roster,
  teams,
}: {
  ids: number[];
  /** For the team assignment, which is the whole reason to filter first. */
  teams: Team[];
  allShown: boolean;
  onSelectAll: (on: boolean) => void;
  onDone: () => void;
  /**
   * Which roster is on screen.
   *
   * **It decides what is offered.** No two of
   * these share an action: hiding somebody already hidden does nothing, and
   * offering it would be offering a button whose only outcome is "0 changed".
   */
  roster: Roster;
}) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function run(
    action: 'hide' | 'unhide' | 'reactivate' | 'assign_team' | 'set_role',
    extra: { team_id?: number | null; role?: string } = {},
    describe = '',
  ) {
    const many = `${ids.length} ${ids.length === 1 ? 'person' : 'people'}`;
    // Confirmed for every action, because the number is the dangerous part: the
    // difference between re-teaming three people and three hundred is one
    // checkbox, and the button carries the count for the same reason.
    if (!await ask(`${describe} — ${many}?`)) return;

    setBusy(true);
    setNote(null);
    try {
      const result = await api<{ changed: number; skipped: string[] }>(
        '/api/users/bulk',
        { method: 'POST', body: JSON.stringify({ ids, action, ...extra }) },
      );
      // **Partial success is the normal case**, not an edge one: any large
      // selection contains the actor themselves. Saying only "done" would hide
      // who was left behind, and there is no second screen to find that out on.
      setNote(
        result.skipped.length
          ? `${result.changed} changed. Left alone: ${result.skipped.join('; ')}.`
          : null,
      );
      onDone();
    } catch (e) {
      setNote(e instanceof Error ? e.message : 'Could not do that.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-3 rounded-md border border-brand/40 bg-brand/5 px-3 py-2">
      <div className="flex flex-wrap items-center gap-4">
        <label className="flex items-center gap-2 text-sm text-content">
          <input
            type="checkbox"
            checked={allShown}
            onChange={(e) => onSelectAll(e.target.checked)}
            className="size-4 accent-[var(--gg-brand)]"
          />
          Select all shown
        </label>
        <span className="text-sm text-content-muted">
          {ids.length} selected
        </span>
        <div className="ml-auto flex flex-wrap items-end gap-2">
          {roster === 'hidden' ? (
            <button
              type="button"
              onClick={() =>
                void run(
                  'unhide',
                  {},
                  'Unhide — they come back suspended, so letting them in stays separate',
                )
              }
              disabled={busy || ids.length === 0}
              className="rounded-md border border-edge px-3 py-1.5 text-sm text-content transition-colors hover:bg-surface-hover disabled:opacity-40"
            >
              {busy ? 'Working…' : `Unhide ${ids.length || ''}`}
            </button>
          ) : roster === 'deactivated' ? (
            <button
              type="button"
              onClick={() =>
                void run(
                  'reactivate',
                  {},
                  'Reactivate — undoes what the directory did, not a suspension',
                )
              }
              disabled={busy || ids.length === 0}
              className="rounded-md border border-edge px-3 py-1.5 text-sm text-content transition-colors hover:bg-surface-hover disabled:opacity-40"
            >
              {busy ? 'Working…' : `Reactivate ${ids.length || ''}`}
            </button>
          ) : (
            <>
              {/* **The point of filtering, really.** "Everybody in Sales at
                  Phoenix onto the Phoenix Sales team" becomes three dropdowns and
                  one press, where before it was a dropdown per row. */}
              <Select
                label=""
                value=""
                onChange={(v) =>
                  void run(
                    'assign_team',
                    { team_id: v === 'none' ? null : Number(v) },
                    v === 'none'
                      ? 'Remove from their team'
                      : `Move onto ${teams.find((t) => String(t.id) === v)?.name}`,
                  )
                }
                options={[
                  { value: '', label: 'Assign team…' },
                  ...teams.map((t) => ({ value: String(t.id), label: t.name })),
                  { value: 'none', label: '— unassign —' },
                ]}
              />
              <Select
                label=""
                value=""
                onChange={(v) =>
                  void run('set_role', { role: v }, `Set role to ${v}`)
                }
                options={[
                  { value: '', label: 'Set role…' },
                  ...ROLES.map((r) => ({ value: r, label: r })),
                ]}
              />
              <button
                type="button"
                onClick={() =>
                  void run(
                    'hide',
                    {},
                    'Hide — off every leaderboard, history kept, one click back',
                  )
                }
                disabled={busy || ids.length === 0}
                className="rounded-md border border-danger px-3 py-1.5 text-sm text-danger transition-colors hover:bg-danger/10 disabled:opacity-40"
              >
                {busy ? 'Working…' : `Hide ${ids.length || ''}`}
              </button>
            </>
          )}
        </div>
      </div>
      {note && (
        <p className="mt-2 text-sm text-content-muted" role="status">
          {note}
        </p>
      )}
    </div>
  );
}

/**
 * One of the two rosters.
 *
 * Its own component rather than the page's `Tab`, and deliberately quieter: this
 * sits *inside* a tab, and two rows of equally loud tabs read as two questions of
 * equal weight when the second is a corner of the first.
 */
function RosterTab({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-current={active ? 'page' : undefined}
      className={`-mb-px border-b-2 px-3 py-2 text-sm transition-colors ${
        active
          ? 'border-brand text-content'
          : 'border-transparent text-content-muted hover:text-content'
      }`}
    >
      {children}
    </button>
  );
}
