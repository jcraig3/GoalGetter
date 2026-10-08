import { useEffect, useMemo, useRef } from 'react';

/** What happened, for the screen to say something about it. */
export type YouTubeTrouble =
  /** Chrome wouldn't start it with sound, so it plays muted until a click. */
  | 'muted'
  /** Its owner doesn't allow it to play anywhere but YouTube, or it's
   *  age-restricted: no sign-in changes that. */
  | 'not-embeddable'
  /** Removed, private, or the link is wrong. */
  | 'unavailable'
  /** Ready but never started, even muted: YouTube's "Sign in to confirm
   *  you're not a bot", which it shows a browser that isn't signed in. */
  | 'sign-in';

const ORIGIN = 'https://www.youtube.com';

/** How long to wait for it to start before playing it muted instead — longer
 *  while it is still buffering, which is not being blocked. */
const BLOCKED_AFTER_MS = 2500;
/** And then for it to start muted, before it is put down to a sign-in. */
const STUCK_AFTER_MS = 4000;

/**
 * A YouTube video that plays by itself, from the right moment (Phase 24).
 *
 * **YouTube's normal player, not its privacy mode.** `youtube-nocookie.com`
 * never sees the browser's YouTube sign-in, so a signed-in Chrome profile still
 * got "Sign in to confirm you're not a bot" there. `youtube.com` uses it.
 *
 * **It never waits for a click.** Chrome lets a page start sound only after
 * somebody has clicked it; a wall left running, or reloaded, often hasn't been.
 * So if it hasn't started shortly after it is ready, it plays muted — the same
 * as an uploaded clip does — and the first click or key anywhere on the page
 * turns the sound on, for this video and every one after it.
 *
 * **Talks to the player by message, not with YouTube's script.** The embed
 * understands `postMessage` commands when it is loaded with `enablejsapi`, so
 * none of YouTube's code runs in GoalGetter's own page.
 */
