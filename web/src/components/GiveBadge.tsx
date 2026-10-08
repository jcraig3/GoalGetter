import { type FormEvent, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { api } from '../api';
import type { Badge } from '../pages/badgesCopy';
import Modal from './Modal';
import PeoplePicker from './PeoplePicker';
import type { PickPerson } from './peoplePick';
import MissingHint from './MissingHint';

/**
 * Pinning a badge on somebody.
 *
 * Behind `recognition.send`, and that is deliberate rather than a convenient
 * capability to borrow. A badge given by hand *is* recognition — the durable
 * kind, the one still on somebody's profile after the season it was given in
 * has reset — so it belongs with the people allowed to recognise, and the
 * server's role check says the same two roles.
 *
 * The people list is already scoped by the API to who the viewer can see,
 * which is the same set the server will accept, so nobody can choose a person
 * and then be refused.
 */
export default function GiveBadge({
  onClose,
  onGiven,
  userId: chosen,
}: {
  onClose: () => void;
  onGiven: () => void;
  /** Somebody already chosen — from "Give a badge" on their profile (9.2). */
  userId?: number;
}) {
  const [badges, setBadges] = useState<Badge[]>([]);
  const [people, setPeople] = useState<PickPerson[]>([]);
  const [badgeId, setBadgeId] = useState('');
  const [userId, setUserId] = useState<number | null>(chosen ?? null);
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    Promise.all([
      api<Badge[]>('/api/points/badges'),
      api<PickPerson[]>('/api/users'),
    ])
      .then(([found, who]) => {
        setBadges(found);
        setPeople(who);
      })
      .catch(() => setError('Could not load badges or people.'));
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api(`/api/points/badges/${badgeId}/award`, {
        method: 'POST',
        body: JSON.stringify({ user_id: userId, reason }),
      });
      onGiven();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not give that.');
    } finally {
      setBusy(false);
    }
  }

  const field =
    'mt-1 w-full rounded-md border border-edge bg-bg px-3 py-2 text-content outline-none focus:border-brand';

  return (
    <Modal
      title="Give a badge"
      description="It stays on their profile after the season ends."
      onClose={onClose}
    >
      <form onSubmit={submit} className="space-y-4">
        {badges.length === 0 && !error && (
          <p className="text-sm text-content-muted">
            No badges have been set up yet.{' '}
            <Link to="/points/setup" onClick={onClose} className="text-brand hover:underline">
              Set one up in Points setup → Badges
            </Link>
          </p>
        )}

        <label className="block">
          <span className="text-sm text-content-muted">Badge</span>
          <select
            value={badgeId}
            onChange={(event) => setBadgeId(event.target.value)}
            className={field}
          >
            <option value="">Choose a badge…</option>
            {badges.map((badge) => (
              <option key={badge.id} value={badge.id}>
                {badge.name}
              </option>
            ))}
          </select>
        </label>

        <PeoplePicker label="Who" people={people} value={userId} onChange={setUserId} />

        <label className="block">
          <span className="text-sm text-content-muted">Why (optional)</span>
          <input
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            maxLength={200}
            placeholder="Covered the late shift all week"
            className={field}
          />
        </label>

        {error && (
          <p role="alert" className="rounded-md border border-danger px-3 py-2 text-sm text-danger">
            {error}
          </p>
        )}

        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md px-4 py-2 text-sm text-content-muted hover:text-content"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={busy || !badgeId || !userId}
            className="rounded-md bg-brand px-4 py-2 text-sm text-white disabled:opacity-60"
          >
            {busy ? 'Giving…' : 'Give badge'}
          </button>
          <MissingHint checks={[[!badgeId, 'Choose a badge.'], [!userId, 'Choose who gets it.']]} />
        </div>
      </form>
    </Modal>
  );
}
