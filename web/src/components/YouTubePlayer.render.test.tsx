// @vitest-environment jsdom
/** A YouTube video that plays by itself, from the right moment (Phase 24). */
import { act, render } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import YouTubePlayer, { troubleWords, youtubeIdFromLink, type YouTubeTrouble } from './YouTubePlayer';

const YOUTUBE = 'https://www.youtube.com';

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

function show(props: Partial<Parameters<typeof YouTubePlayer>[0]> = {}) {
  const troubles: (YouTubeTrouble | null)[] = [];
  const { container } = render(
    <YouTubePlayer videoId="dQw4w9WgXcQ" onTrouble={(t) => troubles.push(t)} {...props} />,
  );
  const frame = container.querySelector('iframe')!;
  const sent: { event: string; func?: string }[] = [];
  vi.spyOn(frame.contentWindow!, 'postMessage').mockImplementation((message: unknown) => {
    sent.push(JSON.parse(String(message)));
  });
  /** A message as the YouTube player sends it. */
  const say = (data: object, origin = YOUTUBE) =>
    act(() => {
      window.dispatchEvent(
        new MessageEvent('message', { data: JSON.stringify(data), origin, source: frame.contentWindow }),
      );
    });
  const commands = () => sent.filter((m) => m.event === 'command').map((m) => m.func);
  return { frame, say, commands, troubles, sent };
}

test('YouTube’s normal player, so a signed-in browser is used, from the set moment', () => {
  const { frame } = show({ start: 43.6, end: 60 });
  const src = new URL(frame.src);
  expect(src.origin).toBe(YOUTUBE);
  expect(src.pathname).toBe('/embed/dQw4w9WgXcQ');
  expect(src.searchParams.get('autoplay')).toBe('1');
  expect(src.searchParams.get('start')).toBe('43');
  expect(src.searchParams.get('end')).toBe('60');
  expect(src.searchParams.get('enablejsapi')).toBe('1');
  expect(src.searchParams.get('origin')).toBe(window.location.origin);
  expect(src.searchParams.get('mute')).toBe('0');
  expect(frame.getAttribute('allow')).toContain('autoplay');
});

test('it asks the player to report, until it answers', () => {
  const { sent, say } = show();
  act(() => vi.advanceTimersByTime(600));
  expect(sent.filter((m) => m.event === 'listening').length).toBeGreaterThan(1);
  say({ event: 'onReady' });
  const asked = sent.length;
  act(() => vi.advanceTimersByTime(1000));
  expect(sent.filter((m) => m.event === 'listening').length).toBe(
    sent.slice(0, asked).filter((m) => m.event === 'listening').length,
  );
});

test('ready: told to play; started: nothing more to do', () => {
  const { say, commands, troubles } = show();
  say({ event: 'onReady' });
  expect(commands()).toEqual(['addEventListener', 'addEventListener', 'addEventListener', 'playVideo']);
  say({ event: 'infoDelivery', info: { playerState: 1 } });
  act(() => vi.advanceTimersByTime(10_000));
  expect(commands().filter((c) => c !== 'addEventListener')).toEqual(['playVideo']);
  expect(troubles).toEqual([null]);
});

test('sound held back by Chrome: it plays muted instead of waiting for a click', () => {
  const { say, commands, troubles } = show();
  say({ event: 'onReady' });
  act(() => vi.advanceTimersByTime(2600));
  expect(commands().filter((c) => c !== 'addEventListener')).toEqual(['playVideo', 'mute', 'playVideo']);
  expect(troubles).toEqual(['muted']);
  say({ event: 'onStateChange', info: 1 });
  // Said by the TV's corner speaker, not in words over the screen.
  expect(troubleWords('muted')).toBeNull();
});

test('YouTube saying autoplay was blocked goes straight to muted', () => {
  const { say, commands } = show();
  say({ event: 'onReady' });
  say({ event: 'onAutoplayBlocked' });
  expect(commands().filter((c) => c !== 'addEventListener')).toEqual(['playVideo', 'mute', 'playVideo']);
});

