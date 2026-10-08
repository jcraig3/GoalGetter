import { useEffect, useState } from 'react';

import { api } from '../api';
import { toast } from '../toast';

interface Tv {
  id: number;
  name: string;
  channel_name: string;
  revoked: boolean;
}

interface Sent {
  display_name: string;
  starts_in_seconds: number;
  hold_seconds: number;
}

/**
 * Send what is being edited to one television, to see it there (5j).
 *
 * **One screen, chosen by name**, because the point is to look at it: the
 * person sending it is standing in front of that TV, or about to be. It plays
 * once, marked "Preview", for a slide's thirty seconds or a celebration's
 * length, and the screen goes back to its rotation. Nothing is saved and
 * nothing is announced. See `app/display_previews.py`.
 *
 * **A select and a Send button** (7.4, Q2-9). Choosing the TV used to be the
 * action, so a keyboard arrowing down the list sent a preview to every TV it
 * passed, a wrong pick could not be taken back, and sending again to the same
 * TV needed a detour. One TV is remembered, so a second Send is one click.
 */
export default function PreviewOnTv({
  send,
  disabled = false,
}: {
  /** Posts the unsaved thing to `…/preview/tv/{displayId}`. */
  send: (displayId: number) => Promise<Sent>;
  disabled?: boolean;
}) {
  const [tvs, setTvs] = useState<Tv[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [chosen, setChosen] = useState('');

  useEffect(() => {
    api<Tv[]>('/api/displays')
      .then((all) => {
        const live = all.filter((tv) => !tv.revoked);
        setTvs(live);
        // One TV is the common case: chosen already.
        if (live.length === 1) setChosen(String(live[0]!.id));
      })
      .catch(() => setTvs([]));
  }, []);

  // Nothing to offer, so nothing shown: a disabled control with no TVs behind
  // it would only raise the question of why.
  if (!tvs || tvs.length === 0) return null;

  async function sendNow() {
    if (!chosen) return;
    setBusy(true);
    setError(null);
    try {
      const sent = await send(Number(chosen));
      toast(
        `Sent to ${sent.display_name}. It starts in about ${sent.starts_in_seconds} seconds and plays for ${sent.hold_seconds} seconds.`,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not reach that TV.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <label className="sr-only" htmlFor="preview-on-tv">
          Preview on a TV
        </label>
        <select
          id="preview-on-tv"
          value={chosen}
          disabled={disabled || busy}
          onChange={(e) => setChosen(e.target.value)}
          className="rounded-md border border-edge bg-surface px-3 py-1.5 text-sm text-content transition-colors hover:bg-surface-hover disabled:opacity-50"
        >
          <option value="">Preview on a TV…</option>
          {tvs.map((tv) => (
            <option key={tv.id} value={tv.id}>
              {tv.name} · {tv.channel_name}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={() => void sendNow()}
          disabled={disabled || busy || !chosen}
          className="rounded-md border border-edge px-3 py-1.5 text-sm text-content transition-colors hover:bg-surface-hover disabled:opacity-50"
        >
          {busy ? 'Sending…' : 'Send'}
        </button>
      </div>
      {error && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {error}
        </p>
      )}
    </div>
  );
}
