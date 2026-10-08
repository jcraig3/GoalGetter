// @vitest-environment jsdom
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, test, vi } from 'vitest';

import GameTokens from './GameTokens';

vi.mock('../api', () => ({ api: vi.fn(), ApiError: class extends Error {} }));

const { api } = await import('../api');

const RACE = [{ family: 'race', token: 'face', options: ['face', 'car', 'truck', 'bike'] }];

beforeEach(() => {
  vi.mocked(api).mockReset();
});

test('their own face is chosen until they choose something else', async () => {
  vi.mocked(api).mockResolvedValue(RACE as never);
  render(<GameTokens />);

  const face = await screen.findByRole('button', { name: 'Your face' });

  expect(face.getAttribute('aria-pressed')).toBe('true');
});

test('choosing a piece saves it for that kind of board', async () => {
  vi.mocked(api).mockResolvedValue(RACE as never);
  render(<GameTokens />);

  await userEvent.click(await screen.findByRole('button', { name: 'Car' }));

  await waitFor(() =>
    expect(vi.mocked(api)).toHaveBeenCalledWith(
      '/api/me/tokens',
      expect.objectContaining({ body: JSON.stringify({ family: 'race', token: 'car' }) }),
    ),
  );
});

test('a manager edits somebody else’s', async () => {
  vi.mocked(api).mockResolvedValue(RACE as never);
  render(<GameTokens userId={7} />);

  await screen.findByRole('button', { name: 'Car' });

  expect(vi.mocked(api)).toHaveBeenCalledWith('/api/me/tokens?user_id=7');
});

test('nothing to show when it cannot load', async () => {
  vi.mocked(api).mockRejectedValue(new Error('no'));
  const { container } = render(<GameTokens />);

  await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalled());
  expect(container.textContent).toBe('');
});
