// @vitest-environment jsdom
/**
 * The warehouse form, rendered.
 *
 * Two states this has to get right and neither was covered: which credential the
 * form is offering, and whether the destructive action is on screen at all.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, test, vi } from 'vitest';

import WarehouseSetup from './WarehouseSetup';
import { warehouse } from '../warehouse';

vi.mock('../warehouse', () => ({
  warehouse: { read: vi.fn(), save: vi.fn(), forget: vi.fn(), test: vi.fn() },
}));

const CONNECTED = {
  available: true,
  connected: true,
  account: 'ab12345.us-east-1',
  username: 'SVC',
  warehouse: 'ANALYTICS_WH',
  role: '',
  database: '',
  private_key_set: false,
  token_set: true,
  password_set: false,
  queries: 3,
};

const FRESH = { ...CONNECTED, connected: false, token_set: false, queries: 0 };

function draw(status: typeof CONNECTED, props = {}) {
  vi.mocked(warehouse.read).mockResolvedValue(status);
  return render(<WarehouseSetup {...props} />);
}

describe('a connection using a token', () => {
  test('says so, and warns that it will expire', async () => {
    draw(CONNECTED);

    // The summary line names the warehouse and the credential in one string,
    // so match that rather than the two words, which also appear in the warning.
    expect(
      await screen.findByText(/warehouse ANALYTICS_WH · access token/i),
    ).toBeDefined();
    expect(screen.getByText(/Access tokens expire/i)).toBeDefined();
  });
});

describe('disconnecting', () => {
  test('is absent unless the caller allows it', async () => {
    // The same component renders inside the query wizard as context. A button
    // that severs the connection for every source in the deployment has no
    // business sitting next to a half-written query.
    draw(CONNECTED);
    await screen.findByText(/Connected to/i);

    expect(screen.queryByText('Disconnect')).toBeNull();
  });

  test('names how many queries stop before it does anything', async () => {
    draw(CONNECTED, { canDisconnect: true });
    const user = userEvent.setup();

    await user.click(await screen.findByText('Disconnect'));

    // The count is what makes this a decision rather than a guess.
    expect(screen.getByText(/3 queries stop running/i)).toBeDefined();
    expect(vi.mocked(warehouse.forget)).not.toHaveBeenCalled();
  });

  test('only forgets after the confirm', async () => {
    vi.mocked(warehouse.forget).mockResolvedValue(undefined);
    draw(CONNECTED, { canDisconnect: true });
    const user = userEvent.setup();

    await user.click(await screen.findByText('Disconnect'));
    const confirm = screen.getAllByRole('button', { name: 'Disconnect' });
    await user.click(confirm[confirm.length - 1]!);

    await waitFor(() =>
      expect(vi.mocked(warehouse.forget)).toHaveBeenCalledOnce(),
    );
  });
});

describe('choosing how to authenticate', () => {
  test('starts on the key for a fresh connection', async () => {
    draw(FRESH);

    const key = await screen.findByRole('button', { name: 'Private key' });
    expect(key.getAttribute('aria-pressed')).toBe('true');
  });

  test('opens on the token when that is what is stored', async () => {
    draw(CONNECTED);
    const user = userEvent.setup();

    await user.click(await screen.findByText('Change'));

    expect(
      screen.getByRole('button', { name: 'Access token' }).getAttribute('aria-pressed'),
    ).toBe('true');
  });

  test('switching shows the other credential', async () => {
    draw(FRESH);
    const user = userEvent.setup();

    await user.click(await screen.findByRole('button', { name: 'Access token' }));

    expect(screen.getByLabelText(/Access token/i)).toBeDefined();
    expect(screen.queryByLabelText(/Key passphrase/i)).toBeNull();
  });
});
