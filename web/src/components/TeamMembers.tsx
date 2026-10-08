import { useEffect, useMemo, useState } from 'react';

import { api } from '../api';
import { MIRROR_BASE, STATUS_LABEL, type Mirror, type MirrorPerson } from './TeamsMirror';

export interface Member {
  id: number;
  full_name: string;
  email: string;
  org_role: string;
  team_id: number | null;
  team_name: string | null;
  hidden: boolean;
}

/**
 * Who is on one team, with adding and removing in place.
 *
 * **Uses the same endpoint as the People page's bulk "assign team"**, so a
 * move made here is audited and guarded exactly like one made there — this is
 * a second door to one action, not a second action.
 *
 * **A team that follows Microsoft Teams can still be edited here.** The mirror
 * notices a hand move and leaves it alone, so this says so, and shows who
 * Microsoft Teams puts on the team that is not on it here.
 */
export default function TeamMembers({
  teamId,
  teamName,
  follows,
  people,
  canEdit,
  onChanged,
}: {
  teamId: number;
  teamName: string;
  /** The Microsoft Team or channel this team follows, if any. */
  follows: string | null;
  /** Everybody the viewer can see; members are picked out of this. */
  people: Member[];
  canEdit: boolean;
  onChanged: () => void;
}) {
  const [adding, setAdding] = useState('');
  //: Somebody picked who is already on another team, waiting on a yes.
  const [moving, setMoving] = useState<Member | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [mirror, setMirror] = useState<Mirror | null>(null);

  // Only for a team that follows something, and only an admin may read it —
  // a manager simply sees the list without the Microsoft Teams column.
  useEffect(() => {
    if (!follows || !canEdit) return;
    api<Mirror>(MIRROR_BASE)
      .then(setMirror)
      .catch(() => setMirror(null));
  }, [follows, canEdit, people]);

  const members = people.filter((p) => p.team_id === teamId && !p.hidden);
  const status = useMemo(() => {
    const out = new Map<number, MirrorPerson>();
    for (const p of mirror?.people ?? []) out.set(p.user_id, p);
    return out;
  }, [mirror]);
  // Microsoft Teams puts them here, and they are somewhere else.
  const elsewhere = (mirror?.people ?? []).filter(
    (p) => p.teams_team_id === teamId && p.team_id !== teamId,
  );

  const q = adding.trim().toLowerCase();
  const candidates = q
    ? people
        .filter(
          (p) =>
            p.team_id !== teamId &&
            !p.hidden &&
            (p.full_name.toLowerCase().includes(q) || p.email.toLowerCase().includes(q)),
        )
        .slice(0, 8)
    : [];

  async function assign(ids: number[], team: number | null) {
    setBusy(true);
    setError(null);
    try {
      const result = await api<{ changed: number; skipped: string[] }>('/api/users/bulk', {
        method: 'POST',
        body: JSON.stringify({ ids, action: 'assign_team', team_id: team }),
      });
      if (result.skipped.length) setError(result.skipped.join('; '));
      setAdding('');
      setMoving(null);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not change that.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="col-span-full space-y-3 rounded-md border border-edge bg-bg p-3">
      {follows && (
        <p className="text-xs text-content-muted">
          Follows <strong className="text-content">{follows}</strong> in Microsoft Teams.
          {canEdit && ' Adding or removing people here is kept as a hand move — the mirror will not undo it.'}
        </p>
      )}

      {error && (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      )}

      {members.length === 0 ? (
        <p className="text-sm text-content-muted">Nobody is on {teamName} yet.</p>
      ) : (
        <ul className="divide-y divide-edge">
          {members.map((m) => {
            const s = status.get(m.id);
            return (
              <li key={m.id} className="flex flex-wrap items-center justify-between gap-2 py-1.5 text-sm">
                <span className="min-w-0">
                  <span className="text-content">{m.full_name}</span>
                  <span className="ml-2 text-xs text-content-subtle">{m.org_role}</span>
                  {s && s.status !== 'in_step' && s.status !== 'not_linked' && (
                    <span className="ml-2 text-xs text-warning">{STATUS_LABEL[s.status]}</span>
                  )}
                </span>
                {canEdit && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void assign([m.id], null)}
                    aria-label={`Remove ${m.full_name} from ${teamName}`}
                    className="text-xs text-content-muted hover:text-danger disabled:opacity-60"
                  >
                    Remove
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {elsewhere.length > 0 && (
        <div className="text-sm">
          <p className="text-xs text-content-subtle">In {follows} in Microsoft Teams, not on this team here:</p>
          <ul className="mt-1 space-y-0.5">
            {elsewhere.map((p) => (
              <li key={p.user_id} className="text-content-muted">
                {p.name} · {p.team ?? 'No team'}
                <span className="ml-2 text-xs">{STATUS_LABEL[p.status]}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {canEdit && moving && (
        <div
          role="alertdialog"
          aria-label={`Move ${moving.full_name}?`}
          className="flex flex-wrap items-center gap-3 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm"
        >
          <span className="text-content">
            {moving.full_name} is on {moving.team_name}. Move them to {teamName}?
          </span>
          <span className="flex gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => void assign([moving.id], teamId)}
              className="rounded-md bg-brand px-3 py-1 text-xs font-medium text-white hover:bg-brand-hover disabled:opacity-60"
            >
              Move
            </button>
            <button
              type="button"
              onClick={() => setMoving(null)}
              className="rounded-md border border-edge px-3 py-1 text-xs text-content hover:bg-surface-hover"
            >
              Cancel
            </button>
          </span>
        </div>
      )}

      {canEdit && (
        <div className="relative">
          <input
            type="search"
            value={adding}
            onChange={(e) => setAdding(e.target.value)}
            placeholder="Add someone — type a name or email"
            aria-label={`Add someone to ${teamName}`}
            className="w-full rounded-md border border-edge bg-surface px-3 py-1.5 text-sm text-content sm:w-80"
          />
          {candidates.length > 0 && (
            <ul className="mt-1 divide-y divide-edge rounded-md border border-edge bg-surface sm:w-80">
              {candidates.map((p) => (
                <li key={p.id}>
                  <button
                    type="button"
                    disabled={busy}
                    // **Adding somebody who is on another team moves them**,
                    // because a person is on one team. That used to happen
                    // silently (QA-8), so it asks first.
                    onClick={() => (p.team_id ? setMoving(p) : void assign([p.id], teamId))}
                    className="flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left text-sm hover:bg-surface-hover disabled:opacity-60"
                  >
                    <span className="truncate text-content">{p.full_name}</span>
                    <span className="shrink-0 text-xs text-content-subtle">
                      {p.team_name ? `on ${p.team_name}` : 'no team'}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
