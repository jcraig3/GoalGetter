import { useState } from 'react';

import { avatarColour, initialsOf } from './avatarColour';
import { ringStyle } from './ring';

/**
 * A face, or initials.
 *
 * **Initials are the default, not the failure.** Most directories have
 * photographs of some people and not others, and this drew initials long before
 * photographs existed — so no photo is the ordinary case rather than something
 * gone wrong. A photo that fails to load falls back to them too: a broken image
 * icon on a leaderboard is worse than the letters it replaced.
 *
 * `digest` is a content hash, so the URL it builds can be cached forever — a new
 * photograph is a new hash and a new URL. `src` overrides it for a wall display,
 * which fetches through its own token rather than a session.
 */
export default function Avatar({
  name,
  digest,
  src,
  size = 'sm',
  ring,
}: {
  name: string;
  /** Content hash of the photo. Builds the signed-in URL. */
  digest?: string | null;
  /** A ready-made URL, for callers that authenticate differently. */
  src?: string | null;
  size?: 'sm' | 'lg';
  /** A cosmetic somebody bought, drawn outside the face. See `ring.ts`. */
  ring?: string | null;
}) {
  const [broken, setBroken] = useState(false);


  const box = size === 'lg' ? 'size-14 text-lg' : 'size-8 text-xs';
  const url = src ?? (digest ? `/api/images/${digest}` : null);

  if (url && !broken) {
    return (
      // Decorative, like the initials: the name is always rendered beside it,
      // so alt text would have a screen reader say it twice.
      <img
        src={url}
        alt=""
        aria-hidden="true"
        loading="lazy"
        decoding="async"
        onError={() => setBroken(true)}
        style={ringStyle(ring)}
        className={`shrink-0 rounded-full object-cover ${box}`}
      />
    );
  }

  return (
    <span
      aria-hidden="true"
      // **A colour per person, generated rather than chosen.** Four hundred
      // people in the same indigo circle are four hundred identical circles,
      // and the letters were doing all the work at the size a board draws
      // them. See `avatarColour`.
      style={{ backgroundColor: avatarColour(name), ...ringStyle(ring) }}
      className={`grid shrink-0 place-items-center rounded-full font-medium text-white ${box}`}
    >
      {initialsOf(name)}
    </span>
  );
}