test('the first click anywhere turns the sound on', () => {
  const { say, commands, troubles } = show();
  say({ event: 'onReady' });
  act(() => vi.advanceTimersByTime(2600));
  say({ event: 'onStateChange', info: 1 });
  act(() => {
    window.dispatchEvent(new Event('pointerdown'));
  });
  expect(commands().slice(-2)).toEqual(['unMute', 'playVideo']);
  expect(troubles.at(-1)).toBeNull();
});

test('not starting even muted is YouTube asking for a sign-in', () => {
  const { say, troubles } = show();
  say({ event: 'onReady' });
  act(() => vi.advanceTimersByTime(2600 + 4100));
  expect(troubles.at(-1)).toBe('sign-in');
  expect(troubleWords('sign-in')).toMatch(/open youtube.com in it and sign in once/);
});

test('silent players start muted and never ask for a click', () => {
  const { frame, say, troubles } = show({ sound: false });
  expect(new URL(frame.src).searchParams.get('mute')).toBe('1');
  say({ event: 'onReady' });
  say({ event: 'onStateChange', info: 1 });
  act(() => vi.advanceTimersByTime(10_000));
  expect(troubles).toEqual([null]);
});

test('a video that only plays on YouTube says so', () => {
  const { say, troubles } = show();
  say({ event: 'onError', info: 150 });
  expect(troubles).toEqual(['not-embeddable']);
  expect(troubleWords('not-embeddable')).toMatch(/only be played on YouTube/);
});

test('messages from anywhere else are ignored', () => {
  const { say, commands } = show();
  say({ event: 'onReady' }, 'https://evil.example');
  expect(commands()).toEqual([]);
});

test('a looping background goes back to its start when it ends', () => {
  // Not a one-video playlist (Phase 28): YouTube often wouldn't play one.
  const { frame, say, sent } = show({ loop: true, sound: false, start: 40, loopStart: 40 });
  const src = new URL(frame.src);
  expect(src.searchParams.get('playlist')).toBeNull();
  say({ event: 'onStateChange', info: 0 });
  expect(sent).toContainEqual({ event: 'command', func: 'seekTo', args: [40, true] });
});

test.each([
  ['https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=43', 'dQw4w9WgXcQ'],
  ['https://youtu.be/dQw4w9WgXcQ?t=43', 'dQw4w9WgXcQ'],
  ['https://www.youtube.com/embed/dQw4w9WgXcQ?start=90', 'dQw4w9WgXcQ'],
  ['https://www.youtube.com/shorts/dQw4w9WgXcQ', 'dQw4w9WgXcQ'],
  ['https://example.com/nope', null],
])('the video in %s', (link, id) => {
  expect(youtubeIdFromLink(link)).toBe(id);
});


test('the player is never reloaded while it plays, however often the wall redraws (the flashing bug)', () => {
  const { container, rerender } = render(<YouTubePlayer videoId="dQw4w9WgXcQ" start={30} />);
  const frame = container.querySelector('iframe')!;
  const first = frame.src;
  // The wall redraws every few seconds, each time a little further in.
  for (const later of [33, 36, 39, 42]) rerender(<YouTubePlayer videoId="dQw4w9WgXcQ" start={later} />);
  expect(container.querySelector('iframe')).toBe(frame);
  expect(frame.src).toBe(first);
  expect(new URL(first).searchParams.get('start')).toBe('30');
});

test('buffering is not being blocked: it isn’t muted for a slow start', () => {
  const { say, commands } = show();
  say({ event: 'onReady' });
  act(() => vi.advanceTimersByTime(2000));
  say({ event: 'onStateChange', info: 3 });
  act(() => vi.advanceTimersByTime(2000));
  say({ event: 'onStateChange', info: 1 });
  act(() => vi.advanceTimersByTime(10_000));
  expect(commands()).not.toContain('mute');
});
