import { useEffect, useState } from 'react';

import { api, ApiError } from '../api';
import { toast } from '../toast';

interface Value {
  value: string;
  people: number;
  office_id?: number | null;
  team_id?: number | null;
}

interface Places {
  offices: Value[];
  departments: Value[];
}

interface Option {
  id: number;
  name: string;
  archived?: boolean;
}

/**
 * Offices and Departments (Phase 28): every office and department synced
 * people have, each sent to an office or a team here — an existing one, or a
 * new one named after it. People not yet placed are sorted in now and after
 * every sync; somebody in an office with no team waits there, on the Offices
 * page, for one.
 */
export default function M365Places() {
  const [places, setPlaces] = useState<Places | null>(null);
  const [offices, setOffices] = useState<Option[]>([]);
  const [teams, setTeams] = useState<Option[]>([]);
  const [busy, setBusy] = useState(false);

  async function loadOptions() {
    const [o, t] = await Promise.all([api<Option[]>('/api/offices'), api<Option[]>('/api/teams')]);
    setOffices(o);
    setTeams(t.filter((x) => !x.archived));
  }

  useEffect(() => {
    void api<Places>('/api/admin/directory/places').then(setPlaces).catch(() => setPlaces({ offices: [], departments: [] }));
    void loadOptions();
  }, []);

  async function link(kind: 'office' | 'department', value: string, choice: string) {
    // '' unlinks (0), 'new' makes one named after the value (null).
    const target_id = choice === '' ? 0 : choice === 'new' ? null : Number(choice);
    setBusy(true);
    try {
      setPlaces(
        await api<Places>(`/api/admin/directory/places/${kind}`, {
          method: 'PUT',
          body: JSON.stringify({ value, target_id }),
        }),
      );
      await loadOptions();
      toast(choice === '' ? 'Unlinked' : 'People sorted');
    } catch (e) {
      toast(e instanceof ApiError ? e.message : 'Couldn’t save that.');
    } finally {
      setBusy(false);
    }
  }

  if (!places) return <p className="text-xs text-content-subtle">Loading…</p>;
  if (!places.offices.length && !places.departments.length)
    return <p className="text-sm text-content-muted">Nothing yet — run a sync, and synced people’s offices and departments appear here.</p>;

  const list = (kind: 'office' | 'department', values: Value[], options: Option[], noun: string) => {
    const sorted = values.filter((v) => (kind === 'office' ? v.office_id : v.team_id)).length;
    return (
      <section className="rounded-lg border border-edge">
        <header className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b border-edge px-4 py-3">
          <div>
            <h3 className="text-sm font-medium text-content">{kind === 'office' ? 'Offices' : 'Departments'}</h3>
            <p className="text-xs text-content-subtle">
              {kind === 'office'
                ? 'Each Microsoft 365 office becomes an office here.'
                : 'Each Microsoft 365 department becomes a team here.'}
            </p>
          </div>
          {values.length > 0 && (
            <span className="text-xs text-content-muted">
              {sorted} of {values.length} sorted
            </span>
          )}
        </header>
        {values.length === 0 ? (
          <p className="px-4 py-3 text-xs text-content-subtle">None on synced people yet.</p>
        ) : (
          <ul className="divide-y divide-edge">
            {values.map((v) => {
              const linked = kind === 'office' ? v.office_id : v.team_id;
              const exists = options.some((o) => o.name.toLowerCase() === v.value.toLowerCase());
              return (
                <li
                  key={v.value}
                  className="grid gap-2 px-4 py-2.5 sm:grid-cols-[minmax(0,1fr)_auto_minmax(11rem,16rem)] sm:items-center sm:gap-4"
                >
                  <div className="min-w-0">
                    <p className="break-words text-sm text-content">{v.value}</p>
                    <p className="text-xs text-content-subtle">
                      {v.people} {v.people === 1 ? 'person' : 'people'}
                    </p>
                  </div>
                  <span aria-hidden="true" className="hidden text-content-subtle sm:block">
                    →
                  </span>
                  <select
                    aria-label={`${noun} for ${v.value}`}
                    disabled={busy}
                    value={linked ? String(linked) : ''}
                    onChange={(e) => void link(kind, v.value, e.target.value)}
                    className={`w-full rounded-md border bg-bg px-2.5 py-1.5 text-sm ${
                      linked ? 'border-brand text-content' : 'border-edge text-content-muted'
                    }`}
                  >
                    <option value="">Don’t sort</option>
                    {!exists && <option value="new">+ New {noun.toLowerCase()} “{v.value}”</option>}
                    {options.length > 0 && (
                      <optgroup label={`Existing ${noun.toLowerCase()}s`}>
                        {options.map((o) => (
                          <option key={o.id} value={o.id}>
                            {o.name}
                          </option>
                        ))}
                      </optgroup>
                    )}
                  </select>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    );
  };

  return (
    <div className="space-y-4">
      <p className="text-sm text-content-muted">
        Choose where people go by their Microsoft 365 office and department. Anyone not on a team yet is sorted
        now and after every sync; people in an office with no team show on the Offices page to place.
      </p>
      {list('office', places.offices, offices, 'Office')}
      {list('department', places.departments, teams, 'Team')}
    </div>
  );
}
