import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';

import { api, ApiError } from '../api';
import { applyAppearance, type Appearance } from '../appearance';
import CelebrationTakeover from '../components/CelebrationTakeover';
import WallScreen from '../components/wall/WallScreen';
import WallStage from '../components/wall/WallStage';
import { WallRotation, type Rotation } from '../components/wall/paging';
import { tokenImageUrl, type Channel } from '../components/wall/types';
import { reportSound, soundAllowedNow, WallSoundContext, type WallSound } from '../components/wall/sound';
import SoundBadge from '../components/wall/SoundBadge';
import { useSiteIcon } from '../siteIcon';
import {
  bestOffset,
  nextPollIn,
  positionAt,
  remember,
  sample,
  type Sample,
} from './wallClock';
import PairingCode from '../components/PairingCode';
import QuietScreen from '../components/wall/QuietScreen';

/**
 * A wall screen.
 *
 * Runs unattended for months on a TV nobody can reach, which changes what the
 * page has to do:
 *
 *   * Never show an error to a room. A failed poll keeps the last good data on
 *     screen rather than replacing a leaderboard with a stack trace.
 *   * Survive the network going away and coming back, without anyone pressing
 *     anything.
 *   * Be readable from across a room — large type, high contrast, no chrome.
 *   * Rotate on its own, because nobody is going to click.
 */
