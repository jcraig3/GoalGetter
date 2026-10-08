import { useEffect, useState } from 'react';

import { api } from '../api';
import { Swatch, type Entry } from './BackgroundLibrary';
import { BADGE_MARKS, BadgeMark, type BadgeMarkKey } from './badgeMarks';
import Loading from './Loading';

/** How many badge marks ship — the shelf's count before the rest loads. */
export const BUILT_IN_MARKS = Object.keys(BADGE_MARKS).length;

interface PackSound {
  key: string;
  name: string;
  description: string;
}

/**
 * Assets → Built-in (Phase 27): what ships with GoalGetter — the starter
 * sounds, the bundled backgrounds and the badge art. Nothing to remove; each
 * is offered wherever a sound, a background or a badge is chosen.
 */
export default function BuiltInAssets({ onCount }: { onCount?: (n: number) => void }) {
  const [sounds, setSounds] = useState<PackSound[] | null>(null);
  const [backgrounds, setBackgrounds] = useState<Entry[] | null>(null);

  useEffect(() => {
    void Promise.all([
      api<{ pack: PackSound[] }>('/api/sounds').then((r) => r.pack),
      api<{ entries: Entry[] }>('/api/backgrounds').then((r) => r.entries.filter((e) => e.bundled)),
    ])
      .then(([pack, bundled]) => {
        setSounds(pack);
        setBackgrounds(bundled);
        onCount?.(pack.length + bundled.length + BUILT_IN_MARKS);
      })
      .catch(() => {
        setSounds([]);
        setBackgrounds([]);
      });
  }, [onCount]);

  if (!sounds || !backgrounds) return <Loading />;

  return (
    <div className="space-y-8">
      <section>
        <h3 className="mb-3 text-sm font-medium text-content">Starter sounds</h3>
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {sounds.map((s) => (
            <li key={s.key} className="rounded-lg border border-edge bg-surface p-3">
              <p className="text-sm text-content">{s.name}</p>
              <p className="mb-2 truncate text-xs text-content-subtle">{s.description}</p>
              <audio
                src={`/api/sounds/pack/${s.key}`}
                controls
                preload="none"
                className="w-full"
                aria-label={`Play ${s.name}`}
              />
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h3 className="mb-3 text-sm font-medium text-content">Backgrounds</h3>
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          {backgrounds.map((b) => (
            <li key={b.id} className="overflow-hidden rounded-lg border border-edge bg-surface">
              <Swatch background={b.background} imageUrl={(d) => `/api/images/${d}`} />
              <p className="truncate px-2 py-1.5 text-xs text-content">{b.name}</p>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h3 className="mb-3 text-sm font-medium text-content">Badge art</h3>
        <ul className="grid grid-cols-[repeat(auto-fill,minmax(4.5rem,1fr))] gap-2">
          {(Object.keys(BADGE_MARKS) as BadgeMarkKey[]).map((key) => (
            <li key={key} className="flex flex-col items-center rounded-md border border-edge p-2" title={key}>
              <BadgeMark icon={key} className="h-11 w-11" />
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
