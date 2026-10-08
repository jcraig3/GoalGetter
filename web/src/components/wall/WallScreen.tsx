import { useEffect, useRef, useState } from 'react';

import {
  endTime,
  remaining,
  tickInterval,
} from '../../pages/competitionClock';
import Board from './Board';
import Champion from './Champion';
import Comparison from './Comparison';
import OvertakeBanner from './OvertakeBanner';
import Gauge, { BigNumber, StretchStrip } from './Gauge';
import Podium from './Podium';
import Race from './Race';
import Spotlight from './Spotlight';
import HeadToHead from './HeadToHead';
import { agoInWords } from '../../time';
import WallBackground from './WallBackground';
import { useFittedSize } from './fitText';
import { sessionImageUrl, type ImageUrl, type Slide } from './types';
import GameBoard, { GAME_FAMILIES, type Family } from './GameBoard';
import { useWallShape } from './WallStage';
import { startFromLink } from '../WalkupMedia';
import YouTubePlayer, { youtubeIdFromLink } from '../YouTubePlayer';
import { useWallSound } from './sound';

/**
 * One wall screen, whoever is looking at it.
 *
 * **Extracted so an editor can render the real thing.** The product this
 * borrows from asks you to design a full-screen celebration through forty
 * fields and a static thumbnail — you find out what it looks like by walking to
 * the TV. The fix is not a preview that imitates the wall; it is the wall,
 * drawn smaller. Two renderers drift, and the preview stops being one the week
 * after anybody relies on it.
 *
 * The only thing that differs between the two callers is `imageUrl`: a screen
 * authenticates with the token in its own URL, an editor with a session. Taking
 * a builder rather than a token means these components never learn what a
 * display token is, and a preview needs no token to exist.
 */
