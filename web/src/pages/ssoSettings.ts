/**
 * Which connection signs people in, and what flipping that switch means.
 *
 * **Extracted because it was wrong while it was inline.** A deployment has exactly
 * one sign-in provider, so "is single sign-on on?" is really two questions — is it
 * enabled at all, and is it enabled *for the connection whose panel I am looking
 * at* — and the panel answered the second by reading a field that only changes when
 * the form is saved. So ticking the box set `enabled` and left the tick invisible:
 * `enabled && isSignIn` stayed false, because the provider had not been recorded
 * yet. The two toggles either side of it bound straight to their own field, which
 * is exactly why they worked and this one did not.
 *
 * The fix is that turning it on *names* the provider at the same moment, which is
 * what the save was already doing on the way out. Here rather than in the
 * component so it can be tested, since eyeballing it is what missed it.
 */

/** The parts of the sign-in settings this decides on. */
export interface SignInState {
  enabled: boolean;
  /** Which connection signs people in, or null when none does. */
  provider: string | null;
}

/**
 * Whether single sign-on is on *and* pointed at this connection.
 *
 * Both halves matter. A deployment signing in through Google should not show
 * Microsoft's panel as the one doing it.
 */
export function signsInWith(settings: SignInState, provider: string): boolean {
  return settings.enabled && settings.provider === provider;
}

/**
 * What the settings become when this connection's switch is flipped.
 *
 * **Turning it on repoints sign-in at this provider**, which is the whole reason
 * the provider is not a second choice an admin has to make: they are standing in
 * one connection's panel, so which one they mean is not ambiguous.
 *
 * **Turning it off leaves the provider alone.** Clearing it would look tidier and
 * would throw away the only record of which connection was configured for sign-in
 * — so switching off and on again would come back pointed at nothing, and the
 * issuer shown underneath would vanish with it.
 */
export function flipSignIn(
  settings: SignInState,
  provider: string,
  enabled: boolean,
): SignInState {
  return {
    enabled,
    provider: enabled ? provider : settings.provider,
  };
}
