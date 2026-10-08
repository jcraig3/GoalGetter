import type { Appearance } from '../../appearance';

/**
 * What a wall screen is made of.
 *
 * Extracted from the display page so that an editor can render the *real*
 * screen rather than something built to look like it. Two renderers drift: one
 * gets a new medal colour, the other does not, and the preview stops being a
 * preview the week after anybody relies on it.
 */

export interface Entry {
  rank: number;
  entity_id: number;
  entity_name: string;
  photo_digest?: string | null;
  /** A ring they bought, as a colour. See `components/ring.ts`. */
  ring?: string | null;
  /** How far along a race layout they are, 0–1. Worked out by the server. */
  progress?: number;
  /** Across the finish line — only possible when there is one. */
  finished?: boolean;
  /** The piece they move on a race board; null or absent is their own face. */
  token?: string | null;
  /** A team's own colour and short name, on a team row (6.7); null on a person's. */
  colour?: string | null;
  short_name?: string | null;
  /** This row is a team (6.7). The only field that says so. */
  is_team?: boolean;
  team_name: string | null;
  value: string;
  movement: number | null;
}

/** Who a spotlight is about. */
export interface Person {
  id: number;
  name: string;
  photo_digest?: string | null;
  ring?: string | null;
  /** A title they bought, shown under their name. Written by an admin. */
  title?: string | null;
  job_title: string | null;
  team_name: string | null;
}

/**
 * One number on a spotlight, with enough beside it to draw without knowing
 * what it means — the wall formats `value` by `unit`, the same way a board does.
 */
export interface Stat {
  label: string;
  value: string;
  unit: string | null;
  decimal_places: number;
  unit_label?: string | null;
  rank: number;
  movement: number | null;
  /** How many people are on the board, for "3rd of 14".*/
  of: number;
}

/**
 * One column of a comparison.
 *
 * The fields a leaderboard slide carries, so a panel draws with the component
 * the wall already has for a board rather than a second renderer that drifts.
 */
export interface Panel {
  title: string;
  subtitle: string | null;
  entries: Entry[];
  total_entrants: number;
  entity_type: string | null;
  unit: string | null;
  decimal_places: number;
  unit_label?: string | null;
  direction: string | null;
}

export interface Achievement {
  id: number;
  about_name: string | null;
  title: string;
  body: string | null;
  /** When it happened, for "2 min ago" (7.9). */
  created_at?: string;
  /** The number it was for, "$500" (7.9). */
  figure?: string | null;
}

/**
 * One screen of any kind.
 *
 * A single shape with `kind` rather than a union: the wall loops over slides and
 * switches once, instead of learning six response shapes. The unused fields cost
 * a few bytes of JSON and save a decoder.
 */
export interface Slide {
  id: number;
  kind: string;
  dwell_seconds: number;
  title: string;
  subtitle: string | null;

  entries: Entry[];
  total_entrants: number;
  entity_type: string | null;
  unit: string | null;
  decimal_places: number;
  unit_label?: string | null;
  direction: string | null;
  /** Where a race layout draws its finish line, in the metric's unit. */
  finish_line?: string | null;
  /** "Wed 23 Sep" when the newest number is over a day old (10.6). */
  as_of?: string | null;
  /** Last period's top three, on a calendar board with nothing yet (10.1). */
  previous?: { label: string; entries: Entry[] } | null;

  current_value: string | null;
  target_value: string | null;
  /** Levels past the target. Absent from a server that predates them. */
  stretch?: { label: string; value: string; reached: boolean }[];
  percent: number | null;
  status: string | null;

  prize: string | null;
  ends_at: string | null;
  state: string | null;
  final: boolean;

  achievements: Achievement[];

  /** Spotlight slides. */
  person?: Person | null;
  stats: Stat[];
  /**
   * Consecutive days with a number, or null when the screen names no metric
   * to count one from — which is not the same as a streak of zero.
   */
  streak_days?: number | null;

  /** Comparison slides: two to four boards, in the order they are drawn. */
  panels: Panel[];

  url: string | null;
  media_kind: string | null;
  /** Picture and video screens (Phase 26): a stored file's digest, where a
   *  video starts, and how a picture fills the screen. */
  media_digest?: string | null;
  media_start_seconds?: number | null;
  fit?: 'cover' | 'contain' | null;
  /** In an editor's preview only: the look with nothing of its own, and
   *  where the background comes from ("the leaderboard “Sales floor”"). */
  inherited?: Record<string, unknown>;
  background_from?: string;
  body: string | null;

  /**
   * How to draw it, already merged by the server from organization, item,
   * channel and screen.
   *
   * **Per slide, not per channel.** Two screens in one rotation can
   * legitimately differ — the same contest themed red, the goal after it
   * inheriting the house style — so a channel-level object would have to be
   * overridden per slide anyway, which is the merge this avoids doing twice.
   */
  appearance?: Partial<Appearance>;
}

export interface Channel {
  channel_name: string;
  organization_name: string;
  slides: Slide[];
  refresh_seconds: number;
  /**
   * The server's clock, in ms since the epoch. Every screen rotates by it, which
   * is what keeps the screens on a channel in step — see `wallClock.ts`.
   */
  server_time?: number;
  /**
   * When somebody last asked this screen to reload itself.
   *
   * The screen remembers the value it first saw and reloads when it changes.
   * Null means nobody ever has, which is the ordinary case — so "first seen"
   * is what matters rather than "not null".
   */
  reload_at?: string | null;
  /**
   * Night mode, or no slide scheduled right now (6.10): show a clock or a
   * dark screen instead of the rotation. Null is the ordinary case.
   */
  quiet?: { mode: 'clock' | 'dark'; until: string | null } | null;
  /** The organization's zone, so a clock tells the office's time. */
  time_zone?: string;
}

/**
 * How a face is fetched, which is the one thing the wall and a preview differ
 * on.
 *
 * A screen authenticates with the token in its URL and an editor authenticates
 * with a session, so they build different image URLs. Passing the builder in
 * means the screen components never learn what a display token is — and the
 * preview needs no token to exist.
 */
export type ImageUrl = (digest: string) => string;

/** The signed-in route, for previews and anything else inside the app. */
export const sessionImageUrl: ImageUrl = (digest) => `/api/images/${digest}`;

/** The display's own token route, for a screen with no session. */
export const tokenImageUrl =
  (token: string): ImageUrl =>
  (digest) =>
    `/api/display/${token}/assets/${digest}`;
