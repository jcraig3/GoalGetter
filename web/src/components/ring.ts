import type { CSSProperties } from 'react';

/**
 * The ring somebody bought, as a style for their face.
 *
 * **An outline outside the face, never its border.** The podium already
 * borders faces in gold, silver and bronze by *rank*, and a bought gold ring
 * drawn the same way would make somebody in fourth look like they came first.
 * An outline sits outside any border, with a gap, so the medal keeps its
 * meaning and the ring reads as the separate thing it is.
 *
 * `width` and `gap` are CSS lengths so the wall can size them in `em` — the
 * wall's type scale is em-based, and a ring measured in pixels would stay
 * hairline-thin on a face drawn for a television across the room.
 *
 * The colour is checked again here though the server already refuses anything
 * else: this string ends up in a `style` attribute on a public screen, and
 * checking twice is cheaper than being wrong once.
 */
export function ringStyle(
  ring: string | null | undefined,
  width = '2px',
  gap = '2px',
): CSSProperties | undefined {
  if (!ring || !/^#[0-9a-fA-F]{6}$/.test(ring)) return undefined;
  return { outline: `${width} solid ${ring}`, outlineOffset: gap };
}

/** Whether there is a ring worth drawing at all. */
export function hasRing(ring: string | null | undefined): ring is string {
  return ringStyle(ring) !== undefined;
}
