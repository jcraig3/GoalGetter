import { useEffect, useRef, useState, type ReactNode } from 'react';

import type { Celebration } from '../pages/celebrationQueue';
import CelebrationArt from './wall/CelebrationArt';
import TvAnnouncementScreen from './TvAnnouncementScreen';
import YouTubePlayer, { troubleWords, type YouTubeTrouble } from './YouTubePlayer';

/**
 * An announcement, as it looks on a wall.
 *
 * **One component for the wall and for the preview**, which is the only way a
 * preview stays one. The walk-up editor's Preview button renders exactly this,
 * with the same layouts, the same words and the same player — and differs only
 * in where a stored clip is fetched from: a wall has a display token and no
 * session, an editor has a session and no token.
 *
 * Three layouts, chosen by what is playing:
 *
 *     uploaded video   fills the screen, the words over it — no adverts, and
 *                      nothing forbids text over a file that is ours
 *     YouTube          as large as the screen allows, the words in a band of
 *                      their own beneath it, because YouTube's embed rules
 *                      forbid anything in front of its player
 *     anything else    the words, centred, with a sound playing under them
 *
 * `footer` goes in each layout's own text area — for a preview, its label and
 * close button — so that it is never placed over a YouTube player either.
 */
export default function AnnouncementScreen({
  celebration,
  joinedAt = 0,
  fileUrl,
  footer,
  label,
  onSound,
  quiet = false,
}: {
  celebration: Celebration;
  /** Seconds into the announcement this screen arrived. */
  joinedAt?: number;
  /** Where a stored clip's bytes are, from its digest. */
  fileUrl: (digest: string) => string;
  footer?: ReactNode;
  /**
   * Set for a preview, which somebody operates: the screen becomes a labelled
   * dialog. Left unset on a wall, where it is decorative — a television has
   * no keyboard and nobody navigating it, so it is hidden from screen readers.
   */
  label?: string;
  /** Told whether the browser let it play with sound: false when it had to
   *  play muted (Phase 24). A wall reports it, so a TV nobody clicks can be
   *  seen to need sound allowed. */
  onSound?: (allowed: boolean) => void;
  /** Silent: an editor's preview drawn while somebody types (Phase 25). */
  quiet?: boolean;
}) {
  const role = label
    ? ({ role: 'dialog', 'aria-modal': true, 'aria-label': label } as const)
    : ({ 'aria-hidden': true } as const);
  // What the YouTube player ran into — sound held back, a video that only
  // plays on YouTube — said under it. Fresh for each celebration.
  const [trouble, setTrouble] = useState<YouTubeTrouble | null>(null);
  useEffect(() => setTrouble(null), [celebration.id]);

  // **A neutral announcement has a screen of its own** (Phase 25): its own
  // background, the words over it, its sound effect first.
  if (celebration.event_key === 'announcement') {
    return (
      <TvAnnouncementScreen
        celebration={celebration}
        joinedAt={joinedAt}
        fileUrl={fileUrl}
        footer={footer}
        role={role}
        onSound={onSound}
        quiet={quiet}
      />
    );
  }

  // Keyed on the celebration throughout, so a new one mounts a fresh player
  // rather than reusing the last one's position.

  // **Their own music video, filling the screen, with the words over it.**
  // Only possible for a clip served from this deployment — see the note on
  // YouTube below.
  if (celebration.media_kind === 'video' && celebration.media_digest) {
    return (
      <div className="fixed inset-0 z-50 bg-black" {...role}>
        <Player
          key={celebration.id}
          kind="video"
          src={fileUrl(celebration.media_digest)}
          from={(celebration.media_start_seconds ?? 0) + joinedAt}
          className="absolute inset-0 size-full object-cover"
          onSound={onSound}
        />
        {/* Darkest behind the words and clear at the top, so the video stays
            the picture and the text stays readable from across the room. */}
        <div className="absolute inset-0 bg-gradient-to-t from-black/85 via-black/35 to-transparent" />
        <div className="absolute inset-x-0 bottom-0 px-16 pb-16 text-center">
          <Words celebration={celebration} onDark />
          {footer}
        </div>
      </div>
    );
  }

  // **YouTube: the video as large as the screen allows, and the words beside
  // it — never over it.** YouTube's embed rules forbid "overlays, frames, or
  // other visual elements in front of any part of a YouTube embedded player",
  // so the full-screen-with-text-on-top look is only for an uploaded clip.
  // Nothing here is positioned over the player; the band below it is its own
  // part of the layout.
  if (celebration.media_kind === 'youtube' && celebration.media_id) {
    return (
      <div className="fixed inset-0 z-50 flex flex-col bg-bg" {...role}>
        <div className="flex min-h-0 flex-1 items-center justify-center p-8">
          <YouTubePlayer
            key={celebration.id}
            videoId={celebration.media_id}
            // From the walk-up's start, plus however far in this screen joined.
            start={(celebration.media_start_seconds ?? 0) + joinedAt}
            end={celebration.media_end_seconds}
            onTrouble={(next) => {
              setTrouble(next);
              if (next === 'muted') onSound?.(false);
              else if (next === null) onSound?.(true);
            }}
            className="aspect-video h-full max-h-full w-auto max-w-full rounded-2xl border-0"
          />
        </div>
        <div className="shrink-0 px-16 pb-12 text-center">
          <Words celebration={celebration} />
          {/* Below the player, never over it: YouTube's embed rules forbid
              anything in front of the player. */}
          {troubleWords(trouble) && (
            <p className="mt-3 text-base text-content-muted">{troubleWords(trouble)}</p>
          )}
          {footer}
        </div>
      </div>
    );
  }

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-bg px-16 text-center"
      {...role}
    >
      {celebration.event_key === 'wheel.won' ? (
        <WheelLanding key={celebration.id} joinedAt={joinedAt} />
      ) : (
        <Media
          key={celebration.id}
          celebration={celebration}
          joinedAt={joinedAt}
          fileUrl={fileUrl}
          onSound={onSound}
        />
      )}
      <div
        className={
          celebration.event_key === 'wheel.won' && joinedAt < SPIN_SECONDS
            ? 'mt-10 motion-safe:animate-[gg-reveal_600ms_ease-out_both]'
            : // The words follow the trophy in, a beat behind it.
              'mt-6 motion-safe:animate-[gg-rise-in_700ms_ease-out_both]'
        }
        style={
          celebration.event_key === 'wheel.won' && joinedAt < SPIN_SECONDS
            ? { animationDelay: `${SPIN_SECONDS - joinedAt}s` }
            : { animationDelay: `${0.55 - joinedAt}s` }
        }
      >
        <Words celebration={celebration} />
        {footer}
      </div>
    </div>
  );
}

