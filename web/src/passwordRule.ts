/**
 * The one password rule (11.4), for every form that sets one: setup,
 * invitations, changes, resets, temporary passwords and choosing your own.
 * Mirrors `security.NewPassword` on the server, which is what decides.
 *
 * Length over character-class rules — current guidance is to require length,
 * not to demand a symbol and a digit, which mostly produces "Password1!".
 */
export const MIN_PASSWORD_LENGTH = 12;

/** bcrypt reads 72 bytes and no more — fewer characters with accents or emoji. */
const MAX_PASSWORD_BYTES = 72;

/** What is wrong with a password being typed, or null. Silent while empty. */
export function passwordProblem(password: string): string | null {
  if (!password) return null;
  if (password.length < MIN_PASSWORD_LENGTH) {
    const short = MIN_PASSWORD_LENGTH - password.length;
    return `${short} more character${short === 1 ? '' : 's'} needed`;
  }
  if (new TextEncoder().encode(password).length > MAX_PASSWORD_BYTES) {
    return `Too long — ${MAX_PASSWORD_BYTES} characters at most`;
  }
  return null;
}

/** The hint under an empty field. */
export const PASSWORD_HINT = `At least ${MIN_PASSWORD_LENGTH} characters.`;

const WORDS = [
  'amber', 'anchor', 'apple', 'arrow', 'autumn', 'badge', 'basil', 'beacon', 'birch', 'bison',
  'breeze', 'bridge', 'cedar', 'cherry', 'cobalt', 'comet', 'copper', 'coral', 'crane', 'delta',
  'ember', 'falcon', 'fern', 'fjord', 'garnet', 'glacier', 'harbor', 'hazel', 'heron', 'indigo',
  'island', 'jasper', 'juniper', 'kestrel', 'lagoon', 'lantern', 'lemon', 'maple', 'meadow', 'mint',
  'nectar', 'oak', 'ocean', 'olive', 'orbit', 'otter', 'pebble', 'pepper', 'pine', 'planet',
  'quartz', 'raven', 'river', 'rocket', 'saffron', 'sierra', 'spruce', 'summit', 'thistle', 'tiger',
  'timber', 'tulip', 'valley', 'velvet', 'willow', 'winter', 'zephyr',
];

/**
 * Four random words and a number: easy to read out to somebody standing next
 * to you, and well past the rule. From the browser's cryptographic random
 * source, never `Math.random`.
 */
export function suggestPassword(): string {
  const words: string[] = [];
  // Four different words: "pepper-pepper" reads like a typo when said aloud.
  while (words.length < 4) {
    const word = WORDS[crypto.getRandomValues(new Uint32Array(1))[0]! % WORDS.length]!;
    if (!words.includes(word)) words.push(word);
  }
  const number = 10 + (crypto.getRandomValues(new Uint32Array(1))[0]! % 90);
  return `${words.join('-')}-${number}`;
}
