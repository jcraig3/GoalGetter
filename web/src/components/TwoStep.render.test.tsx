// @vitest-environment jsdom
/**
 * Two-step sign-in, on screen.
 *
 * What has to be true: the second step sends the code with the challenge and
 * signs in; required setup shows a QR code, confirms with a code, and shows the
 * recovery codes before going in; an SSO-only account is not offered a switch;
 * and the account page sets it up.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, test, vi } from 'vitest';

import { TwoStepSignIn, isMfaStep } from './TwoStep';
import TwoStepSettings from './TwoStepSettings';

vi.mock('../api', () => ({
  api: vi.fn(),
  ApiError: class extends Error {
    status = 0;
  },
}));
vi.mock('qrcode', () => ({ default: { toDataURL: () => Promise.resolve('data:image/png;base64,AAAA') } }));

const { api } = await import('../api');

const ME = { id: 1, email: 'peter@acme.example', full_name: 'Peter Parker' };

beforeEach(() => {
  vi.mocked(api).mockReset();
});

test('a challenge is recognised', () => {
  expect(isMfaStep({ mfa: 'code', challenge: 'x' })).toBe(true);
  expect(isMfaStep(ME)).toBe(false);
});

test('the code finishes signing in', async () => {
  vi.mocked(api).mockResolvedValue(ME as never);
  const onSignedIn = vi.fn();
  render(<TwoStepSignIn step={{ mfa: 'code', challenge: 'ch' }} onSignedIn={onSignedIn} onRestart={() => {}} />);

  await userEvent.type(screen.getByPlaceholderText('123456'), '123456');
  await userEvent.click(screen.getByRole('button', { name: 'Continue' }));

  await waitFor(() => expect(onSignedIn).toHaveBeenCalledWith(ME));
  expect(vi.mocked(api)).toHaveBeenCalledWith(
    '/api/auth/login/mfa',
    expect.objectContaining({ body: JSON.stringify({ challenge: 'ch', code: '123456' }) }),
  );
});

test('required setup shows a QR code, then the recovery codes, then goes in', async () => {
  vi.mocked(api).mockImplementation(((path: string) => {
    if (path === '/api/auth/login/mfa/setup') return Promise.resolve({ secret: 'ABCDEFGH', uri: 'otpauth://totp/x' });
    if (path === '/api/auth/login/mfa/enable') return Promise.resolve({ user: ME, recovery_codes: ['aaaa-bbbb', 'cccc-dddd'] });
    return Promise.resolve({});
  }) as never);
  const onSignedIn = vi.fn();
  render(<TwoStepSignIn step={{ mfa: 'setup', challenge: 'ch' }} onSignedIn={onSignedIn} onRestart={() => {}} />);

  expect(await screen.findByAltText('QR code for your authenticator app')).toBeDefined();
  expect(screen.getByText('ABCD EFGH')).toBeDefined();
  await userEvent.type(screen.getByPlaceholderText('123456'), '654321');
  await userEvent.click(screen.getByRole('button', { name: 'Turn on two-step sign-in' }));

  expect(await screen.findByText('aaaa-bbbb')).toBeDefined();
  expect(onSignedIn).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole('button', { name: 'I have saved them' }));
  expect(onSignedIn).toHaveBeenCalledWith(ME);
});

test('an SSO-only account is told, not offered a switch', async () => {
  vi.mocked(api).mockResolvedValue({ enabled: false, required: false, has_password: false, recovery_left: 0 } as never);
  render(<TwoStepSettings />);

  expect(await screen.findByText(/handles its own second step/)).toBeDefined();
  expect(screen.queryByRole('button', { name: 'Set up two-step sign-in' })).toBeNull();
});

test('the account page sets it up', async () => {
  vi.mocked(api).mockImplementation(((path: string) => {
    if (path === '/api/auth/mfa') return Promise.resolve({ enabled: false, required: false, has_password: true, recovery_left: 0 });
    if (path === '/api/auth/mfa/setup') return Promise.resolve({ secret: 'ABCDEFGH', uri: 'otpauth://totp/x' });
    if (path === '/api/auth/mfa/enable') return Promise.resolve({ recovery_codes: ['aaaa-bbbb'] });
    return Promise.resolve({});
  }) as never);
  render(<TwoStepSettings />);

  await userEvent.click(await screen.findByRole('button', { name: 'Set up two-step sign-in' }));
  await userEvent.type(await screen.findByPlaceholderText('123456'), '123456');
  await userEvent.click(screen.getByRole('button', { name: 'Turn on two-step sign-in' }));

  expect(await screen.findByText('aaaa-bbbb')).toBeDefined();
});

test('when required it cannot be turned off', async () => {
  vi.mocked(api).mockResolvedValue({ enabled: true, required: true, has_password: true, recovery_left: 9 } as never);
  render(<TwoStepSettings />);

  expect(await screen.findByText(/9 recovery codes left/)).toBeDefined();
  expect(screen.queryByRole('button', { name: 'Turn off' })).toBeNull();
});
