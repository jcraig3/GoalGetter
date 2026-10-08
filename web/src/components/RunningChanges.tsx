import { useEffect, useState, type FormEvent } from 'react';

import { api } from '../api';
import { useOrgTimezone } from '../orgAppearance';
import { browserZone, fromLocalInput, toLocalInput, zoneName } from '../pages/competitionClock';
import Field from './Field';
import Modal from './Modal';
import PeoplePicker from './PeoplePicker';
import type { PickPerson } from './peoplePick';

interface Contest {
  id: number;
  prize: string | null;
  ends_at: string;
  entity_type: string;
}

/**
 * **Changing a contest while it runs** (6.14): a better prize, a later end, a
 * late entrant — with one reason for all of it, which everybody in the
 * contest sees on its page beside what changed.
 *
 * Only these three. An earlier end, a new start, other rules, or taking
 * somebody out would change who wins, so they stay locked — and the form
 * does not offer them, rather than offering and refusing.
 */
export default function RunningChanges({
  contest,
  entrantIds,
  onClose,
  onSaved,
}: {
  contest: Contest;
  /** Who is already in it, so they are not offered again. */
  entrantIds: number[];
  onClose: () => void;
  onSaved: (said: string) => Promise<void>;
}) {
  const zone = useOrgTimezone() ?? browserZone();
  const [prize, setPrize] = useState(contest.prize ?? '');
  const [endsAt, setEndsAt] = useState(contest.ends_at);
  const [joining, setJoining] = useState<number[]>([]);
  const [people, setPeople] = useState<PickPerson[]>([]);
  const [teams, setTeams] = useState<{ id: number; name: string }[]>([]);
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const load =
      contest.entity_type === 'team'
        ? api<{ id: number; name: string }[]>('/api/teams').then(setTeams)
        : api<PickPerson[]>('/api/users').then(setPeople);
    load.catch(() => setError('Could not load who could join.'));
  }, [contest.entity_type]);

  const prizeChanged = prize.trim() !== (contest.prize ?? '');
  const endChanged = new Date(endsAt).getTime() !== new Date(contest.ends_at).getTime();
  const endEarlier = new Date(endsAt).getTime() < new Date(contest.ends_at).getTime();
  const anything = prizeChanged || endChanged || joining.length > 0;
  const missing = !anything
    ? 'Change the prize, the end, or who is in it.'
    : endEarlier
      ? 'A running contest can be extended but not cut short.'
      : note.trim().length < 3
        ? 'Say why — everybody in it will see the reason.'
        : null;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (missing) return;
    setBusy(true);
    setError(null);
    try {
      if (prizeChanged || endChanged) {
        await api(`/api/competitions/${contest.id}`, {
          method: 'PATCH',
          body: JSON.stringify({
            ...(prizeChanged ? { prize: prize.trim() || null } : {}),
            ...(endChanged ? { ends_at: endsAt } : {}),
            note: note.trim(),
          }),
        });
      }
      for (const id of joining) {
        await api(`/api/competitions/${contest.id}/participants`, {
          method: 'POST',
          body: JSON.stringify({ entity_id: id, note: note.trim() }),
        });
      }
      const said = [
        prizeChanged && 'prize changed',
        endChanged && 'end extended',
        joining.length > 0 && `${joining.length} joined`,
      ].filter(Boolean);
      await onSaved(`Contest updated: ${said.join(', ')}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not change that.');
    } finally {
      setBusy(false);
    }
  }

  const candidates = (
    contest.entity_type === 'team' ? teams : people.map((p) => ({ id: p.id, name: p.full_name }))
  ).filter((c) => !entrantIds.includes(c.id));

  return (
    <Modal
      title="Change while running"
      description="A better prize, more time, or somebody new — with a reason everybody in it can read."
      onClose={onClose}
    >
      <form onSubmit={submit} className="space-y-4">
        <Field
          label="Prize"
          value={prize}
          onChange={setPrize}
          required={false}
          maxLength={200}
        />

        <div>
          <label htmlFor="running-end" className="block text-sm text-content-muted">
            Ends
          </label>
          <input
            id="running-end"
            type="datetime-local"
            value={toLocalInput(endsAt, zone)}
            min={toLocalInput(contest.ends_at, zone)}
            onChange={(e) => {
              const next = fromLocalInput(e.target.value, zone);
              if (next) setEndsAt(next);
            }}
            className="mt-1 w-full rounded-md border border-edge bg-bg px-3 py-2 text-content outline-none focus:border-brand"
          />
          <p className="mt-1 text-xs text-content-muted">
            Later only — ending early would hand it to whoever is ahead today. Times are{' '}
            {zoneName(zone)}.
          </p>
        </div>

        <div>
          {contest.entity_type === 'team' ? (
            <fieldset>
              <legend className="text-sm text-content-muted">Teams joining late</legend>
              <div className="mt-1 max-h-40 space-y-1 overflow-y-auto">
                {candidates.map((team) => (
                  <label key={team.id} className="flex items-center gap-2 text-sm text-content">
                    <input
                      type="checkbox"
                      checked={joining.includes(team.id)}
                      onChange={(e) =>
                        setJoining((was) =>
                          e.target.checked ? [...was, team.id] : was.filter((id) => id !== team.id),
                        )
                      }
                    />
                    {team.name}
                  </label>
                ))}
              </div>
            </fieldset>
          ) : (
            <PeoplePicker
              multiple
              label="Joining late (optional)"
              people={people.filter((p) => !entrantIds.includes(p.id))}
              value={joining}
              onChange={setJoining}
            />
          )}
          <p className="mt-1 text-xs text-content-muted">
            Their numbers count from the start, the same as everyone&rsquo;s.
          </p>
        </div>

        <div>
          <label htmlFor="running-note" className="block text-sm text-content-muted">
            Why
          </label>
          <textarea
            id="running-note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            maxLength={300}
            rows={2}
            placeholder="The floor asked for another week"
            className="mt-1 w-full rounded-md border border-edge bg-bg px-3 py-2 text-content outline-none placeholder:text-content-subtle focus:border-brand"
          />
          <p className="mt-1 text-xs text-content-muted">
            Shown on the contest&rsquo;s page with what changed, and kept in the audit log.
          </p>
        </div>

        {error && (
          <p role="alert" className="rounded-md border border-danger px-3 py-2 text-sm text-danger">
            {error}
          </p>
        )}

        <div className="flex flex-wrap items-center gap-3 pt-2">
          <button
            type="submit"
            disabled={busy || missing !== null}
            className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
          >
            {busy ? 'Saving…' : 'Save changes'}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-edge px-4 py-2 text-sm text-content-muted transition-colors hover:bg-surface-hover hover:text-content"
          >
            Cancel
          </button>
          {missing && !busy && <span className="text-xs text-content-muted">{missing}</span>}
        </div>
      </form>
    </Modal>
  );
}