/**
 * What the announcement says, in the order a room reads it: what it is for,
 * the number, whose it is, then the detail.
 *
 * The occasion leads because it answers the question the music raises —
 * "Recognition", "Goal hit" — before anybody has read a name. **Then the
 * figure, largest of all** (7.9): "$500" is the news, and it used to be the
 * smallest text on the wall, inside the sentence at the bottom. A win with no
 * number — a shout-out, a birthday — keeps the name as its largest line. The
 * title is skipped when it only repeats a line above it: an achievement's name
 * is both its occasion and its title.
 */
function Words({
  celebration,
  onDark = false,
}: {
  celebration: Celebration;
  onDark?: boolean;
}) {
  const main = onDark ? 'text-white' : 'text-content';
  const soft = onDark ? 'text-white/80' : 'text-content-muted';
  // Skipped when it only repeats a line above it — the occasion (which an
  // achievement's name is) or the person's name.
  const title =
    celebration.title &&
    celebration.title !== celebration.occasion &&
    celebration.title !== celebration.about_name
      ? celebration.title
      : null;

  return (
    <>
      {celebration.occasion && (
        <p className="text-4xl font-semibold uppercase tracking-[0.2em] text-brand">
          {celebration.occasion}
        </p>
      )}
      {celebration.figure && (
        <p
          data-testid="celebration-figure"
          className={`mt-4 text-[10rem] font-bold leading-none tabular-nums ${main}`}
        >
          {celebration.figure}
        </p>
      )}
      {celebration.about_name && (
        <p
          className={`${celebration.figure ? 'mt-6 text-6xl font-semibold' : 'mt-4 text-8xl font-bold'} leading-none ${main}`}
        >
          {celebration.about_name}
        </p>
      )}
      {title && (
        <p className={`mt-6 text-5xl font-semibold leading-tight ${main}`}>{title}</p>
      )}
      {celebration.body && (
        <p className={`mt-5 ${celebration.figure ? 'text-4xl' : 'text-3xl'} ${soft}`}>
          {celebration.body}
        </p>
      )}
    </>
  );
}

