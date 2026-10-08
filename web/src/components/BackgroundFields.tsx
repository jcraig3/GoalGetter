import { useEffect, useState } from 'react';

import { api } from '../api';
import BackgroundLibrary from './BackgroundLibrary';
import Field from './Field';
import { youtubeIdFromLink } from './YouTubePlayer';
import TimeField from './TimeField';
import Select from './Select';
import type { Background } from '../appearance';
import { SCENE_NAMES } from './wall/Scenes';

/**
 * What sits behind a wall screen.
 *
 * **The controls change with the kind, because the questions do.** A solid
 * colour has one; a gradient has two; a photograph has a file and how much to
 * darken it. Showing all of them at once and greying five out is a form that
 * asks eight questions to answer one.
 *
 * Dim and blur are offered for every kind that can carry detail, and the hint
 * says why: a photograph behind white text is unreadable at ten feet, and
 * darkening the photograph is the fix that keeps the photograph.
 */
const EMPTY: Background = {
  kind: 'none',
  color: null,
  color_to: null,
  color_mid: null,
  angle: null,
  style: null,
  motion: null,
  asset: null,
  dim: null,
  blur: null,
};

const SHELVES = [
  ['calm', 'Calm'],
  ['energy', 'Energy'],
  ['celebration', 'Celebration'],
  ['seasonal', 'Seasonal'],
  ['brand', 'Your brand'],
] as const;

/**
 * Keeping the current background on a shelf.
 *
 * Asks for a name and a shelf and nothing else: the background itself is
 * whatever is already set above, which is the one the person is looking at.
 */
