// @vitest-environment jsdom
/**
 * Painting an appearance, and remembering a person's own choice.
 *
 * The merge itself lives on the server and is tested there. What can only be
 * tested in a browser is what these do to the document — and the one that
 * matters most is `system`, which has to leave the media query in charge rather
 * than resolving to a value.
 */
import { beforeEach, describe, expect, test } from 'vitest';

import {
  FONT_STACKS,
  SYSTEM_STACK,
  applyAppearance,
  applyTheme,
  displayName,
  storedTheme,
  type Appearance,
} from './appearance';

const RESOLVED: Appearance = {
  logo: null,
  slogan: null,
  primary: '#112233',
  secondary: '#445566',
  accent: '#778899',
  font: 'montserrat',
  font_scale: 1.4,
  panel_opacity: 0.5,
  panel_blur: 8,
  panel_radius: 20,
  ranked_layout: 'list',
  row_count: 10,
  show_values: true,
  goal_layout: 'gauge',
  name_display: 'full',
  end_time_format: 'default',
  milestones: 'all',
  background: null,
};

beforeEach(() => {
  document.documentElement.removeAttribute('data-theme');
  document.documentElement.removeAttribute('style');
  localStorage.clear();
});

describe('applyAppearance', () => {
  test('paints the brand onto custom properties', () => {
    applyAppearance(RESOLVED);
    const style = document.documentElement.style;

    expect(style.getPropertyValue('--gg-brand')).toBe('#112233');
    expect(style.getPropertyValue('--gg-panel-radius')).toBe('20px');
    expect(style.getPropertyValue('--gg-font-scale')).toBe('1.4');
  });

  test('can paint onto any element, which is what the preview needs', () => {
    // A preview pane is the real appearance applied to a box, not a second
    // renderer that drifts from the first.
    const box = document.createElement('div');

    applyAppearance(RESOLVED, box);

    expect(box.style.getPropertyValue('--gg-brand')).toBe('#112233');
    expect(document.documentElement.style.getPropertyValue('--gg-brand')).toBe(
      '',
    );
  });

  test('falls back to the system stack for a font it does not know', () => {
    // Bundled fonts are files. A name with no file behind it must not produce
    // an empty stack, which is how a wall ends up in Times New Roman.
    applyAppearance({ ...RESOLVED, font: 'nonesuch' });

    expect(
      document.documentElement.style.getPropertyValue('--gg-wall-font'),
    ).toBe(SYSTEM_STACK);
  });

  test('uses the named stack for one it does', () => {
    applyAppearance(RESOLVED);

    expect(
      document.documentElement.style.getPropertyValue('--gg-wall-font'),
    ).toBe(FONT_STACKS.montserrat);
  });

  test('does nothing at all when there is nothing to apply', () => {
    applyAppearance(null);

    expect(document.documentElement.getAttribute('style')).toBeNull();
  });
});

describe('applyTheme', () => {
  test('sets the attribute for an explicit choice', () => {
    applyTheme('light');

    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
  });

  test('system removes the attribute rather than resolving it', () => {
    // **The media query has to stay in charge.** Resolving "system" to a value
    // would freeze it, so somebody whose laptop goes dark at sunset would keep
    // a light app until they reloaded.
    applyTheme('dark');
    applyTheme('system');

    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
  });

  test('remembers the choice', () => {
    applyTheme('dark');

    expect(storedTheme()).toBe('dark');
  });

  test('follows the system when nothing was ever chosen', () => {
    expect(storedTheme()).toBe('system');
  });

  test('ignores a stored value that is not a theme', () => {
    localStorage.setItem('gg.theme', 'chartreuse');

    expect(storedTheme()).toBe('system');
  });
});

describe('displayName', () => {
  test.each([
    ['full', 'Peter Parker'],
    ['first', 'Peter'],
    ['first_initial', 'Peter P.'],
    ['last', 'Parker'],
    ['nickname', 'Spidey'],
  ] as const)('writes %s as %s', (style, expected) => {
    expect(displayName('Peter Parker', 'Spidey', style)).toBe(expected);
  });

  test('matches the server for a one-word name', () => {
    // The same rule exists in `api/app/appearance.py`. Both must agree, or a
    // celebration banner and the board behind it disagree about a person.
    for (const style of ['full', 'first', 'first_initial', 'last'] as const) {
      expect(displayName('Groot', null, style)).toBe('Groot');
    }
  });

  test('falls back when a nickname was asked for and there is none', () => {
    expect(displayName('Peter Parker', null, 'nickname')).toBe('Peter Parker');
  });
});
