import { createContext, useContext } from 'react';

import { api } from '../../api';

/**
 * Sound on a TV (Phase 24).
 *
 * **Everything on a wall that has sound plays it** — celebrations, YouTube
 * screens, and YouTube or uploaded-video backgrounds — **one at a time**: a
 * celebration over a YouTube screen over the background. The others are
 * muted, not paused, so they stay in time and come back when it lets go.
 *
 * **A tab needs one click or key press before it may start sound.** That is
 * the browser's rule and no page can get round it. So the channel says so
 * the moment it opens, if it hasn't got it ("Sound is off · click anywhere or
 * press OK"), and one press turns sound on for the life of the tab. Each
 * screen also tells the server, so TVs & Channels shows a TV whose sound is
 * off.
 */
export interface WallSound {
  /** Rendered on a wall (not an editor's preview): backgrounds play sound. */
  onWall: boolean;
  /** Whether this tab may play sound: null until known. */
  allowed: boolean | null;
  /** A celebration has the screen. */
  celebrating: boolean;
  /** The screen showing now has a sound of its own (a YouTube screen). */
  screenSound: boolean;
  /** Something found out whether the browser let it play with sound. */
  report: (allowed: boolean) => void;
  /** An editor's preview of one screen, opened by a click: its video plays
   *  with sound. Off for the small previews in a list, which stay quiet. */
  previewSound?: boolean;
}

/** Outside a wall — an editor's preview — nothing is reported or hushed, and
 *  backgrounds stay quiet. */
export const WallSoundContext = createContext<WallSound>({
  onWall: false,
  allowed: null,
  celebrating: false,
  screenSound: false,
  report: () => {},
});

export function useWallSound(): WallSound {
  return useContext(WallSoundContext);
}

const reported = new Map<string, boolean>();

/** Tell the server, only when the answer changes for this screen. */
export function reportSound(token: string, allowed: boolean) {
  if (!token || reported.get(token) === allowed) return;
  reported.set(token, allowed);
  void api(`/api/display/${token}/sound`, {
    method: 'POST',
    body: JSON.stringify({ blocked: !allowed }),
  }).catch(() => {
    // Said again next time something plays.
    reported.delete(token);
  });
}

/**
 * Whether this tab may start sound right now, without playing anything: an
 * audio context starts "suspended" when the browser is holding sound back,
 * and "running" when it isn't. Null where there is no way to tell.
 */
export function soundAllowedNow(): boolean | null {
  const Context =
    (window as unknown as { AudioContext?: typeof AudioContext }).AudioContext ??
    (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
  if (!Context) return null;
  try {
    const context = new Context();
    const running = context.state === 'running';
    void context.close();
    return running;
  } catch {
    return null;
  }
}
