import { useEffect, useRef } from 'react';

import type { Background } from '../../appearance';
import { sessionImageUrl, type ImageUrl } from './types';
import Scene from './Scenes';
import YouTubePlayer, { youtubeIdFromLink } from '../YouTubePlayer';
import { useWallSound } from './sound';

/**
 * What sits behind everything else on a wall.
 *
 * **It was stored, validated and inherited for a phase before anything drew
 * it.** The whole background shape — kind, colours, asset, dim, blur — resolved
 * correctly through four layers and reached a television that painted the
 * default near-black over the top of it.
 *
 * **Dim and blur belong here, not to the panels.** A photograph behind white
 * text is unreadable at ten feet, and the fix is to darken the photograph
 * rather than to make every panel opaque — which hides the photograph entirely
 * and raises the question of why it is there at all.
 */
export default function WallBackground({
  background,
  imageUrl = sessionImageUrl,
  voice,
}: {
  background: Background | null | undefined;
  imageUrl?: ImageUrl;
  /** Told by the screen in charge instead of the wall's own rules — an
   *  announcement, whose background's sound waits for its sound effect
   *  (Phase 25). `sound` is fixed for the video's life; `hush` comes and goes. */
  voice?: { sound: boolean; hush: boolean };
}) {
  const kind = background?.kind ?? 'none';
  const sound = useWallSound();
  const video = useRef<HTMLVideoElement | null>(null);
  // An uploaded video's own sound: on when this tab may play sound and
  // neither a celebration nor a YouTube screen has the floor.
  const wantSound = voice
    ? voice.sound && !voice.hush
    : sound.onWall && sound.allowed === true && !sound.celebrating && !sound.screenSound;
  const report = sound.report;
  useEffect(() => {
    const node = video.current;
    if (!node) return;
    node.muted = !wantSound;
    if (wantSound) {
      void node.play()?.catch(() => {
        // The browser said no after all: muted, rather than stopped.
        node.muted = true;
        report(false);
        void node.play()?.catch(() => {});
      });
    }
  }, [wantSound, background?.asset, report]);
  // `inherit` should never reach a renderer — `resolve` collapses it — but a
  // wall must not go dark because an older row said something newer code does
  // not recognise.
  if (!background || kind === 'none' || kind === 'inherit') return null;

  const dim = background.dim ?? 0;
  const blur = background.blur ?? 0;
  const moving = kind === 'gradient' && Boolean(background.motion);

  return (
    <div
      aria-hidden="true"
      // Named, so a thumbnail can leave it out (P3-8).
      data-wall-background=""
      // **`-z-10`, and it is not optional.** Inside one stacking context a
      // positioned element paints *above* its in-flow siblings whatever the
      // DOM order — so an `absolute` layer written first still covered the
      // title, the logo and the board. A negative index puts it back behind
      // them, above only the wall's own background colour.
      //
      // That last part is why the wall and the preview carry `isolate`:
      // without a stacking context to sit in, a negative index sinks below the
      // nearest ancestor's background instead and the photograph disappears
      // entirely.
      className="pointer-events-none absolute inset-0 -z-10"
    >
      <div
        className="absolute inset-0 overflow-hidden [container-type:size]"
        style={{
          // Scaled up slightly whenever it is blurred: a blur samples past its
          // own edges and leaves a pale border otherwise, which on a wall
          // reads as a badly cropped photograph.
          ...(blur > 0
            ? { filter: `blur(${blur}px)`, transform: 'scale(1.06)' }
            : null),
          ...(moving ? null : layer(background, kind, imageUrl)),
        }}
      >
        {moving && (
          <div
            // **Moved, never repainted.** The gradient is drawn once on a
            // layer twice the size of the screen, and that layer drifts with
            // `transform` — which a television's graphics chip does on its
            // own. Animating the gradient itself would repaint the whole
            // screen every frame, and that is what makes a cheap stick stutter.
            //
            // `motion-safe`, so a device asked for less motion gets the
            // gradient standing still rather than not at all.
            className="absolute -inset-1/2 motion-safe:animate-[gg-drift_40s_ease-in-out_infinite_alternate]"
            style={layer(background, kind, imageUrl)}
          />
        )}
        {kind === 'scene' && (
          // **A drawn scene** (6.9): in this background's colours, moving
          // only when it was set to move.
          <Scene
            scene={background.scene ?? 'mesh'}
            colours={{
              base: background.color ?? '#0b0e14',
              mid: background.color_mid ?? background.color_to ?? '#334155',
              top: background.color_to ?? background.color_mid ?? '#64748b',
            }}
            moving={Boolean(background.motion)}
          />
        )}
        {kind === 'video' && background.asset && (
          <video
            ref={video}
            // Starts muted — what lets a browser autoplay it at all — and its
            // sound comes on when this tab may play sound and nothing else
            // has the floor (Phase 24). `playsInline` stops a phone-sized
            // browser going fullscreen.
            src={imageUrl(background.asset)}
            autoPlay
            muted
            loop
            playsInline
            // Nothing to fetch until it plays: `metadata` is enough to size it,
            // and the television asks for the footage in ranges as it needs it.
            preload="metadata"
            // Cover, like a photograph: fitted on the screen rather than
            // cropped on upload, so the framing can still change.
            className="absolute inset-0 size-full object-cover"
          />
        )}
        {kind === 'youtube' && background.asset && (
          <YouTubePlayer
            // An id; an older row may hold the whole link.
            videoId={youtubeIdFromLink(background.asset) ?? background.asset}
            start={background.start}
            loopStart={background.start}
            // **With sound on a wall** (Phase 24, asked for), quiet while a
            // celebration or a YouTube screen has the sound; silent in an
            // editor's preview. See `wall/sound.ts`.
            sound={voice ? voice.sound : sound.onWall}
            hush={voice ? voice.hush : sound.celebrating || sound.screenSound}
            onTrouble={(next) => {
              if (next === 'muted') sound.report(false);
              else if (next === null && sound.onWall) sound.report(true);
            }}
            loop
            // 16:9, at least as wide and as tall as the screen, centred: it
            // fills any shape of TV with no letterbox, like `object-cover`.
            className="absolute left-1/2 top-1/2 h-[max(100cqh,56.25cqw)] w-[max(100cqw,177.78cqh)] -translate-x-1/2 -translate-y-1/2 border-0"
          />
        )}
      </div>

      {dim > 0 && (
        // Over the blur, not under it: dimming first and blurring afterwards
        // would blur the dimming too and lighten the edges.
        <div
          className="absolute inset-0 bg-black"
          style={{ opacity: dim }}
        />
      )}

      {PICTURES.has(kind) && (
        // **A shade behind the header, whatever the dim says.** A title, a
        // subtitle and the channel's name in muted grey over a bright
        // photograph were not there at all from across a room (review §8).
        // Darkening the whole picture more would override a dim somebody
        // chose; this darkens only the strip the words sit on.
        <div
          data-testid="header-shade"
          className="absolute inset-x-0 top-0 h-80 bg-gradient-to-b from-black/65 via-black/30 to-transparent"
        />
      )}
    </div>
  );
}

