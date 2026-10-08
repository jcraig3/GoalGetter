import { useRef, useState } from 'react';

import Avatar from './Avatar';
import { api } from '../api';
import { useAuth } from '../auth';
import { LibraryPictures } from './LogoField';

/**
 * Choosing a photograph, or going back to the one the directory has.
 *
 * **Two controls, and the second only when it would do something.** "Use the
 * default" on an account that has never had a custom photo is a button that
 * cannot be pressed meaningfully, and offering it invites the question of what
 * it would revert to.
 *
 * The file goes up as the request body rather than a form: the browser sends a
 * `File` as a body just as happily, and the server decodes the bytes to find out
 * what they are regardless of what the upload claims.
 */
export default function PhotoPicker({
  userId,
  name,
  digest,
  hasCustom,
  onChanged,
}: {
  userId: number;
  name: string;
  digest: string | null;
  /** Whether "use the default" would change anything. */
  hasCustom: boolean;
  onChanged: (digest: string | null) => void;
}) {
  const file = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { user } = useAuth();
  const [browsing, setBrowsing] = useState(false);

  async function send(chosen: File) {
    setBusy(true);
    setError(null);
    try {
      const updated = await api<{ photo_digest: string | null }>(
        `/api/users/${userId}/photo`,
        { method: 'POST', body: chosen },
      );
      onChanged(updated.photo_digest);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : 'That photo could not be used.',
      );
    } finally {
      setBusy(false);
    }
  }

  async function fromLibrary(chosen: string) {
    setBusy(true);
    setError(null);
    setBrowsing(false);
    try {
      const updated = await api<{ photo_digest: string | null }>(`/api/users/${userId}/photo/from-library`, {
        method: 'POST',
        body: JSON.stringify({ digest: chosen }),
      });
      onChanged(updated.photo_digest);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That picture could not be used.');
    } finally {
      setBusy(false);
    }
  }

  async function revert() {
    setBusy(true);
    setError(null);
    try {
      const updated = await api<{ photo_digest: string | null }>(
        `/api/users/${userId}/photo`,
        { method: 'DELETE' },
      );
      onChanged(updated.photo_digest);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not change that back.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="flex items-center gap-4">
        <Avatar name={name} digest={digest} size="lg" />
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => file.current?.click()}
            disabled={busy}
            className="rounded-md border border-edge px-3 py-2 text-sm text-content transition-colors hover:bg-surface-hover disabled:opacity-50"
          >
            {busy ? 'Working…' : digest ? 'Change photo' : 'Add a photo'}
          </button>
          {/* Or a picture already in the library (Phase 27) — for those
              who can see it. */}
          {(user?.org_role === 'admin' || user?.org_role === 'manager') && (
            <button
              type="button"
              onClick={() => setBrowsing((was) => !was)}
              disabled={busy}
              className="rounded-md border border-edge px-3 py-2 text-sm text-content transition-colors hover:bg-surface-hover disabled:opacity-50"
            >
              From library
            </button>
          )}
          {hasCustom && (
            <button
              type="button"
              onClick={() => void revert()}
              disabled={busy}
              className="text-sm text-content-muted underline transition-colors hover:text-content disabled:opacity-50"
            >
              Use the default
            </button>
          )}
          <input
            ref={file}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            hidden
            onChange={(e) => {
              const chosen = e.target.files?.[0];
              // Cleared so choosing the same file twice fires again — which is
              // what somebody does after a failure they have just fixed.
              e.target.value = '';
              if (chosen) void send(chosen);
            }}
          />
        </div>
      </div>

      {browsing && <LibraryPictures chosen={null} onChoose={(chosen) => void fromLibrary(chosen)} />}

      {error && (
        <p
          role="alert"
          className="mt-3 rounded-md border border-danger px-3 py-2 text-sm text-danger"
        >
          {error}
        </p>
      )}
    </div>
  );
}
