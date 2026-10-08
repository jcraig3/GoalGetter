// @vitest-environment jsdom
/** "Forgot password?" from the sign-in page (Phase 14). */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, test, vi } from 'vitest';

import ForgotPassword from './ForgotPassword';

vi.mock('../api', () => ({ api: vi.fn(), ApiError: class extends Error {} }));
const { api } = await import('../api');

const ANSWER = 'If that address has an account, a link to choose a new password is on its way.';

function show(selfReset: boolean) {
  vi.mocked(api).mockImplementation((async (path: string) => {
    if (path === '/api/auth/providers') {
      return { local: true, sso_enabled: false, sso_button_label: '', self_reset: selfReset };
    }
    if (path === '/api/auth/forgot-password') return { detail: ANSWER };
    throw new Error(path);
  }) as never);
  render(
    <MemoryRouter>
      <ForgotPassword />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.mocked(api).mockReset();
});

test('asks for the address, then says the same thing whoever it is', async () => {
  show(true);
  await userEvent.type(await screen.findByLabelText('Email'), 'pat@acme.example');
  await userEvent.click(screen.getByRole('button', { name: 'Send me a link' }));

  await waitFor(() =>
    expect(vi.mocked(api)).toHaveBeenCalledWith(
      '/api/auth/forgot-password',
      expect.objectContaining({ body: JSON.stringify({ email: 'pat@acme.example' }) }),
    ),
  );
  expect(await screen.findByText(new RegExp(ANSWER))).toBeTruthy();
});

test('with nowhere to send from, says to ask an administrator', async () => {
  show(false);
  expect(await screen.findByText(/Ask an administrator to send you a reset link/)).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Send me a link' })).toBeNull();
});