/**
 * Whatever plays alongside the words.
 *
 * A YouTube clip is muted-off — that is, sound is *on*, which is the one place in
 * this product where that is true. A room that does not want it mutes the
 * television, which is the control they already have and understand.
 *
 * `joinedAt` is how many seconds into the celebration this screen arrived, so a
 * screen switched on part-way through plays its clip from where the others are.
 */
function Media({
  celebration,
  joinedAt,
  fileUrl,
  onSound,
}: {
  celebration: Celebration;
  joinedAt: number;
  onSound?: (allowed: boolean) => void;
  fileUrl: (digest: string) => string;
}) {
  // **An uploaded walk-up clip.** It arrives as `asset:<digest>` of kind
  // `audio`, and until 4k nothing here handled that kind — so it fell through
  // to the image branch below, drew a broken picture, and played no sound. The
  // server side of walk-up audio was tested in 4g; the screen was not.
  if (celebration.media_kind === 'audio' && celebration.media_digest) {
    return (
      <>
        <Player
          kind="audio"
          src={fileUrl(celebration.media_digest)}
          from={(celebration.media_start_seconds ?? 0) + joinedAt}
          onSound={onSound}
        />
        <CelebrationArt celebration={celebration} joinedAt={joinedAt} photo={photoOf(celebration, fileUrl)} />
      </>
    );
  }

  // **The trophy for its occasion** (6.6), where the emoji was: a cup, a
  // laurel, a medal, a rocket, a cake or a rosette, arriving with confetti.
  if (!celebration.media_url || celebration.media_kind !== 'image') {
    return (
      <CelebrationArt
        celebration={celebration}
        joinedAt={joinedAt}
        photo={photoOf(celebration, fileUrl)}
      />
    );
  }

  return (
    <img
      // A picture from the library by its file (Phase 27), a link as it is.
      src={celebration.media_digest ? fileUrl(celebration.media_digest) : celebration.media_url}
      alt=""
      // Pixels, not `vh`: on a wall this is drawn on the 1920×1080 stage, where
      // the viewport's height means nothing — half the stage is 540.
      className="max-h-[540px] rounded-2xl object-contain"
    />
  );
}

/** Their photograph's URL, through whichever route this screen reads files by. */
function photoOf(
  celebration: Celebration,
  fileUrl: (digest: string) => string,
): string | null {
  return celebration.photo_digest ? fileUrl(celebration.photo_digest) : null;
}

/**
 * An uploaded clip — sound, or a music video — started at the right second.
 *
 * **With sound, and muted only if the browser insists.** Autoplay with sound
 * is allowed once somebody has clicked the page, which a wall's first set-up
 * is. On a screen nobody has touched, the browser refuses; rather than leave
 * a frozen first frame in front of the room, it plays on without sound.
 */
