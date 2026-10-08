import { useEffect, useState } from 'react';

import { api } from '../api';

/**
 * A logo, uploaded and kept.
 *
 * **Not the photo control.** A photograph is centre-cropped to a square and
 * encoded as JPEG, which turns a wordmark into its middle third and puts a
 * white rectangle behind a transparent mark. The server has a separate
 * normaliser for exactly that reason, and this posts to it.
 *
 * The preview beside the picker is the whole confirmation: a logo that came out
 * the wrong shape is visible here, before anybody hangs it on a wall.
 */
export default function LogoField({
  label,
  digest,
  onChange,
  hint,
}: {
  label: string;
  digest: string | null;
  onChange: (digest: string | null) => void;
  hint?: string;
}) {
  const [busy, setBusy] = useState(false);
  const [browsing, setBrowsing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Width over height, once the image has loaded. A logo is usually a
  // wordmark — wide — and a square or tall image is usually somebody's
  // photograph, which then sat beside every person's own face in the header
  // (review §7).
  const [shape, setShape] = useState<number | null>(null);

  async function upload(file: File) {
    setBusy(true);
    setError(null);
    try {
      const uploaded = await api<{ digest: string }>('/api/images/logo', {
        method: 'POST',
        body: file,
      });
      onChange(uploaded.digest);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not use that image.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <span className="block text-sm text-content-muted">{label}</span>

      {digest && (
        <img
          src={`/api/images/${digest}`}
          alt=""
          onLoad={(e) => {
            const img = e.currentTarget;
            if (img.naturalHeight > 0) setShape(img.naturalWidth / img.naturalHeight);
          }}
          // On a checked ground, because the point of keeping the alpha is
          // that it is there — a transparent logo on a plain panel looks
          // identical to one with a background baked in.
          className="mt-2 h-12 w-auto max-w-full rounded border border-edge bg-[length:12px_12px] bg-[linear-gradient(45deg,#8883_25%,transparent_25%,transparent_75%,#8883_75%),linear-gradient(45deg,#8883_25%,transparent_25%,transparent_75%,#8883_75%)] bg-[position:0_0,6px_6px] object-contain p-1"
        />
      )}

      <div className="mt-2 flex flex-wrap items-center gap-2">
        <input
          type="file"
          accept="image/jpeg,image/png,image/webp"
          disabled={busy}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void upload(file);
          }}
          className="block min-w-0 flex-1 text-sm text-content-muted file:mr-3 file:rounded-md file:border file:border-edge file:bg-surface file:px-3 file:py-1.5 file:text-sm file:text-content"
        />
        {/* Or a picture already in the library (Phase 27). */}
        <button
          type="button"
          onClick={() => setBrowsing((was) => !was)}
          className="rounded-md border border-edge px-3 py-1.5 text-sm text-content transition-colors hover:bg-surface-hover"
        >
          From library
        </button>
      </div>
      {browsing && (
        <LibraryPictures
          chosen={digest}
          onChoose={(next) => {
            onChange(next);
            setBrowsing(false);
          }}
        />
      )}

      {digest && shape !== null && shape < 1.2 && (
        <p className="mt-1 text-xs text-warning">
          This is square or tall, like a photograph. A logo reads best wide — a
          wordmark — and a photo here sits beside everybody&rsquo;s own face in
          the header.
        </p>
      )}

      {digest && (
        <button
          type="button"
          onClick={() => onChange(null)}
          className="mt-1 text-xs text-content-muted underline transition-colors hover:text-content"
        >
          Remove
        </button>
      )}

      {busy && <p className="mt-1 text-xs text-content-subtle">Uploading…</p>}
      {hint && !busy && (
        <p className="mt-1 text-xs text-content-subtle">{hint}</p>
      )}
      {error && (
        <p role="alert" className="mt-1 text-xs text-danger">
          {error}
        </p>
      )}
    </div>
  );
}

/** The library's pictures, to choose one (Phase 27). */
export function LibraryPictures({ chosen, onChoose }: { chosen: string | null; onChoose: (digest: string) => void }) {
  const [images, setImages] = useState<{ digest: string; name: string | null }[] | null>(null);
  useEffect(() => {
    api<{ digest: string; kind: string; name: string | null }[]>('/api/assets')
      .then((all) => setImages(all.filter((a) => a.kind === 'image')))
      .catch(() => setImages([]));
  }, []);
  if (images === null) return <p className="mt-2 text-xs text-content-subtle">Loading the library…</p>;
  if (images.length === 0) return <p className="mt-2 text-xs text-content-subtle">No pictures in the library yet.</p>;
  return (
    <div className="mt-2 flex max-h-48 flex-wrap gap-2 overflow-y-auto rounded-md border border-edge p-2">
      {images.map((image) => (
        <button
          key={image.digest}
          type="button"
          onClick={() => onChoose(image.digest)}
          aria-pressed={chosen === image.digest}
          title={image.name ?? undefined}
          className={`rounded-md border p-1 ${chosen === image.digest ? 'border-brand bg-brand-subtle' : 'border-edge hover:bg-surface-hover'}`}
        >
          <img src={`/api/images/${image.digest}`} alt={image.name ?? ''} className="h-12 w-auto max-w-32 object-contain" />
        </button>
      ))}
    </div>
  );
}
