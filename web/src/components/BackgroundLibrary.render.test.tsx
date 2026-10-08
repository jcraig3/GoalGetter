// @vitest-environment jsdom
/**
 * The background library, and the editor that opens it.
 *
 * The property worth a test is the one a person would never think to check:
 * **choosing a background copies it**, whole, so a library entry cannot leave a
 * photograph's file sitting under a gradient, and changing the library later
 * cannot move a wall. The rest — the right upload endpoint for a video, the
 * swatch drawn with the wall's own CSS — are the ways this goes quietly wrong.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, test, vi } from 'vitest';

import type { Background } from '../appearance';
import BackgroundFields from './BackgroundFields';
import BackgroundLibrary from './BackgroundLibrary';
import { gradientCss } from './wall/WallBackground';

vi.mock('../api', () => ({
  api: vi.fn(),
  ApiError: class extends Error {},
}));

const { api } = await import('../api');

const LIBRARY = {
  categories: ['calm', 'energy', 'celebration', 'seasonal', 'brand'],
  entries: [
    {
      id: 'saved:4',
      name: 'Office at night',
      category: 'calm',
      background: { kind: 'image', asset: 'abc', dim: 0.4 },
      bundled: false,
    },
    {
      id: 'bundled:aurora',
      name: 'Aurora',
      category: 'calm',
      background: {
        kind: 'gradient', color: '#0b1020', color_mid: '#134e4a',
        color_to: '#1e1b4b', angle: 135, motion: true,
      },
      bundled: true,
    },
    {
      id: 'bundled:sunset',
      name: 'Sunset',
      category: 'energy',
      background: { kind: 'gradient', color: '#ff6a3d', color_to: '#4a148c', dim: 0.35 },
      bundled: true,
    },
  ],
};

beforeEach(() => {
  vi.mocked(api).mockReset();
});

describe('the gradient CSS', () => {
  test('is the old diagonal when nothing else is said', () => {
    expect(gradientCss({ color: '#000000', color_to: '#ffffff' })).toBe(
      'linear-gradient(135deg, #000000, #ffffff)',
    );
  });

  test('carries a middle stop and an angle', () => {
    expect(
      gradientCss({ color: '#000000', color_mid: '#123456', color_to: '#ffffff', angle: 200 }),
    ).toBe('linear-gradient(200deg, #000000, #123456, #ffffff)');
  });

  test('can glow from a point instead', () => {
    expect(gradientCss({ color: '#000000', color_to: '#ffffff', style: 'radial' })).toContain(
      'radial-gradient',
    );
  });
});

describe('the library', () => {
  test('opens on what this organization kept', async () => {
    // The shelf somebody coming back to the library came for.
    vi.mocked(api).mockResolvedValue(LIBRARY as never);
    render(<BackgroundLibrary onChoose={() => {}} onClose={() => {}} />);

    expect(await screen.findByText('Office at night')).toBeTruthy();
    expect(screen.queryByText('Aurora')).toBeNull();
  });

  test('a shelf shows only what is on it', async () => {
    vi.mocked(api).mockResolvedValue(LIBRARY as never);
    render(<BackgroundLibrary onChoose={() => {}} onClose={() => {}} />);

    await userEvent.click(await screen.findByRole('button', { name: 'Energy' }));

    expect(screen.getByText('Sunset')).toBeTruthy();
    expect(screen.queryByText('Aurora')).toBeNull();
  });

  test('a moving background says so on its swatch', async () => {
    vi.mocked(api).mockResolvedValue(LIBRARY as never);
    render(<BackgroundLibrary onChoose={() => {}} onClose={() => {}} />);

    await userEvent.click(await screen.findByRole('button', { name: 'Calm' }));

    expect(screen.getByText('moves')).toBeTruthy();
  });

  test('choosing one hands back the whole background', async () => {
    vi.mocked(api).mockResolvedValue(LIBRARY as never);
    const chosen = vi.fn();
    render(<BackgroundLibrary onChoose={chosen} onClose={() => {}} />);

    await userEvent.click(await screen.findByRole('button', { name: 'Energy' }));
    await userEvent.click(screen.getByRole('button', { name: /Sunset/ }));

    expect(chosen).toHaveBeenCalledWith(LIBRARY.entries[2]!.background);
  });

  test('a bundled background cannot be removed', async () => {
    vi.mocked(api).mockResolvedValue(LIBRARY as never);
    render(<BackgroundLibrary onChoose={() => {}} onClose={() => {}} />);

    await userEvent.click(await screen.findByRole('button', { name: 'Calm' }));

    expect(screen.queryByRole('button', { name: /Remove Aurora/ })).toBeNull();
  });
});

describe('the editor', () => {
  function editor(value: Partial<Background>) {
    const onChange = vi.fn();
    render(
      <BackgroundFields
        value={{
          kind: 'none', color: null, color_to: null, asset: null, dim: null, blur: null,
          ...value,
        } as Background}
        onChange={onChange}
      />,
    );
    return onChange;
  }

  test('choosing from the library replaces the background whole', async () => {
    // **Replaced, not merged.** Merging would leave a photograph's file sitting
    // under a gradient that never uses it.
    vi.mocked(api).mockResolvedValue(LIBRARY as never);
    const onChange = editor({ kind: 'image', asset: 'old-photo', blur: 12 });

    await userEvent.click(screen.getByRole('button', { name: 'Choose from the library' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Energy' }));
    await userEvent.click(screen.getByRole('button', { name: /Sunset/ }));

    const next = onChange.mock.calls.at(-1)![0] as Background;
    expect(next.kind).toBe('gradient');
    expect(next.asset).toBeNull();
    expect(next.blur).toBeNull();
  });

  test('keeping sends only the fields that say something', async () => {
    vi.mocked(api).mockResolvedValue({} as never);
    editor({ kind: 'solid', color: '#112233' });

    await userEvent.click(screen.getByRole('button', { name: 'Keep this in the library' }));
    await userEvent.type(screen.getByPlaceholderText('Office at night'), 'Navy');
    await userEvent.click(screen.getByRole('button', { name: 'Keep' }));

    await waitFor(() =>
      expect(vi.mocked(api)).toHaveBeenCalledWith('/api/backgrounds', expect.anything()),
    );
    const sent = JSON.parse(
      (vi.mocked(api).mock.calls.at(-1)![1] as RequestInit).body as string,
    );
    expect(sent.background).toEqual({ kind: 'solid', color: '#112233' });
  });

  test('nothing to keep offers no keeping', () => {
    editor({ kind: 'none' });

    expect(screen.queryByRole('button', { name: 'Keep this in the library' })).toBeNull();
  });

  test('a video goes to the video endpoint, not the photograph one', async () => {
    // The photograph normaliser would refuse an MP4 with a message about
    // images — the right refusal from the wrong checker.
    vi.mocked(api).mockResolvedValue({ digest: 'vid' } as never);
    editor({ kind: 'video' });

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, new File(['x'], 'loop.mp4', { type: 'video/mp4' }));

    await waitFor(() =>
      expect(vi.mocked(api)).toHaveBeenCalledWith(
        '/api/images/background-video',
        expect.anything(),
      ),
    );
  });

  test('a gradient can be darkened, and a gradient cannot be blurred', () => {
    // A blurred gradient is the same gradient.
    editor({ kind: 'gradient', color: '#ffffff', color_to: '#eeeeee' });

    expect(screen.getByLabelText('Darken')).toBeTruthy();
    expect(screen.queryByLabelText('Blur')).toBeNull();
  });

  test('a gradient can be set to drift', async () => {
    const onChange = editor({ kind: 'gradient', color: '#000000', color_to: '#111111' });

    await userEvent.click(screen.getByLabelText(/Drift slowly/));

    expect((onChange.mock.calls.at(-1)![0] as Background).motion).toBe(true);
  });
});
