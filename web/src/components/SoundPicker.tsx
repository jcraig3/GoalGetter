import { useEffect, useRef, useState } from 'react';

import { api } from '../api';
import { toast } from '../toast';

interface PackSound {
  key: string;
  name: string;
  description: string;
  seconds: number;
}

interface OwnSound {
  url: string;
  digest: string;
  name: string | null;
  seconds: number | null;
}

export interface Sounds {
  pack: PackSound[];
  library: OwnSound[];
  defaults: Record<string, string>;
  kinds: { key: string; label: string }[];
}

/** One request for every picker on a page. */
let loading: Promise<Sounds> | null = null;
export function loadSounds(fresh = false): Promise<Sounds> {
  if (!loading || fresh) loading = api<Sounds>('/api/sounds');
  return loading;
}

/** Playing one sound at a time, stopped when another starts. */
let playing: HTMLAudioElement | null = null;
function play(src: string) {
  playing?.pause();
  playing = new Audio(src);
  void playing.play().catch(() => undefined);
}

/**
 * **Choosing a sound for a celebration** (6.17): none, one from the starter
 * pack, or one of the organization's own from Assets — each with ▶ to hear it
 * first. A pack sound is copied into the organization's store when chosen,
 * which is what lets a wall play it.
 *
 * `value` is `asset:<sha256>` or empty for none.
 */
