// @vitest-environment jsdom
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, test, vi } from 'vitest';

import PersonPassword from './PersonPassword';

vi.mock('../api', () => ({ api: vi.fn(), ApiError: class extends Error {} }));
vi.mock('../confirm', () => ({ ask: vi.fn(async () => true) }));

const { api } = await import('../api');

const PERSON = { id: 7, full_name: 'Sam Rivera', email: 'sam@acme.example', invite_pending: false };

function draw(person: Partial<typeof PERSON> & Record<string, unknown> = {}, isMe = false) {
  const onHandoff = vi.fn();
  render(
    <MemoryRouter>
      <PersonPassword
        person={{ ...PERSON, ...person }}
        isMe={isMe}
        onHandoff={onHandoff}
        onError={() => {}}
        onChanged={() => {}}
      />
    </MemoryRouter>,
  );
  return onHandoff;
}

beforeEach(() => {
  vi.mocked(api).mockReset();
});

test('somebody who must use SSO is offered nothing that cannot work (11.3)', () => {
  draw({ must_use_sso: true });
  expect(screen.getByText(/sign in with their company account/)).toBeTruthy();
  expect(screen.queryByRole('button')).toBeNull();
});

test('both ways for somebody with a password', () => {
  draw();
  expect(screen.getByRole('button', { name: 'Issue a reset link' })).toBeTruthy();
  expect(screen.getByRole('button', { name: 'Set a temporary password' })).toBeTruthy();
});

test('no reset link before they have a password to reset', () => {
  draw({ invite_pending: true });
  expect(screen.queryByRole('button', { name: 'Issue a reset link' })).toBeNull();
  expect(screen.getByRole('button', { name: 'Set a temporary password' })).toBeTruthy();
});

test('your own page points at Account, and offers nothing else (P4-5)', () => {
  draw({}, true);
  expect(screen.queryByRole('button')).toBeNull();
  expect(screen.getByRole('link', { name: 'Account page' }).getAttribute('href')).toBe('/account');
});

test('somebody with no password is not offered a reset of it (P4-5)', () => {
  draw({ has_password: false });
  expect(screen.getByText(/They have no password — they sign in with Microsoft/)).toBeTruthy();
  expect(screen.queryByRole('button', { name: 'Issue a reset link' })).toBeNull();
  expect(screen.getByRole('button', { name: 'Set a temporary password' })).toBeTruthy();
});

test('says when signing in with Microsoft is what binds them (P4-6)', () => {
  draw({ must_use_sso: true, sso_reason: 'signed_in' });
  expect(screen.getByText(/signed in with Microsoft before/)).toBeTruthy();
});

test('setting one hands it over to copy (11.2)', async () => {
  vi.mocked(api).mockResolvedValue(undefined as never);
  const onHandoff = draw();

  await userEvent.click(screen.getByRole('button', { name: 'Set a temporary password' }));
  await userEvent.click(screen.getByRole('button', { name: 'Suggest one' }));
  const chosen = (screen.getByLabelText('Temporary password') as HTMLInputElement).value;
  await userEvent.click(screen.getByRole('button', { name: 'Set password' }));

  await waitFor(() =>
    expect(vi.mocked(api)).toHaveBeenCalledWith(
      '/api/users/7/temporary-password',
      expect.objectContaining({ body: JSON.stringify({ password: chosen }) }),
    ),
  );
  expect(onHandoff).toHaveBeenCalledWith(expect.objectContaining({ link: chosen }));
});

test('waiting on them says so', () => {
  draw({ must_change_password: true });
  expect(screen.getByText(/they choose their own the next time they sign in/)).toBeTruthy();
});
