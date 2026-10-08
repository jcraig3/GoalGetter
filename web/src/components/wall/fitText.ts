import { useLayoutEffect, useRef, useState } from 'react';

/**
 * The largest of `sizes` at which an element's text fits its box.
 *
 * **Smaller before cut off.** A long headline on a message slide used to end
 * in an ellipsis, so the room read half a sentence (QA-16). Now the text steps
 * down a size at a time while it overflows, and only the smallest size is
 * allowed to be clipped — that is the floor below which a wall is not readable
 * from across a room, so it is where shrinking stops.
 *
 * "Overflows" is the element's own business: give it a fixed or maximum
 * height, or a line clamp, and this reads `scrollHeight` against it. Measured
 * before paint, so the larger sizes are never seen.
 *
 * @param sizes Tailwind text classes, largest first.
 * @param text  What is being fitted; a change starts from the largest again.
 */
export function useFittedSize<T extends HTMLElement>(sizes: string[], text: string) {
  const ref = useRef<T>(null);
  const [fit, setFit] = useState({ text, index: 0 });
  const index = fit.text === text ? fit.index : 0;

  useLayoutEffect(() => {
    const element = ref.current;
    if (!element || index >= sizes.length - 1) return;
    if (
      element.scrollHeight > element.clientHeight + 1 ||
      element.scrollWidth > element.clientWidth + 1
    ) {
      setFit({ text, index: index + 1 });
    }
  });

  return { ref, size: sizes[index] ?? sizes[0] ?? '' };
}
