// @vitest-environment jsdom
/** Sound on a TV: everything with sound plays it, one at a time (Phase 24). */
import { act, render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import type { Background } from '../../appearance';
import { DEFAULT_ICON, setSiteIcon } from '../../siteIcon';
import YouTubePlayer from '../YouTubePlayer';
import SoundBadge from './SoundBadge';
import { WallSoundContext, type WallSound } from './sound';
import WallBackground from './WallBackground';

const WALL: WallSound = { onWall: true, allowed: true, celebrating: false, screenSound: false, report: () => {} };

function commandsTo(frame: HTMLIFrameElement) {
  const sent: string[] = [];
  vi.spyOn(frame.contentWindow!, 'postMessage').mockImplementation((message: unknown) => {
    const data = JSON.parse(String(message));
    if (data.event === 'command') sent.push(data.func);
  });
  return sent;
}

afterEach(() => vi.restoreAllMocks());

test('a playing video goes quiet for a celebration, and comes back after', () => {
  const { container, rerender } = render(<YouTubePlayer videoId="dQw4w9WgXcQ" />);
  const sent = commandsTo(container.querySelector('iframe')!);
  rerender(<YouTubePlayer videoId="dQw4w9WgXcQ" hush />);
  rerender(<YouTubePlayer videoId="dQw4w9WgXcQ" hush={false} />);
  // Sound back, and told to play: a browser that pauses rather than let it
  // make sound is caught and it plays muted instead.
  expect(sent).toEqual(['mute', 'unMute', 'playVideo']);
});

function background(kind: Background['kind'], wall: Partial<WallSound> = {}) {
  return render(
    <WallSoundContext.Provider value={{ ...WALL, ...wall }}>
      <WallBackground background={{ kind, asset: 'dQw4w9WgXcQ' } as Background} imageUrl={(d) => `/x/${d}`} />
    </WallSoundContext.Provider>,
  );
}

test('a YouTube background on a wall plays with sound', () => {
  const { container } = background('youtube');
  expect(new URL(container.querySelector('iframe')!.src).searchParams.get('mute')).toBe('0');
});

test('in an editor’s preview, a background stays quiet', () => {
  const { container } = render(
    <WallBackground background={{ kind: 'youtube', asset: 'dQw4w9WgXcQ' } as Background} />,
  );
  expect(new URL(container.querySelector('iframe')!.src).searchParams.get('mute')).toBe('1');
});

test('an uploaded video background has sound when nothing else has the floor', () => {
  const play = vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined);
  const { container, rerender } = background('video');
  const video = container.querySelector('video')!;
  expect(video.muted).toBe(false);
  // A YouTube screen comes up with its own sound: the background goes quiet.
  rerender(
    <WallSoundContext.Provider value={{ ...WALL, screenSound: true }}>
      <WallBackground background={{ kind: 'video', asset: 'dQw4w9WgXcQ' } as Background} imageUrl={(d) => `/x/${d}`} />
    </WallSoundContext.Provider>,
  );
  expect(video.muted).toBe(true);
  play.mockRestore();
});

test('while the browser holds sound back, an uploaded background plays muted', () => {
  const { container } = background('video', { allowed: false });
  expect(container.querySelector('video')!.muted).toBe(true);
});

test('the corner speaker: on, crossed out, or nothing — never a prompt', () => {
  const { rerender } = render(<SoundBadge allowed sounding />);
  expect(screen.getByRole('status', { name: 'Sound on' })).toBeTruthy();
  rerender(<SoundBadge allowed={false} sounding />);
  expect(screen.getByRole('status', { name: 'Sound off' })).toBeTruthy();
  expect(screen.queryByText(/click|press/i)).toBeNull();
  rerender(<SoundBadge allowed sounding={false} />);
  expect(screen.queryByRole('status')).toBeNull();
});

test('the tab’s icon: the logo when there is one, the Goals target otherwise', () => {
  act(() => setSiteIcon('/api/images/logo123'));
  const link = document.querySelector<HTMLLinkElement>('link[rel="icon"]')!;
  expect(link.getAttribute('href')).toBe('/api/images/logo123');
  act(() => setSiteIcon(null));
  expect(link.getAttribute('href')).toBe(DEFAULT_ICON);
  expect(link.type).toBe('image/svg+xml');
});