export default function SoundPicker({
  label,
  value,
  onChange,
  hint,
}: {
  label: string;
  value: string;
  onChange: (url: string) => void;
  hint?: string;
}) {
  const [sounds, setSounds] = useState<Sounds | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const id = useRef(`sound-${Math.random().toString(36).slice(2)}`).current;

  useEffect(() => {
    loadSounds().then(setSounds).catch(() => setSounds(null));
  }, []);

  const own = sounds?.library.find((s) => s.url === value);
  async function upload(file: File) {
    setBusy('upload');
    try {
      const stored = await api<{ digest: string; kind: string }>('/api/assets', {
        method: 'POST',
        body: file,
        headers: { 'X-File-Name': encodeURIComponent(file.name) },
      });
      if (stored.kind !== 'audio') {
        toast('That isn’t a sound');
        return;
      }
      setSounds(await loadSounds(true));
      onChange(`asset:${stored.digest}`);
    } catch (error) {
      toast(error instanceof Error ? error.message : 'Couldn’t upload that');
    } finally {
      setBusy(null);
    }
  }

  const current = !value ? 'None' : (own?.name ?? 'A sound from Assets');

  async function choosePack(sound: PackSound) {
    setBusy(sound.key);
    try {
      const kept = await api<{ url: string; name: string }>(`/api/sounds/pack/${sound.key}/keep`, {
        method: 'POST',
      });
      // It is one of the organization's own now; every picker should say so.
      setSounds(await loadSounds(true));
      onChange(kept.url);
      setOpen(false);
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not choose that sound.');
    } finally {
      setBusy(null);
    }
  }

  const row =
    'flex items-center gap-3 rounded-md px-2 py-1.5 text-sm hover:bg-surface-hover';
  const playButton =
    'grid size-7 shrink-0 place-items-center rounded-full border border-edge text-xs text-content-muted hover:border-brand hover:text-content';

  return (
    <div>
      <span id={id} className="block text-sm text-content-muted">
        {label}
      </span>
      <div className="mt-1 flex flex-wrap items-center gap-2">
        <span className="rounded-md border border-edge bg-bg px-3 py-2 text-sm text-content" aria-labelledby={id}>
          {own && (
            <button
              type="button"
              aria-label={`Play ${own.name ?? 'sound'}`}
              onClick={() => play(`/api/images/${own.digest}`)}
              className="mr-2 text-content-muted hover:text-content"
            >
              ▶
            </button>
          )}
          {current}
        </span>
        <button
          type="button"
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
          className="rounded-md border border-edge px-3 py-2 text-sm text-content transition-colors hover:bg-surface-hover"
        >
          {open ? 'Close' : 'Choose a sound'}
        </button>
        {value && (
          <button
            type="button"
            onClick={() => onChange('')}
            className="text-sm text-content-muted hover:text-danger hover:underline"
          >
            No sound
          </button>
        )}
      </div>
      {hint && <p className="mt-1 text-xs text-content-muted">{hint}</p>}

      {open && sounds?.pack && (
        // Two columns only when the picker itself has room — it sits in a
        // narrow form as well as a wide card.
        <div className="@container mt-2 rounded-lg border border-edge p-3">
        <div className="grid gap-3 @xl:grid-cols-2">
          <div>
            <p className="mb-1 text-caption uppercase tracking-wide text-content-subtle">Starter pack</p>
            <ul>
              {sounds.pack.map((sound) => (
                <li key={sound.key} className={row}>
                  <button
                    type="button"
                    aria-label={`Play ${sound.name}`}
                    onClick={() => play(`/api/sounds/pack/${sound.key}`)}
                    className={playButton}
                  >
                    ▶
                  </button>
                  <span className="min-w-0 flex-1">
                    <span className="block text-content">{sound.name}</span>
                    <span className="block truncate text-xs text-content-subtle">
                      {sound.description} · {sound.seconds}s
                    </span>
                  </span>
                  <button
                    type="button"
                    disabled={busy !== null}
                    onClick={() => void choosePack(sound)}
                    className="shrink-0 rounded-md border border-edge px-2 py-1 text-xs text-content-muted hover:border-brand hover:text-content disabled:opacity-50"
                  >
                    {busy === sound.key ? 'Adding…' : 'Use'}
                  </button>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <div className="mb-1 flex items-center justify-between gap-2">
              <p className="text-caption uppercase tracking-wide text-content-subtle">Your sounds</p>
              {/* From this computer, straight into the library (Phase 27). */}
              <label className="cursor-pointer rounded-md border border-edge px-2 py-1 text-xs text-content-muted hover:border-brand hover:text-content">
                {busy === 'upload' ? 'Uploading…' : 'Upload'}
                <input
                  type="file"
                  accept="audio/*"
                  className="sr-only"
                  disabled={busy !== null}
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    e.target.value = '';
                    if (file) void upload(file);
                  }}
                />
              </label>
            </div>
            {sounds.library.length === 0 ? (
              <p className="px-2 text-sm text-content-muted">
                None yet. Sounds added in Assets, and pack sounds once used, appear here.
              </p>
            ) : (
              <ul>
                {sounds.library.map((sound) => (
                  <li key={sound.digest} className={row}>
                    <button
                      type="button"
                      aria-label={`Play ${sound.name ?? 'sound'}`}
                      onClick={() => play(`/api/images/${sound.digest}`)}
                      className={playButton}
                    >
                      ▶
                    </button>
                    <span className="min-w-0 flex-1 truncate text-content">
                      {sound.name ?? 'Untitled sound'}
                      {sound.seconds !== null && (
                        <span className="text-xs text-content-subtle"> · {sound.seconds}s</span>
                      )}
                    </span>
                    <button
                      type="button"
                      aria-pressed={sound.url === value}
                      onClick={() => {
                        onChange(sound.url);
                        setOpen(false);
                      }}
                      className="shrink-0 rounded-md border border-edge px-2 py-1 text-xs text-content-muted hover:border-brand hover:text-content aria-pressed:border-brand aria-pressed:text-content"
                    >
                      {sound.url === value ? 'Chosen' : 'Use'}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
        </div>
      )}
    </div>
  );
}

/**
 * **What plays for each kind of win** (6.17), when the person has no walk-up
 * music of their own — on the Celebrations page, for an admin.
 */
export function DefaultSounds() {
  const [sounds, setSounds] = useState<Sounds | null>(null);
  const [chosen, setChosen] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    loadSounds()
      .then((found) => {
        setSounds(found);
        setChosen(found.defaults);
      })
      .catch(() => setSounds(null));
  }, []);

  // Nothing rather than a crash: this sits on the Celebrations page, and a
  // broken answer here must not take the rules down with it.
  if (!sounds?.kinds) return null;
  const changed = JSON.stringify(chosen) !== JSON.stringify(sounds.defaults);

  async function save() {
    setBusy(true);
    try {
      const saved = await api<Record<string, string>>('/api/sounds/defaults', {
        method: 'PUT',
        body: JSON.stringify(Object.fromEntries(sounds!.kinds.map((k) => [k.key, chosen[k.key] || null]))),
      });
      setSounds({ ...(await loadSounds(true)), defaults: saved });
      setChosen(saved);
      toast('Default sounds saved');
    } catch (e) {
      toast(e instanceof Error ? e.message : 'Could not save those.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mb-8 rounded-lg border border-edge bg-surface p-6" aria-labelledby="default-sounds">
      <h2 id="default-sounds" className="text-h3 text-content">
        Default sounds
      </h2>
      <p className="mt-1 text-sm text-content-muted">
        What a wall plays for each kind of win when the person has no walk-up music of their own.
        Their own always comes first. A celebration rule sets its sound on the rule.
      </p>
      <div className="mt-4 grid gap-5 lg:grid-cols-2">
        {sounds.kinds.map((kind) => (
          <SoundPicker
            key={kind.key}
            label={kind.label}
            value={chosen[kind.key] ?? ''}
            onChange={(url) =>
              setChosen((was) => {
                const next = { ...was };
                if (url) next[kind.key] = url;
                else delete next[kind.key];
                return next;
              })
            }
          />
        ))}
      </div>
      <button
        type="button"
        disabled={!changed || busy}
        onClick={() => void save()}
        className="mt-5 rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
      >
        {busy ? 'Saving…' : 'Save sounds'}
      </button>
    </section>
  );
}
