import {
  createContext,
  useContext,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
  type Ref,
} from 'react';

/** What a wall is designed against. Every screen assumes these proportions —
 *  turned on its side for a portrait one. */
export const WALL_WIDTH = 1920;
export const WALL_HEIGHT = 1080;

/**
 * **Which way up the screen is** (6.11). A television mounted on its side —
 * beside a door, down a pillar, in a corridor — is 1080 wide and 1920 tall,
 * and a 16:9 wall letterboxed into it uses a third of the glass. So the stage
 * turns with it, and the layouts that care read this to draw their portrait
 * version.
 */
export type WallShape = 'landscape' | 'portrait';

const Shape = createContext<WallShape>('landscape');

/** The shape of the stage this is drawn on. Landscape outside one. */
export function useWallShape(): WallShape {
  return useContext(Shape);
}

/** Taller than wide is portrait. Exactly square — nothing real — stays
 *  landscape, which every layout was designed against first. */
export function shapeOf(width: number, height: number): WallShape {
  return height > width ? 'portrait' : 'landscape';
}

/**
 * A 1920×1080 wall, scaled to whatever it is shown on.
 *
 * **Every television shows the same picture.** The wall used to be laid out in
 * the TV's own pixels, so a 720p set lost the bottom four rows of a board, a
 * 1080p one overflowed by five pixels, and a 4K one drew everything at a
 * quarter of the size it was designed for (QA-3). Now it is always laid out at
 * 1920×1080 and the whole thing is scaled to fit — so what fits on one screen
 * fits on all of them, and the preview in the editor is the same picture again.
 *
 * **Letterboxed rather than stretched.** A screen that is not 16:9 — a 16:10
 * laptop — gets bars rather than a distorted board. A screen taller than it is
 * wide gets a 1080×1920 stage instead (6.11); see `WallShape`.
 *
 * **Scaled by transform, not by smaller type.** Rendering at full size and
 * scaling the result keeps every proportion exact: what wraps here wraps on
 * the TV. `position: fixed` inside it — a celebration taking over the screen —
 * is placed against the stage, because a transform makes it the containing
 * block, so a takeover scales with everything else.
 */
export default function WallStage({
  children,
  fill,
  stageRef,
  className = '',
  shape: forced,
}: {
  children: ReactNode;
  /** `viewport` on a television; `parent` inside a preview's own box. */
  fill: 'viewport' | 'parent';
  /** Fixed, for a preview that draws one shape whatever box it is in.
   *  Otherwise worked out from the screen. */
  shape?: WallShape;
  /** The 1920×1080 element, for applying an appearance to. */
  stageRef?: Ref<HTMLDivElement>;
  className?: string;
}) {
  const outer = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(fill === 'parent' ? 0.25 : 1);
  const [measured, setMeasured] = useState<WallShape>('landscape');
  const shape = forced ?? measured;

  // **Measured rather than assumed**, and in a layout effect: scaling after
  // paint is a visible jump on every load.
  useLayoutEffect(() => {
    const element = outer.current;
    if (!element) return;
    const measure = () => {
      const width = element.clientWidth;
      const height = element.clientHeight;
      // A box with no size yet (jsdom, or a tab not laid out) keeps the last
      // scale and shape rather than collapsing the wall to nothing.
      if (!width || !height) return;
      const turned = (forced ?? shapeOf(width, height)) === 'portrait';
      setMeasured(shapeOf(width, height));
      setScale(
        Math.min(
          width / (turned ? WALL_HEIGHT : WALL_WIDTH),
          height / (turned ? WALL_WIDTH : WALL_HEIGHT),
        ),
      );
    };
    measure();
    // Not every television's browser has ResizeObserver. A screen changes
    // size only when its window does, so the resize event covers them.
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', measure);
      return () => window.removeEventListener('resize', measure);
    }
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [forced]);

  return (
    <div
      ref={outer}
      className={`${
        fill === 'viewport' ? 'fixed' : 'absolute'
      } inset-0 overflow-hidden bg-black`}
    >
      <div
        ref={stageRef}
        data-wall-stage=""
        data-wall-shape={shape}
        style={{
          width: shape === 'portrait' ? WALL_HEIGHT : WALL_WIDTH,
          height: shape === 'portrait' ? WALL_WIDTH : WALL_HEIGHT,
          transform: `translate(-50%, -50%) scale(${scale})`,
        }}
        // `wall`: the scope where the organization's font, type scale and
        // panel style apply. `isolate` gives the background layer a stacking
        // context to sit behind the content of — see `WallBackground`.
        className={`wall absolute left-1/2 top-1/2 isolate flex flex-col items-center justify-center overflow-hidden bg-bg px-10 py-8 ${className}`}
      >
        <Shape.Provider value={shape}>{children}</Shape.Provider>
      </div>
    </div>
  );
}