function KeepForm({
  background,
  onClose,
  onKept,
}: {
  background: Background;
  onClose: () => void;
  onKept: () => void;
}) {
  const [name, setName] = useState('');
  const [category, setCategory] = useState<string>('calm');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      // Only the fields that say something: nulls would be kept as nulls and
      // mean nothing.
      const shape = Object.fromEntries(
        Object.entries(background).filter(([, value]) => value !== null),
      );
      await api('/api/backgrounds', {
        method: 'POST',
        body: JSON.stringify({ name, category, background: shape }),
      });
      onKept();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not keep that.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-3 rounded-md border border-edge bg-surface-hover p-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="text-sm text-content-muted">Name it</span>
          <input
            value={name}
            maxLength={60}
            onChange={(e) => setName(e.target.value)}
            placeholder="Office at night"
            className="mt-1 w-full rounded-md border border-edge bg-bg px-3 py-2 text-content"
          />
        </label>
        <Select
          label="Shelf"
          value={category}
          onChange={setCategory}
          options={SHELVES.map(([value, label]) => ({ value, label }))}
        />
      </div>
      {error && (
        <p role="alert" className="rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <button
          type="button"
          onClick={save}
          disabled={saving || !name.trim()}
          className="rounded-md bg-brand px-4 py-2 text-sm text-white disabled:opacity-60"
        >
          {saving ? 'Keeping…' : 'Keep'}
        </button>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md px-4 py-2 text-sm text-content-muted hover:text-content"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

export default function BackgroundFields({
  value,
  onChange,
}: {
  value: Background | null | undefined;
  onChange: (next: Background) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [browsing, setBrowsing] = useState(false);
  const [keeping, setKeeping] = useState(false);
  const [kept, setKept] = useState(0);

  const background: Background = { ...EMPTY, ...(value ?? {}) };

  const set = (part: Partial<Background>) =>
    onChange({ ...background, ...part });

  async function upload(file: File, as: 'background' | 'background-video') {
    setBusy(true);
    setError(null);
    try {
      const { digest } = await api<{ digest: string }>(
        `/api/images/${as}`,
        {
          method: 'POST',
          // The bytes are the body, and the browser labels them — `api` leaves
          // a Blob's content type alone for exactly this. Nothing on the
          // server trusts the label anyway; it decodes the file to find out
          // what it is.
          body: file,
        },
      );
      set({ asset: digest });
    } catch (e) {
      // The server's words, which for a video are specific: HEVC from an
      // iPhone, a .mov, too long — each with what to do about it.
      setError(e instanceof Error ? e.message : 'Could not use that file.');
    } finally {
      setBusy(false);
    }
  }

  const detailed =
    background.kind === 'image' ||
    background.kind === 'video' ||
    background.kind === 'youtube';
  // Worth keeping: something is drawn, and any file it needs is already here.
  const keepable =
    background.kind === 'solid' ||
    background.kind === 'gradient' ||
    (detailed && Boolean(background.asset));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-3 text-sm">
        <button
          type="button"
          onClick={() => setBrowsing((open) => !open)}
          aria-expanded={browsing}
          className="text-brand hover:underline"
        >
          {browsing ? 'Hide the library' : 'Choose from the library'}
        </button>
        {keepable && !keeping && (
          <button
            type="button"
            onClick={() => setKeeping(true)}
            className="text-content-muted hover:text-brand"
          >
            Keep this in the library
          </button>
        )}
      </div>

      {browsing && (
        <BackgroundLibrary
          refreshKey={kept}
          onClose={() => setBrowsing(false)}
          onChoose={(chosen) => {
            // Replaced whole, not merged: a library entry is a complete
            // background, and merging would leave a photograph's asset under
            // a gradient that never uses it.
            onChange({ ...EMPTY, ...chosen });
            setBrowsing(false);
          }}
        />
      )}

      {keeping && (
        <KeepForm
          background={background}
          onClose={() => setKeeping(false)}
          onKept={() => {
            setKeeping(false);
            setKept((n) => n + 1);
          }}
        />
      )}
      <Select
        label="Background"
        value={background.kind}
        onChange={(v) => set({ kind: v as Background['kind'] })}
        options={[
          { value: 'none', label: 'None' },
          { value: 'solid', label: 'A colour' },
          { value: 'gradient', label: 'A gradient' },
          { value: 'image', label: 'A photograph' },
          { value: 'video', label: 'A video loop (uploaded)' },
          { value: 'youtube', label: 'A YouTube video' },
          { value: 'scene', label: 'A drawn scene' },
        ]}
      />

      {(background.kind === 'solid' || background.kind === 'gradient') && (
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <span className="block text-sm text-content-muted">
              {background.kind === 'gradient' ? 'From' : 'Colour'}
            </span>
            <input
              type="color"
              aria-label={background.kind === 'gradient' ? 'From' : 'Colour'}
              value={background.color ?? '#0b0e14'}
              onChange={(e) => set({ color: e.target.value })}
              className="mt-1 h-9 w-full cursor-pointer rounded-md border border-edge bg-bg"
            />
          </div>
          {background.kind === 'gradient' && (
            <div>
              <span className="block text-sm text-content-muted">To</span>
              <input
                type="color"
                aria-label="To"
                value={background.color_to ?? '#1c212d'}
                onChange={(e) => set({ color_to: e.target.value })}
                className="mt-1 h-9 w-full cursor-pointer rounded-md border border-edge bg-bg"
              />
            </div>
          )}
        </div>
      )}

      {/* **A drawn scene** (6.9): which one, its three colours, and whether
          it moves. Drawn in code on the wall, so nothing to upload. */}
      {background.kind === 'scene' && (
        <div className="space-y-4">
          <Select
            label="Scene"
            value={background.scene ?? 'mesh'}
            onChange={(v) => set({ scene: v })}
            options={Object.entries(SCENE_NAMES).map(([value, label]) => ({ value, label }))}
          />
          <div className="grid gap-4 sm:grid-cols-3">
            {(
              [
                ['color', 'Base', '#0b0e14'],
                ['color_mid', 'Middle', '#334155'],
                ['color_to', 'Highlight', '#64748b'],
              ] as const
            ).map(([key, label, fallback]) => (
              <div key={key}>
                <span className="block text-sm text-content-muted">{label}</span>
                <input
                  type="color"
                  aria-label={label}
                  value={(background[key] as string | null | undefined) ?? fallback}
                  onChange={(e) => set({ [key]: e.target.value })}
                  className="mt-1 h-9 w-full cursor-pointer rounded-md border border-edge bg-bg"
                />
              </div>
            ))}
          </div>
          <label className="flex items-start gap-2 text-sm text-content">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={Boolean(background.motion)}
              onChange={(e) => set({ motion: e.target.checked })}
            />
            <span>
              Moving
              <span className="block text-xs text-content-subtle">
                Waves roll, lights rise, confetti falls — slowly, and light enough
                for a television stick. Still for anybody whose device asks for
                less motion.
              </span>
            </span>
          </label>
        </div>
      )}

      {background.kind === 'gradient' && (
        <div className="space-y-4">
          <label className="flex items-center gap-2 text-sm text-content">
            <input
              type="checkbox"
              checked={Boolean(background.color_mid)}
              onChange={(e) =>
                set({ color_mid: e.target.checked ? '#3b3f8f' : null })
              }
            />
            A middle colour
          </label>
          {background.color_mid && (
            <input
              type="color"
              aria-label="Middle"
              value={background.color_mid}
              onChange={(e) => set({ color_mid: e.target.value })}
              className="h-9 w-full cursor-pointer rounded-md border border-edge bg-bg"
            />
          )}
          <div className="grid gap-4 sm:grid-cols-2">
            <Select
              label="Shape"
              value={background.style ?? 'linear'}
              onChange={(v) => set({ style: v as 'linear' | 'radial' })}
              options={[
                { value: 'linear', label: 'Across the screen' },
                { value: 'radial', label: 'From a glow' },
              ]}
            />
            {(background.style ?? 'linear') === 'linear' && (
              <Range
                label="Angle"
                value={background.angle ?? 135}
                min={0}
                max={360}
                step={5}
                onChange={(n) => set({ angle: n })}
              />
            )}
          </div>
          <label className="flex items-start gap-2 text-sm text-content">
            <input
              type="checkbox"
              className="mt-0.5"
              checked={Boolean(background.motion)}
              onChange={(e) => set({ motion: e.target.checked })}
            />
            <span>
              Drift slowly
              <span className="block text-xs text-content-subtle">
                Movement without a video file, light enough for a television
                stick. It stays still for anybody whose device asks for less
                motion.
              </span>
            </span>
          </label>
        </div>
      )}

      {background.kind === 'image' && (
        <div>
          <span className="block text-sm text-content-muted">Photograph</span>
          <input
            type="file"
            aria-label="Photograph"
            accept="image/jpeg,image/png,image/webp"
            disabled={busy}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void upload(file, 'background');
            }}
            className="mt-1 block w-full text-sm text-content-muted file:mr-3 file:rounded-md file:border file:border-edge file:bg-surface file:px-3 file:py-1.5 file:text-sm file:text-content"
          />
          <p className="mt-1 text-xs text-content-subtle">
            {busy
              ? 'Uploading…'
              : background.asset
                ? 'Stored. It fills the screen, so its edges may be cropped — a photo the shape of a TV loses least.'
                : 'Fitted inside 1920×1080. Anything larger is detail a television cannot show.'}
          </p>
          {background.asset && <PortraitWarning digest={background.asset} />}
        </div>
      )}

      {background.kind === 'video' && (
        <div>
          <span className="block text-sm text-content-muted">Video</span>
          <input
            type="file"
            aria-label="Video"
            accept="video/mp4"
            disabled={busy}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void upload(file, 'background-video');
            }}
            className="mt-1 block w-full text-sm text-content-muted file:mr-3 file:rounded-md file:border file:border-edge file:bg-surface file:px-3 file:py-1.5 file:text-sm file:text-content"
          />
          <p className="mt-1 text-xs text-content-subtle">
            {busy
              ? 'Uploading…'
              : background.asset
                ? 'Stored. It plays muted, on a loop, from this server — no adverts and no internet needed.'
                : 'An MP4 up to 20 MB and a minute long. A few seconds that loop cleanly work best.'}
          </p>
        </div>
      )}

      {background.kind === 'youtube' && (
        <Field
          label="YouTube link"
          value={background.asset ?? ''}
          // A pasted link is kept as its video id (Phase 28): a whole link cut
          // to fit was a video that never played.
          onChange={(v) => set({ asset: youtubeIdFromLink(v.trim()) ?? (v.trim() || null) })}
          maxLength={300}
          required={false}
          hint="Paste the link. It loops, with sound on a TV. Whether it shows adverts is up to whoever uploaded it to YouTube — an uploaded video loop never does."
        />
      )}
      {background.kind === 'youtube' && (
        <TimeField
          // Remounted per video, so a new link starts with its own time.
          key={background.asset ?? ''}
          label="Start at"
          seconds={background.start ?? null}
          onChange={(start) => set({ start })}
          placeholder="0:00"
          hint="Into the video — 0:40, or 40. It loops back to here."
        />
      )}

      {/* Darken for a gradient as well: a bright one straight behind white
          text is the same problem as a bright photograph, and the bundled
          light gradients arrive dimmed for exactly that reason. Blur only
          where there is detail to soften — a blurred gradient is the same
          gradient. */}
      {(detailed || background.kind === 'gradient' || background.kind === 'scene') && (
        <div className="grid gap-4 sm:grid-cols-2">
          <Range
            label="Darken"
            value={background.dim ?? (background.kind === 'gradient' ? 0 : 0.35)}
            min={0}
            max={1}
            step={0.05}
            onChange={(n) => set({ dim: n })}
            hint="White text over anything bright is unreadable at ten feet."
          />
          {detailed && (
            <Range
              label="Blur"
              value={background.blur ?? 0}
              min={0}
              max={40}
              step={1}
              onChange={(n) => set({ blur: n })}
              hint="Blurring detail is what keeps a busy picture from competing with the numbers."
            />
          )}
        </div>
      )}

      {error && (
        <p
          role="alert"
          className="rounded-md border border-danger px-3 py-2 text-sm text-danger"
        >
          {error}
        </p>
      )}
    </div>
  );
}

