import { useCallback, useEffect, useState } from 'react';

import { api } from '../api';
import { ask } from '../confirm';
import MissingHint from './MissingHint';

interface Capability {
  key: string;
  label: string;
}

interface Member {
  id: number;
  name: string;
}

export interface Role {
  id: number;
  name: string;
  description: string | null;
  base_role: 'agent' | 'manager' | 'admin';
  removed: string[];
  members: Member[];
}

interface Catalogue {
  removable: Record<string, Capability[]>;
  roles: Role[];
}

interface Person {
  id: number;
  full_name: string;
  org_role: string;
  hidden: boolean;
}

const BASE_LABEL: Record<string, string> = { manager: 'Manager', admin: 'Admin', agent: 'Agent' };

/**
 * Custom roles: a built-in role with some things taken away.
 *
 * **Narrower, never wider**, and enforced by the server — a role here decides
 * what somebody may not do, on top of the manager or admin role they already
 * have. People join a role from here, so nothing about editing a person changes.
 */
export default function CustomRoles() {
  const [catalogue, setCatalogue] = useState<Catalogue | null>(null);
  const [people, setPeople] = useState<Person[]>([]);
  const [editing, setEditing] = useState<Role | 'new' | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api<Catalogue>('/api/roles')
      .then(setCatalogue)
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load roles.'));
  }, []);

  useEffect(() => {
    load();
    api<Person[]>('/api/users')
      .then(setPeople)
      .catch(() => setPeople([]));
  }, [load]);

  async function change(path: string, init: RequestInit) {
    setError(null);
    try {
      await api(path, init);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That did not work.');
    }
  }

  if (!catalogue) {
    return error ? <p role="alert" className="text-sm text-danger">{error}</p> : null;
  }

  const labelOf = (base: string, key: string) =>
    catalogue.removable[base]?.find((c) => c.key === key)?.label ?? key;

  return (
    <section className="mt-8 rounded-lg border border-edge bg-surface p-6">
      <h2 className="text-sm font-medium text-content">Roles</h2>
      <p className="mt-1 text-sm text-content-muted">
        A manager or admin with some things taken away — a team lead who cannot run competitions,
        an admin who only reads reports. The server enforces it, and what they can see is the same
        as their built-in role.
      </p>

      {error && (
        <p role="alert" className="mt-3 rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      {catalogue.roles.length > 0 && (
        <ul className="mt-4 divide-y divide-edge rounded-md border border-edge">
          {catalogue.roles.map((role) => {
            const candidates = people.filter(
              (p) => !p.hidden && p.org_role === role.base_role && !role.members.some((m) => m.id === p.id),
            );
            return (
              <li key={role.id} className="px-4 py-3">
                <div className="flex flex-wrap items-baseline justify-between gap-3">
                  <span className="text-content">
                    {role.name}
                    <span className="ml-2 text-xs text-content-subtle">{BASE_LABEL[role.base_role]}, without:</span>
                  </span>
                  <span className="flex gap-3 text-sm">
                    <button type="button" onClick={() => setEditing(role)} className="text-content-muted hover:text-content">
                      Edit
                    </button>
                    <button
                      type="button"
                      onClick={async () => {
                        if (await ask(`Delete “${role.name}”? Its people go back to their built-in role.`)) {
                          void change(`/api/roles/${role.id}`, { method: 'DELETE' });
                        }
                      }}
                      className="text-content-muted hover:text-danger"
                    >
                      Delete
                    </button>
                  </span>
                </div>
                <p className="mt-0.5 text-xs text-content-muted">
                  {role.removed.map((key) => labelOf(role.base_role, key)).join(' · ')}
                </p>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  {role.members.map((m) => (
                    <span key={m.id} className="inline-flex items-center gap-1 rounded-full bg-surface-raised px-2 py-0.5 text-xs text-content">
                      {m.name}
                      <button
                        type="button"
                        aria-label={`Take ${m.name} out of ${role.name}`}
                        onClick={() => void change(`/api/roles/${role.id}/members/${m.id}`, { method: 'DELETE' })}
                        className="text-content-muted hover:text-danger"
                      >
                        ×
                      </button>
                    </span>
                  ))}
                  {candidates.length > 0 && (
                    <select
                      value=""
                      aria-label={`Add somebody to ${role.name}`}
                      onChange={(e) =>
                        e.target.value &&
                        void change(`/api/roles/${role.id}/members`, {
                          method: 'POST',
                          body: JSON.stringify({ user_id: Number(e.target.value) }),
                        })
                      }
                      className="rounded-md border border-edge bg-bg px-2 py-1 text-xs text-content"
                    >
                      <option value="">Add a {role.base_role}…</option>
                      {candidates.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.full_name}
                        </option>
                      ))}
                    </select>
                  )}
                </div>
                {editing !== 'new' && editing?.id === role.id && (
                  <RoleForm
                    role={role}
                    removable={catalogue.removable}
                    onClose={() => setEditing(null)}
                    onSaved={() => {
                      setEditing(null);
                      load();
                    }}
                  />
                )}
              </li>
            );
          })}
        </ul>
      )}

      {editing === 'new' ? (
        <RoleForm
          removable={catalogue.removable}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            load();
          }}
        />
      ) : (
        <button
          type="button"
          onClick={() => setEditing('new')}
          className="mt-4 rounded-md border border-edge px-4 py-2 text-sm text-content hover:border-brand"
        >
          New role
        </button>
      )}
    </section>
  );
}

