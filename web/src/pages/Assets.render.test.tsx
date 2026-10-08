// @vitest-environment jsdom
/**
 * Organization → Assets (6.3).
 *
 * What has to be true: files show on their shelves with where they are used;
 * one in use cannot be removed; an added file is sent as itself with its
 * name; and a file can be renamed.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, test, vi } from 'vitest';

import Assets, { type Asset, onShelf } from './Assets';

vi.mock('../api', () => ({ api: vi.fn(), ApiError: class extends Error {} }));
vi.mock('../confirm', () => ({ ask: vi.fn(async () => true) }));

const { api } = await import('../api');

function asset(overrides: Partial<Asset>): Asset {
  return {
    digest: 'a'.repeat(64),
    kind: 'image',
    content_type: 'image/png',
    byte_size: 40_000,
    width: 1024,
    height: 1024,
    duration_ms: null,
    name: 'Gold star',
    created_at: '2026-10-01T12:00:00Z',
    used_in: [],
    ...overrides,
  };
}

const BACKDROP = asset({
  digest: 'b'.repeat(64),
  name: 'Office backdrop',
  content_type: 'image/jpeg',
  used_in: [{ label: "The organization's background", link: '/appearance' }],
});
const HORN = asset({
  digest: 'c'.repeat(64),
  kind: 'audio',
  content_type: 'audio/wav',
  name: 'Airhorn',
  width: null,
  height: null,
  duration_ms: 2400,
});

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation((async (path: string) => {
    if (path === '/api/assets?photos=true') return [asset({}), BACKDROP, HORN];
    return {};
  }) as never);
});

function show() {
  render(
    <MemoryRouter>
      <Assets />
    </MemoryRouter>,
  );
}

const card = (name: string) => screen.getByRole('button', { name }).closest('li')!;

test('files show on their shelves, with where each is used', async () => {
  show();

  expect(await screen.findByRole('button', { name: 'Gold star' })).toBeDefined();
  expect(within(card('Office backdrop')).getByRole('link', { name: "The organization's background" })).toBeDefined();
  expect(within(card('Gold star')).getByText('Not used anywhere')).toBeDefined();

  await userEvent.click(screen.getByRole('button', { name: /Sound/ }));
  expect(screen.getByRole('button', { name: 'Airhorn' })).toBeDefined();
  expect(screen.queryByRole('button', { name: 'Gold star' })).toBeNull();
});

test('a file in use cannot be removed; one that is not can', async () => {
  show();
  await screen.findByRole('button', { name: 'Gold star' });

  const used = within(card('Office backdrop')).getByRole('button', { name: 'Remove' }) as HTMLButtonElement;
  expect(used.disabled).toBe(true);

  await userEvent.click(within(card('Gold star')).getByRole('button', { name: 'Remove' }));
  await waitFor(() =>
    expect(vi.mocked(api)).toHaveBeenCalledWith(`/api/assets/${'a'.repeat(64)}`, { method: 'DELETE' }),
  );
});

test('an added file is sent as itself, with its name', async () => {
  show();
  await screen.findByRole('button', { name: 'Gold star' });

  const file = new File(['png-bytes'], 'Trophy art.png', { type: 'image/png' });
  await userEvent.upload(screen.getByLabelText('Choose files to add'), file);

  await waitFor(() => {
    const call = vi.mocked(api).mock.calls.find(
      ([path, init]) => path === '/api/assets' && (init as RequestInit)?.method === 'POST',
    );
    expect((call![1] as RequestInit).body).toBe(file);
    expect((call![1] as RequestInit).headers).toEqual({ 'X-File-Name': 'Trophy%20art.png' });
  });
});

test('a file can be renamed in place', async () => {
  show();
  await userEvent.click(await screen.findByRole('button', { name: 'Gold star' }));
  const box = screen.getByLabelText('Name');
  await userEvent.clear(box);
  await userEvent.type(box, 'Star of the week{Enter}');

  await waitFor(() =>
    expect(vi.mocked(api)).toHaveBeenCalledWith(`/api/assets/${'a'.repeat(64)}`, {
      method: 'PATCH',
      body: JSON.stringify({ name: 'Star of the week' }),
    }),
  );
});

test('profile pictures sit on their own shelf, and nowhere else', () => {
  const photo = asset({ photo_of: 'Alice', photo_source: 'synced', used_in: [] });
  expect(onShelf(photo, 'photos')).toBe(true);
  expect(['all', 'image', 'unused', 'builtin'].some((s) => onShelf(photo, s as never))).toBe(false);
  expect(onShelf(asset({}), 'photos')).toBe(false);
});
