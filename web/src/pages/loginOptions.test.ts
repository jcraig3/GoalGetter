import { describe, expect, test } from 'vitest';

import { loginOptions, type Providers } from './loginOptions';

const providers = (sso_enabled: boolean, sso_required = false): Providers => ({
  local: true,
  sso_enabled,
  sso_required,
  sso_button_label: 'Sign in with Microsoft',
});

describe('the ordinary cases', () => {
  test('passwords only: the form, and nothing else', () => {
    expect(loginOptions(providers(false))).toEqual({
      form: true,
      sso: false,
      ssoFirst: false,
      divider: false,
      hint: false,
    });
  });

  test('both offered: the form, then the button, with a rule between them', () => {
    expect(loginOptions(providers(true))).toEqual({
      form: true,
      sso: true,
      ssoFirst: false,
      divider: true,
      hint: false,
    });
  });
});

describe('SSO required (11.1)', () => {
  test('the button leads, and the form is still there for everybody else', () => {
    // It used to hide the form behind a link kept for admins, which left a
    // contractor with no work account nowhere to sign in.
    expect(loginOptions(providers(true, true))).toEqual({
      form: true,
      sso: true,
      ssoFirst: true,
      divider: true,
      hint: true,
    });
  });

  test('an older server that says local: false still reads as required', () => {
    const old = { local: false, sso_enabled: true, sso_button_label: 'Sign in' };
    expect(loginOptions(old)).toMatchObject({ form: true, ssoFirst: true, hint: true });
  });
});

describe('the edges', () => {
  test('before the answer arrives, offer the form', () => {
    // It is the one that works without knowing anything, and a page that
    // flickers a sign-in button in and out reads as broken.
    expect(loginOptions(null)).toMatchObject({ form: true, sso: false });
  });

  test('required with SSO switched off is still not a locked door', () => {
    expect(loginOptions({ ...providers(false), sso_required: true })).toMatchObject({
      form: true,
      sso: false,
      hint: false,
    });
  });
});