export default function DisplayFeed() {
  const { token } = useParams();
  const [channel, setChannel] = useState<Channel | null>(null);
  const [slideIndex, setSlideIndex] = useState(0);
  //: When the showing slide began and how long it runs, on the shared clock —
  //: so a board with more rows than fit turns its pages in step on every
  //: screen. See `usePages`.
  const [slideWindow, setSlideWindow] = useState<{ start: number; length: number } | null>(
    null,
  );
  const [dead, setDead] = useState(false);
  //: The server's reason for refusing this screen where it is — the channel
  //: is limited to a network this screen is not on. Null when allowed.
  const [refusal, setRefusal] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  //: Somebody is standing at the screen, holding it on one slide.
  const [paused, setPaused] = useState(false);
  // **Sound** (Phase 24, `wall/sound.ts`): whether this tab may play it —
  // asked of the browser as the channel opens, then told by every player —
  // and a celebration on the screen, which everything else goes quiet for.
  const [celebrating, setCelebrating] = useState(false);
  const [soundAllowed, setSoundAllowed] = useState<boolean | null>(null);
  const report = useCallback(
    (allowed: boolean) => {
      setSoundAllowed(allowed);
      reportSound(token ?? '', allowed);
    },
    [token],
  );
  useEffect(() => {
    const now = soundAllowedNow();
    if (now !== null) report(now);
    // No prompt on the screen (asked for): a press that happens anyway, from
    // a remote or a keyboard, simply lets sound play from then on.
    const pressed = () => report(true);
    window.addEventListener('pointerdown', pressed, { once: true });
    window.addEventListener('keydown', pressed, { once: true });
    return () => {
      window.removeEventListener('pointerdown', pressed);
      window.removeEventListener('keydown', pressed);
    };
  }, [report]);

  //: The reload marker this screen started with. Undefined until the first
  //: answer arrives, so the first poll never counts as a change.
  const reloadSeen = useRef<string | null | undefined>(undefined);

  //: Recent readings of how far this screen's clock is from the server's.
  //: See `wallClock.ts` — every screen on a channel rotates by the server's
  //: time, which is what keeps them in step.
  const samples = useRef<Sample[]>([]);
  //: The shared clock. Stable, so the components reading it do not re-arm
  //: their timers every render.
  const clock = useCallback(() => Date.now() + bestOffset(samples.current), []);

  // **Refused is not the same as unreachable.** A 404 means revoked or wrong —
  // permanent, and worth saying, because a screen showing a frozen board
  // forever is worse than one saying it has been disconnected. A 403 means
  // this network is not allowed to show the channel, so the last good data
  // comes off the screen too; it keeps asking, because a network can be
  // allowed again. Heard from whichever feed hears first — see
  // `CelebrationTakeover`.
  const refuse = useCallback((e: ApiError) => {
    if (e.status === 404) setDead(true);
    else setRefusal(e.message);
  }, []);

  const load = useCallback(async () => {
    try {
      const sentAt = Date.now();
      const next = await api<Channel>(`/api/display/${token}`);
      if (next.server_time) {
        samples.current = remember(
          samples.current,
          sample(next.server_time, sentAt, Date.now()),
        );
      }

      // **Asked to reload, from three rooms away.** A browser open since a
      // deploy three weeks ago is running the old bundle; one that has wedged
      // shows a frozen board. Both are on a wall somebody would otherwise
      // need a ladder to reach.
      if (reloadSeen.current === undefined) {
        reloadSeen.current = next.reload_at ?? null;
      } else if ((next.reload_at ?? null) !== reloadSeen.current) {
        window.location.reload();
        return;
      }
      setChannel(next);
      setStale(false);
      setDead(false);
      setRefusal(null);
    } catch (e) {
      if (e instanceof ApiError && (e.status === 404 || e.status === 403)) {
        refuse(e);
      } else {
        // Anything else is probably the network. Keep showing the last good
        // data and mark it stale; a leaderboard from ten minutes ago is far
        // more useful to a room than an error message.
        setStale(true);
      }
    }
  }, [token, refuse]);

  useEffect(() => {
    void load();
  }, [load]);

  // Poll — **on the shared boundary, not on a private interval.** Every
  // screen on the channel asks on the minute (the interval comes from the
  // server), so a slide added or removed reaches them all together instead of
  // one screen rotating through a different list from the one beside it for
  // up to a minute. A few random milliseconds on top keep forty screens from
  // arriving at the server in the same instant.
  const refreshSeconds = channel?.refresh_seconds ?? 60;
  useEffect(() => {
    if (dead) return;
    let timer: number | undefined;
    const schedule = () => {
      const wait = nextPollIn(clock(), refreshSeconds, Math.random() * 2_000);
      timer = window.setTimeout(async () => {
        await load();
        schedule();
      }, wait);
    };
    schedule();
    return () => window.clearTimeout(timer);
  }, [load, refreshSeconds, dead, clock]);

  // Rotate — **by the shared clock, never by counting.**
  //
  // Every screen works out which slide should be showing from the server's
  // time and the slides' dwells, so two tabs, or twenty televisions, land on
  // the same slide at the same moment however long each has been running.
  // Counting from page load is what put them out of step before.
  //
  // It re-reads the position at each boundary rather than adding one, so a
  // screen that was slow for a moment — a heavy slide, a busy stick — catches
  // up instead of carrying the delay forward.
  //
  // **A celebration no longer holds it.** It used to, and that was the other
  // half of the drift: each screen paused its own count for however long its
  // own celebration lasted. The rotation now carries on underneath, the same
  // on every screen, and the celebration itself starts at the same instant
  // everywhere — see `CelebrationTakeover`.
  const slideCount = channel?.slides.length ?? 0;
  const dwells = channel?.slides.map((s) => s.dwell_seconds) ?? [];
  const dwellKey = dwells.join(',');
  const current = channel?.slides[slideIndex % Math.max(slideCount, 1)];
  useEffect(() => {
    if (slideCount === 0) return;
    // Somebody standing at the screen with it paused — see the keyboard
    // controls below. Letting go of it puts it straight back in step.
    if (paused) return;
    let timer: number | undefined;
    const tick = () => {
      const position = positionAt(dwellKey.split(',').map(Number), clock());
      if (!position) return;
      setSlideIndex(position.index);
      setSlideWindow({
        start: clock() - (position.length - position.remaining),
        length: position.length,
      });
      // On the boundary exactly. Firing a hair early finds the same slide
      // with a millisecond left and arms again, so every screen changes on
      // the real instant rather than on one padded to be safe.
      timer = window.setTimeout(tick, position.remaining);
    };
    tick();
    return () => window.clearTimeout(timer);
  }, [slideCount, dwellKey, paused, clock]);

  // **Keys, for the person standing in front of it.**
  //
  // A wall runs unattended for months and then, twice a year, somebody is at
  // it with a keyboard: setting it up, showing it to a visitor, or trying to
  // read the board that just went past. Every one of those is "hold this" or
  // "go back one", and both are impossible on a screen that only moves on its
  // own.
  //
  // Deliberately not documented on the screen. A wall with a legend of
  // shortcuts along the bottom is a wall with a legend of shortcuts along the
  // bottom, for ever, read by four hundred people who will never press one.
  useEffect(() => {
    if (slideCount === 0) return;

    function onKey(event: KeyboardEvent) {
      switch (event.key) {
        case ' ':
        case 'k':
          // Space scrolls a page by default, and a wall has nothing to
          // scroll — but the browser does not know that.
          event.preventDefault();
          setPaused((was) => !was);
          break;
        case 'ArrowRight':
        case 'n':
          // Moving by hand pauses too. Somebody stepping forward wants to
          // look at what they landed on, not watch it leave.
          setPaused(true);
          setSlideIndex((i) => (i + 1) % slideCount);
          break;
        case 'ArrowLeft':
        case 'p':
          setPaused(true);
          setSlideIndex((i) => (i - 1 + slideCount) % slideCount);
          break;
        case 'f':
          // Toggled rather than requested: pressing it twice should put the
          // screen back, and a television left fullscreen by accident is a
          // thing somebody has to find the remote for.
          if (document.fullscreenElement) void document.exitFullscreen();
          else void document.documentElement.requestFullscreen().catch(() => {});
          break;
        default:
          break;
      }
    }

    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [slideCount]);

  // A screen being removed while the wall is on a later slide would otherwise
  // leave the index past the end.
  const slide = current;
  const background = slide?.appearance?.background;
  // A video screen — YouTube or uploaded — has its own sound (Phase 26).
  const screenSound = slide?.kind === 'video' && Boolean(slide?.url);
  const backgroundSound =
    Boolean(background?.asset) && (background?.kind === 'youtube' || background?.kind === 'video');
  const wallSound: WallSound = {
    onWall: true,
    allowed: soundAllowed,
    celebrating,
    screenSound,
    report,
  };
  // The tab's icon is the organization's logo here too, if it has one.
  const logo = slide?.appearance?.logo ?? null;
  useSiteIcon(logo ? tokenImageUrl(token ?? '')(logo) : null);

  const rotation = useMemo<Rotation | null>(
    () =>
      slideWindow && { now: clock, start: slideWindow.start, length: slideWindow.length, paused },
    [slideWindow, clock, paused],
  );

  // **The wall paints itself in the organization's own appearance.**
  //
  // It did not, for a while: `applyAppearance` was called by the app shell and
  // by the preview, and never here — so an admin chose a brand colour, watched
  // the preview turn green, and the television stayed indigo. The preview and
  // the wall disagreeing is precisely the failure the shared renderer exists
  // to prevent, and sharing a renderer does nothing if one caller never
  // applies the theme.
  //
  // Per slide, not per channel: the server has already merged organization,
  // item, channel and screen for each one, and two slides in one rotation can
  // legitimately differ.
  const wall = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (wall.current && slide?.appearance) {
      applyAppearance(slide.appearance as Appearance, wall.current);
    }
  }, [slide?.appearance]);

  // **Disconnected, and offering a way back** (6.1). It used to say "Ask an
  // administrator for a new display link" — which meant somebody with a
  // ladder and a keyboard. Now it shows a pairing code, an admin connects it
  // again from their desk, and the screen loads its new link by itself: a
  // full load rather than a route change, so it starts clean and on the
  // newest build.
  if (dead) {
    return (
      <PairingCode
        heading="This screen was disconnected. To connect it again"
        previousToken={token}
        onPaired={(url) => window.location.replace(url)}
      />
    );
  }

  if (refusal) {
    return (
      <Screen>
        <p className="text-4xl text-content-muted">Not allowed on this network</p>
        <p className="mt-4 max-w-3xl text-xl text-content-subtle">{refusal}</p>
      </Screen>
    );
  }

  if (!channel) {
    return (
      <Screen>
        <p className="text-3xl text-content-subtle">Connecting…</p>
      </Screen>
    );
  }

  if (!slide && !channel.quiet) {
    return (
      <Screen>
        <p className="text-4xl text-content">{channel.channel_name}</p>
        <p className="mt-4 text-2xl text-content-subtle">
          Nothing on this channel yet.
        </p>
      </Screen>
    );
  }

  return (
    <Screen innerRef={wall}>
      {/* Outside the rotation, over the top of it. A wall is opened once and left
          running, so the click that opened it is what lets a clip play with
          sound — see the note in the component. */}
      <CelebrationTakeover token={token ?? ''} now={clock} onRefused={refuse} onBusy={setCelebrating} />
      {/* A speaker in the corner while something with sound is on: crossed
          out while the browser holds sound back. Never a prompt. */}
      <SoundBadge allowed={soundAllowed} sounding={celebrating || screenSound || backgroundSound} />

      {/* **Night mode, or nothing scheduled now** (6.10). In the same tree as
          the rotation, so the celebration layer above stays mounted across
          the change and does not play anything twice. It still shows a
          preview sent from an editor after hours; the server holds back the
          real wins. */}
      {channel.quiet || !slide ? (
        <QuietScreen
          mode={channel.quiet?.mode ?? 'clock'}
          until={channel.quiet?.until ?? null}
          timeZone={channel.time_zone ?? 'UTC'}
          channelName={channel.channel_name}
          now={clock}
        />
      ) : (
        <WallRotation.Provider value={rotation}>
          <WallSoundContext.Provider value={wallSound}>
            <WallScreen
              slide={slide}
              channelName={channel.channel_name}
              stale={stale}
              paused={paused}
              imageUrl={tokenImageUrl(token ?? '')}
            />
          </WallSoundContext.Provider>
        </WallRotation.Provider>
      )}
    </Screen>
  );
}

function Screen({
  children,
  innerRef,
}: {
  children: React.ReactNode;
  innerRef?: React.Ref<HTMLDivElement>;
}) {
  // Outside the app shell entirely: no nav, no top bar, nothing to click. The
  // same 1920×1080 stage the editor's preview draws, scaled to this screen —
  // see `WallStage`.
  return (
    <WallStage fill="viewport" stageRef={innerRef}>
      {children}
    </WallStage>
  );
}
