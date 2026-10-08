import { useCallback, useEffect, useState, type FormEvent } from 'react';

import { api } from '../api';
import { useAuth } from '../auth';
import EmptyState from '../components/EmptyState';
import Field from '../components/Field';
import IconButton from '../components/IconButton';
import {
  ArchiveIcon,
  BuildingIcon,
  ChevronDownIcon,
  PencilIcon,
  RestoreIcon,
  TrashIcon,
} from '../components/icons';
import PageHeader from '../components/PageHeader';
import { ArchiveTabs } from '../components/Tabs';
import TeamMembers, { type Member } from '../components/TeamMembers';
import { ask } from '../confirm';
import Loading from '../components/Loading';
import { toast } from '../toast';
import TeamEditor, { Mark } from '../components/TeamEditor';
import { useFocusRow, useOpenFromUrl } from '../urlIntent';

interface Team {
  id: number;
  name: string;
  description: string | null;
  color: string | null;
  /** How a wall knows it (6.7). */
  short_name?: string | null;
  logo?: string | null;
  archived: boolean;
  member_count: number;
  office_id: number | null;
  office_name: string | null;
  /** The Microsoft Team or channel it follows, when it follows one. */
  follows?: string | null;
}

interface Office {
  id: number;
  name: string;
}

export default function Teams() {
  const { can, user } = useAuth();
  const canManage = can('teams.manage');
  // A manager sees their own team's people and nobody else's (app/scope.py),
  // so opening another team would show an empty list that looks like a fact.
  const canSeeMembers = (team: Team) =>
    canManage || (can('users.view') && user?.team_id === team.id);

  const [teams, setTeams] = useState<Team[] | null>(null);
  const [offices, setOffices] = useState<Office[]>([]);
  const [showArchived, setShowArchived] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [renaming, setRenaming] = useState<Team | null>(null);
  const [busy, setBusy] = useState(false);
  useOpenFromUrl('new', () => setCreating(true));
  useFocusRow(teams !== null);
  // One team open at a time: a list of rosters stacked open is a page nobody
  // can find the next team on.
  const [open, setOpen] = useState<number | null>(null);
  const [people, setPeople] = useState<Member[] | null>(null);

  const loadPeople = useCallback(async () => {
    try {
      setPeople(await api<Member[]>('/api/users'));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load people.');
    }
  }, []);

  function toggle(team: Team) {
    setOpen((current) => (current === team.id ? null : team.id));
    if (people === null) void loadPeople();
  }

  const load = useCallback(async () => {
    try {
      const [t, o] = await Promise.all([
        api<Team[]>(`/api/teams?include_archived=${showArchived}`),
        // Offices are admin-only; a manager viewing this page gets a 403 here,
        // which is fine — they see the office name, just no dropdown.
        api<Office[]>('/api/offices').catch(() => [] as Office[]),
      ]);
      // A tab is its own list. `include_archived` means "both", which was
      // showing active teams under Archived.
      setTeams(t.filter((x) => x.archived === showArchived));
      setOffices(o);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load teams.');
    }
  }, [showArchived]);

  const setOffice = (team: Team, officeId: number | null) =>
    run(
      () =>
        api(`/api/teams/${team.id}`, {
          method: 'PATCH',
          body: JSON.stringify({ office_id: officeId }),
        }),
      'Could not change office.',
    );

  useEffect(() => {
    void load();
  }, [load]);

  async function run(fn: () => Promise<unknown>, failure: string, success?: string) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      if (success) toast(success);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : failure);
    } finally {
      setBusy(false);
    }
  }

  const create = (name: string) =>
    run(async () => {
      await api('/api/teams', { method: 'POST', body: JSON.stringify({ name }) });
      setCreating(false);
    }, 'Could not create team.', `${name} created`);


  const archive = (team: Team) =>
    run(
      () => api(`/api/teams/${team.id}/archive`, { method: 'POST' }),
      'Could not archive team.',
      'Team archived',
    );

  const restore = (team: Team) =>
    run(
      () => api(`/api/teams/${team.id}/restore`, { method: 'POST' }),
      'Could not restore team.',
      'Team restored',
    );

  async function remove(team: Team) {
    // Deletion is permanent and, unlike archiving, cannot be undone — so it
    // asks. Archive is offered as the safer option in the wording itself.
    if (
      !await ask(
        `Delete "${team.name}" permanently?\n\nThis cannot be undone. Archive it instead if you may want its history later.`,
      )
    )
      return;
    void run(
      () => api(`/api/teams/${team.id}`, { method: 'DELETE' }),
      'Could not delete team.',
      'Team deleted',
    );
  }

  return (
    <>
      <PageHeader
        title="Teams"
        description="Group agents into teams. Leaderboards and goals can be scoped to a team."
        actions={
          canManage && (
            <button
              onClick={() => setCreating((v) => !v)}
              className="rounded-md bg-brand px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover"
            >
              {creating ? 'Cancel' : 'New team'}
            </button>
          )
        }
      />

      {error && (
        <p role="alert" className="mb-4 rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      {renaming && (
        <TeamEditor
          team={renaming}
          onClose={() => setRenaming(null)}
          onSaved={async () => {
            setRenaming(null);
            toast('Team saved');
            await load();
          }}
        />
      )}

      {creating && (
        <div className="mb-4 rounded-lg border border-edge bg-surface p-4">
          <TeamForm
            label="Team name"
            busy={busy}
            onSubmit={create}
            onCancel={() => setCreating(false)}
          />
        </div>
      )}

      <ArchiveTabs showArchived={showArchived} onChange={setShowArchived} />

      {teams === null ? (
        <Loading />
      ) : teams.length === 0 ? (
        <EmptyState
          title="No teams yet"
          description="Create a team, then assign agents to it."
        />
      ) : (
        <ul className="rounded-lg border border-edge bg-surface">
          {teams.map((team) => (
            <li
              key={team.id}
              id={`row-${team.id}`}
              // A grid rather than a flex row, so office and actions line up in
              // columns down the page. Under flex, each row's dropdown started
              // wherever that team's name happened to end — which is what made a
              // list of them look untidy, more than the control itself did.
              className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-2 border-b border-edge px-4 py-3 last:border-0 sm:grid-cols-[minmax(0,1fr)_7rem_11rem_auto]"
            >
              <>
                  {/* Wraps, so on a phone the chip goes under the name rather
                      than squeezing it to "$…" (Q2-18). */}
                  <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                    {/* How a wall knows it, beside its name (6.7). */}
                    <Mark
                      look={{ entity_name: team.name, colour: team.color, short_name: team.short_name }}
                      logo={team.logo}
                    />
                    <span
                      className={`truncate ${
                        team.archived ? 'text-content-muted' : 'text-content'
                      }`}
                    >
                      {team.name}
                    </span>
                    {team.archived && (
                      <span className="shrink-0 rounded-full bg-surface-raised px-2 py-0.5 text-xs text-content-muted">
                        archived
                      </span>
                    )}
                    {team.follows && (
                      <span
                        title={`Follows ${team.follows} in Microsoft Teams`}
                        className="shrink-0 truncate rounded-full bg-surface-raised px-2 py-0.5 text-xs text-content-muted"
                      >
                        from Microsoft Teams
                      </span>
                    )}
                  </span>

                  {canSeeMembers(team) ? (
                    <button
                      type="button"
                      onClick={() => toggle(team)}
                      aria-expanded={open === team.id}
                      className="flex items-center gap-1 text-left text-caption text-content-subtle hover:text-content"
                    >
                      <Members team={team} flag={canManage} />
                      <ChevronDownIcon
                        className={`size-3 transition-transform ${open === team.id ? 'rotate-180' : ''}`}
                      />
                    </button>
                  ) : (
                    <span className="text-caption text-content-subtle">
                      <Members team={team} flag={canManage} />
                    </span>
                  )}

                  {canManage && offices.length > 0 ? (
                    <OfficePicker
                      team={team}
                      offices={offices}
                      onChange={(officeId) => void setOffice(team, officeId)}
                    />
                  ) : (
                    <span className="truncate text-caption text-content-subtle">
                      {team.office_name}
                    </span>
                  )}

                  {canManage ? (
                    <span className="flex justify-end gap-1">
                      {team.archived ? (
                        <>
                          <IconButton
                            label="Restore"
                            icon={<RestoreIcon className="size-4" />}
                            onClick={() => void restore(team)}
                          />
                          <IconButton
                            label="Delete"
                            icon={<TrashIcon className="size-4" />}
                            danger
                            onClick={() => remove(team)}
                          />
                        </>
                      ) : (
                        <>
                          <IconButton
                            label="Edit"
                            icon={<PencilIcon className="size-4" />}
                            onClick={() => setRenaming(team)}
                          />
                          <IconButton
                            label="Archive"
                            icon={<ArchiveIcon className="size-4" />}
                            onClick={() => void archive(team)}
                          />
                          <IconButton
                            label="Delete"
                            icon={<TrashIcon className="size-4" />}
                            danger
                            onClick={() => remove(team)}
                          />
                        </>
                      )}
                    </span>
                  ) : (
                    <span />
                  )}

                  {open === team.id &&
                    (people === null ? (
                      <p className="col-span-full text-sm text-content-muted">Loading…</p>
                    ) : (
                      <TeamMembers
                        teamId={team.id}
                        teamName={team.name}
                        follows={team.follows ?? null}
                        people={people}
                        canEdit={canManage && !team.archived}
                        onChanged={() => {
                          void loadPeople();
                          void load();
                        }}
                      />
                    ))}
                </>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

/**
 * Which office a team belongs to, editable in place.
 *
 * Reads as text until you touch it — a building icon, the office name, and a
 * chevron, with the border appearing only on hover and focus. A row of fully
 * drawn dropdowns competes with the team names for attention, and the office is
 * the thing you glance at, not the thing you came for.
 *
 * **Unassigned is stated, not decorated.** The previous version outlined the
 * whole control in warning amber, which made a list of new teams look like a
 * list of errors. It is amber *text* saying "No office" instead: the same
 * information, and it stops shouting once you have read it.
 */
function OfficePicker({
  team,
  offices,
  onChange,
}: {
  team: Team;
  offices: Office[];
  onChange: (officeId: number | null) => void;
}) {
  const unassigned = team.office_id === null;

  return (
    <span className="group/office relative flex items-center">
      <BuildingIcon className="pointer-events-none absolute left-2 size-3.5 text-content-subtle" />
      <select
        value={team.office_id ?? ''}
        onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
        aria-label={`Office for ${team.name}`}
        // appearance-none to drop the platform arrow, since the icon and the
        // chevron below are drawn here. text-ellipsis matters because office
        // names are free text and "Phoenix — North Valley" is a real one.
        // A visible edge at rest: without one it read as a label, and nobody
        // found that a team's office could be changed here (review §7).
        className={`w-full appearance-none truncate rounded-md border border-edge bg-bg py-1 pl-7 pr-6 text-xs outline-none transition-colors hover:bg-surface-hover focus:border-brand ${
          unassigned ? 'italic text-content-subtle' : 'text-content-muted'
        }`}
      >
        <option value="">No office</option>
        {offices.map((office) => (
          <option key={office.id} value={office.id}>
            {office.name}
          </option>
        ))}
      </select>
      <ChevronDownIcon className="pointer-events-none absolute right-2 size-3 text-content-subtle opacity-0 transition-opacity group-hover/office:opacity-100" />
    </span>
  );
}

function TeamForm({
  label,
  initial = '',
  busy,
  onSubmit,
  onCancel,
}: {
  label: string;
  initial?: string;
  busy: boolean;
  onSubmit: (name: string) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(initial);

  function submit(e: FormEvent) {
    e.preventDefault();
    if (name.trim()) onSubmit(name.trim());
  }

  return (
    <form onSubmit={submit} className="flex w-full items-end gap-2">
      <div className="min-w-0 flex-1">
        <Field label={label} value={name} onChange={setName} autoFocus />
      </div>
      <button
        type="submit"
        disabled={busy || !name.trim()}
        className="rounded-md bg-brand px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
      >
        Save
      </button>
      <button
        type="button"
        onClick={onCancel}
        className="rounded-md border border-edge px-3 py-2 text-sm text-content-muted transition-colors hover:bg-surface-hover hover:text-content"
      >
        Cancel
      </button>
    </form>
  );
}

/**
 * "12 members", or for an admin, an empty team pointed out (review §7): a
 * Sales Team with nobody on it is usually one to archive, and said nowhere.
 */
function Members({ team, flag }: { team: Team; flag: boolean }) {
  if (team.member_count === 0 && flag && !team.archived) {
    return <span className="text-warning">Empty — archive?</span>;
  }
  return (
    <>
      {team.member_count} {team.member_count === 1 ? 'member' : 'members'}
    </>
  );
}
