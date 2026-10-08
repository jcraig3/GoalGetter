// @vitest-environment jsdom
/**
 * The walk-up editor on somebody's profile.
 *
 * Three things a person would only discover at the wall: a music video goes to
 * the video checker (so an iPhone's HEVC is explained rather than called "not
 * an MP3"), the start box appears for the YouTube link being typed rather than
 * for the one last saved, and an uploaded clip's internal reference never sits
 * in the Link box waiting to be saved as a link.
 */
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import WalkupMedia, { startFromLink } from './WalkupMedia';

vi.mock('../api', () => ({ api: vi.fn(), ApiError: class extends Error {} }));
// An agent: the Assets picker is an admin's, and is tested below as one.
let role = 'agent';
vi.mock('../auth', () => ({ useAuth: () => ({ user: { org_role: role } }) }));

const { api } = await import('../api');

const NONE = { url: null, kind: null, start_seconds: null, end_seconds: null };

beforeEach(() => {
  vi.mocked(api).mockReset();
});

test('a music video is sent to the video check', async () => {
  vi.mocked(api).mockResolvedValue(NONE as never);
  const { container } = render(<WalkupMedia />);
  await screen.findByText('Walk-up media');

  const input = container.querySelector('input[type="file"]') as HTMLInputElement;
  await userEvent.upload(input, new File(['x'], 'song.mp4', { type: 'video/mp4' }));

  await waitFor(() =>
    expect(vi.mocked(api)).toHaveBeenCalledWith('/api/me/walkup/video', expect.anything()),
  );
});

test('a song is sent to the audio check', async () => {
  vi.mocked(api).mockResolvedValue(NONE as never);
  const { container } = render(<WalkupMedia />);
  await screen.findByText('Walk-up media');

  const input = container.querySelector('input[type="file"]') as HTMLInputElement;
  await userEvent.upload(input, new File(['x'], 'song.mp3', { type: 'audio/mpeg' }));

  await waitFor(() =>
    expect(vi.mocked(api)).toHaveBeenCalledWith('/api/me/walkup/audio', expect.anything()),
  );
});

test('the start box appears for the YouTube link being typed', async () => {
  // It used to follow the saved clip, so somebody with an uploaded song could
  // not set a start time for a new link until they had saved it.
  vi.mocked(api).mockResolvedValue({
    url: 'asset:' + 'a'.repeat(64), kind: 'audio', start_seconds: 0, end_seconds: 15,
  } as never);
  render(<WalkupMedia />);
  await screen.findByText('Walk-up media');
  expect(screen.queryByLabelText(/Start at/)).toBeNull();

  await userEvent.type(screen.getByLabelText(/Link/), 'https://www.youtube.com/watch?v=dQw4w9WgXcQ');

  expect(screen.getByLabelText(/Start at/)).toBeDefined();
});

test('an uploaded clip leaves the Link box empty', async () => {
  // Showing `video:…` in a box labelled Link invited saving it as one.
  vi.mocked(api).mockResolvedValue({
    url: 'video:' + 'b'.repeat(64), kind: 'video', start_seconds: 0, end_seconds: 15,
  } as never);
  render(<WalkupMedia />);
  await screen.findByText('Walk-up media');

  expect((screen.getByLabelText(/Link/) as HTMLInputElement).value).toBe('');
});

test('it says plainly which choice has no adverts', async () => {
  vi.mocked(api).mockResolvedValue(NONE as never);
  render(<WalkupMedia />);

  expect(await screen.findByText(/uploaded video plays with no adverts/)).toBeDefined();
});


// -- Preview -----------------------------------------------------------------

const SHAPE = {
  title: 'Great work today!',
  body: null,
  about_name: 'Peter Parker',
  occasion: 'Recognition',
  media_url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
  media_kind: 'youtube',
  media_id: 'dQw4w9WgXcQ',
  media_digest: null,
  media_start_seconds: 42,
  media_end_seconds: 57,
  hold_seconds: 15,
};

function answer(preview: unknown = SHAPE) {
  vi.mocked(api).mockImplementation(((path: string) =>
    Promise.resolve(
      path.includes('/preview')
        ? preview
        : { url: SHAPE.media_url, kind: 'youtube', start_seconds: 42, end_seconds: 57 },
    )) as never);
}

