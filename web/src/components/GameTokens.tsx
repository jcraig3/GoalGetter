import { useEffect, useState } from 'react';

import { api } from '../api';
import { FAMILY_LABELS, PIECE_LABELS, PieceArt } from './wall/GameBoard';

interface Family {
  family: string;
  token: string;
  options: string[];
}

// The labels live with the drawings (6.8), so a new family is named once.
const NAMES: Record<string, string> = PIECE_LABELS;
const FAMILY_NAMES = FAMILY_LABELS;

/**
 * The piece somebody moves round a game board.
 *
 * One choice per family of board rather than per board: a car belongs on a
 * race track, and choosing one for every individual leaderboard would be a
 * setting nobody finds. Their own face is the default, and needs no choosing.
 *
 * Given a `userId`, this edits that person's instead — a manager setting up a
 * race for a team that never opens its own settings.
 */
export default function GameTokens({ userId }: { userId?: number }) {
  const query = userId ? `?user_id=${userId}` : '';
  const [families, setFamilies] = useState<Family[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<Family[]>(`/api/me/tokens${query}`)
      .then(setFamilies)
      .catch(() => setFamilies([]));
  }, [query]);

  async function choose(family: string, token: string) {
    setBusy(true);
    setError(null);
    try {
      setFamilies(
        await api<Family[]>(`/api/me/tokens${query}`, {
          method: 'PUT',
          body: JSON.stringify({ family, token }),
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save that.');
    } finally {
      setBusy(false);
    }
  }

  if (!families || families.length === 0) return null;

  return (
    <div className="mt-6 border-t border-edge pt-6">
      <h2 className="text-sm font-medium text-content">Game board piece</h2>
      <p className="mt-1 text-xs text-content-muted">
        What {userId ? 'they move' : 'you move'} on each kind of game-board screen. It takes
        the colour of {userId ? 'their' : 'your'} ring, if{' '}
        {userId ? 'they wear' : 'you wear'} one.
      </p>

      {error && (
        <p role="alert" className="mt-3 text-sm text-danger">
          {error}
        </p>
      )}

      {families.map((family) => (
        <fieldset key={family.family} className="mt-4">
          <legend className="text-sm text-content-muted">
            {FAMILY_NAMES[family.family] ?? family.family}
          </legend>
          <div className="mt-2 flex flex-wrap gap-2">
            {family.options.map((option) => (
              <button
                key={option}
                type="button"
                disabled={busy}
                aria-pressed={family.token === option}
                onClick={() => void choose(family.family, option)}
                className={`rounded-md border px-3 py-1.5 text-sm transition-colors disabled:opacity-60 ${
                  family.token === option
                    ? 'border-brand bg-brand-subtle text-content'
                    : 'border-edge text-content-muted hover:text-content'
                }`}
              >
                {/* The piece itself, so choosing is seeing (6.8). */}
                <span className="flex items-center gap-2">
                  {option !== 'face' && (
                    <PieceArt token={option} colour="var(--gg-brand)" className="h-6 w-8" />
                  )}
                  {option === 'face'
                    ? // "Their face" when an admin is choosing for somebody else (review §7).
                      userId === undefined
                      ? 'Your face'
                      : 'Their face'
                    : (NAMES[option] ?? option)}
                </span>
              </button>
            ))}
          </div>
        </fieldset>
      ))}
    </div>
  );
}