function Player({
  kind,
  src,
  from,
  className,
  onSound,
}: {
  kind: 'audio' | 'video';
  src: string;
  from: number;
  className?: string;
  onSound?: (allowed: boolean) => void;
}) {
  const element = useRef<HTMLMediaElement | null>(null);
  // **Where it starts is decided once** (Phase 24): `from` includes how far
  // into the celebration this screen joined, which grows on every redraw,
  // and seeking again each time made the song skip every few seconds.
  const startAt = useRef(from);
  const tell = useRef(onSound);
  tell.current = onSound;

  useEffect(() => {
    const media = element.current;
    if (!media) return;
    const begin = () => {
      media.currentTime = startAt.current;
      const playing = media.play?.();
      if (playing && typeof playing.catch === 'function') {
        playing.then(
          () => tell.current?.(true),
          () => {
            media.muted = true;
            tell.current?.(false);
            void media.play?.()?.catch?.(() => {});
          },
        );
      }
    };
    // Seeking before the file's length is known is ignored by some browsers,
    // so it waits for the metadata when it has to.
    if (media.readyState >= 1) begin();
    else media.addEventListener('loadedmetadata', begin, { once: true });
    // A press that happens anyway — a remote, a keyboard — brings the sound
    // of a clip that had to start muted.
    const unmute = () => {
      if (!media.muted) return;
      media.muted = false;
      void media.play?.()?.then(() => tell.current?.(true), () => {});
    };
    window.addEventListener('pointerdown', unmute);
    window.addEventListener('keydown', unmute);
    return () => {
      media.removeEventListener('loadedmetadata', begin);
      window.removeEventListener('pointerdown', unmute);
      window.removeEventListener('keydown', unmute);
    };
  }, [src]);

  if (kind === 'video') {
    return (
      <video
        ref={(node) => {
          element.current = node;
        }}
        src={src}
        autoPlay
        playsInline
        preload="auto"
        className={className}
      />
    );
  }
  return (
    <audio
      ref={(node) => {
        element.current = node;
      }}
      src={src}
      autoPlay
      preload="auto"
    />
  );
}

/** How long the prize wheel turns before it lands. */
export const SPIN_SECONDS = 3;

/**
 * The prize wheel, spinning on the wall and landing — then the words.
 *
 * **CSS keyframes rather than a timer**, so every screen that started the
 * celebration at the same instant also lands at the same instant: the shared
 * clock already started them together, and an animation of a fixed length
 * cannot drift the way a chain of timers can.
 *
 * A screen that joins after the wheel has landed shows it standing still, in
 * step with the rest, rather than spinning again on its own. A device asked
 * for less motion gets the same.
 *
 * Drawn in the organization's own colours rather than as art — it is the idea
 * of the wheel, not a picture of this wheel, and the real segments are on the
 * Spend page for anybody who wants them.
 */
function WheelLanding({ joinedAt }: { joinedAt: number }) {
  const spinning = joinedAt < SPIN_SECONDS;
  return (
    <div className="relative size-[18rem]" aria-hidden="true">
      <span className="absolute left-1/2 top-0 z-10 -translate-x-1/2 -translate-y-2 border-x-[18px] border-t-[28px] border-x-transparent border-t-content" />
      <div
        data-spinning={spinning ? 'true' : 'false'}
        className={`size-full rounded-full border-8 border-surface ${
          spinning
            ? 'motion-safe:animate-[gg-wheel-land_3s_cubic-bezier(0.15,0.85,0.25,1)_both]'
            : ''
        }`}
        style={{
          backgroundImage:
            'repeating-conic-gradient(var(--gg-brand) 0 30deg, color-mix(in srgb, var(--gg-brand) 45%, var(--gg-surface)) 30deg 60deg, color-mix(in srgb, var(--gg-accent) 70%, var(--gg-surface)) 60deg 90deg)',
        }}
      />
    </div>
  );
}

