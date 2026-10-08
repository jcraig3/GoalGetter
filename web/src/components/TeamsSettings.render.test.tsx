// @vitest-environment jsdom
/**
 * The Microsoft Teams panel.
 *
 * What a person setting it up needs to be true: they are told how to make the
 * link, a saved link is never shown back in full, an edit that leaves the link
 * box empty keeps the old one, a failing channel says why, and the test button
 * reports what actually happened.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, test, vi } from 'vitest';

import TeamsSettings from './TeamsSettings';

vi.mock('../api', () => ({ api: vi.fn(), ApiError: class extends Error {} }));

const { api } = await import('../api');

const CHOICES = [
  { key: 'goal.achieved', label: 'Goals hit' },
  { key: 'recognition', label: 'Recognition' },
  { key: 'competition.won', label: 'Competition wins' },
  { key: 'achievement', label: 'Achievements' },
];

const DEST = {
  id: 3, kind: 'teams', name: 'Sales floor', via: 'workflow', link_hint: 'prod-12.westus.logic.azure.com/…ret123',
  channel_label: null, team_external_id: null, channel_external_id: null,
  events: ['goal.achieved', 'recognition'], office_id: null, team_id: null, enabled: true,
  last_sent_at: null, last_error: null, last_error_at: null, failing: false,
};

function answer(destinations: unknown[] = [DEST], extra: Record<string, unknown> = {}) {
  vi.mocked(api).mockImplementation(((path: string, init?: RequestInit) => {
    if (path in extra) return Promise.resolve(extra[path]);
    if (path.split('?')[0] === '/api/announcements/destinations' && !init?.method) {
      return Promise.resolve({ enabled: extra.__paused ? false : true, choices: CHOICES, destinations });
    }
    if (path === '/api/announcements/enabled') {
      // Answers with the whole listing, as the real endpoint does.
      const on = JSON.parse(String(init?.body ?? '{}')).on ?? true;
      return Promise.resolve({ enabled: on, choices: CHOICES, destinations });
    }
    if (path === '/api/offices' || path === '/api/teams') return Promise.resolve([]);
    return Promise.resolve({});
  }) as never);
}

beforeEach(() => {
  vi.mocked(api).mockReset();
});

test('it explains how to make the Workflows link', async () => {
  answer([]);
  render(<TeamsSettings />);

  await userEvent.click(await screen.findByRole('button', { name: 'Add a Teams channel' }));

  expect(screen.getByText(/Post to a channel when a webhook request is received/)).toBeDefined();
});

test('a saved link is shown as a hint, never in full', async () => {
  answer();
  render(<TeamsSettings />);

  expect(await screen.findByText(/logic\.azure\.com\/…ret123/)).toBeDefined();
});

test('editing without pasting a new link keeps the old one', async () => {
  answer();
  render(<TeamsSettings />);
  await userEvent.click(await screen.findByRole('button', { name: 'Edit' }));

  await userEvent.click(screen.getByRole('button', { name: 'Save' }));

  await waitFor(() => {
    const call = vi.mocked(api).mock.calls.find(([, init]) => (init as RequestInit)?.method === 'PATCH');
    expect(call).toBeDefined();
    expect(JSON.parse((call![1] as RequestInit).body as string)).not.toHaveProperty('webhook_url');
  });
});

test('a failing channel says why', async () => {
  answer([{ ...DEST, failing: true, last_error: 'The channel refused the post (404). The Workflow may have been deleted.' }]);
  render(<TeamsSettings />);

  expect(await screen.findByText(/may have been deleted/)).toBeDefined();
});

test('the test button reports what happened', async () => {
  answer([DEST], { '/api/announcements/destinations/3/test': { ok: false, error: 'The channel answered 500.' } });
  render(<TeamsSettings />);

  await userEvent.click(await screen.findByRole('button', { name: 'Send a test' }));

  expect(await screen.findByText('The channel answered 500.')).toBeDefined();
});

test('the panel is told how many channels are on', async () => {
  answer([DEST, { ...DEST, id: 4, enabled: false }]);
  const onCount = vi.fn();
  render(<TeamsSettings onCount={onCount} />);

  await waitFor(() => expect(onCount).toHaveBeenCalledWith(1));
});

test('a new channel cannot be saved without a link', async () => {
  answer([]);
  render(<TeamsSettings />);
  await userEvent.click(await screen.findByRole('button', { name: 'Add a Teams channel' }));

  await userEvent.type(screen.getByPlaceholderText('Sales floor channel'), 'Floor');

  expect((screen.getByRole('button', { name: 'Save' }) as HTMLButtonElement).disabled).toBe(true);
});

test('each channel switches in one press from the list', async () => {
  answer();
  render(<TeamsSettings />);

  await userEvent.click(await screen.findByLabelText('Post to Sales floor'));

  await waitFor(() =>
    expect(vi.mocked(api)).toHaveBeenCalledWith(
      '/api/announcements/destinations/3/enabled',
      expect.objectContaining({ body: JSON.stringify({ on: false }) }),
    ),
  );
});

test('while paused, a channel says so', async () => {
  answer([DEST], { __paused: true });
  render(<TeamsSettings />);

  expect(await screen.findByText('paused')).toBeDefined();
});

// ── Picking a channel ───────────────────────────────────────────────────────

const SIGNED_IN = {
  '/api/announcements/account': { registered: true, connected: true, connected_as: 'goalgetter@acme.example' },
  '/api/announcements/account/teams': [{ id: 'team-1', name: 'Metropolis Sales Team' }],
  '/api/announcements/account/teams/team-1/channels': [
    { id: 'chan-0', name: 'General', membership: 'standard' },
    { id: 'chan-1', name: 'Closers', membership: 'private' },
  ],
};

test('without an account it offers the sign-in', async () => {
  answer([], { '/api/announcements/account': { registered: true, connected: false, connected_as: '' } });
  render(<TeamsSettings />);

  expect(await screen.findByRole('button', { name: 'Sign in with Microsoft' })).toBeDefined();
});

test('it says who posts', async () => {
  answer([], SIGNED_IN);
  render(<TeamsSettings />);

  expect(await screen.findByText('goalgetter@acme.example')).toBeDefined();
});

test('with an account, a channel is picked from its Teams', async () => {
  answer([], SIGNED_IN);
  render(<TeamsSettings />);
  await screen.findByText('goalgetter@acme.example');
  await userEvent.click(screen.getByRole('button', { name: 'Add a Teams channel' }));

  expect((screen.getByLabelText('Pick a channel') as HTMLInputElement).checked).toBe(true);
  await userEvent.selectOptions(await screen.findByLabelText('Team'), 'team-1');
  await userEvent.selectOptions(await screen.findByLabelText('Channel'), await screen.findByRole('option', { name: 'Closers (private)' }));

  // Named after the channel until somebody types a name.
  expect((screen.getByPlaceholderText('Sales floor channel') as HTMLInputElement).value).toBe('Closers');
  await userEvent.click(screen.getByRole('button', { name: 'Save' }));

  await waitFor(() => {
    const call = vi.mocked(api).mock.calls.find(([path, init]) => path === '/api/announcements/destinations' && (init as RequestInit)?.method === 'POST');
    expect(call).toBeDefined();
    expect(JSON.parse((call![1] as RequestInit).body as string)).toMatchObject({
      via: 'graph', team_external_id: 'team-1', channel_external_id: 'chan-1', name: 'Closers',
    });
  });
});

test('a picked channel is listed by its Team and channel', async () => {
  answer(
    [{ ...DEST, via: 'graph', link_hint: '', channel_label: 'Metropolis Sales Team › Closers', team_external_id: 'team-1', channel_external_id: 'chan-1' }],
    SIGNED_IN,
  );
  render(<TeamsSettings />);

  expect(await screen.findByText(/Metropolis Sales Team › Closers/)).toBeDefined();
});

test('a Workflows link is still an option with an account', async () => {
  answer([], SIGNED_IN);
  render(<TeamsSettings />);
  await screen.findByText('goalgetter@acme.example');
  await userEvent.click(screen.getByRole('button', { name: 'Add a Teams channel' }));

  await userEvent.click(screen.getByLabelText('Use a Workflows link'));

  expect(screen.getByText(/Post to a channel when a webhook request is received/)).toBeDefined();
});


// ── Slack ───────────────────────────────────────────────────────────────────

test('a Slack channel is added with its webhook link, and no Microsoft sign-in', async () => {
  answer([]);
  render(<TeamsSettings kind="slack" />);

  await userEvent.click(await screen.findByRole('button', { name: 'Add a Slack channel' }));

  expect(screen.queryByText(/Sign in with Microsoft/)).toBeNull();
  expect(screen.queryByLabelText('Pick a channel')).toBeNull();
  expect(screen.getByText(/Incoming Webhooks/)).toBeDefined();

  await userEvent.type(screen.getByPlaceholderText('Sales floor channel'), '#sales');
  await userEvent.type(
    screen.getByPlaceholderText('https://hooks.slack.com/services/…'),
    'https://hooks.slack.com/services/T/B/x',
  );
  await userEvent.click(screen.getByRole('button', { name: 'Save' }));

  await waitFor(() => {
    const call = vi.mocked(api).mock.calls.find(
      ([path, init]) => path === '/api/announcements/destinations' && (init as RequestInit)?.method === 'POST',
    );
    expect(JSON.parse((call![1] as RequestInit).body as string)).toMatchObject({
      kind: 'slack', via: 'workflow', webhook_url: 'https://hooks.slack.com/services/T/B/x',
    });
  });
});

test('the Slack card lists only Slack channels', async () => {
  answer([]);
  render(<TeamsSettings kind="slack" />);

  await screen.findByRole('button', { name: 'Add a Slack channel' });

  expect(vi.mocked(api)).toHaveBeenCalledWith('/api/announcements/destinations?kind=slack');
});

test('the Teams switch does not pause a Slack channel', async () => {
  answer([{ ...DEST, kind: 'slack' }], { __paused: true });
  render(<TeamsSettings kind="slack" />);

  await screen.findByText('Sales floor');
  expect(screen.queryByText('paused')).toBeNull();
});
