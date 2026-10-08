import { useEffect, useId, useState } from 'react';

import { api, ApiError } from '../api';

export type MediaKind = 'image' | 'video' | 'audio';

/** What a stored file is called where a link would go — see `app/media.py`. */
const SCHEME: Record<MediaKind, string> = { image: 'image:', video: 'video:', audio: 'asset:' };

const ACCEPT: Record<MediaKind, string> = {
  image: 'image/png,image/jpeg,image/webp,image/gif',
  video: 'video/mp4',
  audio: 'audio/*',
};

const WORD: Record<MediaKind, string> = { image: 'picture', video: 'video', audio: 'sound' };

interface LibraryFile {
  digest: string;
  kind: MediaKind;
  name: string | null;
  duration_ms: number | null;
}

export function storedDigest(value: string): string | null {
  const match = value.match(/^(image|video|asset):([0-9a-f]{64})$/);
  return match?.[2] ?? null;
}

export function storedKind(value: string): MediaKind | null {
  if (value.startsWith('image:')) return 'image';
  if (value.startsWith('video:')) return 'video';
  if (value.startsWith('asset:')) return 'audio';
  return null;
}

/**
 * A picture, a video or a sound: **uploaded from this computer, or chosen
 * from the asset library** — and, where a link makes sense, pasted as one
 * (Phase 25). One field for every place that takes media, so each works the
 * same way and everything uploaded lands in the library.
 *
 * The value is one string, as the server keeps it: a link, or a stored file
 * as `image:`, `video:` or `asset:` (a sound) followed by its digest.
 */
export default function MediaField({
  label,
  value,
  onChange,
  kinds,
  link,
  hint,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  kinds: MediaKind[];
  /** A link may be pasted instead: what it may be a link to, in words. */
  link?: string;
  hint?: string;
}) {
  const id = useId();
  const [browsing, setBrowsing] = useState(false);
  const [library, setLibrary] = useState<LibraryFile[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const digest = storedDigest(value);
  const chosen = digest ? library?.find((file) => file.digest === digest) : undefined;

  useEffect(() => {
    if (!browsing && !digest) return;
    if (library) return;
    api<LibraryFile[]>('/api/assets')
      .then(setLibrary)
      .catch(() => setLibrary([]));
  }, [browsing, digest, library]);

  async function upload(file: File) {
    setBusy(true);
    setProblem(null);
    try {
      const stored = await api<LibraryFile>('/api/assets', {
        method: 'POST',
        body: file,
        headers: { 'X-File-Name': encodeURIComponent(file.name) },
      });
      if (!kinds.includes(stored.kind)) {
        setProblem(`That's a ${WORD[stored.kind]}; this needs a ${kinds.map((k) => WORD[k]).join(' or ')}.`);
        return;
      }
      setLibrary((files) => (files ? [stored, ...files.filter((f) => f.digest !== stored.digest)] : files));
      onChange(SCHEME[stored.kind] + stored.digest);
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : 'Couldn’t upload that.');
    } finally {
      setBusy(false);
    }
  }

  const fitting = (library ?? []).filter((file) => kinds.includes(file.kind));
  const accept = kinds.map((k) => ACCEPT[k]).join(',');

  return (
    <div className="text-sm">
      <p id={id} className="text-content-muted">
        {label}
      </p>

      {value ? (
        <div className="mt-1 flex items-center gap-3 rounded-md border border-edge bg-surface-raised p-2">
          {digest && storedKind(value) === 'image' && (
            <img src={`/api/images/${digest}`} alt="" className="size-12 rounded object-cover" />
          )}
          {digest && storedKind(value) === 'video' && (
            <video src={`/api/images/${digest}`} muted className="h-12 w-20 rounded object-cover" />
          )}
          <span className="min-w-0 flex-1 truncate text-content">
            {digest ? (chosen?.name ?? `A ${WORD[storedKind(value) ?? 'image']} from the library`) : value}
          </span>
          {digest && storedKind(value) === 'audio' && (
            <audio src={`/api/images/${digest}`} controls className="h-8 max-w-48" />
          )}
          <button type="button" onClick={() => onChange('')} className="text-xs text-content-muted hover:text-danger">
            Remove
          </button>
        </div>
      ) : null}

      <div className="mt-2 flex flex-wrap items-center gap-2" role="group" aria-labelledby={id}>
        <label className="cursor-pointer rounded-md border border-edge px-3 py-1.5 text-content transition-colors hover:bg-surface-hover">
          {busy ? 'Uploading…' : 'Upload'}
          <input
            type="file"
            accept={accept}
            className="sr-only"
            disabled={busy}
            onChange={(e) => {
              const file = e.target.files?.[0];
              e.target.value = '';
              if (file) void upload(file);
            }}
          />
        </label>
        <button
          type="button"
          onClick={() => setBrowsing((was) => !was)}
          aria-expanded={browsing}
          className="rounded-md border border-edge px-3 py-1.5 text-content transition-colors hover:bg-surface-hover"
        >
          From library
        </button>
        {link && (
          <input
            type="url"
            value={digest ? '' : value}
            onChange={(e) => onChange(e.target.value)}
            placeholder={link}
            aria-label={`${label}: a link`}
            className="min-w-48 flex-1 rounded-md border border-edge bg-bg px-3 py-1.5 text-content outline-none focus:border-brand"
          />
        )}
      </div>
      {hint && <p className="mt-1 text-xs text-content-subtle">{hint}</p>}
      {problem && <p className="mt-1 text-xs text-danger">{problem}</p>}

      {browsing && (
        <div className="mt-2 max-h-64 overflow-y-auto rounded-md border border-edge p-2">
          {library === null ? (
            <p className="text-content-muted">Loading the library…</p>
          ) : fitting.length === 0 ? (
            <p className="text-content-muted">Nothing in the library yet — upload one.</p>
          ) : (
            <ul className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {fitting.map((file) => (
                <li key={file.digest}>
                  <button
                    type="button"
                    onClick={() => {
                      onChange(SCHEME[file.kind] + file.digest);
                      setBrowsing(false);
                    }}
                    className={`flex w-full flex-col items-center gap-1 rounded-md border p-2 text-xs transition-colors ${
                      digest === file.digest ? 'border-brand bg-brand-subtle' : 'border-edge hover:bg-surface-hover'
                    }`}
                  >
                    {file.kind === 'image' && (
                      <img src={`/api/images/${file.digest}`} alt="" className="h-16 w-full rounded object-cover" />
                    )}
                    {file.kind === 'video' && (
                      <video src={`/api/images/${file.digest}`} muted className="h-16 w-full rounded object-cover" />
                    )}
                    {file.kind === 'audio' && <span className="flex h-16 items-center text-2xl" aria-hidden="true">♪</span>}
                    <span className="w-full truncate text-content">{file.name ?? WORD[file.kind]}</span>
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
