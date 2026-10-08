/** What `/api/auth/providers` says the login page should offer. */
export interface Providers {
  /** Always true since 11.1; kept so an older server still reads right. */
  local: boolean;
  sso_enabled: boolean;
  sso_button_label: string;
  /** SSO is required of people in the directory. */
  sso_required?: boolean;
  /** Mail can be sent, so "Forgot password?" emails a link (Phase 14). */
  self_reset?: boolean;
}

/** What the login page draws. */
export interface LoginOptions {
  /** The email and password fields, and the button that submits them. */
  form: boolean;
  sso: boolean;
  /** The SSO button above the form rather than below it. */
  ssoFirst: boolean;
  /** The "or" rule between the two ways in. */
  divider: boolean;
  /** The line under the form saying who it is for. */
  hint: boolean;
}

/**
 * Which halves of the login page are on screen, and in what order.
 *
 * **The password form is always there** (11.1). "Require single sign-on" used
 * to hide it behind a quiet link kept for admins — which left people the
 * company works with but does not employ, with no work account, nowhere to
 * sign in. It now binds only people in the directory, so the form is for
 * everybody else: admins, contractors, an agency's closers.
 *
 * When SSO is required the button leads — it is how most people get in — and a
 * line under the form says who the form is for. A policy, never a hint about
 * any one account: the server refuses a directory person's password with the
 * same words as a wrong one.
 *
 * Nothing here is a secret. The server decides who may actually use a password,
 * and anybody can POST to the endpoint whatever this page draws.
 */
export function loginOptions(providers: Providers | null): LoginOptions {
  // Before the answer arrives, offer the password form and nothing else. It is
  // the one that works without knowing anything, and a page that flickers a
  // sign-in button in and out reads as broken.
  if (providers === null || !providers.sso_enabled) {
    return { form: true, sso: false, ssoFirst: false, divider: false, hint: false };
  }
  const required = providers.sso_required ?? !providers.local;
  return { form: true, sso: true, ssoFirst: required, divider: true, hint: required };
}