describe('Preview', () => {
  afterEach(() => vi.useRealTimers());

  test('sits beside Save', async () => {
    answer();
    render(<WalkupMedia />);

    expect(await screen.findByRole('button', { name: 'Preview' })).toBeDefined();
  });

  test('previews the link as typed, with its start time', async () => {
    // Before saving — the point is to hear it first.
    answer();
    render(<WalkupMedia />);
    await screen.findByText('Walk-up media');

    await userEvent.click(screen.getByRole('button', { name: 'Preview' }));

    const call = vi.mocked(api).mock.calls.find(([path]) => String(path).includes('/preview'))!;
    expect(JSON.parse((call[1] as RequestInit).body as string)).toEqual({
      url: SHAPE.media_url,
      start_seconds: 42,
    });
  });

  test('shows the announcement the wall would show', async () => {
    answer();
    render(<WalkupMedia />);
    await screen.findByText('Walk-up media');

    await userEvent.click(screen.getByRole('button', { name: 'Preview' }));

    const dialog = await screen.findByRole('dialog', { name: 'Walk-up preview' });
    expect(dialog.textContent).toContain('Recognition');
    expect(dialog.textContent).toContain('Peter Parker');
    expect(dialog.querySelector('iframe')?.getAttribute('src')).toContain('start=42');
  });

  test('says it is only on this screen', async () => {
    answer();
    render(<WalkupMedia />);
    await screen.findByText('Walk-up media');

    await userEvent.click(screen.getByRole('button', { name: 'Preview' }));

    expect(await screen.findByText(/only on this screen/i)).toBeDefined();
  });

  test('closes on its own button', async () => {
    answer();
    render(<WalkupMedia />);
    await screen.findByText('Walk-up media');
    await userEvent.click(screen.getByRole('button', { name: 'Preview' }));

    await userEvent.click(await screen.findByRole('button', { name: 'Close preview' }));

    expect(screen.queryByRole('dialog')).toBeNull();
  });

  test('closes on Escape', async () => {
    answer();
    render(<WalkupMedia />);
    await screen.findByText('Walk-up media');
    await userEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await screen.findByRole('dialog');

    fireEvent.keyDown(window, { key: 'Escape' });

    expect(screen.queryByRole('dialog')).toBeNull();
  });

  test('goes away by itself when the clip would end', async () => {
    // **The failure the old wall test button had**: its screen would not go
    // away. This one lasts exactly as long as the announcement would.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    answer();
    render(<WalkupMedia />);
    await screen.findByText('Walk-up media');
    await userEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await screen.findByRole('dialog');

    await act(async () => {
      await vi.advanceTimersByTimeAsync(14_000);
    });
    expect(screen.queryByRole('dialog')).not.toBeNull();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_500);
    });
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  test('an uploaded video previews through the signed-in route', async () => {
    // The one thing that differs from the wall: an editor has a session and
    // no display token.
    answer({
      ...SHAPE, media_url: 'video:' + 'c'.repeat(64), media_kind: 'video',
      media_id: null, media_digest: 'c'.repeat(64), media_start_seconds: 0,
    });
    render(<WalkupMedia />);
    await screen.findByText('Walk-up media');

    await userEvent.click(screen.getByRole('button', { name: 'Preview' }));

    const dialog = await screen.findByRole('dialog');
    expect(dialog.querySelector('video')?.getAttribute('src')).toBe(`/api/images/${'c'.repeat(64)}`);
  });

  test('a link the server will not accept says why, and opens nothing', async () => {
    vi.mocked(api).mockImplementation(((path: string) =>
      path.includes('/preview')
        ? Promise.reject(new Error('Use a YouTube link, or a direct link to a GIF or image.'))
        : Promise.resolve(NONE)) as never);
    render(<WalkupMedia />);
    await screen.findByText('Walk-up media');

    await userEvent.click(screen.getByRole('button', { name: 'Preview' }));

    expect(await screen.findByRole('alert')).toBeDefined();
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});

describe('a link copied at a moment (QA-31)', () => {
  test.each([
    ['https://www.youtube.com/watch?v=abc&t=43s', 43],
    ['https://youtu.be/abc?t=43', 43],
    ['https://www.youtube.com/watch?v=abc&t=1m3s', 63],
    ['https://www.youtube.com/embed/abc?start=90', 90],
    ['https://www.youtube.com/watch?v=abc', null],
  ])('%s starts at %s', (link, seconds) => {
    expect(startFromLink(link)).toBe(seconds);
  });
});

test('an admin can choose a sound already in Assets (8.1)', async () => {
  role = 'admin';
  vi.mocked(api).mockImplementation((async (path: string) => {
    if (path === '/api/assets') {
      return [
        { digest: 'a'.repeat(64), name: 'Horn', kind: 'audio' },
        { digest: 'b'.repeat(64), name: 'Logo', kind: 'image' },
      ];
    }
    if (path === '/api/me/walkup/asset') return { url: null, kind: 'audio', start_seconds: 0, end_seconds: 4 };
    return NONE;
  }) as never);
  render(<WalkupMedia />);

  const pick = await screen.findByLabelText('Or choose from Assets');
  // Only what plays.
  expect(screen.queryByText(/Logo/)).toBeNull();
  fireEvent.change(pick, { target: { value: 'a'.repeat(64) } });
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Use it' }));
  });

  const call = vi.mocked(api).mock.calls.find(([p]) => p === '/api/me/walkup/asset')!;
  expect(JSON.parse((call[1] as RequestInit).body as string)).toEqual({ digest: 'a'.repeat(64) });
  expect(screen.getByText('Uploaded clip')).toBeDefined();
  role = 'agent';
});
