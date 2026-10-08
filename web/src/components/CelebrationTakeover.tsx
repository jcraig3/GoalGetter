import { useEffect, useLayoutEffect, useRef, useState } from 'react';

import { api, ApiError } from '../api';
import {
  nextChangeIn,
  playingAt,
  secondsIn,
  type Celebration,
} from '../pages/celebrationQueue';
import AnnouncementScreen from './AnnouncementScreen';
import { tokenImageUrl } from './wall/types';
import { reportSound } from './wall/sound';
import { applyAppearance, type Appearance } from '../appearance';
import WallScreen from './wall/WallScreen';
import type { Slide } from './wall/types';

interface Feed {
  celebrations: Celebration[];
  cooldown_seconds: number;
  server_time?: number;
}

/**
 * How often to ask whether anything has just been won.
 *
 * **Shorter than the lead the server gives each win**, which is what lets
 * every screen on a channel start it at the same instant: a screen has to have
 * heard about a win before the moment it is due to begin. See
 * `events.CELEBRATION_SYNC_LEAD_SECONDS`, which is five.
 */
const POLL_MS = 3_000;

/**
 * The moment, on a wall.
 *
 * Everything else on a display is the steady state — boards, goals, a contest
 * ticking down. This is the exception that stops all of it, and it is the half of
 * the product that makes a wall more than a dashboard nobody looks at: closing a
 * deal produces something the room sees and hears, in the seconds after it
 * happened, rather than a row somebody might find later.
 *
 * **Every screen on the channel shows it at the same instant.** The server
 * gives each win the moment it takes over and the moment it lets go, and this
 * shows whichever the shared clock says is on — so three televisions in one
 * room celebrate together rather than one after another. A screen that joins
 * part-way through joins in step, with its clip at the same second as the
 * others.
 *
 * **Polled separately from the rotation**, and much more often. The channel feed
 * is heavy — every board, goal and competition on it — and rebuilding all of that
 * every few seconds to notice one win would be wasteful. Two endpoints means this
 * one can be cheap and frequent.
 *
 * **Sound plays here and nowhere else.** A walk-up song starting at somebody's
 * desk because they opened a laptop is a different and much less welcome thing —
 * see the note in `CelebrationOverlay`, which is the same moment for one person
 * and deliberately silent.
 */
export default function CelebrationTakeover({
  token,
  now = Date.now,
  onBusy,
  onRefused,
}: {
  token: string;
  /** The shared clock: the server's time, in ms. See `wallClock.ts`. */
  now?: () => number;
  /** Told when the screen is taken over and when it is let go. */
  onBusy?: (busy: boolean) => void;
  /**
   * Told when the server refuses this screen outright — revoked (404) or on
   * the wrong network (403) — as opposed to merely not answering.
   */
  onRefused?: (error: ApiError) => void;
}) {
  const [timetable, setTimetable] = useState<Celebration[]>([]);
  // **Said to the server whether this browser lets it play sound** (Phase 24),
  // only when that changes: nobody clicks a TV, so TVs & Channels is where a
  // muted one is found, with how to allow sound on it. See `wall/sound.ts`.
  const onSound = (allowed: boolean) => reportSound(token, allowed);
  // Bumped to re-read the timetable at the instant something changes.
  const [, setTick] = useState(0);

  // Ask what has just been won.
  //
  // Kept in a ref so a new callback from the parent does not restart the poll.
  const refused = useRef(onRefused);
  refused.current = onRefused;
  useEffect(() => {
    let alive = true;
    const poll = async () => {
      try {
        const next = await api<Feed>(`/api/display/${token}/celebrations`);
        if (alive) setTimetable(next.celebrations);
      } catch (e) {
        // **A refusal is passed up, because this is the quickest to hear it.**
        // It asks every three seconds and the channel only once a minute, so
        // a revoked screen used to play on for up to a minute and a half
        // while this one was being told no (QA-15).
        if (e instanceof ApiError && (e.status === 404 || e.status === 403)) {
          if (alive) refused.current?.(e);
        }
        // Anything else: a wall that cannot reach the API keeps rotating.
        // Missing a celebration is a smaller failure than a screen full of
        // error text.
      }
    };
    void poll();
    const timer = setInterval(() => void poll(), POLL_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [token]);

  const at = now();
  const showing = playingAt(timetable, at);

  // **Sleep until the next start or end**, rather than checking on a tick —
  // so a win begins on the instant the server gave it, which is the instant
  // every other screen begins it too.
  //
  // This effect owns the only timer that ends a celebration, and it re-arms
  // whenever the timetable or the current celebration changes. That matters:
  // an earlier version kept the dismiss timer in an effect whose own state it
  // changed, so React's cleanup cancelled it a moment later and every
  // celebration stayed on the wall until the page was reloaded.
  useEffect(() => {
    const wait = nextChangeIn(timetable, now());
    if (wait === null) return;
    // On the edge exactly. If a browser fires a hair early, the re-read finds
    // the edge a millisecond away and simply arms again — so the answer is
    // always the one for the real instant, never one padded to be safe.
    const timer = setTimeout(() => setTick((n) => n + 1), wait);
    return () => clearTimeout(timer);
  }, [timetable, showing?.id, now]);

  const busy = Boolean(showing);
  useEffect(() => {
    onBusy?.(busy);
  }, [busy, onBusy]);

  if (!showing) return null;

  if (showing.slide) {
    return <SlidePreview key={showing.id} slide={showing.slide} token={token} />;
  }

  return (
    <AnnouncementScreen
      key={showing.id}
      celebration={showing}
      joinedAt={secondsIn(showing, at)}
      fileUrl={tokenImageUrl(token)}
      footer={showing.preview ? <PreviewMark /> : undefined}
      onSound={onSound}
    />
  );
}

/**
 * "Preview", on the screen itself. Somebody sent this from an editor to see
 * how it looks here; the rest of the room should not take it for news (5j).
 */
function PreviewMark() {
  return (
    <span className="mt-8 inline-block rounded bg-black/60 px-4 py-1.5 text-wall-xl uppercase tracking-widest text-white">
      Preview
    </span>
  );
}

/**
 * An unsaved slide, over the rotation for its thirty seconds.
 *
 * Inside the same scaled stage as the rotation, so it is drawn at the wall's
 * own 1920×1080 like every other slide, and painted in its own appearance —
 * which the server resolved for the channel it was built for.
 */
function SlidePreview({ slide, token }: { slide: Slide; token: string }) {
  const box = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    if (box.current && slide.appearance) {
      applyAppearance(slide.appearance as Appearance, box.current);
    }
  }, [slide.appearance]);

  return (
    // The stage's own frame (`WallStage`), so the slide sits exactly where a
    // slide in the rotation does.
    <div
      ref={box}
      className="wall fixed inset-0 z-50 isolate flex flex-col items-center justify-center overflow-hidden bg-bg px-10 py-8"
      aria-hidden="true"
    >
      <WallScreen slide={slide} channelName="" imageUrl={tokenImageUrl(token)} />
      <div className="absolute bottom-8 left-1/2 -translate-x-1/2">
        <PreviewMark />
      </div>
    </div>
  );
}
