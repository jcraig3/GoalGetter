// @vitest-environment jsdom
/** A neutral announcement taking over the screens (Phase 25). */
import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import type { Celebration } from '../pages/celebrationQueue';
import AnnouncementScreen from './AnnouncementScreen';

const DIGEST = 'a'.repeat(64);
const SOUND = 'b'.repeat(64);

function announcement(overrides: Partial<Celebration> = {}): Celebration {
  return {
    id: 'announcement:1',
    title: 'Lunch is here',
    body: 'In the kitchen',
    about_name: null,
    media_url: null,
    media_kind: null,
    media_id: null,
    media_digest: null,
    media_start_seconds: null,
    media_end_seconds: null,
    hold_seconds: 15,
    created_at: '2026-10-08T12:00:00Z',
    starts_at: 0,
    ends_at: 15_000,
    occasion: '',
    event_key: 'announcement',
    background: null,
    sound_digest: null,
    ...overrides,
  };
}

const fileUrl = (digest: string) => `/files/${digest}`;

function show(overrides: Partial<Celebration> = {}, quiet = false) {
  return render(<AnnouncementScreen celebration={announcement(overrides)} fileUrl={fileUrl} quiet={quiet} />);
}

function commandsTo(frame: HTMLIFrameElement) {
  const sent: string[] = [];
  vi.spyOn(frame.contentWindow!, 'postMessage').mockImplementation((message: unknown) => {
    const data = JSON.parse(String(message));
    if (data.event === 'command') sent.push(data.func);
  });
  return sent;
}

beforeEach(() => {
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
});

afterEach(() => vi.restoreAllMocks());

test('the words, with no "Goal hit" above them', () => {
  show();
  expect(screen.getByText('Lunch is here')).toBeTruthy();
  expect(screen.getByText('In the kitchen')).toBeTruthy();
  expect(screen.queryByText(/Recognition|Goal hit|Celebration/)).toBeNull();
});

test('a YouTube background fills the screen, the words on top and readable', () => {
  const { container } = show({ background: { kind: 'youtube', asset: 'dQw4w9WgXcQ' } as Celebration['background'] });
  const frame = container.querySelector('iframe')!;
  expect(new URL(frame.src).pathname).toBe('/embed/dQw4w9WgXcQ');
  expect(screen.getByText('Lunch is here').parentElement!.className).toContain('text-white');
});

test('a picture from the library in the middle', () => {
  const { container } = show({ media_kind: 'image', media_digest: DIGEST, media_url: `image:${DIGEST}` });
  expect(container.querySelector('img')!.getAttribute('src')).toBe(`/files/${DIGEST}`);
});

test('the sound effect first, then the video’s own sound', () => {
  const { container } = show({
    sound_digest: SOUND,
    media_kind: 'youtube',
    media_id: 'dQw4w9WgXcQ',
    media_url: 'https://youtu.be/dQw4w9WgXcQ',
  });
  const audio = container.querySelector('audio')!;
  expect(audio.getAttribute('src')).toBe(`/files/${SOUND}`);
  const frame = container.querySelector('iframe')!;
  // Waiting its turn: muted from the start, not a blip of sound.
  expect(new URL(frame.src).searchParams.get('mute')).toBe('1');
  const sent = commandsTo(frame);
  act(() => {
    audio.dispatchEvent(new Event('ended'));
  });
  expect(sent).toContain('unMute');
});

test('with no effect, the video speaks from the start', () => {
  const { container } = show({ media_kind: 'youtube', media_id: 'dQw4w9WgXcQ', media_url: 'https://youtu.be/dQw4w9WgXcQ' });
  expect(container.querySelector('audio')).toBeNull();
  expect(new URL(container.querySelector('iframe')!.src).searchParams.get('mute')).toBe('0');
});

test('one sound at a time: with a video in the middle, the background stays quiet', () => {
  const { container } = show({
    background: { kind: 'youtube', asset: 'bgVideo1234' } as Celebration['background'],
    media_kind: 'youtube',
    media_id: 'dQw4w9WgXcQ',
    media_url: 'https://youtu.be/dQw4w9WgXcQ',
  });
  const frames = [...container.querySelectorAll('iframe')];
  const background = frames.find((f) => f.src.includes('bgVideo1234'))!;
  const middle = frames.find((f) => f.src.includes('dQw4w9WgXcQ'))!;
  expect(new URL(background.src).searchParams.get('mute')).toBe('1');
  expect(new URL(middle.src).searchParams.get('mute')).toBe('0');
});

test('quiet, for the editor: no effect, nothing speaks', () => {
  const { container } = show(
    { sound_digest: SOUND, media_kind: 'youtube', media_id: 'dQw4w9WgXcQ', media_url: 'https://youtu.be/dQw4w9WgXcQ' },
    true,
  );
  expect(container.querySelector('audio')).toBeNull();
  expect(new URL(container.querySelector('iframe')!.src).searchParams.get('mute')).toBe('1');
});

test('a win is drawn as before', () => {
  show({ event_key: 'recognition', occasion: 'Recognition', about_name: 'Peter Parker' });
  expect(screen.getByText('Recognition')).toBeTruthy();
});
