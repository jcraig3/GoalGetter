import { describe, expect, it } from 'vitest';

import { flipSignIn, signsInWith } from './ssoSettings';

/**
 * The bug these exist for, written down so it cannot come back.
 *
 * Ticking "Enable single sign-on" showed no tick. The box was checked against
 * `enabled && provider === thisProvider`, and the provider was only recorded when
 * the form was saved — so the first click set `enabled` and changed nothing
 * visible, on the one toggle of three that was not bound straight to its own
 * field.
 */
describe('flipSignIn', () => {
  it('names the provider as it turns on, so the box can show as checked', () => {
    // **The actual regression.** Without the provider moving in the same step,
    // `signsInWith` stays false and the tick never appears.
    const after = flipSignIn({ enabled: false, provider: null }, 'microsoft', true);

    expect(after).toEqual({ enabled: true, provider: 'microsoft' });
    expect(signsInWith(after, 'microsoft')).toBe(true);
  });

  it('repoints sign-in away from whichever connection had it', () => {
    // One sign-in provider per deployment: turning it on in Microsoft's panel
    // means Microsoft, and Google stops being it.
    const after = flipSignIn({ enabled: true, provider: 'google' }, 'microsoft', true);

    expect(signsInWith(after, 'microsoft')).toBe(true);
    expect(signsInWith(after, 'google')).toBe(false);
  });

  it('remembers which connection it was, when switched off', () => {
    // Clearing the provider would look tidier and would lose the only record of
    // what was configured — so off-then-on would come back pointed at nothing,
    // taking the issuer shown underneath with it.
    const off = flipSignIn({ enabled: true, provider: 'microsoft' }, 'microsoft', false);

    expect(off).toEqual({ enabled: false, provider: 'microsoft' });
  });

  it('can be switched off and on again and land where it started', () => {
    const start = { enabled: true, provider: 'microsoft' };
    const back = flipSignIn(flipSignIn(start, 'microsoft', false), 'microsoft', true);

    expect(back).toEqual(start);
  });
});

describe('signsInWith', () => {
  it('needs sign-on to be on at all', () => {
    expect(signsInWith({ enabled: false, provider: 'microsoft' }, 'microsoft')).toBe(
      false,
    );
  });

  it('needs it to be this connection', () => {
    // Otherwise Microsoft's panel would claim to be signing people in while
    // Google actually was.
    expect(signsInWith({ enabled: true, provider: 'google' }, 'microsoft')).toBe(false);
  });

  it('is false when nothing signs anybody in', () => {
    expect(signsInWith({ enabled: true, provider: null }, 'microsoft')).toBe(false);
  });
});
