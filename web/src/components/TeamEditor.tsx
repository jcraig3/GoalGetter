import { useEffect, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';

import { api } from '../api';
import UploadToLibrary from './UploadToLibrary';
import Field from './Field';
import Modal from './Modal';
import { MarkLabel, markColour, markLabel } from './wall/entryLook';

export interface TeamLook {
  id: number;
  name: string;
  color: string | null;
  short_name?: string | null;
  logo?: string | null;
}

/** The colours offered first: distinct from each other on a dark wall. */
const SWATCHES = ['#2563eb', '#dc2626', '#16a34a', '#d97706', '#9333ea', '#0891b2', '#db2777', '#475569'];

/**
 * A team's name and how it is known on a wall (6.7): a short name, a colour
 * and a logo. Shown as the wall will draw it, while it is being chosen.
 */
export default function TeamEditor({
  team,
  onClose,
  onSaved,
}: {
  team: TeamLook;
  onClose: () => void;
  onSaved: () => Promise<void> | void;
}) {
  const [name, setName] = useState(team.name);
  const [shortName, setShortName] = useState(team.short_name ?? '');
  const [colour, setColour] = useState(team.color ?? '');
  const [logo, setLogo] = useState<string | null>(team.logo ?? null);
  const [images, setImages] = useState<{ digest: string; name: string | null }[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<{ digest: string; name: string | null; kind: string }[]>('/api/assets')
      .then((all) => setImages(all.filter((a) => a.kind === 'image')))
      .catch(() => setImages([]));
  }, []);

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api(`/api/teams/${team.id}`, {
        method: 'PATCH',
        body: JSON.stringify({
          name: name.trim(),
          short_name: shortName.trim() || null,
          color: colour || null,
          logo,
        }),
      });
      await onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save the team.');
    } finally {
      setBusy(false);
    }
  }

  const look = { entity_name: name || team.name, colour: colour || null, short_name: shortName.trim() || null };

  return (
    <Modal title={`Edit ${team.name}`} description="Its name, and how a wall shows it." onClose={onClose}>
      <form onSubmit={save} className="space-y-5">
        <Field label="Name" value={name} onChange={setName} maxLength={200} />
        <Field
          label="Short name"
          value={shortName}
          onChange={setShortName}
          maxLength={12}
          required={false}
          // No placeholder: "ENT" in the box read as a value already set (review §7).
          hint={`For where the full name will not fit — a podium, a race piece. Leave empty to use its initials, “${markLabel({ entity_name: name || team.name })}”.`}
        />

        <fieldset>
          <legend className="text-sm text-content-muted">Colour</legend>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {SWATCHES.map((swatch) => (
              <button
                key={swatch}
                type="button"
                aria-label={swatch}
                aria-pressed={colour === swatch}
                onClick={() => setColour(swatch)}
                style={{ backgroundColor: swatch }}
                className={`size-8 rounded-full border-2 ${colour === swatch ? 'border-content' : 'border-transparent'}`}
              />
            ))}
            <input
              type="color"
              aria-label="Another colour"
              value={colour || '#64748b'}
              onChange={(e) => setColour(e.target.value)}
              className="size-8 cursor-pointer rounded-full border border-edge bg-transparent"
            />
            <button
              type="button"
              onClick={() => setColour('')}
              aria-pressed={!colour}
              className={`rounded-md border px-2 py-1 text-xs hover:bg-surface-hover ${!colour ? 'border-brand text-content' : 'border-edge text-content-muted'}`}
            >
              From its name
            </button>
          </div>
          {/* It was "None", and the preview drew green — the wall's colour
              from the name, which is what an unset colour really is (§7). */}
          {!colour && (
            <p className="mt-1 text-xs text-content-subtle">
              Picked from the name, so every team gets its own without choosing.
            </p>
          )}
        </fieldset>

        <fieldset>
          <legend className="text-sm text-content-muted">Logo</legend>
          <p className="mt-1 text-xs text-content-subtle">
            From{' '}
            <Link to="/library" className="underline">
              Assets
            </Link>
            {images && images.length === 0 ? ' — add a picture there first.' : '. One with a transparent background sits best on the colour.'}
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => setLogo(null)}
              aria-pressed={logo === null}
              aria-label="Initials"
              className={`flex items-center gap-2 rounded-md border px-2 py-1 text-xs ${logo === null ? 'border-brand bg-brand-subtle text-content' : 'border-edge text-content-muted hover:bg-surface-hover'}`}
            >
              {/* The default "logo" is its initials on its colour (§7) —
                  shown as one, not as "No logo". */}
              <Mark look={look} className="size-10 text-sm" />
              Initials
            </button>
            <UploadToLibrary
              onUploaded={(file) => {
                if (file.kind !== 'image') return;
                setImages((all) => [{ digest: file.digest, name: file.name }, ...(all ?? [])]);
                setLogo(file.digest);
              }}
            />
            {(images ?? []).map((image) => (
              <button
                key={image.digest}
                type="button"
                onClick={() => setLogo(image.digest)}
                aria-pressed={logo === image.digest}
                aria-label={image.name ?? 'Picture'}
                title={image.name ?? undefined}
                className={`rounded-md border p-1 ${logo === image.digest ? 'border-brand bg-brand-subtle' : 'border-edge hover:bg-surface-hover'}`}
              >
                <img src={`/api/images/${image.digest}`} alt="" className="size-10 object-contain" />
              </button>
            ))}
          </div>
        </fieldset>

        {/* As a wall draws it: a podium place and a row on a board. */}
        <div className="rounded-lg border border-edge bg-bg p-4">
          <p className="text-caption uppercase tracking-wide text-content-subtle">On a wall</p>
          <div className="mt-3 flex items-center gap-6">
            <Mark look={look} logo={logo} className="size-16 text-xl" />
            <div className="flex min-w-0 flex-1 items-center gap-3 rounded-md bg-surface px-3 py-2">
              <span className="text-content-subtle">1</span>
              <Mark look={look} logo={logo} className="size-8 text-xs" />
              <span className="truncate text-content">{look.entity_name}</span>
            </div>
          </div>
        </div>

        {error && (
          <p role="alert" className="rounded-md border border-danger px-3 py-2 text-sm text-danger">
            {error}
          </p>
        )}
        <div className="flex gap-2">
          <button
            type="submit"
            disabled={busy || !name.trim()}
            className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
          >
            {busy ? 'Saving…' : 'Save'}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-edge px-4 py-2 text-sm text-content-muted hover:bg-surface-hover"
          >
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  );
}

/** A team's mark: its logo on its colour, or its short name on its colour. */
export function Mark({
  look,
  logo,
  className = 'size-6 text-[0.6rem]',
}: {
  look: { entity_name: string; colour?: string | null; short_name?: string | null };
  logo?: string | null;
  className?: string;
}) {
  const style = { backgroundColor: markColour(look) };
  return logo ? (
    <img src={`/api/images/${logo}`} alt="" aria-hidden="true" style={style} className={`shrink-0 rounded-full object-contain p-[12%] ${className}`} />
  ) : (
    <span aria-hidden="true" style={style} className={`grid shrink-0 place-items-center rounded-full font-semibold text-white ${className}`}>
      <MarkLabel entry={{ ...look, colour: look.colour ?? null, short_name: look.short_name ?? null }} />
    </span>
  );
}
