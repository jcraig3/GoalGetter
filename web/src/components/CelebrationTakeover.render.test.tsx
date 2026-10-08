// @vitest-environment jsdom
/**
 * A win taking over a wall — at the time the server gave it, and letting go.
 *
 * Two properties have a history here. **Letting go** was broken once: the
 * component cancelled its own dismiss timer a millisecond after setting it, and
 * every celebration stayed on the wall until the page was reloaded. And since
 * 4k, **starting on time**: every screen on a channel shows a win at the
 * instant the server scheduled it, so a room with three screens celebrates
 * together rather than one after another.
 *
 * The clock is faked, and the timetable is built from it, so each test says
 * exactly when a win is due relative to "now".
 */
import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import CelebrationTakeover from './CelebrationTakeover';
import { sampleSlide } from './wall/sample';

vi.mock('../api', () => ({ api: vi.fn(), ApiError: class extends Error {} }));

const { api } = await import('../api');

const T = new Date('2026-09-28T12:00:00Z').getTime();

function win(overrides: Record<string, unknown> = {}, startsIn = 0, hold = 10) {
  return {
    id: 'win:1',
    title: 'Peter Parker',
    body: 'closed a big one',
    about_name: 'Peter Parker',
    media_url: null,
    media_kind: null,
    media_id: null,
    media_digest: null,
    media_start_seconds: null,
    media_end_seconds: null,
    hold_seconds: hold,
    created_at: '2026-09-28T12:00:00Z',
    starts_at: T + startsIn,
    ends_at: T + startsIn + hold * 1000,
    ...overrides,
  };
}

function feed(...celebrations: unknown[]) {
  return { celebrations, cooldown_seconds: 5, server_time: T };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(T);
  vi.mocked(api).mockReset();
  vi.mocked(api).mockResolvedValue(feed(win()) as never);
});

afterEach(() => vi.useRealTimers());

/** Let the mocked fetch resolve and its effects settle. */
async function settle() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
}