function Range({
  label,
  value,
  min,
  max,
  step,
  onChange,
  hint,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
  hint?: string;
}) {
  return (
    <div>
      <span className="block text-sm text-content-muted">
        {label}
        <span className="ml-2 tabular-nums text-content-subtle">{value}</span>
      </span>
      <input
        type="range"
        aria-label={label}
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mt-2 w-full accent-brand"
      />
      {hint && <p className="mt-1 text-xs text-content-subtle">{hint}</p>}
    </div>
  );
}

/**
 * A portrait photograph on landscape TVs, said before it is hung (8.4): it
 * fills by losing most of its height, which is usually somebody's head.
 * Measured from the picture itself, so it holds for one chosen from Assets too.
 */
function PortraitWarning({ digest }: { digest: string }) {
  const [portrait, setPortrait] = useState(false);
  useEffect(() => {
    const image = new Image();
    image.onload = () => setPortrait(image.naturalHeight > image.naturalWidth);
    image.src = `/api/images/${digest}`;
    return () => {
      image.onload = null;
    };
  }, [digest]);
  if (!portrait) return null;
  return (
    <p className="mt-2 rounded-md border border-warning px-3 py-2 text-xs text-warning">
      This picture is taller than it is wide. On a landscape TV it fills the screen by losing
      most of its top and bottom — a landscape photo, or a portrait TV, suits it better.
    </p>
  );
}
