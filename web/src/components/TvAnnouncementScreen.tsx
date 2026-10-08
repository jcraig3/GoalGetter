import { useEffect, useRef, useState, type ReactNode } from 'react';

import type { Celebration } from '../pages/celebrationQueue';
import WallBackground from './wall/WallBackground';
import YouTubePlayer, { troubleWords, youtubeIdFromLink, type YouTubeTrouble } from './YouTubePlayer';

/**
 * A neutral announcement taking over the screens (Phase 25): "Lunch is here".
 *
 * **Its own screen, behind its words**: a colour, a picture, a video, or a
 * YouTube video filling the screen — the words always on top and readable.
 * Something can sit in the middle as well: a YouTube video, an MP4, a picture.
 *
 * **Sound, in order** (asked for): its sound effect first, then the video's
 * own sound — the middle video's if it has one, otherwise the background's —
 * once the effect has finished. One thing makes sound at a time.
 */
export default function TvAnnouncementScreen({
  celebration,
  joinedAt = 0,
  fileUrl,
  footer,
  role,
  onSound,
  quiet = false,
}: {
  celebration: Celebration;
  joinedAt?: number;
  fileUrl: (digest: string) => string;
  footer?: ReactNode;
  role: Record<string, unknown>;
  onSound?: (allowed: boolean) => void;
  /** Silent: an editor's preview drawn while somebody types. */
  quiet?: boolean;
}) {
  const background = celebration.background ?? null;
  const kind = celebration.media_kind;
  const hasEffect = Boolean(celebration.sound_digest) && !quiet;
  // The effect has had its turn: the video's sound may come in.
  const [effectDone, setEffectDone] = useState(!hasEffect);
  const [trouble, setTrouble] = useState<YouTubeTrouble | null>(null);

  const middleVideo = kind === 'youtube' || kind === 'video';
  const backgroundVideo = background?.kind === 'youtube' || background?.kind === 'video';
  // Whose sound it is, after the effect: the middle's, or else the background's.
  const middleSpeaks = !quiet && middleVideo && effectDone;
  const backgroundSpeaks = !quiet && !middleVideo && backgroundVideo && effectDone;

  const overPicture = Boolean(background && background.kind && !['solid', 'gradient', 'none'].includes(background.kind));

  return (
    // Sized by the screen it's drawn on (`cqw`, `cqh`) rather than the browser
    // window, so the editor's small preview is the TV, smaller.
    <div className="fixed inset-0 z-50 overflow-hidden bg-bg [container-type:size]" {...role}>
      {/* **A background video plays behind the words, with its sound** (asked
          for): drawn here, full screen, by the same players as the middle, so
          its sound waits for the effect the same way. Anything else is the
          wall's ordinary background. */}
      {backgroundVideo ? (
        <div className="absolute inset-0 overflow-hidden">
          {background?.kind === 'youtube' && background.asset && (
            <YouTubePlayer
              videoId={youtubeIdFromLink(background.asset) ?? background.asset}
              start={(background.start ?? 0) + joinedAt}
              loopStart={background.start}
              sound={!quiet}
              hush={!backgroundSpeaks}
              loop
              onTrouble={(next) => {
                setTrouble(next);
                if (next === 'muted') onSound?.(false);
                else if (next === null) onSound?.(true);
              }}
              className="pointer-events-none absolute left-1/2 top-1/2 h-[max(100cqh,56.25cqw)] w-[max(100cqw,177.78cqh)] -translate-x-1/2 -translate-y-1/2 border-0"
            />
          )}
          {background?.kind === 'video' && background.asset && (
            <MiddleVideo
              src={fileUrl(background.asset)}
              from={(background.start ?? 0) + joinedAt}
              speaks={backgroundSpeaks}
              onSound={onSound}
              className="absolute inset-0 size-full object-cover"
            />
          )}
          {(background?.dim ?? 0) > 0 && (
            <div className="absolute inset-0 bg-black" style={{ opacity: background?.dim ?? 0 }} />
          )}
        </div>
      ) : (
        <WallBackground background={background} imageUrl={fileUrl} voice={{ sound: !quiet, hush: true }} />
      )}
      {overPicture && (
        // Darker where the words are, so they read over any picture or video.
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,rgba(0,0,0,0.55),rgba(0,0,0,0.15))]" />
      )}

      {hasEffect && celebration.sound_digest && (
        <Effect
          src={fileUrl(celebration.sound_digest)}
          from={joinedAt}
          onDone={() => setEffectDone(true)}
          onSound={onSound}
        />
      )}

      <div className="relative flex h-full flex-col items-center justify-center gap-[3cqh] px-[4cqw] py-[4cqh] text-center">
        <div className={overPicture ? 'text-white [text-shadow:0_2px_24px_rgba(0,0,0,0.6)]' : 'text-content'}>
          <p className="text-[6.5cqw] font-bold leading-tight tracking-tight">{celebration.title}</p>
          {celebration.body && (
            <p className={`mx-auto mt-[1.5cqh] max-w-[80cqw] text-[2.8cqw] leading-snug ${overPicture ? 'text-white/90' : 'text-content-muted'}`}>
              {celebration.body}
            </p>
          )}
          {troubleWords(trouble) && <p className="mt-[1cqh] text-[1.4cqw] opacity-80">{troubleWords(trouble)}</p>}
        </div>
        {/* **In the middle: a smaller window below the words** (asked for). */}
        {kind === 'youtube' && celebration.media_id && (
          <YouTubePlayer
            videoId={celebration.media_id}
            start={(celebration.media_start_seconds ?? 0) + joinedAt}
            sound={!quiet}
            hush={!middleSpeaks}
            onTrouble={(next) => {
              setTrouble(next);
              if (next === 'muted') onSound?.(false);
              else if (next === null) onSound?.(true);
            }}
            // A width and a ratio, not a height: an iframe left to size itself
            // from a height came out with no width at all.
            className="pointer-events-none aspect-video w-[min(60cqw,80cqh)] flex-none rounded-2xl border-0 shadow-2xl"
          />
        )}
        {kind === 'video' && celebration.media_digest && (
          <MiddleVideo
            src={fileUrl(celebration.media_digest)}
            from={(celebration.media_start_seconds ?? 0) + joinedAt}
            speaks={middleSpeaks}
            onSound={onSound}
            className="max-h-[45cqh] max-w-[60cqw] flex-none rounded-2xl object-contain shadow-2xl"
          />
        )}
        {kind === 'image' && (celebration.media_digest || celebration.media_url) && (
          <img
            src={celebration.media_digest ? fileUrl(celebration.media_digest) : (celebration.media_url ?? '')}
            alt=""
            className="max-h-[45cqh] max-w-full rounded-2xl object-contain shadow-2xl"
          />
        )}

        {footer}
      </div>
    </div>
  );
}

