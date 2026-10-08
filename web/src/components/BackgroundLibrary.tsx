import { useEffect, useState } from 'react';

import { api } from '../api';
import type { Background } from '../appearance';
import { Tab } from './Tabs';
import { gradientCss } from './wall/WallBackground';
import { ask } from '../confirm';
import Loading from './Loading';
import { toast } from '../toast';
import Scene from './wall/Scenes';

export interface Entry {
  id: string;
  name: string;
  category: string;
  background: Background;
  bundled: boolean;
}

interface Library {
  categories: string[];
  entries: Entry[];
}

const SHELF: Record<string, string> = {
  calm: 'Calm',
  energy: 'Energy',
  celebration: 'Celebration',
  seasonal: 'Seasonal',
  brand: 'Your brand',
  scenes: 'Scenes',
  assets: 'Your photos & video',
};

/**
 * Choosing a background from the shelves.
 *
 * **Choosing copies.** The entry's background is written onto this screen,
 * not linked to it — so editing or removing a library entry later changes no
 * wall that already uses it. Nothing on a television should move because
 * somebody tidied a list.
 *
 * The swatches are drawn with the same CSS the wall uses, so what is picked
 * here is what the screen shows.
 */
export default function BackgroundLibrary({
  onChoose,
  onClose,
  imageUrl = (digest: string) => `/api/images/${digest}`,
  refreshKey = 0,
}: {
  onChoose: (background: Background) => void;
  onClose: () => void;
  imageUrl?: (digest: string) => string;
  refreshKey?: number;
}) {
  const [library, setLibrary] = useState<Library | null>(null);
  const [shelf, setShelf] = useState<string>('yours');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Library>('/api/backgrounds')
      .then((found) => {
        setLibrary(found);
        // Land on what this organization kept, if it has kept anything:
        // that is the shelf somebody coming back to the library came for.
        setShelf(found.entries.some((e) => !e.bundled) ? 'yours' : 'calm');
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load.'));
  }, [refreshKey]);

  async function remove(entry: Entry) {
    if (!await ask(`Take "${entry.name}" off the shelf? Screens using it keep it.`)) {
      return;
    }
    try {
      await api(`/api/backgrounds/${entry.id.split(':')[1]}`, { method: 'DELETE' });
      toast('Taken off the shelf');
      setLibrary((current) =>
        current
          ? { ...current, entries: current.entries.filter((e) => e.id !== entry.id) }
          : current,
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not remove.');
    }
  }

  if (error && !library) {
    return (
      <p role="alert" className="rounded-md border border-danger px-3 py-2 text-sm text-danger">
        {error}
      </p>
    );
  }
  if (!library) return <Loading />;

  const kept = library.entries.filter((e) => !e.bundled);
  const shown =
    shelf === 'yours'
      ? kept
      : library.entries.filter((e) => e.bundled && e.category === shelf);

  return (
    <div className="space-y-3 rounded-md border border-edge bg-surface-hover p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap gap-1">
          {kept.length > 0 && (
            <Tab active={shelf === 'yours'} onClick={() => setShelf('yours')}>
              Kept here
            </Tab>
          )}
          {library.categories.map((category) => (
            <Tab key={category} active={shelf === category} onClick={() => setShelf(category)}>
              {SHELF[category] ?? category}
            </Tab>
          ))}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="text-sm text-content-muted hover:text-content"
        >
          Close
        </button>
      </div>

      {shown.length === 0 ? (
        <p className="text-sm text-content-muted">Nothing on this shelf yet.</p>
      ) : (
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {shown.map((entry) => (
            <li key={entry.id} className="group relative">
              <button
                type="button"
                onClick={() => onChoose(entry.background)}
                className="block w-full overflow-hidden rounded-md border border-edge text-left hover:border-brand focus-visible:border-brand"
              >
                <Swatch background={entry.background} imageUrl={imageUrl} />
                <span className="block truncate px-2 py-1.5 text-sm text-content">
                  {entry.name}
                </span>
              </button>
              {!entry.bundled && (
                <button
                  type="button"
                  onClick={() => remove(entry)}
                  aria-label={`Remove ${entry.name} from the library`}
                  className="absolute right-1 top-1 rounded bg-surface/80 px-1.5 text-xs text-content-muted opacity-0 hover:text-danger focus-visible:opacity-100 group-hover:opacity-100"
                >
                  Remove
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      <p className="text-xs text-content-subtle">
        Choosing one copies it onto this screen, so changing the library later
        never changes a wall that already uses it.
      </p>
    </div>
  );
}

/** A small picture of a background, drawn the way the wall draws it. */
export function Swatch({
  background,
  imageUrl,
}: {
  background: Background;
  imageUrl: (digest: string) => string;
}) {
  const shade = background.dim ? { boxShadow: `inset 0 0 0 999px rgba(0,0,0,${background.dim})` } : {};
  const box = 'block aspect-video w-full';

  if (background.kind === 'solid') {
    return <span className={box} style={{ backgroundColor: background.color ?? '#000', ...shade }} />;
  }
  if (background.kind === 'gradient') {
    return (
      <span className={`${box} relative`} style={{ backgroundImage: gradientCss(background), ...shade }}>
        {background.motion && (
          <span className="absolute bottom-1 right-1 rounded bg-black/50 px-1 text-[10px] text-white">
            moves
          </span>
        )}
      </span>
    );
  }
  if (background.kind === 'image' && background.asset) {
    return (
      <span
        className={box}
        style={{
          backgroundImage: `url(${imageUrl(background.asset)})`,
          backgroundSize: 'cover',
          backgroundPosition: 'center',
          ...shade,
        }}
      />
    );
  }
  if (background.kind === 'scene') {
    // The scene itself, small: the same drawing the wall makes.
    return (
      <span className={`${box} relative overflow-hidden`} style={shade}>
        <Scene
          scene={background.scene ?? 'mesh'}
          colours={{
            base: background.color ?? '#0b0e14',
            mid: background.color_mid ?? background.color_to ?? '#334155',
            top: background.color_to ?? background.color_mid ?? '#64748b',
          }}
          moving={Boolean(background.motion)}
        />
        {background.motion && (
          <span className="absolute bottom-1 right-1 rounded bg-black/50 px-1 text-[10px] text-white">
            moves
          </span>
        )}
      </span>
    );
  }
  if (background.kind === 'video' && background.asset) {
    return (
      <video
        src={imageUrl(background.asset)}
        muted
        preload="metadata"
        className={`${box} object-cover`}
        aria-hidden="true"
      />
    );
  }
  return (
    <span className={`${box} grid place-items-center bg-bg text-xs text-content-muted`}>
      {background.kind === 'youtube' ? 'YouTube video' : 'Background'}
    </span>
  );
}
