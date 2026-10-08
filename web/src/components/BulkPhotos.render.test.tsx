// @vitest-environment jsdom
/**
 * Staff photos: a zip, a folder or single photos, dropped or chosen, each
 * matched by its name — and one nobody matched given to somebody by hand.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, test, vi } from 'vitest';

import BulkPhotos from './BulkPhotos';

vi.mock('../api', () => ({ api: vi.fn(), ApiError: class extends Error {} }));
vi.mock('../toast', () => ({ toast: vi.fn() }));

const { api } = await import('../api');

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation((async (path: string, init?: RequestInit) => {
    if (path === '/api/users/photos/one') {
      const name = decodeURIComponent((init?.headers as Record<string, string>)['X-File-Name']!);
      return name === 'pparker.jpg'
        ? { filename: name, status: 'matched', detail: 'Photo set.', user_id: 7, user_name: 'Peter Parker' }
        : { filename: name, status: 'unmatched', detail: 'Nobody here matches “mystery”.', user_id: null, user_name: null };
    }
    if (path === '/api/users/photos/bulk')
      return {
        matched: 1,
        unresolved: 0,
        outcomes: [{ filename: 'jsmith.jpg', status: 'matched', detail: 'Photo set.', user_id: 9, user_name: 'Jane Smith' }],
      };
    if (path === '/api/users') return [{ id: 11, full_name: 'Mary Jane Watson', email: 'mjw@acme.test' }];
    return {};
  }) as never);
});

const jpg = (name: string) => new File(['x'], name, { type: 'image/jpeg' });

test('single photos are sent one at a time, each matched by its name', async () => {
  render(<BulkPhotos />);
  await userEvent.upload(screen.getByLabelText('Choose staff photos or a zip'), [jpg('pparker.jpg'), jpg('mystery.jpg')]);

  expect(await screen.findByText('Set — Peter Parker')).toBeDefined();
  expect(screen.getByText('Not matched')).toBeDefined();
  const sent = vi.mocked(api).mock.calls.filter(([path]) => path === '/api/users/photos/one');
  expect(sent).toHaveLength(2);
});

test('a zip is sent as itself, and its files are listed', async () => {
  render(<BulkPhotos />);
  const zip = new File(['zip'], 'headshots.zip', { type: 'application/zip' });
  await userEvent.upload(screen.getByLabelText('Choose staff photos or a zip'), zip);

  expect(await screen.findByText('headshots.zip › jsmith.jpg')).toBeDefined();
  expect(vi.mocked(api).mock.calls.some(([path, init]) => path === '/api/users/photos/bulk' && init?.body === zip)).toBe(true);
});

test('dropping files works the same as choosing them', async () => {
  render(<BulkPhotos />);
  const zone = screen.getByRole('button', { name: /Upload staff photos/ });
  fireEvent.drop(zone, { dataTransfer: { files: [jpg('pparker.jpg')], items: [] } });

  expect(await screen.findByText('Set — Peter Parker')).toBeDefined();
});

test('a photo nobody matched can be given to the right person by hand', async () => {
  render(<BulkPhotos />);
  const mystery = jpg('mystery.jpg');
  await userEvent.upload(screen.getByLabelText('Choose staff photos or a zip'), mystery);

  await userEvent.click(await screen.findByRole('button', { name: 'Choose person' }));
  const picker = await screen.findByLabelText('Whose photo is mystery.jpg?');
  await userEvent.type(picker, 'Mary');
  await userEvent.click(await screen.findByText('Mary Jane Watson'));
  await userEvent.click(screen.getByRole('button', { name: 'Set photo' }));

  await waitFor(() =>
    expect(vi.mocked(api)).toHaveBeenCalledWith('/api/users/11/photo', { method: 'POST', body: mystery }),
  );
  expect(await screen.findByText('Set — Mary Jane Watson')).toBeDefined();
});