function RoleForm({
  role,
  removable,
  onClose,
  onSaved,
}: {
  role?: Role;
  removable: Record<string, Capability[]>;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(role?.name ?? '');
  const [base, setBase] = useState<Role['base_role']>(role?.base_role ?? 'manager');
  const [removed, setRemoved] = useState<string[]>(role?.removed ?? []);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const options = removable[base] ?? [];

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await api(role ? `/api/roles/${role.id}` : '/api/roles', {
        method: role ? 'PATCH' : 'POST',
        body: JSON.stringify({ name, base_role: base, removed: removed.filter((k) => options.some((o) => o.key === k)) }),
      });
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mt-3 space-y-4 rounded-md border border-edge bg-surface-hover p-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block">
          <span className="text-sm text-content-muted">Name</span>
          <input
            value={name}
            maxLength={60}
            onChange={(e) => setName(e.target.value)}
            placeholder="Team lead"
            className="mt-1 w-full rounded-md border border-edge bg-bg px-3 py-2 text-sm text-content"
          />
        </label>
        <label className="block">
          <span className="text-sm text-content-muted">Based on</span>
          <select
            value={base}
            onChange={(e) => {
              setBase(e.target.value as Role['base_role']);
              setRemoved([]);
            }}
            disabled={!!role && role.members.length > 0}
            className="mt-1 w-full rounded-md border border-edge bg-bg px-3 py-2 text-sm text-content"
          >
            <option value="manager">Manager</option>
            <option value="admin">Admin</option>
          </select>
        </label>
      </div>
      <fieldset>
        <legend className="text-sm text-content-muted">May not</legend>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          {options.map((option) => (
            <label key={option.key} className="flex items-center gap-2 text-sm text-content">
              <input
                type="checkbox"
                checked={removed.includes(option.key)}
                onChange={(e) =>
                  setRemoved(e.target.checked ? [...removed, option.key] : removed.filter((k) => k !== option.key))
                }
              />
              {option.label}
            </label>
          ))}
        </div>
      </fieldset>
      {error && (
        <p role="alert" className="rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => void save()}
          disabled={saving || !name.trim() || removed.length === 0}
          className="rounded-md bg-brand px-4 py-2 text-sm text-white disabled:opacity-60"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
        <MissingHint checks={[[!name.trim(), 'Name the role.'], [removed.length === 0, 'Take away at least one thing — otherwise it is the built-in role.']]} />
        <button type="button" onClick={onClose} className="rounded-md px-4 py-2 text-sm text-content-muted hover:text-content">
          Cancel
        </button>
      </div>
    </div>
  );
}