export default function YouTubePlayer({
  videoId,
  start,
  end,
  sound = true,
  loop = false,
  controls = false,
  className,
  onTrouble,
  hush = false,
  loopStart,
}: {
  videoId: string;
  /** Seconds into the video to start at. */
  start?: number | null;
  end?: number | null;
  /** False for backgrounds and silent screens: muted from the start. */
  sound?: boolean;
  loop?: boolean;
  controls?: boolean;
  className?: string;
  onTrouble?: (trouble: YouTubeTrouble | null) => void;
  /** Quiet for now — a celebration has taken over the screen — and back to
   *  sound when it lets go. Muted rather than paused, so it stays in time. */
  hush?: boolean;
  /** Where a looping video starts again; the start of the video if not given. */
  loopStart?: number | null;
}) {
  const frame = useRef<HTMLIFrameElement | null>(null);
  // The latest callback, without restarting the player when it changes.
  const tell = useRef(onTrouble);
  tell.current = onTrouble;
  // Set by the player's lifecycle below, for `hush` to use.
  const command = useRef<(func: string) => void>(() => {});
  const playingMuted = useRef(false);
  const hushed = useRef(hush);
  hushed.current = hush;
  // **Hushed from the start: muted in the address**, so not a blip of sound
  // escapes before the player hears it — an announcement's video waiting for
  // its sound effect to finish (Phase 25). A muted start says nothing about
  // whether sound is allowed, so it doesn't report either way.
  const startedHushed = useRef(hush).current;
  // When sound was last asked for, so a browser that pauses the video rather
  // than let it make sound is caught and it plays muted instead.
  const unmutedAt = useRef(0);
  // Where a looping video goes back to when it ends; null when it doesn't loop.
  const loopFrom = useRef<number | null>(null);
  loopFrom.current = loop ? Math.floor(loopStart ?? 0) : null;

  // **Worked out once per video, never again** (the flashing bug). A wall
  // re-renders every few seconds, and `start` includes how far into the
  // celebration this screen joined, which grows; putting the new value in
  // the address reloaded the player each time — a flash of its play button,
  // a second of song, and again. The moment it first appears is what counts.
  const src = useMemo(() => {
    const params = new URLSearchParams({
      autoplay: '1',
      mute: sound && !startedHushed ? '0' : '1',
      controls: controls ? '1' : '0',
      playsinline: '1',
      rel: '0',
      iv_load_policy: '3',
      disablekb: '1',
      fs: '0',
      enablejsapi: '1',
      origin: window.location.origin,
    });
    if (start) params.set('start', String(Math.floor(start)));
    if (end) params.set('end', String(Math.floor(end)));
    // **No `loop=1&playlist=<id>`**: YouTube often wouldn't play a video
    // asked for as a one-video playlist — a background that never started.
    // Looping is done below, by going back to the start when it ends.
    return `${ORIGIN}/embed/${encodeURIComponent(videoId)}?${params}`;
    // `start` and `end` deliberately left out: see above.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoId, sound, loop, controls]);

  useEffect(() => {
    const node = frame.current;
    if (!node) return;
    let heard = false;
    let playing = false;
    let mutedFallback = false;
    let blockedTimer: ReturnType<typeof setTimeout> | undefined;
    let stuckTimer: ReturnType<typeof setTimeout> | undefined;

    const send = (func: string, args: unknown[] = []) =>
      node.contentWindow?.postMessage(JSON.stringify({ event: 'command', func, args }), ORIGIN);
    command.current = (func) => send(func);

    const playMuted = () => {
      if (playing || mutedFallback) return;
      mutedFallback = true;
      playingMuted.current = true;
      send('mute');
      send('playVideo');
      if (sound) tell.current?.('muted');
      // Not even muted: YouTube is holding it behind its sign-in check.
      stuckTimer = setTimeout(() => {
        if (!playing) tell.current?.('sign-in');
      }, STUCK_AFTER_MS);
    };

    const onMessage = (event: MessageEvent) => {
      if (event.origin !== ORIGIN || event.source !== node.contentWindow) return;
      let data: { event?: string; info?: unknown };
      try {
        data = typeof event.data === 'string' ? JSON.parse(event.data) : event.data;
      } catch {
        return;
      }
      heard = true;
      const state =
        data.event === 'onStateChange'
          ? (data.info as number)
          : (data.info as { playerState?: number } | null)?.playerState;
      if (data.event === 'onReady') {
        // Told explicitly, so YouTube's own "autoplay was blocked" arrives.
        for (const name of ['onStateChange', 'onError', 'onAutoplayBlocked']) send('addEventListener', [name]);
        send('playVideo');
        // Ready but not started: Chrome held the sound back — or YouTube is
        // asking for a sign-in, which a muted try tells apart.
        blockedTimer = setTimeout(playMuted, BLOCKED_AFTER_MS);
      } else if (data.event === 'onAutoplayBlocked') {
        playMuted();
      } else if (data.event === 'onError') {
        const code = data.info as number;
        tell.current?.(code === 101 || code === 150 ? 'not-embeddable' : 'unavailable');
      }
      if (state === 3 && !playing && !mutedFallback) {
        // Buffering is starting, not being blocked: give it its time.
        clearTimeout(blockedTimer);
        blockedTimer = setTimeout(playMuted, BLOCKED_AFTER_MS);
      }
      if (state === 0 && loopFrom.current !== null) {
        send('seekTo', [loopFrom.current, true]);
        send('playVideo');
      }
      if (state === 1 && !playing) {
        playing = true;
        // Started during a celebration: quiet until it lets go.
        if (hushed.current) send('mute');
        clearTimeout(blockedTimer);
        clearTimeout(stuckTimer);
        if (!startedHushed) tell.current?.(mutedFallback && sound ? 'muted' : null);
      }
      if (state === 2 && Date.now() - unmutedAt.current < 1500) {
        // Paused the moment it was given sound: the browser wouldn't allow
        // it. Muted rather than stopped.
        unmutedAt.current = 0;
        playingMuted.current = true;
        send('mute');
        send('playVideo');
        if (sound) tell.current?.('muted');
      }
    };
    window.addEventListener('message', onMessage);

    // The player only reports once it is told somebody is listening — asked
    // again until it answers, as YouTube's own script does.
    const listen = () =>
      node.contentWindow?.postMessage(JSON.stringify({ event: 'listening', id: videoId, channel: 'widget' }), ORIGIN);
    let tries = 0;
    const listening = setInterval(() => {
      if (heard || tries++ > 40) clearInterval(listening);
      else listen();
    }, 250);
    node.addEventListener('load', listen);

    // **The first click or key anywhere turns the sound on** (and lets every
    // later video start with it).
    const unlock = () => {
      if (!sound || !mutedFallback) return;
      mutedFallback = false;
      playingMuted.current = false;
      send('unMute');
      send('playVideo');
      tell.current?.(null);
    };
    window.addEventListener('pointerdown', unlock);
    window.addEventListener('keydown', unlock);

    return () => {
      window.removeEventListener('message', onMessage);
      window.removeEventListener('pointerdown', unlock);
      window.removeEventListener('keydown', unlock);
      node.removeEventListener('load', listen);
      clearInterval(listening);
      clearTimeout(blockedTimer);
      clearTimeout(stuckTimer);
    };
  }, [src, sound, videoId]);

  // **Hushed while a celebration has the screen**, then its sound back —
  // unless the browser is holding sound back anyway.
  useEffect(() => {
    if (!sound) return;
    if (hush) command.current('mute');
    else if (!playingMuted.current) {
      unmutedAt.current = Date.now();
      command.current('unMute');
      command.current('playVideo');
    }
  }, [hush, sound]);

  return <iframe ref={frame} src={src} title="" allow="autoplay; encrypted-media" className={className} />;
}

/** The video id in a YouTube link: watch?v=, youtu.be/, embed/, shorts/. */
export function youtubeIdFromLink(url: string): string | null {
  try {
    const link = new URL(url);
    const id =
      link.searchParams.get('v') ??
      link.pathname.match(/^\/(?:embed\/|shorts\/|live\/)?([A-Za-z0-9_-]{11})(?:\/|$)/)?.[1] ??
      null;
    return id && /^[A-Za-z0-9_-]{11}$/.test(id) ? id : null;
  } catch {
    return null;
  }
}

/** What the screen says about it, in a few words. */
export function troubleWords(trouble: YouTubeTrouble | null): string | null {
  // Muted says nothing in words: the TV's corner speaker shows it, and TVs &
  // Channels says how to allow sound — never a prompt on the screen.
  if (trouble === 'muted') return null;
  if (trouble === 'not-embeddable') return 'This video can only be played on YouTube itself.';
  if (trouble === 'unavailable') return 'This video isn’t available.';
  if (trouble === 'sign-in')
    return 'YouTube wants this screen’s browser signed in: open youtube.com in it and sign in once.';
  return null;
}
