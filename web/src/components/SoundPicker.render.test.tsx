// @vitest-environment jsdom
/** Choosing a sound for a celebration (6.17). */
import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, test, vi } from 'vitest';

vi.mock('../api', () => ({ api: vi.fn() }));
vi.mock('../toast', () => ({ toast: vi.fn() }));

const { api } = await import('../api');
const { default: SoundPicker, DefaultSounds } = await import('./SoundPicker');

const OWN = { url: 'asset:' + 'a'.repeat(64), digest: 'a'.repeat(64), name: 'Fanfare', seconds: 2 };
const SOUNDS = {
  pack: [
    { key: 'fanfare', name: 'Fanfare', description: 'Brass.', seconds: 2 },
    { key: 'gong', name: 'Gong', description: 'One deep stroke.', seconds: 3.8 },
  ],
  library: [OWN],
  defaults: {},
  kinds: [
    { key: 'goal', label: 'Goals hit' },
    { key: 'recognition', label: 'Recognition' },
  ],
};

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation(async (path: string, init?: RequestInit) => {
    if (path === '/api/sounds') return SOUNDS as never;
    if (path === '/api/sounds/pack/gong/keep') return { url: 'asset:' + 'b'.repeat(64), name: 'Gong' } as never;
    if (path === '/api/sounds/defaults') return JSON.parse(init!.body as string) as never;
    return {} as never;
  });
});

async function settle() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe('the sound picker', () => {
  test('names the sound chosen, and offers the pack and your own', async () => {
    const onChange = vi.fn();
    render(<SoundPicker label="Sound" value={OWN.url} onChange={onChange} />);
    await settle();
    expect(screen.getByText('Fanfare', { selector: 'span' })).toBeDefined();

    fireEvent.click(screen.getByRole('button', { name: 'Choose a sound' }));
    expect(screen.getByText('Starter pack')).toBeDefined();
    expect(screen.getByRole('button', { name: 'Play Gong' })).toBeDefined();
    expect(screen.getByRole('button', { name: 'Chosen' }).getAttribute('aria-pressed')).toBe('true');
  });

  test('a pack sound is copied in when chosen', async () => {
    const onChange = vi.fn();
    render(<SoundPicker label="Sound" value="" onChange={onChange} />);
    await settle();
    fireEvent.click(screen.getByRole('button', { name: 'Choose a sound' }));
    const gong = screen.getByRole('button', { name: 'Play Gong' }).closest('li')!;
    await act(async () => {
      fireEvent.click(gong.querySelector('button:last-child')!);
    });
    expect(vi.mocked(api)).toHaveBeenCalledWith('/api/sounds/pack/gong/keep', { method: 'POST' });
    expect(onChange).toHaveBeenCalledWith('asset:' + 'b'.repeat(64));
  });

  test('can be cleared', async () => {
    const onChange = vi.fn();
    render(<SoundPicker label="Sound" value={OWN.url} onChange={onChange} />);
    await settle();
    fireEvent.click(screen.getByRole('button', { name: 'No sound' }));
    expect(onChange).toHaveBeenCalledWith('');
  });
});

describe('default sounds', () => {
  test('saves the whole set, null for silence', async () => {
    render(<DefaultSounds />);
    await settle();
    const pickers = screen.getAllByRole('button', { name: 'Choose a sound' });
    fireEvent.click(pickers[0]!);
    fireEvent.click(screen.getByRole('button', { name: 'Use' , pressed: false }));
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Save sounds' }));
    });
    const put = vi.mocked(api).mock.calls.find(([path]) => path === '/api/sounds/defaults')!;
    expect(JSON.parse((put[1] as RequestInit).body as string)).toEqual({ goal: OWN.url, recognition: null });
  });
});
