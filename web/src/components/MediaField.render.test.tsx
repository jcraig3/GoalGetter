// @vitest-environment jsdom
/** Upload from this computer, or choose from the library (Phase 25). */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { beforeEach, expect, test, vi } from 'vitest';

import MediaField, { type MediaKind } from './MediaField';

vi.mock('../api', () => ({
  api: vi.fn(),
  ApiError: class ApiError extends Error {
    constructor(_status: number, message: string) {
      super(message);
    }
  },
}));
const { api } = await import('../api');

const PIC = 'a'.repeat(64);
const CLIP = 'b'.repeat(64);
const SONG = 'c'.repeat(64);

const LIBRARY = [
  { digest: PIC, kind: 'image', name: 'Pizza', duration_ms: null },
  { digest: CLIP, kind: 'video', name: 'Confetti', duration_ms: 4000 },
  { digest: SONG, kind: 'audio', name: 'Fanfare', duration_ms: 3000 },
];

const changes: string[] = [];

function Harness({ kinds, link }: { kinds: MediaKind[]; link?: string }) {
  const [value, setValue] = useState('');
  return (
    <MediaField
      label="Media"
      value={value}
      kinds={kinds}
      link={link}
      onChange={(next) => {
        changes.push(next);
        setValue(next);
      }}
    />
  );
}

beforeEach(() => {
  changes.length = 0;
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation((async (_path: string, init?: RequestInit) => {
    if (init?.method === 'POST') return { digest: PIC, kind: 'image', name: 'up.png', duration_ms: null };
    return LIBRARY;
  }) as never);
});

test('from the library: only what fits here', async () => {
  render(<Harness kinds={['video', 'image']} />);
  await userEvent.click(screen.getByRole('button', { name: 'From library' }));
  expect(await screen.findByText('Pizza')).toBeTruthy();
  expect(screen.getByText('Confetti')).toBeTruthy();
  expect(screen.queryByText('Fanfare')).toBeNull();
  await userEvent.click(screen.getByText('Confetti'));
  expect(changes.at(-1)).toBe(`video:${CLIP}`);
});

test('a sound is kept as asset:', async () => {
  render(<Harness kinds={['audio']} />);
  await userEvent.click(screen.getByRole('button', { name: 'From library' }));
  await userEvent.click(await screen.findByText('Fanfare'));
  expect(changes.at(-1)).toBe(`asset:${SONG}`);
});

test('uploaded from this computer, into the library, and chosen', async () => {
  const { container } = render(<Harness kinds={['image']} />);
  const input = container.querySelector('input[type="file"]') as HTMLInputElement;
  await userEvent.upload(input, new File(['png'], 'up.png', { type: 'image/png' }));
  await waitFor(() => expect(changes.at(-1)).toBe(`image:${PIC}`));
  const [, init] = vi.mocked(api).mock.calls.find(([, i]) => i?.method === 'POST')!;
  expect((init!.headers as Record<string, string>)['X-File-Name']).toBe('up.png');
});

test('an upload of the wrong kind is said, not kept', async () => {
  const { container } = render(<Harness kinds={['audio']} />);
  const input = container.querySelector('input[type="file"]') as HTMLInputElement;
  // Past the picker's own filter, as a person choosing "All files" can.
  await userEvent.setup({ applyAccept: false }).upload(input, new File(['png'], 'up.png', { type: 'image/png' }));
  expect(await screen.findByText(/That's a picture; this needs a sound/)).toBeTruthy();
  expect(changes).toEqual([]);
});

test('a link, where one makes sense', async () => {
  render(<Harness kinds={['video', 'image']} link="Or paste a YouTube link" />);
  await userEvent.type(screen.getByPlaceholderText('Or paste a YouTube link'), 'x');
  expect(changes.at(-1)).toBe('x');
});