async function wait(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

describe('CelebrationTakeover', () => {
  test('takes over the screen for a win that is on now', async () => {
    render(<CelebrationTakeover token="t" />);

    await settle();

    expect(screen.getByText('Peter Parker')).toBeDefined();
    expect(screen.getByText('closed a big one')).toBeDefined();
  });

  test('lets go of it after the hold', async () => {
    // **The regression this file was first written for.** A celebration that
    // never ends is a wall stuck on one person's name until somebody reloads
    // it — and nothing about it looks like an error.
    render(<CelebrationTakeover token="t" />);
    await settle();
    expect(screen.getByText('Peter Parker')).toBeDefined();

    await wait(10_000);

    expect(screen.queryByText('Peter Parker')).toBeNull();
  });

  test('waits for its start time rather than starting when it arrives', async () => {
    // **The 4k change.** The server gives every screen the same start time,
    // so a screen that heard early waits — and starts with the rest.
    vi.mocked(api).mockResolvedValue(feed(win({}, 4_000)) as never);
    render(<CelebrationTakeover token="t" />);
    await settle();

    expect(screen.queryByText('Peter Parker')).toBeNull();

    await wait(4_000);

    expect(screen.getByText('Peter Parker')).toBeDefined();
  });

  test('two screens on one channel show it at the same instant', async () => {
    // Whenever each one loaded, the same timetable and the same clock give
    // the same answer.
    vi.mocked(api).mockResolvedValue(feed(win({}, 3_000)) as never);
    render(<CelebrationTakeover token="a" />);
    await wait(1_700);
    render(<CelebrationTakeover token="b" />);
    await settle();

    expect(screen.queryAllByText('Peter Parker')).toHaveLength(0);

    await wait(1_300);

    expect(screen.queryAllByText('Peter Parker')).toHaveLength(2);
  });

  test('uses the shared clock, not the screen’s own', async () => {
    // A television's own clock is routinely seconds out. Handed a clock that
    // is five seconds ahead, the win is already on.
    vi.mocked(api).mockResolvedValue(feed(win({}, 5_000)) as never);
    render(<CelebrationTakeover token="t" now={() => Date.now() + 5_000} />);
    await settle();

    expect(screen.getByText('Peter Parker')).toBeDefined();
  });

  test('says when it is busy, and when it is not', async () => {
    const onBusy = vi.fn();
    render(<CelebrationTakeover token="t" onBusy={onBusy} />);
    await settle();

    expect(onBusy).toHaveBeenCalledWith(true);

    await wait(10_000);

    expect(onBusy).toHaveBeenLastCalledWith(false);
  });

  test('does not replay a win that has finished', async () => {
    // Since 4k this is true after a reload as well: a finished win is not on
    // the timetable any more, so there is nothing to replay.
    render(<CelebrationTakeover token="t" />);
    await settle();

    await wait(60_000);

    expect(screen.queryByText('Peter Parker')).toBeNull();
  });

  test('shows nothing when there is nothing to show', async () => {
    vi.mocked(api).mockResolvedValue(feed() as never);

    const { container } = render(<CelebrationTakeover token="t" />);
    await settle();

    expect(container.firstChild).toBeNull();
  });

  test('a wall that cannot reach the server keeps quiet rather than erroring', async () => {
    // Missing a celebration is a smaller failure than a screen full of error
    // text in front of an office.
    vi.mocked(api).mockRejectedValue(new Error('offline'));

    const { container } = render(<CelebrationTakeover token="t" />);
    await settle();

    expect(container.firstChild).toBeNull();
  });

  test('a longer clip holds the screen for longer', async () => {
    vi.mocked(api).mockResolvedValue(feed(win({}, 0, 15)) as never);
    render(<CelebrationTakeover token="t" />);
    await settle();

    await wait(11_000);
    expect(screen.getByText('Peter Parker')).toBeDefined();

    await wait(5_000);
    expect(screen.queryByText('Peter Parker')).toBeNull();
  });

  test('an uploaded walk-up clip plays, through the wall’s own URL', async () => {
    // **Broken until 4k**: an uploaded clip fell through to the image branch,
    // drew a broken picture and played no sound.
    vi.mocked(api).mockResolvedValue(
      feed(win({ media_url: 'asset:abc', media_kind: 'audio', media_digest: 'abc' })) as never,
    );
    const { container } = render(<CelebrationTakeover token="tok" />);
    await settle();

    const audio = container.querySelector('audio');
    expect(audio?.getAttribute('src')).toBe('/api/display/tok/assets/abc');
    expect(container.querySelector('img')).toBeNull();
  });

  test('a screen that joins part-way starts the clip where the others are', async () => {
    vi.mocked(api).mockResolvedValue(
      feed(win({ media_url: 'https://youtu.be/x', media_kind: 'youtube', media_id: 'dQw4w9WgXcQ',
                 media_start_seconds: 10 }, -4_000)) as never,
    );
    const { container } = render(<CelebrationTakeover token="t" />);
    await settle();

    const src = container.querySelector('iframe')?.getAttribute('src') ?? '';
    expect(new URL(src).searchParams.get('start')).toBe('14');
  });

  test('the YouTube player is never reloaded as the wall keeps polling (the flashing bug)', async () => {
    vi.mocked(api).mockResolvedValue(
      feed(win({ media_url: 'https://youtu.be/x', media_kind: 'youtube', media_id: 'dQw4w9WgXcQ',
                 media_start_seconds: 10 }, 0, 30)) as never,
    );
    const { container } = render(<CelebrationTakeover token="t" />);
    await settle();
    const frame = container.querySelector('iframe')!;
    const src = frame.getAttribute('src');
    // Four polls later, each a redraw a few seconds further in.
    await wait(12_000);
    expect(container.querySelector('iframe')).toBe(frame);
    expect(frame.getAttribute('src')).toBe(src);
  });

  test('an uploaded song starts once, and isn’t re-seeked on every poll', async () => {
    const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
    vi.mocked(api).mockResolvedValue(
      feed(win({ media_url: 'asset:abc', media_kind: 'audio', media_digest: 'abc', media_start_seconds: 10 }, 0, 30)) as never,
    );
    const { container } = render(<CelebrationTakeover token="t" />);
    await settle();
    container.querySelector('audio')!.dispatchEvent(new Event('loadedmetadata'));
    await wait(12_000);
    expect(play).toHaveBeenCalledTimes(1);
    play.mockRestore();
  });

  test('a TV says when its browser held the sound back, once (Phase 24)', async () => {
    const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockRejectedValueOnce(new Error('NotAllowedError'));
    vi.mocked(api).mockImplementation((async (path: string) =>
      path.endsWith('/sound')
        ? undefined
        : feed(win({ media_url: 'asset:abc', media_kind: 'audio', media_digest: 'abc' }, 0, 30))) as never);
    const { container } = render(<CelebrationTakeover token="t" />);
    await settle();
    container.querySelector('audio')!.dispatchEvent(new Event('loadedmetadata'));
    await wait(9_000);
    const reports = vi.mocked(api).mock.calls.filter(([path]) => String(path).endsWith('/sound'));
    expect(reports).toEqual([['/api/display/t/sound', { method: 'POST', body: JSON.stringify({ blocked: true }) }]]);
    play.mockRestore();
  });

  test('leads with what the announcement is for', async () => {
    // The first thing anybody across the room reads: why the music started.
    vi.mocked(api).mockResolvedValue(feed(win({ occasion: 'Recognition' })) as never);
    render(<CelebrationTakeover token="t" />);
    await settle();

    expect(screen.getByText('Recognition')).toBeDefined();
  });

  test('makes the figure the largest thing, and puts their face in the glow (7.9)', async () => {
    vi.mocked(api).mockResolvedValue(
      feed(
        win({
          occasion: 'Big deal',
          title: 'Big deal',
          figure: '$500',
          photo_digest: 'abc123',
          body: 'Peter just closed $500!',
        }),
      ) as never,
    );
    render(<CelebrationTakeover token="t" />);
    await settle();

    const figure = screen.getByTestId('celebration-figure');
    expect(figure.textContent).toBe('$500');
    expect(figure.className).toContain('text-[10rem]');
    // The name comes after the figure, and smaller than it.
    const name = screen.getByText('Peter Parker');
    expect(figure.compareDocumentPosition(name) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(name.className).toContain('text-6xl');
    // Through the wall's own token, like every other file it plays.
    const photo = screen.getByTestId('celebration-photo') as HTMLImageElement;
    expect(photo.getAttribute('src')).toContain('abc123');
  });

  test('a win with no number keeps the name as its largest line', async () => {
    render(<CelebrationTakeover token="t" />);
    await settle();

    expect(screen.queryByTestId('celebration-figure')).toBeNull();
    expect(screen.queryByTestId('celebration-photo')).toBeNull();
    expect(screen.getAllByText('Peter Parker')[0]!.className).toContain('text-8xl');
  });

  test('does not say an achievement’s name twice', async () => {
    // Its name is both the occasion and the title.
    vi.mocked(api).mockResolvedValue(
      feed(win({ occasion: 'Big deal', title: 'Big deal', about_name: 'Clark Kent' })) as never,
    );
    render(<CelebrationTakeover token="t" />);
    await settle();

    expect(screen.getAllByText('Big deal')).toHaveLength(1);
  });

  test('an uploaded music video fills the screen with the words over it', async () => {
    // **The look people asked for**, and only possible for a clip served from
    // this deployment: no adverts, and nothing forbidding text over it.
    vi.mocked(api).mockResolvedValue(
      feed(win({
        occasion: 'Recognition', media_url: 'video:abc', media_kind: 'video',
        media_digest: 'abc',
      })) as never,
    );
    const { container } = render(<CelebrationTakeover token="tok" />);
    await settle();

    const video = container.querySelector('video');
    expect(video?.getAttribute('src')).toBe('/api/display/tok/assets/abc');
    expect(video?.className).toContain('object-cover');
    expect(screen.getByText('Recognition')).toBeDefined();
  });

  test('a YouTube video has nothing laid over it', async () => {
    // **YouTube's embed rules forbid anything in front of its player**, so the
    // words sit in their own band beneath it rather than on top.
    vi.mocked(api).mockResolvedValue(
      feed(win({
        occasion: 'Goal hit', media_url: 'https://youtu.be/dQw4w9WgXcQ',
        media_kind: 'youtube', media_id: 'dQw4w9WgXcQ',
      })) as never,
    );
    const { container } = render(<CelebrationTakeover token="t" />);
    await settle();

    const iframe = container.querySelector('iframe')!;
    const words = screen.getByText('Goal hit');
    // Different parts of the layout, and neither positioned over the other.
    expect(iframe.parentElement?.contains(words)).toBe(false);
    expect(words.closest('.absolute')).toBeNull();
    expect(iframe.closest('.absolute')).toBeNull();
  });

  test('a video the browser will not play with sound plays without it', async () => {
    // Rather than leave a frozen first frame in front of the room.
    const play = vi
      .spyOn(HTMLMediaElement.prototype, 'play')
      .mockRejectedValueOnce(new Error('NotAllowedError'))
      .mockResolvedValue(undefined);
    Object.defineProperty(HTMLMediaElement.prototype, 'readyState', {
      configurable: true, get: () => 4,
    });
    vi.mocked(api).mockResolvedValue(
      feed(win({ media_url: 'video:abc', media_kind: 'video', media_digest: 'abc' })) as never,
    );
    const { container } = render(<CelebrationTakeover token="t" />);
    await settle();

    expect((container.querySelector('video') as HTMLVideoElement).muted).toBe(true);
    expect(play).toHaveBeenCalledTimes(2);
    play.mockRestore();
    delete (HTMLMediaElement.prototype as unknown as Record<string, unknown>).readyState;
  });

  test('a prize-wheel win spins, then says what it landed on', async () => {
    vi.mocked(api).mockResolvedValue(
      feed(win({ event_key: 'wheel.won', occasion: 'Prize wheel', title: 'Won Long lunch' })) as never,
    );
    const { container } = render(<CelebrationTakeover token="t" />);
    await settle();

    expect(container.querySelector('[data-spinning="true"]')).not.toBeNull();
    expect(screen.getByText('Prize wheel')).toBeDefined();
    expect(screen.getByText('Won Long lunch')).toBeDefined();
  });

  test('a screen that joins after the wheel has landed does not spin it again', async () => {
    // It shows the wheel standing still, in step with the rest of the room.
    vi.mocked(api).mockResolvedValue(
      feed(win({ event_key: 'wheel.won', occasion: 'Prize wheel' }, -5_000)) as never,
    );
    const { container } = render(<CelebrationTakeover token="t" />);
    await settle();

    expect(container.querySelector('[data-spinning="false"]')).not.toBeNull();
  });
});

describe('a preview sent from an editor (5j)', () => {
  test('an announcement is marked as a preview', async () => {
    vi.mocked(api).mockResolvedValue(feed(win({ id: 'preview:3', preview: true })) as never);
    render(<CelebrationTakeover token="t" />);

    await settle();

    expect(screen.getByText('Peter Parker')).toBeDefined();
    expect(screen.getByText('Preview')).toBeDefined();
  });

  test('a real win is not', async () => {
    render(<CelebrationTakeover token="t" />);

    await settle();

    expect(screen.queryByText('Preview')).toBeNull();
  });

  test('a previewed slide is drawn as the wall draws it, then lets go', async () => {
    const slide = { ...sampleSlide('leaderboard'), kind: 'message', title: 'Pizza at four', body: 'In the kitchen' };
    vi.mocked(api).mockResolvedValue(
      feed(win({ id: 'preview:4', preview: true, title: 'Pizza at four', slide }, 0, 30)) as never,
    );
    render(<CelebrationTakeover token="t" />);

    await settle();
    expect(screen.getByText('Pizza at four')).toBeDefined();
    expect(screen.getByText('In the kitchen')).toBeDefined();
    expect(screen.getByText('Preview')).toBeDefined();

    vi.mocked(api).mockResolvedValue(feed() as never);
    await wait(30_000);
    expect(screen.queryByText('Pizza at four')).toBeNull();
  });
});
