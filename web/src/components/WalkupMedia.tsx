import { useEffect, useState, type FormEvent } from 'react';

import { api } from '../api';
import { useAuth } from '../auth';
import type { Celebration } from '../pages/celebrationQueue';
import CelebrationPreview, { startingNow, type CelebrationShape } from './CelebrationPreview';
import Field from './Field';
import { ask } from '../confirm';
import { toast } from '../toast';

interface Walkup {
  url: string | null;
  kind: string | null;
  start_seconds: number | null;
  end_seconds: number | null;
}

/**
 * Walk-up music — yours, or somebody's you manage.
 *
 * A batter has one; somebody closing a deal gets fifteen seconds on the wall.
 * It plays on the office screens, not at your desk: a song starting because
 * you opened a laptop is a different and much less welcome thing.
 *
 * Given a `userId`, this edits that person's instead — which is how most of
 * them get set, since plenty of people never open their own settings.
 */
export default function WalkupMedia({ userId }: { userId?: number }) {
  const query = userId ? `?user_id=${userId}` : '';
  const [walkup, setWalkup] = useState<Walkup | null>(null);
  const [url, setUrl] = useState('');
  const [uploading, setUploading] = useState(false);
  const [start, setStart] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [preview, setPreview] = useState<Celebration | null>(null);
  const [previewing, setPreviewing] = useState(false);
  // Sounds and videos already in Assets, for whoever can see the library
  // (8.1): the review found a bare file input as the only way in.
  const { user } = useAuth();
  // Null until asked — and never asked for anybody who cannot see Assets.
  const [library, setLibrary] = useState<{ digest: string; name: string | null; kind: string }[] | null>(null);
  const [fromLibrary, setFromLibrary] = useState('');

  useEffect(() => {
    if (user?.org_role !== 'admin') return;
    api<{ digest: string; name: string | null; kind: string }[]>('/api/assets')
      .then((all) => setLibrary(all.filter((a) => a.kind === 'audio' || a.kind === 'video')))
      .catch(() => setLibrary([]));
  }, [user?.org_role]);

  async function chooseFromLibrary() {
    if (!fromLibrary) return;
    setUploading(true);
    setError(null);
    try {
      const next = await api<Walkup>(`/api/me/walkup/asset${query}`, {
        method: 'PUT',
        body: JSON.stringify({ digest: fromLibrary }),
      });
      setWalkup(next);
      setUrl(linkOf(next));
      setFromLibrary('');
      toast('Walk-up set from Assets');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not use that file.');
    } finally {
      setUploading(false);
    }
  }

  useEffect(() => {
    api<Walkup>(`/api/me/walkup${query}`)
      .then((current) => {
        setWalkup(current);
        setUrl(linkOf(current));
        setStart(current.start_seconds ? String(current.start_seconds) : '');
      })
      .catch(() => setError('Could not load your walk-up media.'));
  }, [query]);

  async function removeClip() {
    if (!(await ask('Remove the uploaded clip? Nothing plays until another is added.'))) return;
    setSaving(true);
    setError(null);
    try {
      const next = await api<Walkup>(`/api/me/walkup${query}`, {
        method: 'PUT',
        body: JSON.stringify({ url: null, start_seconds: null }),
      });
      setWalkup(next);
      setUrl('');
      setStart('');
      toast('Walk-up clip removed');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not remove it.');
    } finally {
      setSaving(false);
    }
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const next = await api<Walkup>(`/api/me/walkup${query}`, {
        method: 'PUT',
        body: JSON.stringify({
          url: url.trim() || null,
          start_seconds: start ? Number(start) : null,
        }),
      });
      setWalkup(next);
      setUrl(linkOf(next));
      setStart(next.start_seconds ? String(next.start_seconds) : '');
      setSaved(true);
    } catch (e) {
      // The server's message is the useful one — it names which links are
      // accepted, and repeating that list here would be a second copy to keep
      // in step with the allowlist.
      setError(e instanceof Error ? e.message : 'Could not save that.');
    } finally {
      setSaving(false);
    }
  }

  /**
   * What the announcement would look like, played here and nowhere else.
   *
   * Asks the server rather than working it out, so the link is read by the
   * same parser Save uses — a link that previews is a link that saves, and a
   * bad one gets the same sentence either way. An empty box previews what is
   * saved, which is how an uploaded clip is previewed.
   */
  async function showPreview() {
    setPreviewing(true);
    setError(null);
    try {
      const shape = await api<CelebrationShape>(
        `/api/me/walkup/preview${query}`,
        {
          method: 'POST',
          body: JSON.stringify({
            url: url.trim() || null,
            start_seconds: start ? Number(start) : null,
          }),
        },
      );
      setPreview(startingNow(shape));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not preview that.');
    } finally {
      setPreviewing(false);
    }
  }

  /**
   * Send the bytes, exactly as a photograph is sent — to the video check or
   * the audio one, depending on what was chosen. The server decodes the file
   * either way and trusts nothing about its label; the label only decides
   * which checker gets to refuse it, so that an iPhone video is told about
   * HEVC rather than about not being an MP3.
   */
  async function upload(file: File) {
    setUploading(true);
    setError(null);
    const as = file.type.startsWith('video/') ? 'video' : 'audio';
    try {
      const next = await api<Walkup>(`/api/me/walkup/${as}${query}`, {
        method: 'POST',
        body: file,
      });
      setWalkup(next);
      setUrl(linkOf(next));
      setSaved(true);
      window.setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not use that file.');
    } finally {
      setUploading(false);
    }
  }

  if (walkup === null && !error) return null;

  return (
    <div className="mt-6 border-t border-edge pt-6">
      <h2 className="text-sm font-medium text-content">Walk-up media</h2>
      <p className="mt-1 text-xs text-content-muted">
        A song or music video that plays on the office screens when {userId ? 'they hit' : 'you hit'} a
        goal or someone recognises {userId ? 'them' : 'you'}. Capped at 15 seconds — the room needs its
        leaderboard back.
      </p>

      {error && (
        <p role="alert" className="mt-3 text-sm text-danger">
          {error}
        </p>
      )}

      {/* **Upload first, because it is what most people can actually do.**
          Pasting a YouTube address means finding the song, copying the link
          and knowing which second to start at. Everybody has a file. */}
      <div className="mt-4">
        <span className="block text-sm text-content-muted">Upload a clip</span>
        <input
          type="file"
          aria-label="Upload a clip"
          accept="audio/*,video/mp4"
          disabled={uploading}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void upload(file);
          }}
          className="mt-1 block w-full text-sm text-content-muted file:mr-3 file:rounded-md file:border file:border-edge file:bg-surface file:px-3 file:py-1.5 file:text-sm file:text-content"
        />
        <p className="mt-1 text-xs text-content-subtle">
          {uploading
            ? 'Uploading…'
            : walkup?.kind === 'video'
              ? 'A video is stored — it fills the screen with the announcement over it. Upload another to replace it.'
              : walkup?.kind === 'audio'
                ? 'A clip is stored. Upload another to replace it.'
                : 'A song (MP3, M4A, WAV, OGG, FLAC) or a music video (MP4). Only the first 15 seconds play.'}
        </p>
        {library !== null && (
          <div className="mt-3 flex flex-wrap items-end gap-2">
            <label className="block min-w-0 flex-1 text-sm text-content-muted">
              Or choose from Assets
              <select
                value={fromLibrary}
                onChange={(e) => setFromLibrary(e.target.value)}
                // Shown, not hidden, while Assets has nothing to offer — nobody
                // finds an option that only exists once they have (P3-18).
                disabled={library.length === 0}
                className="mt-1 block w-full rounded-md border border-edge bg-bg px-3 py-2 text-content disabled:opacity-60"
              >
                <option value="">
                  {library.length === 0 ? 'Add sounds or video in Assets to choose one here' : 'Choose a sound or video…'}
                </option>
                {library.map((a) => (
                  <option key={a.digest} value={a.digest}>
                    {a.name || (a.kind === 'video' ? 'A video' : 'A sound')} · {a.kind === 'video' ? 'Video' : 'Sound'}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              onClick={() => void chooseFromLibrary()}
              disabled={!fromLibrary || uploading}
              className="rounded-md border border-edge px-3 py-2 text-sm text-content hover:bg-surface-hover disabled:opacity-50"
            >
              Use it
            </button>
          </div>
        )}
        {/* **The stored clip, with something to do with it.** It could be
            replaced but not heard or taken away (QA-31). */}
        {(walkup?.kind === 'audio' || walkup?.kind === 'video') && !uploading && (
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
            <span className="text-content">
              Uploaded {walkup.kind === 'video' ? 'video' : 'clip'}
            </span>
            <button
              type="button"
              onClick={() => void showPreview()}
              disabled={previewing}
              className="rounded-md border border-edge px-2.5 py-1 text-xs text-content hover:bg-surface-hover disabled:opacity-50"
            >
              ▶ Play
            </button>
            <button
              type="button"
              onClick={() => void removeClip()}
              disabled={saving}
              className="rounded-md border border-edge px-2.5 py-1 text-xs text-content-muted hover:border-danger hover:text-danger disabled:opacity-50"
            >
              Remove
            </button>
          </div>
        )}
        {/* Said here, where the choice is made, because it is the difference
            somebody would otherwise find out about in front of the office. */}
        <p className="mt-1 text-xs text-content-subtle">
          An uploaded video plays with no adverts and fills the whole screen.
          A YouTube link can show an advert first — that is up to whoever
          uploaded the video to YouTube, and nothing here can skip it.
        </p>
      </div>

      <p className="mt-4 text-xs text-content-subtle">Or link to one:</p>

      <form onSubmit={save} className="mt-2 space-y-4">
        <Field
          label="Link"
          value={url}
          onChange={(next) => {
            setUrl(next);
            // A link copied at a moment carries it — "&t=43s" — and the box
            // below used to stay at 0 regardless (QA-31).
            const at = startFromLink(next);
            if (at !== null) setStart(String(at));
          }}
          maxLength={500}
          hint="Leave empty for none."
          required={false}
        />

        {/* Only for video. A still image has no timeline, and an uploaded clip
            is already trimmed to its cap on the way in, so offering a start
            time for either would be a control that does nothing. */}
        {looksLikeVideoLink(url) && (
          <Field
            label="Start at (seconds)"
            value={start}
            onChange={setStart}
            numeric={{ decimals: 0 }}
            hint="Skip the intro — jump straight to the part worth hearing."
          />
        )}

        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={saving}
            className="rounded-md border border-edge px-4 py-2 text-sm text-content transition-colors hover:bg-surface-hover disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
          <button
            type="button"
            onClick={() => void showPreview()}
            disabled={previewing || uploading}
            className="rounded-md border border-edge px-4 py-2 text-sm text-content transition-colors hover:bg-surface-hover disabled:opacity-50"
          >
            {previewing ? 'Loading…' : 'Preview'}
          </button>
          {saved && <span className="text-sm text-success">Saved</span>}
        </div>
        <p className="text-xs text-content-subtle">
          Preview plays the announcement here, on your screen only — the office
          walls are not interrupted.
        </p>
      </form>

      {preview && (
        <CelebrationPreview
          celebration={preview}
          label="Walk-up preview"
          onClose={() => setPreview(null)}
        />
      )}
    </div>
  );
}

/**
 * Whether the link being typed is one a start time means something for.
 *
 * **From what is in the box, not from what was last saved.** It used to read
 * the saved clip's kind, so somebody who had uploaded a song and then pasted a
 * YouTube link could not see the start box until they had saved — and then
 * had to save again.
 */
/**
 * The moment a YouTube link was copied at, in seconds: `t=43`, `t=43s`,
 * `t=1m3s` or `start=43`. Null when it names none.
 */
export function startFromLink(url: string): number | null {
  const match = /[?&#](?:t|start)=([0-9hms]+)/i.exec(url);
  if (!match) return null;
  const value = match[1]!.toLowerCase();
  if (/^\d+$/.test(value)) return Number(value);
  const parts = /^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$/.exec(value);
  if (!parts || !value) return null;
  const [, h, m, s] = parts;
  return Number(h ?? 0) * 3600 + Number(m ?? 0) * 60 + Number(s ?? 0);
}

function looksLikeVideoLink(url: string): boolean {
  const text = url.trim().toLowerCase();
  return /(^|\/\/)(www\.|m\.|music\.)?(youtube\.com|youtu\.be)\//.test(text);
}

/**
 * What belongs in the Link box: a link, or nothing.
 *
 * An uploaded clip is stored under an internal reference (`asset:` or
 * `video:`), and showing that in a box labelled "Link" invited somebody to
 * press Save on it — which the server refuses, because it is not a link.
 */
function linkOf(walkup: Walkup): string {
  return walkup.kind === 'audio' || walkup.kind === 'video' ? '' : (walkup.url ?? '');
}