export default function WallScreen({
  slide,
  channelName,
  stale = false,
  paused = false,
  imageUrl = sessionImageUrl,
  headingLevel = 1,
}: {
  slide: Slide;
  channelName: string;
  /** Data has stopped arriving. Said quietly; see the note below. */
  stale?: boolean;
  /** Somebody is standing at the screen holding it on one slide. */
  paused?: boolean;
  imageUrl?: ImageUrl;
  /** 2 inside a preview, so the page keeps its one `h1` (Q2-27). */
  headingLevel?: 1 | 2;
}) {
  const Title = headingLevel === 2 ? 'h2' : 'h1';
  // **Anything unrecognised falls back rather than blanking.** A wall nobody is
  // standing next to must not go empty because a value arrived that this build
  // has no drawing for — an older screen, a newer server, a typo in a seed file.
  //
  // One source, always: `slide.appearance`, resolved by the server through
  // organization, item, channel and screen. A preview of an unsaved edit merges
  // its changes onto that before rendering — see `WallPreview`.
  const chosenLayout = slide.appearance?.ranked_layout;
  const ranked =
    chosenLayout === 'podium' ||
    chosenLayout === 'race' ||
    GAME_FAMILIES.includes(chosenLayout as Family)
      ? (chosenLayout as string)
      : 'list';
  const measured =
    slide.appearance?.goal_layout === 'big_number' ? 'big_number' : 'gauge';
  const rows = slide.appearance?.row_count ?? 10;
  const showValues = slide.appearance?.show_values ?? true;
  const title = useFittedSize<HTMLHeadingElement>(TITLE_SIZES, slide.title);
  // **On a portrait wall the channel's line goes above the title** (6.11)
  // rather than beside it, where it would take a third of a narrow screen
  // from the headline.
  const portrait = useWallShape() === 'portrait';
  // **A picture or a video is the screen** (Phase 26): it fills the TV and
  // takes the background's place, with nothing in front of it.
  if (slide.kind === 'image' || slide.kind === 'video') {
    return <FullScreenMedia slide={slide} imageUrl={imageUrl} paused={paused} stale={stale} />;
  }
  // **A message is its words, massive, in the middle**, over its background.
  if (slide.kind === 'message') {
    return <MessageScreen slide={slide} imageUrl={imageUrl} paused={paused} stale={stale} />;
  }

  return (
    // The full height of the stage, so what is under the header knows how much
    // room it has — which is how a board decides how many rows fit.
    <div className="flex h-full w-full max-w-6xl flex-col">
      {/* Behind everything, and positioned against the screen rather than
          against this column — the wall's own wrapper is the positioned
          ancestor, so a background covers the whole television and not just
          the width the content happens to take. */}
      <WallBackground
        background={slide.appearance?.background}
        imageUrl={imageUrl}
      />

      {/* **Only on a ranked screen, and only while it is running.** A goal has
          nobody to pass, and a settled contest's positions cannot change —
          announcing a movement there would be describing history as news. */}
      {(slide.kind === 'leaderboard' ||
        (slide.kind === 'competition' && !slide.final)) && (
        <OvertakeBanner slideId={slide.id} entries={slide.entries} />
      )}

      {/* A soft shadow under the header's words, for the same reason the
          background shades the strip behind them. */}
      <header
        className={`flex gap-6 [text-shadow:0_2px_10px_rgb(0_0_0/0.6)] ${
          portrait ? 'flex-col-reverse gap-3' : 'items-baseline justify-between'
        }`}
      >
        <div className="flex min-w-0 items-center gap-6">
          {/* **The company's mark, on the company's wall** — the one logo
              the organization set, the same as in the app's header. */}
          {slide.appearance?.logo && (
            <img
              src={imageUrl(slide.appearance.logo as string)}
              alt=""
              aria-hidden="true"
              // Height-bounded and auto-width: a wordmark is wide and a badge
              // is square, and constraining the width would squash one of them.
              className="h-[1.6em] w-auto shrink-0 object-contain text-wall-5xl"
            />
          )}
          <div className="min-w-0">
          {/* **Two lines, and smaller, before an ellipsis** — a long headline
              used to be cut to half a sentence (QA-16). `leading-tight` over
              the size's own line height of 1, which clipped the tails off g,
              p and y. */}
          <Title
            ref={title.ref}
            className={`line-clamp-2 break-words ${title.size} leading-tight font-semibold text-content`}
          >
            {slide.title}
          </Title>
          {slide.subtitle && (
            <p className="mt-2 text-wall-2xl text-content-muted">{slide.subtitle}</p>
          )}
          {/* **Honest about old numbers** (10.6): only when the newest is
              over a day old, so a working wall never carries it. */}
          {slide.as_of && (
            <p className="mt-2 inline-block rounded-full bg-warning/15 px-4 py-1 text-wall-xl text-warning">
              Numbers as of {slide.as_of}
            </p>
          )}
          </div>
        </div>
        <div className={portrait ? 'flex flex-wrap items-baseline gap-x-4' : 'shrink-0 text-right'}>
          {channelName && <p className="text-wall-2xl text-content-muted">{channelName}</p>}
          {/* **The company's own line, on the company's own wall.** It was
              editable on the Appearance tab and rendered nowhere, which is the
              same as not having the setting. Beside the channel name rather
              than under the title: the title is what this screen is about, and
              a slogan competing with it wins an argument it should not be
              in. */}
          {slide.appearance?.slogan && (
            <p className="mt-1 text-wall-xl text-content-subtle">
              {slide.appearance.slogan}
            </p>
          )}
          {/* **Said, because a rotation that stops looks identical to one
              that broke.** Quiet and small: the person who paused it knows
              why, and the room does not need telling. */}
          {paused && (
            <p className="mt-1 text-wall-base text-content-subtle">Paused</p>
          )}
          {stale && (
            // Small and quiet. The room does not need to be alarmed, but
            // somebody should be able to tell that the figures have stopped
            // moving rather than that everyone has stopped working.
            <p className="mt-1 text-wall-base text-warning">Reconnecting…</p>
          )}
        </div>
      </header>

      {/* `data-wall-body`: the fixed-height space a paged list measures
          itself against. See `usePages`. */}
      <div data-wall-body="" className="mt-10 flex min-h-0 flex-1 flex-col justify-center">
        {slide.kind === 'leaderboard' &&
          (ranked === 'race' ? (
            <Race slide={slide} imageUrl={imageUrl} rows={rows} showValues={showValues} />
          ) : GAME_FAMILIES.includes(ranked as Family) ? (
            <GameBoard
              slide={slide}
              family={ranked as Family}
              imageUrl={imageUrl}
              rows={rows}
              showValues={showValues}
            />
          ) : ranked === 'podium' ? (
            <Podium
              key={slide.id}
              slide={slide}
              imageUrl={imageUrl}
              rows={rows}
              showValues={showValues}
            />
          ) : (
            <Board
              key={slide.id}
              slide={slide}
              imageUrl={imageUrl}
              rows={rows}
              showValues={showValues}
              paged
            />
          ))}
        {slide.kind === 'goal' &&
          (measured === 'big_number' ? (
            <BigNumber slide={slide} />
          ) : (
            <Gauge slide={slide} />
          ))}
        {slide.kind === 'goal' && slide.stretch && slide.stretch.length > 0 && (
          <StretchStrip slide={slide} />
        )}
        {slide.kind === 'competition' && (
          <CompetitionScreen
            slide={slide}
            imageUrl={imageUrl}
            ranked={ranked}
            rows={rows}
            showValues={showValues}
          />
        )}
        {slide.kind === 'achievements' && <Achievements slide={slide} />}
        {slide.kind === 'spotlight' && (
          <Spotlight slide={slide} imageUrl={imageUrl} />
        )}
        {slide.kind === 'comparison' && (
          <Comparison
            slide={slide}
            imageUrl={imageUrl}
            rows={rows}
            showValues={showValues}
          />
        )}
      </div>
    </div>
  );
}

