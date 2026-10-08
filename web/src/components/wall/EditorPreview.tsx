import { useEffect, useState } from 'react';

import { api } from '../../api';
import type { Appearance } from '../../appearance';
import WallPreview from './WallPreview';
import type { SampleContext } from './sample';
import { nobodyYet } from './NobodyYet';
import type { Slide } from './types';

/**
 * The wall, large, beside the form that changes it (5j).
 *
 * The Appearance page proved the pattern: a change is judged by looking at it.
 * The board, goal and competition forms showed a thumbnail, and only once
 * "Give this its own appearance" was open; this one is on show from the
 * start, follows every unsaved change, and carries the item's own name, so
 * it looks like this item rather than like any board.
 *
 * Sample numbers, said so underneath: an unsaved board has no standings yet,
 * and a preview that invented real-looking ones would be the lie.
 */
export default function EditorPreview({
  kind,
  title,
  chosen,
  inherited,
  sample,
  real,
}: {
  /** `leaderboard`, `goal` or `competition`. */
  kind: string;
  /** The name as typed so far. Empty draws the sample's own. */
  title?: string;
  /** What this item has set for itself, unsaved. */
  chosen: Record<string, unknown>;
  /** The organization's look, which anything unset follows. */
  inherited: Appearance | null;
  /** What the form says — unit, who, period, prize — for the sample (7.4). */
  sample?: SampleContext;
  /**
   * Where to ask for this form drawn with **real numbers** (8.7), and the
   * form as it would be saved. Absent until the form says enough to ask.
   */
  real?: { path: string; body: unknown } | null;
}) {
  const [mode, setMode] = useState<'sample' | 'real'>('sample');
  const [slide, setSlide] = useState<Slide | null | undefined>(undefined);
  const key = real ? JSON.stringify(real.body) : '';

  // A moment after the form stops changing, as the slide editor does.
  useEffect(() => {
    if (mode !== 'real' || !real) return;
    let stale = false;
    const timer = window.setTimeout(() => {
      api<Slide | null>(real.path, { method: 'POST', body: key })
        .then((drawn) => !stale && setSlide(drawn))
        .catch(() => !stale && setSlide(null));
    }, 400);
    return () => {
      stale = true;
      window.clearTimeout(timer);
    };
    // `key` is the body; `real` is a fresh object each render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, key, real?.path]);

  const showingReal = mode === 'real' && real && slide;
  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-3">
        <p className="text-caption uppercase tracking-wide text-content-subtle">On a wall</p>
        {real !== undefined && (
          <span className="inline-flex rounded-md border border-edge p-0.5 text-xs" role="group" aria-label="Numbers">
            {(['sample', 'real'] as const).map((m) => (
              <button
                key={m}
                type="button"
                aria-pressed={mode === m}
                disabled={m === 'real' && !real}
                onClick={() => setMode(m)}
                className={`rounded px-2 py-0.5 disabled:opacity-50 ${
                  mode === m ? 'bg-brand-subtle text-content' : 'text-content-muted hover:text-content'
                }`}
              >
                {m === 'sample' ? 'Sample' : 'Real numbers'}
              </button>
            ))}
          </span>
        )}
      </div>
      <WallPreview
        kind={kind}
        slide={showingReal ? slide : undefined}
        title={title?.trim() || undefined}
        appearance={inherited ? ({ ...inherited, ...chosen } as Appearance) : null}
        turnable
        sample={sample}
        // Not on a channel yet, so no invented one ("Main floor") (7.4).
        channelName=""
      />
      <p className="mt-2 text-xs text-content-subtle">
        {showingReal && kind === 'leaderboard' && nobodyYet(slide)
          ? 'Nothing in this period yet — this is what a TV shows right now. Nothing is saved.'
          : showingReal
          ? `Real numbers, as a wall for everyone would draw this ${kind === 'leaderboard' ? 'board' : kind} now. Nothing is saved.`
          : mode === 'real' && slide === null
            ? 'Nothing to show with real numbers yet — no data in this period. Showing a sample.'
            : `Sample numbers, in this ${kind === 'leaderboard' ? 'board' : kind}’s layout and look. Changes show here before they are saved.`}
      </p>
    </div>
  );
}
