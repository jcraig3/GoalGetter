// @vitest-environment jsdom
/** Preview on a TV sends on Send, not on choosing (7.4, Q2-9). */
import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, expect, test, vi } from 'vitest';

import PreviewOnTv from './PreviewOnTv';

vi.mock('../api', () => ({ api: vi.fn() }));
vi.mock('../toast', () => ({ toast: vi.fn() }));
const { api } = await import('../api');

const TVS = [
  { id: 1, name: 'Lobby', channel_name: 'Lobby', revoked: false },
  { id: 2, name: 'Floor', channel_name: 'Sales floor', revoked: false },
];

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(api).mockResolvedValue(TVS as never);
});

async function open(send = vi.fn(async () => ({ display_name: 'Floor', starts_in_seconds: 4, hold_seconds: 10 }))) {
  render(<PreviewOnTv send={send} />);
  await act(async () => {
    await Promise.resolve();
  });
  return send;
}

test('choosing a TV sends nothing; Send does', async () => {
  const send = await open();
  const select = screen.getByLabelText('Preview on a TV');
  // Arrowing through the list is choosing, over and over.
  fireEvent.change(select, { target: { value: '1' } });
  fireEvent.change(select, { target: { value: '2' } });
  expect(send).not.toHaveBeenCalled();

  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
  });
  expect(send).toHaveBeenCalledExactlyOnceWith(2);

  // Again, to the same TV, in one click.
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: 'Send' }));
  });
  expect(send).toHaveBeenCalledTimes(2);
});

test('Send waits for a TV to be chosen', async () => {
  await open();
  expect((screen.getByRole('button', { name: 'Send' }) as HTMLButtonElement).disabled).toBe(true);
});

test('the only TV is chosen already', async () => {
  vi.mocked(api).mockResolvedValue([TVS[0]] as never);
  await open();
  expect((screen.getByRole('button', { name: 'Send' }) as HTMLButtonElement).disabled).toBe(false);
});