/** The sound effect: once, from the start, then the video's turn. */
function Effect({
  src,
  from,
  onDone,
  onSound,
}: {
  src: string;
  from: number;
  onDone: () => void;
  onSound?: (allowed: boolean) => void;
}) {
  const element = useRef<HTMLAudioElement | null>(null);
  const done = useRef(onDone);
  done.current = onDone;
  const tell = useRef(onSound);
  tell.current = onSound;
  const startAt = useRef(from);

  useEffect(() => {
    const audio = element.current;
    if (!audio) return;
    const finish = () => done.current();
    const begin = () => {
      if (Number.isFinite(audio.duration) && startAt.current >= audio.duration) {
        // A screen that joined after the effect had already played.
        finish();
        return;
      }
      audio.currentTime = startAt.current;
      const playing = audio.play?.();
      if (playing && typeof playing.then === 'function') {
        playing.then(
          () => tell.current?.(true),
          () => {
            audio.muted = true;
            tell.current?.(false);
            void audio.play?.()?.catch(() => finish());
          },
        );
      }
    };
    audio.addEventListener('ended', finish);
    // A clip that won't load mustn't keep the video quiet for good.
    audio.addEventListener('error', finish);
    if (audio.readyState >= 1) begin();
    else audio.addEventListener('loadedmetadata', begin, { once: true });
    return () => {
      audio.removeEventListener('ended', finish);
      audio.removeEventListener('error', finish);
      audio.removeEventListener('loadedmetadata', begin);
    };
  }, [src]);

  return <audio ref={element} src={src} preload="auto" className="hidden" />;
}

/** An uploaded video in the middle: muted until it is its turn to speak. */
function MiddleVideo({
  src,
  from,
  speaks,
  onSound,
  className,
}: {
  src: string;
  from: number;
  speaks: boolean;
  onSound?: (allowed: boolean) => void;
  className: string;
}) {
  const element = useRef<HTMLVideoElement | null>(null);
  const startAt = useRef(from);
  const tell = useRef(onSound);
  tell.current = onSound;

  useEffect(() => {
    const video = element.current;
    if (!video) return;
    const begin = () => {
      video.currentTime = startAt.current;
      void video.play?.()?.catch(() => {});
    };
    if (video.readyState >= 1) begin();
    else video.addEventListener('loadedmetadata', begin, { once: true });
    return () => video.removeEventListener('loadedmetadata', begin);
  }, [src]);

  useEffect(() => {
    const video = element.current;
    if (!video) return;
    video.muted = !speaks;
    if (speaks) {
      void video.play?.()?.then(
        () => tell.current?.(true),
        () => {
          // The browser wouldn't let it speak: muted, rather than stopped.
          video.muted = true;
          tell.current?.(false);
          void video.play?.()?.catch(() => {});
        },
      );
    }
  }, [speaks]);

  return (
    <video
      ref={element}
      src={src}
      autoPlay
      muted
      loop
      playsInline
      className={className}
    />
  );
}