/** Backgrounds that are a picture of something, rather than a colour. */
const PICTURES = new Set(['image', 'video', 'youtube']);

/** The CSS that draws one kind of background. */
function layer(
  background: Background,
  kind: string,
  imageUrl: ImageUrl,
): React.CSSProperties {
  if (kind === 'solid') {
    return { backgroundColor: background.color ?? '#000000' };
  }

  if (kind === 'gradient') {
    return { backgroundImage: gradientCss(background) };
  }

  if (kind === 'image' && background.asset) {
    return {
      // Cover, not contain: a television is 16:9 and the photograph somebody
      // chose probably is not. The server keeps the whole image and the screen
      // decides how to fill — which is reversible, unlike cropping on upload.
      backgroundImage: `url(${imageUrl(background.asset)})`,
      backgroundSize: 'cover',
      backgroundPosition: 'center',
    };
  }

  return {};
}

/**
 * A gradient background as CSS.
 *
 * Exported for the library's swatches, which draw a preset with exactly the
 * CSS the wall will — a swatch that looked different from the screen would be
 * a preview that lies.
 */
export function gradientCss(background: Pick<
  Background,
  'color' | 'color_to' | 'color_mid' | 'angle' | 'style'
>): string {
  const from = background.color ?? '#000000';
  const to = background.color_to ?? from;
  const stops = background.color_mid ? `${from}, ${background.color_mid}, ${to}` : `${from}, ${to}`;
  if (background.style === 'radial') {
    return `radial-gradient(circle at 30% 30%, ${stops})`;
  }
  return `linear-gradient(${background.angle ?? 135}deg, ${stops})`;
}
