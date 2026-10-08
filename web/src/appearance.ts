/**
 * How everything looks, on the client side.
 *
 * The server owns the merge — see `api/app/appearance.py`, which resolves
 * organization → channel → screen into one complete object. This file does the
 * two things that can only happen in a browser: painting the resolved values
 * onto CSS custom properties, and remembering the one preference that belongs
 * to a person rather than to the company.
 *
 * **The app theme and the wall theme are separate on purpose.** A wall is a
 * dark room with a projector; a laptop is somebody's own eyes at 4pm. The
 * organization chooses its brand, and the person chooses whether their own
 * screen is light or dark — those are different questions and conflating them
 * means one of the two answers is always wrong.
 */

export interface Background {
  kind:
    | 'inherit'
    | 'none'
    | 'solid'
    | 'gradient'
    | 'image'
    // An uploaded MP4, checked at upload so it cannot save and then show a
    // black screen. The ad-free alternative to `youtube` — see `app/video.py`.
    | 'video'
    | 'youtube'
    // A drawn scene (6.9), by name, in this background's three colours.
    | 'scene';
  color: string | null;
  color_to: string | null;
  /** An optional middle stop for a gradient. */
  color_mid?: string | null;
  /** Seconds into a YouTube or uploaded video to start (and loop back) at. */
  start?: number | null;
  /** Degrees, for a linear gradient. */
  angle?: number | null;
  style?: 'linear' | 'radial' | null;
  /** A slow drift, for a gradient — motion without a video file. */
  motion?: boolean | null;
  /** Which drawn scene, for `scene`: `waves`, `skyline`… See `wall/Scenes.tsx`. */
  scene?: string | null;
  asset: string | null;
  dim: number | null;
  blur: number | null;
}

/** The resolved shape: every field filled, because the server merged it. */
export interface Appearance {
  logo: string | null;
  slogan: string | null;
  primary: string;
  secondary: string;
  accent: string;
  font: string;
  font_scale: number;
  panel_opacity: number;
  panel_blur: number;
  panel_radius: number;
  ranked_layout: string;
  goal_layout: string;
  /** How many rows a ranked screen draws. A drawing decision, not a filter. */
  row_count: number;
  /** Whether the numbers are drawn beside the names. */
  show_values: boolean;
  name_display: 'full' | 'first' | 'first_initial' | 'last' | 'nickname';
  end_time_format: 'default' | 'simple' | 'full' | 'off';
  /** Which wins stop a wall's rotation and take over the screen. */
  milestones: 'none' | 'important' | 'all';
  background: Background | null;
}

/** What the person chose for their own screen, not the company's. */
export type ThemeChoice = 'light' | 'dark' | 'system';

const THEME_KEY = 'gg.theme';

/**
 * The font stacks behind each bundled name.
 *
 * **Every one ends in a real fallback**, because the point of bundling rather
 * than fetching from a font service is that a wall in a warehouse with no
 * internet still renders. A stack ending in nothing would undo that.
 */
/** The stack every unknown name falls back to. */
export const SYSTEM_STACK =
  'system-ui, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif';

export const FONT_STACKS: Record<string, string> = {
  system: SYSTEM_STACK,
  inter: 'Inter, system-ui, sans-serif',
  montserrat: 'Montserrat, system-ui, sans-serif',
  raleway: 'Raleway, system-ui, sans-serif',
  ubuntu: 'Ubuntu, system-ui, sans-serif',
  oswald: 'Oswald, Impact, system-ui, sans-serif',
  bebas: '"Bebas Neue", Impact, system-ui, sans-serif',
  indie: '"Indie Flower", Comic Sans MS, cursive',
};

export const FONT_LABELS: Record<string, string> = {
  system: 'System default',
  inter: 'Inter',
  montserrat: 'Montserrat',
  raleway: 'Raleway',
  ubuntu: 'Ubuntu',
  oswald: 'Oswald',
  bebas: 'Bebas Neue',
  indie: 'Indie Flower',
};

export const NAME_DISPLAY_LABELS: Record<string, string> = {
  full: 'Peter Parker',
  first: 'Peter',
  first_initial: 'Peter P.',
  last: 'Parker',
  nickname: 'Their nickname',
};

/**
 * Paint an appearance onto an element as CSS custom properties.
 *
 * **Onto an element rather than always the document**, so the same function
 * serves the live preview: a preview pane is the real appearance applied to a
 * box, not a second renderer that drifts from the first one.
 *
 * Only the brand colours are overridden. The greys, borders and text colours
 * stay with the light/dark theme, because an organization choosing a purple
 * brand has not asked for purple body text — and letting them would make an
 * unreadable wall one colour picker away.
 */
export function applyAppearance(
  appearance: Appearance | null,
  element: HTMLElement = document.documentElement,
): void {
  if (!appearance) return;

  element.style.setProperty('--gg-brand', appearance.primary);
  element.style.setProperty('--gg-brand-hover', appearance.secondary);
  element.style.setProperty('--gg-accent', appearance.accent);

  element.style.setProperty(
    '--gg-wall-font',
    FONT_STACKS[appearance.font] ?? SYSTEM_STACK,
  );
  element.style.setProperty('--gg-font-scale', String(appearance.font_scale));
  element.style.setProperty(
    '--gg-panel-opacity',
    String(appearance.panel_opacity),
  );
  element.style.setProperty('--gg-panel-blur', `${appearance.panel_blur}px`);
  element.style.setProperty(
    '--gg-panel-radius',
    `${appearance.panel_radius}px`,
  );
}

/** What the person last chose, defaulting to following their system. */
export function storedTheme(): ThemeChoice {
  try {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === 'light' || saved === 'dark' || saved === 'system')
      return saved;
  } catch {
    // Private windows and blocked site data both throw. Following the system
    // is a fine answer when we cannot remember a better one.
  }
  return 'system';
}

/**
 * Apply a theme choice, and remember it.
 *
 * `system` removes the attribute rather than resolving it to a value, so the
 * CSS media query stays in charge — which means somebody switching their laptop
 * to dark at sunset gets a dark app without reloading.
 */
export function applyTheme(choice: ThemeChoice): void {
  const root = document.documentElement;
  if (choice === 'system') {
    root.removeAttribute('data-theme');
  } else {
    root.setAttribute('data-theme', choice);
  }

  try {
    localStorage.setItem(THEME_KEY, choice);
  } catch {
    // Not remembering it is a smaller problem than failing to apply it.
  }
}

/** A person's name, written the way the organization asked for. */
export function displayName(
  fullName: string,
  nickname: string | null,
  style: Appearance['name_display'],
): string {
  const parts = fullName.split(/\s+/).filter(Boolean);
  const first = parts[0] ?? fullName;
  const last = parts.length > 1 ? parts[parts.length - 1] : '';

  if (style === 'nickname' && nickname) return nickname;
  if (style === 'first') return first;
  if (style === 'first_initial') return last ? `${first} ${last[0]}.` : first;
  if (style === 'last') return last || first;
  return fullName;
}
