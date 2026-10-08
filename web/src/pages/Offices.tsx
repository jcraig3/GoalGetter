import { useCallback, useEffect, useState, type FormEvent } from 'react';

import { api } from '../api';
import { useAuth } from '../auth';
import EmptyState from '../components/EmptyState';
import IconButton from '../components/IconButton';
import {
  ArchiveIcon,
  PencilIcon,
  RestoreIcon,
  TrashIcon,
} from '../components/icons';
import Field from '../components/Field';
import UnteamedPeople from '../components/UnteamedPeople';
import PageHeader from '../components/PageHeader';
import { ArchiveTabs } from '../components/Tabs';
import { ask } from '../confirm';
import Loading from '../components/Loading';
import { toast } from '../toast';
import { useFocusRow } from '../urlIntent';

interface Office {
  id: number;
  name: string;
  description: string | null;
  archived: boolean;
  team_count: number;
  agent_count: number;
  /** In the office, on no team yet (Phase 28). */
  unteamed_count?: number;
}

export default function Offices() {
  const { can } = useAuth();
  const canManage = can('offices.manage');

  const [offices, setOffices] = useState<Office[] | null>(null);
  const [showArchived, setShowArchived] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [renaming, setRenaming] = useState<Office | null>(null);
  const [busy, setBusy] = useState(false);
  useFocusRow(offices !== null);

  // Whose "not on a team" list is open (Phase 28).
  const [placing, setPlacing] = useState<number | null>(null);
  const load = useCallback(async () => {
    try {
      // `include_archived` means "both", which is right for a checkbox and
      // wrong for a tab: the archived tab was showing active offices too.
      // Narrowed here rather than in the API, because the parameter has a
      // second caller that genuinely wants both.
      const all = await api<Office[]>(
        `/api/offices?include_archived=${showArchived}`,
      );
      setOffices(all.filter((o) => o.archived === showArchived));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load offices.');
    }
  }, [showArchived]);

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

  async function remove(office: Office) {
    if (
      !await ask(
        `Delete "${office.name}" permanently?\n\nThis cannot be undone. Archive it instead if you may want its history later.`,
      )
    )
      return;
    void run(
      () => api(`/api/offices/${office.id}`, { method: 'DELETE' }),
      'Could not delete office.',
      'Office deleted',
    );
  }

  return (
    <>
      <PageHeader
        title="Offices"
        description="Locations. Each office holds teams, and each team holds agents."
        actions={
          canManage && (
            <button
              onClick={() => setCreating((v) => !v)}
              className="rounded-md bg-brand px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover"
            >
              {creating ? 'Cancel' : 'New office'}
            </button>
          )
        }
      />

      {error && (
        <p role="alert" className="mb-4 rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      {creating && (
        <div className="mb-4 rounded-lg border border-edge bg-surface p-4">
          <OfficeForm
            label="Office name"
            busy={busy}
            onSubmit={(name) =>
              run(async () => {
                await api('/api/offices', {
                  method: 'POST',
                  body: JSON.stringify({ name }),
                });
                setCreating(false);
              }, 'Could not create office.')
            }
            onCancel={() => setCreating(false)}
          />
        </div>
      )}

      <ArchiveTabs showArchived={showArchived} onChange={setShowArchived} />

      {offices === null ? (
        <Loading />
      ) : offices.length === 0 ? (
        <EmptyState
          title="No offices yet"
          description="Create an office, then assign teams to it from the Teams page."
        />
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {offices.map((office) => (
            <li
              key={office.id}
              id={`row-${office.id}`}
              className="group rounded-lg border border-edge bg-surface p-4"
            >
              {renaming?.id === office.id ? (
                <OfficeForm
                  label="Rename office"
                  initial={office.name}
                  busy={busy}
                  onSubmit={(name) =>
                    run(async () => {
                      await api(`/api/offices/${office.id}`, {
                        method: 'PATCH',
                        body: JSON.stringify({ name }),
                      });
                      setRenaming(null);
                    }, 'Could not rename office.')
                  }
                  onCancel={() => setRenaming(null)}
                />
              ) : (
                <>
                  <div className="flex items-start justify-between gap-2">
                    <span
                      className={office.archived ? 'text-content-muted' : 'text-content'}
                    >
                      {office.name}
                    </span>
                    {office.archived && (
                      <span className="rounded-full bg-surface-raised px-2 py-0.5 text-xs text-content-muted">
                        archived
                      </span>
                    )}
                  </div>

                  <p className="mt-2 text-sm text-content-muted">
                    {office.team_count} {office.team_count === 1 ? 'team' : 'teams'} ·{' '}
                    {office.agent_count} {office.agent_count === 1 ? 'agent' : 'agents'}
                  </p>
                  {canManage && !office.archived && (office.unteamed_count ?? 0) > 0 && (
                    <>
                      <button
                        type="button"
                        onClick={() => setPlacing(placing === office.id ? null : office.id)}
                        aria-expanded={placing === office.id}
                        className="mt-1 text-left text-xs text-warning hover:underline"
                      >
                        ⚠ {office.unteamed_count} {office.unteamed_count === 1 ? 'agent isn’t' : 'agents aren’t'} on a team
                      </button>
                      {placing === office.id && (
                        <UnteamedPeople officeId={office.id} officeName={office.name} onChanged={() => void load()} />
                      )}
                    </>
                  )}
                  {/* Unused, said so (review §7): five offices with no team
                      and nobody in them were left to be noticed. */}
                  {canManage && !office.archived && office.team_count === 0 && office.agent_count === 0 && (
                    <p className="mt-1 text-xs text-warning">Unused — archive it to tidy the pickers?</p>
                  )}

                  {canManage && (
                    // Always visible, not hover-revealed. Three text buttons were
                    // too wide to leave on screen; three icons are not, and an
                    // action you have to hover to discover is one people do not
                    // find.
                    <div className="mt-4 flex gap-1">
                      {office.archived ? (
                        <>
                          <IconButton
                            label="Restore"
                            icon={<RestoreIcon className="size-4" />}
                            onClick={() =>
                              void run(
                                () =>
                                  api(`/api/offices/${office.id}/restore`, {
                                    method: 'POST',
                                  }),
                                'Could not restore.',
                                'Office restored',
                              )
                            }
                          />
                          <IconButton
                            label="Delete"
                            icon={<TrashIcon className="size-4" />}
                            danger
                            onClick={() => remove(office)}
                          />
                        </>
                      ) : (
                        <>
                          <IconButton
                            label="Rename"
                            icon={<PencilIcon className="size-4" />}
                            onClick={() => setRenaming(office)}
                          />
                          <IconButton
                            label="Archive"
                            icon={<ArchiveIcon className="size-4" />}
                            onClick={() =>
                              void run(
                                () =>
                                  api(`/api/offices/${office.id}/archive`, {
                                    method: 'POST',
                                  }),
                                'Could not archive.',
                                'Office archived',
                              )
                            }
                          />
                          <IconButton
                            label="Delete"
                            icon={<TrashIcon className="size-4" />}
                            danger
                            onClick={() => remove(office)}
                          />
                        </>
                      )}
                    </div>
                  )}
                </>
              )}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}


function OfficeForm({
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