/** The title's sizes, largest first. See `useFittedSize`. */
const TITLE_SIZES = ['text-wall-5xl', 'text-wall-4xl', 'text-wall-3xl'];

/** A message's sizes: the smallest is still readable across a room. */
/**
 * A contest on the wall: the prize, the countdown, and the table.
 *
 * The prize and the deadline go *above* the standings, not below. A room
 * glancing at a screen reads the top two lines and moves on — "Steak dinner ·
 * 2d 4h left" is the reason to look at the names underneath, so it cannot be
 * the thing that gets cut off.
 *
 * The table itself is `<Board>`: a competition is a ranked list, and rendering
 * it a second way would mean two sets of medal colours to keep in step.
 */
function CompetitionScreen({
  slide,
  imageUrl,
  ranked,
  rows,
  showValues,
}: {
  slide: Slide;
  imageUrl: ImageUrl;
  ranked: string;
  rows: number;
  showValues: boolean;
}) {
  // **A settled contest gets a different screen, not a different row in the
  // same one.** While it runs, a room wants the table: where am I, who is
  // close, how long is left. Once it is over the only question left is who
  // won, and a table answers that in the same size type it answers "who came
  // seventh".
  if (slide.final) {
    return <Champion slide={slide} imageUrl={imageUrl} />;
  }

  return (
    <>
      <div className="mb-8 flex flex-wrap items-baseline justify-between gap-4">
        <p className="text-wall-3xl text-gold">{slide.prize ?? ''}</p>
        <p className="text-wall-3xl text-content-muted">
          {/* A settled contest never reaches here — it draws the champion
              screen above — so the only two states left are running and
              awaiting settlement. */}
          {slide.state === 'ended' ? (
            <span className="text-warning">Provisional</span>
          ) : (
            <Countdown
              to={slide.ends_at}
              style={slide.appearance?.end_time_format ?? 'default'}
            />
          )}
        </p>
      </div>
      {ranked === 'race' ? (
        <Race slide={slide} imageUrl={imageUrl} rows={rows} showValues={showValues} />
      ) : GAME_FAMILIES.includes(ranked as Family) ? (
        <GameBoard
          slide={slide}
          family={ranked as Family}
          imageUrl={imageUrl}
          rows={rows}
          showValues={showValues}
        />
      ) : slide.entries.length === 2 ? (
        // Two entrants are two sides, not a table of two rows (8.5). A race
        // or a game board chosen on purpose still wins, above.
        <HeadToHead slide={slide} imageUrl={imageUrl} showValues={showValues} />
      ) : ranked === 'podium' ? (
        <Podium
          key={slide.id}
          slide={slide}
          imageUrl={imageUrl}
          rows={rows}
          showValues={showValues}
        />
      ) : (
        <Board
          key={slide.id}
          slide={slide}
          imageUrl={imageUrl}
          rows={rows}
          showValues={showValues}
          paged
        />
      )}
      {slide.total_entrants > slide.entries.length && (
        <p className="mt-6 text-wall-2xl text-content-subtle">
          Top {slide.entries.length} of {slide.total_entrants}
        </p>
      )}
    </>
  );
}

