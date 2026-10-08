import { useEffect, useState } from 'react';

import { api, ApiError } from '../api';
import { toast } from '../toast';

interface Person {
  id: number;
  full_name: string;
  email: string;
  department: string;
}

interface Team {
  id: number;
  name: string;
  office_id: number | null;
  archived?: boolean;
}

/**
 * The people in an office who aren't on a team yet (Phase 28): each one put
 * on a team, or a new team in this office made for all of them.
 */
export default function UnteamedPeople({
  officeId,
  officeName,
  onChanged,
}: {
  officeId: number;
  officeName: string;
  onChanged: () => void;
}) {
  const [people, setPeople] = useState<Person[] | null>(null);
  const [teams, setTeams] = useState<Team[]>([]);
  const [newName, setNewName] = useState('');
  const [busy, setBusy] = useState(false);

  async function load() {
    const [found, all] = await Promise.all([
      api<Person[]>(`/api/offices/${officeId}/unteamed`),
      api<Team[]>('/api/teams'),
    ]);
    setPeople(found);
    // This office's teams first: where they most likely belong.
    setTeams(
      all
        .filter((t) => !t.archived)
        .sort((a, b) => Number(b.office_id === officeId) - Number(a.office_id === officeId) || a.name.localeCompare(b.name)),
    );
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [officeId]);

  async function work(fn: () => Promise<unknown>, done: string) {
    setBusy(true);
    try {
      await fn();
      toast(done);
      await load();
      onChanged();
    } catch (e) {
      toast(e instanceof ApiError ? e.message : 'Couldn’t do that.');
    } finally {
      setBusy(false);
    }
  }

  const place = (ids: number[], teamId: number) =>
    Promise.all(ids.map((id) => api(`/api/users/${id}`, { method: 'PATCH', body: JSON.stringify({ team_id: teamId }) })));

  if (!people) return <p className="mt-2 text-xs text-content-subtle">Loading…</p>;
  if (people.length === 0) return <p className="mt-2 text-xs text-content-subtle">Everyone here is on a team.</p>;

  return (
    <div className="mt-3 space-y-2 rounded-md border border-edge bg-surface-raised p-3">
      <ul className="max-h-64 space-y-1.5 overflow-y-auto">
        {people.map((p) => (
          <li key={p.id} className="flex items-center gap-2 text-sm">
            <span className="min-w-0 flex-1 truncate text-content" title={p.email}>
              {p.full_name}
              {p.department && <span className="ml-1 text-xs text-content-subtle">{p.department}</span>}
            </span>
            <select
              aria-label={`Team for ${p.full_name}`}
              disabled={busy}
              value=""
              onChange={(e) => {
                const team = teams.find((t) => t.id === Number(e.target.value));
                if (team) void work(() => place([p.id], team.id), `${p.full_name} → ${team.name}`);
              }}
              className="w-36 rounded-md border border-edge bg-bg px-2 py-1 text-xs text-content"
            >
              <option value="">Put on a team…</option>
              {teams.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </li>
        ))}
      </ul>
      <form
        className="flex gap-2 border-t border-edge pt-2"
        onSubmit={(e) => {
          e.preventDefault();
          const name = newName.trim();
          if (!name) return;
          void work(async () => {
            const team = await api<Team>('/api/teams', {
              method: 'POST',
              body: JSON.stringify({ name, office_id: officeId }),
            });
            await place(
              people.map((p) => p.id),
              team.id,
            );
            setNewName('');
          }, `Team “${name}” made in ${officeName}`);
        }}
      >
        <input
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          placeholder="New team for all of them"
          aria-label="New team name"
          maxLength={200}
          className="min-w-0 flex-1 rounded-md border border-edge bg-bg px-2 py-1 text-xs text-content outline-none focus:border-brand"
        />
        <button
          type="submit"
          disabled={busy || !newName.trim()}
          className="rounded-md bg-brand px-2.5 py-1 text-xs font-medium text-white hover:bg-brand-hover disabled:opacity-50"
        >
          Create
        </button>
      </form>
    </div>
  );
}
