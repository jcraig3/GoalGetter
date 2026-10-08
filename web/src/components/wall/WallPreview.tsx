import { useLayoutEffect, useRef, useState } from 'react';

import { applyAppearance, type Appearance } from '../../appearance';
import WallScreen from './WallScreen';
import { useWallSound, WallSoundContext } from './sound';
import WallStage, { type WallShape } from './WallStage';
import { sampleSlide, type SampleContext } from './sample';
import type { Slide } from './types';

/**
 * The wall, at desk size.
 *
 * **The real screen scaled down, not a drawing of it.** The product this
 * borrows from has no preview anywhere: its theme step shows a static
 * thumbnail, and its celebration editor is forty fields you fill in blind and
 * then walk to a TV to check. A preview built to *imitate* the wall would be no
 * better within a month, because the two would drift — so this renders
 * `WallScreen`, the same component the TV runs, inside a box.
 *
 * **Scaled by transform, not by smaller type.** A wall is designed at 1920×1080
 * with `text-wall-5xl` headings; re-specifying every size for a preview would mean
 * two sets of numbers and a preview that lies about line wrapping. Rendering at
 * full size and scaling the whole thing keeps the proportions exact — what
 * wraps here wraps there.
 */
export default function WallPreview({
  slide,
  kind = 'leaderboard',
  title,
  channelName = '',
  appearance,
  className = '',
  turnable = false,
  sample,
  sound = false,
}: {
  /** A real slide. Omit it and a sample of `kind` is drawn instead. */
  slide?: Slide | null;
  /** Which sample to draw when there is no real slide. */
  kind?: string;
  /** The sample's title: the name of the thing being edited, as typed. */
  title?: string;
  channelName?: string;
  /** Applied to the preview alone, so unsaved edits show here and nowhere else. */
  appearance?: Appearance | null;
  className?: string;
  /** Offer "Landscape · Portrait" underneath (6.11), for whoever is setting
   *  up a television mounted on its side. Off for a preview that is only a
   *  picture of a board. */
  turnable?: boolean;
  /** What the editor's form says, so the sample follows it (7.4). */
  sample?: SampleContext;
  /** Play a video slide with sound — the screen editor's preview. Off for
   *  the small previews in a list, which would all play at once. */
  sound?: boolean;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [shape, setShape] = useRememberedShape(turnable);

  // Applied to the preview's own element, so an unsaved brand colour is visible
  // here without repainting the app around it.
  useLayoutEffect(() => {
    if (box.current) applyAppearance(appearance ?? null, box.current);
  }, [appearance]);

  // **Merged onto the slide rather than passed beside it.** A wall reads one
  // place for how to draw itself — `slide.appearance`, already resolved by the
  // server — and a preview that took layout and background through separate
  // props would be a second way of saying the same thing, which is how the two
  // renderers drift. An unsaved edit simply wins over what the server last
  // resolved.
  const base = slide ?? sampleSlide(kind, title, sample);
  const shown: Slide = {
    ...base,
    appearance: { ...base.appearance, ...(appearance ?? {}) },
  };

  const portrait = shape === 'portrait';
  const outer = useWallSound();
  return (
    <WallSoundContext.Provider value={{ ...outer, previewSound: sound }}>
    <div>
      <div
        ref={box}
        data-preview-shape={shape}
        // 16:9, because that is what a television is — or 9:16, for one on its
        // side. Anything else would let a layout look right here and overflow
        // in the room. Portrait is held to a narrow column so it is not a
        // metre tall on a desk.
        // `wall`: the scope where the organization's font, type scale and panel
        // style apply. Without it a preview would show the colours and none of
        // the rest, which is a preview of something no television shows.
        className={`wall relative overflow-hidden rounded-lg border border-edge bg-bg ${
          portrait ? 'mx-auto aspect-[9/16] w-full max-w-[20rem]' : 'aspect-video w-full'
        } ${className}`}
      >
        {/* The same stage the television draws, scaled to this box instead of
            to a screen — so the preview and the wall cannot disagree about what
            fits. */}
        <WallStage fill="parent" shape={shape}>
          <WallScreen slide={shown} channelName={channelName} headingLevel={2} />
        </WallStage>
        {/* **Said, inside the picture** (7.4): the names and numbers are
            made up, the way a TV preview says PREVIEW. */}
        {!slide && (
          <span className="pointer-events-none absolute right-2 top-2 rounded bg-black/60 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-white/80">
            Sample
          </span>
        )}
      </div>
      {turnable && (
        <div className="mt-2 flex justify-end gap-1" role="group" aria-label="Screen shape">
          {(['landscape', 'portrait'] as const).map((option) => (
            <button
              key={option}
              type="button"
              aria-pressed={shape === option}
              onClick={() => setShape(option)}
              className={`rounded-full border px-2.5 py-0.5 text-xs transition-colors ${
                shape === option
                  ? 'border-brand bg-brand/10 text-content'
                  : 'border-edge text-content-muted hover:bg-surface-hover hover:text-content'
              }`}
            >
              {option === 'landscape' ? 'Landscape' : 'Portrait'}
            </button>
          ))}
        </div>
      )}
    </div>
    </WallSoundContext.Provider>
  );
}

const SHAPE_KEY = 'gg:preview-shape';

/**
 * Which way up the previews are drawn, remembered in this browser: somebody
 * setting up a portrait screen checks every slide that way, and should not
 * have to turn each one. Landscape wherever storage is not available.
 */
function useRememberedShape(turnable: boolean): [WallShape, (shape: WallShape) => void] {
  const [shape, setShape] = useState<WallShape>(() => {
    if (!turnable) return 'landscape';
    try {
      return window.localStorage.getItem(SHAPE_KEY) === 'portrait' ? 'portrait' : 'landscape';
    } catch {
      return 'landscape';
    }
  });
  const choose = (next: WallShape) => {
    setShape(next);
    try {
      window.localStorage.setItem(SHAPE_KEY, next);
    } catch {
      // A private window: remembered for this page only.
    }
  };
  return [turnable ? shape : 'landscape', choose];
}
