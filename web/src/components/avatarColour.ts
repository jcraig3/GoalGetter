/**
 * A colour per person, so a roster of initials is scannable.
 *
 * **Generated, not chosen from a library of drawings.** An illustrated avatar
 * set means shipping art — and a cartoon face is a worse answer than initials
 * for the actual job, which is recognising a colleague on a board from across a
 * room. What initials lacked was distinctness: four hundred people in the same
 * indigo circle are four hundred identical circles, and the letters are doing
 * all the work at the size a wall shows them.
 *
 * So: the letters stay, and the circle carries a colour that is always the same
 * for the same person. No assets, no network, no invented faces.
 *
 * **Deterministic from the name.** Somebody's colour is the same on a
 * leaderboard, on their profile and in a celebration — a colour that changed
 * between screens would be worse than no colour, because the eye would learn it
 * and then be wrong. Seeded on the name rather than the id because the id is
 * not in hand at every call site, and a rename changing somebody's colour is a
 * once-a-career non-event.
 */

/**
 * A stable 32-bit hash of a string.
 *
 * FNV-1a: four lines, no dependency, and well-spread for short inputs — which
 * is all a hue needs. Not a checksum and not a cryptographic hash; nothing here
 * depends on it being hard to reverse.
 */
function hash(text: string): number {
  let value = 0x811c9dc5;
  for (let i = 0; i < text.length; i += 1) {
    value ^= text.charCodeAt(i);
    value = Math.imul(value, 0x01000193);
  }
  return value >>> 0;
}

/**
 * How many hues to choose between.
 *
 * **Twelve, not 360.** Adjacent hues are indistinguishable at the size an
 * avatar is drawn, so a continuous range buys nothing and makes two colleagues
 * look identical as often as a coarse one does. Twelve are told apart at a
 * glance and are enough that a team of eight rarely collides.
 */
const HUES = 12;

/**
 * Lightness and saturation, fixed.
 *
 * **The same in light mode and dark.** An avatar is a self-contained chip with
 * its own text on it, so it does not need to match the page — it needs to be
 * legible against itself, in both. 42% lightness keeps white text above 4.5:1
 * for every hue, which a lighter shade does not for yellows and greens.
 */
const SATURATION = 58;
const LIGHTNESS = 42;

/** The background for somebody's initials. Always the same for the same name. */
export function avatarColour(name: string): string {
  const hue = (hash(name.trim().toLowerCase()) % HUES) * (360 / HUES);
  return `hsl(${hue} ${SATURATION}% ${LIGHTNESS}%)`;
}

/**
 * Their initials, at most two.
 *
 * Lived in three components separately, each with the same four lines — which
 * is three places to fix when somebody turns up with one name.
 */
export function initialsOf(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('');
}