/**
 * Time left, redrawn as coarsely as it deserves.
 *
 * A wall runs for weeks without a reload, so a countdown that ticks every
 * second for a fortnight is millions of renders producing the same pixels.
 * `tickInterval` matches the rate to the smallest unit actually on screen.
 */
function Countdown({ to, style }: { to: string | null; style: string }) {
  const [now, setNow] = useState(() => new Date());
  const left = to ? remaining(to, now) : 0;
  // A fixed date needs no clock at all, and neither does "off". Ticking either
  // would be a timer running for weeks to redraw the same characters.
  const ticking = style !== 'full' && style !== 'off';
  const interval = tickInterval(left);

  useEffect(() => {
    if (!to || !ticking) return;
    const timer = setInterval(() => setNow(new Date()), interval);
    return () => clearInterval(timer);
  }, [interval, to, ticking]);

  if (!to) return null;
  const said = endTime(to, now, style);
  return said ? <span>{said}</span> : null;
}

function Achievements({ slide }: { slide: Slide }) {
  const now = new Date();
  return (
    <ul className="space-y-4">
      {slide.achievements.map((achievement) => (
        <li key={achievement.id} className="wall-panel flex items-baseline gap-6 px-8 py-5">
          <p className="min-w-0 flex-1 truncate text-wall-3xl text-content">
            {/* **The accent colour's job.** A brand has three colours and the
                third needs a reason to exist — this is it: the name of
                whoever just did something, in the company's own palette
                rather than a generic green. */}
            <span className="font-semibold text-accent">
              {achievement.about_name}
            </span>
            {' — '}
            {achievement.title}
          </p>
          {/* The number and when (7.9): "$500 · 2 minutes ago" says what
              happened and that it is news, where the name and the rule alone
              said neither. */}
          {achievement.figure && (
            <span className="shrink-0 text-wall-3xl font-semibold tabular-nums text-content">
              {achievement.figure}
            </span>
          )}
          {achievement.created_at && (
            <span className="shrink-0 text-wall-xl text-content-muted">
              {agoInWords(new Date(achievement.created_at), now)}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

/** Said in a corner, quietly: a held or reconnecting screen (Phase 26). */
function Corner({ paused, stale }: { paused: boolean; stale: boolean }) {
  if (!paused && !stale) return null;
  return (
    <p className="absolute bottom-4 left-6 z-10 rounded-full bg-black/50 px-4 py-1 text-wall-base text-white/90">
      {stale ? 'Reconnecting…' : 'Paused'}
    </p>
  );
}

/**
 * **A picture, a GIF or a video, filling the TV** (Phase 26). It takes the
 * background's place: nothing is drawn under it and nothing over it.
 *
 * A picture fills the screen, cropping what doesn't fit (`cover`), or shows
 * all of itself (`contain`) over a blurred copy of itself rather than black
 * bars. A video starts where it was told to and plays with sound, by the
 * wall's rules — quiet while a celebration has the screen.
 */
function FullScreenMedia({
  slide,
  imageUrl,
  paused,
  stale,
}: {
  slide: Slide;
  imageUrl: ImageUrl;
  paused: boolean;
  stale: boolean;
}) {
  const source = slide.media_digest ? imageUrl(slide.media_digest) : (slide.url ?? '');
  return (
    <div className="absolute inset-0 overflow-hidden bg-black">
      {slide.kind === 'image' && source && (
        <>
          {slide.fit === 'contain' && (
            <img
              src={source}
              alt=""
              aria-hidden="true"
              className="absolute inset-0 size-full scale-110 object-cover opacity-50 blur-2xl"
            />
          )}
          <img
            src={source}
            alt=""
            className={`absolute inset-0 size-full ${slide.fit === 'contain' ? 'object-contain' : 'object-cover'}`}
          />
        </>
      )}
      {slide.kind === 'video' && slide.media_kind === 'youtube' && <FullScreenYouTube slide={slide} />}
      {slide.kind === 'video' && slide.media_kind === 'video' && source && (
        <FullScreenVideo src={source} start={slide.media_start_seconds ?? 0} />
      )}
      <Corner paused={paused} stale={stale} />
    </div>
  );
}

function FullScreenYouTube({ slide }: { slide: Slide }) {
  const { onWall, previewSound, celebrating, report } = useWallSound();
  const id = slide.url ? youtubeIdFromLink(slide.url) : null;
  if (!id) return null;
  return (
    // Filling the screen whatever its shape: cropped, never letterboxed.
    <div className="absolute inset-0 overflow-hidden [container-type:size]">
      <YouTubePlayer
        videoId={id}
        // Where it was told to start, or else where the link was copied at.
        start={slide.media_start_seconds ?? startFromLink(slide.url ?? '')}
        // With sound on a wall and in the screen editor's preview; quiet in a
      // list of slides, where several would play at once.
      sound={onWall || Boolean(previewSound)}
      hush={celebrating}
        onTrouble={(next) => {
          if (next === 'muted') report(false);
          else if (next === null) report(true);
        }}
        className="pointer-events-none absolute left-1/2 top-1/2 h-[max(100cqh,56.25cqw)] w-[max(100cqw,177.78cqh)] -translate-x-1/2 -translate-y-1/2 border-0"
      />
    </div>
  );
}

/** An uploaded video, filling the screen from its start, with sound. */
function FullScreenVideo({ src, start }: { src: string; start: number }) {
  const { onWall, allowed, celebrating, report, previewSound } = useWallSound();
  const element = useRef<HTMLVideoElement | null>(null);
  const startAt = useRef(start);
  const wantSound = (onWall && allowed === true && !celebrating) || Boolean(previewSound);

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
    video.muted = !wantSound;
    if (wantSound) {
      void video.play?.()?.catch(() => {
        // The browser said no after all: muted, rather than stopped.
        video.muted = true;
        report(false);
        void video.play?.()?.catch(() => {});
      });
    }
  }, [wantSound, report]);

  return (
    <video ref={element} src={src} autoPlay muted loop playsInline className="absolute inset-0 size-full object-cover" />
  );
}

/** The headline as large as fits, then smaller only as far as it must. */
const HEADLINE_SIZES = [
  'text-[11em]',
  'text-[9em]',
  'text-[7.5em]',
  'text-wall-8xl',
  'text-wall-7xl',
  'text-wall-6xl',
  'text-wall-5xl',
];
const MORE_SIZES = ['text-wall-5xl', 'text-wall-4xl', 'text-wall-3xl', 'text-wall-2xl'];

/**
 * **A message: its words, massive, in the middle of the screen** (Phase 26),
 * over the screen's background. The headline is drawn as large as it fits and
 * steps down only as far as it has to; anything more sits under it, smaller.
 */
function MessageScreen({
  slide,
  imageUrl,
  paused,
  stale,
}: {
  slide: Slide;
  imageUrl: ImageUrl;
  paused: boolean;
  stale: boolean;
}) {
  const headline = useFittedSize<HTMLParagraphElement>(HEADLINE_SIZES, slide.title);
  const more = useFittedSize<HTMLParagraphElement>(MORE_SIZES, slide.body ?? '');
  return (
    <div className="flex h-full w-full flex-col items-center justify-center gap-[3%] px-[4%] py-[4%] text-center [text-shadow:0_2px_16px_rgb(0_0_0/0.5)]">
      <WallBackground background={slide.appearance?.background} imageUrl={imageUrl} />
      <div className={`flex min-h-0 w-full items-center justify-center ${slide.body ? 'flex-[3]' : 'flex-1'}`}>
        <p
          ref={headline.ref}
          // Room above and below for the letters themselves: with lines this
          // tight, descenders spill past the box, and the fitter would read
          // that as "doesn't fit" at every size and draw it at the smallest.
          className={`max-h-full w-full overflow-hidden break-words py-[0.1em] font-bold leading-[1.1] tracking-tight text-content ${headline.size}`}
        >
          {slide.title}
        </p>
      </div>
      {slide.body && (
        <div className="flex min-h-0 w-full flex-1 items-start justify-center">
          <p
            ref={more.ref}
            className={`max-h-full w-full overflow-hidden break-words leading-snug text-content-muted ${more.size}`}
          >
            {slide.body}
          </p>
        </div>
      )}
      <Corner paused={paused} stale={stale} />
    </div>
  );
}
