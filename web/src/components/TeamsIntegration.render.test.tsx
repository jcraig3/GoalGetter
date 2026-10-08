// @vitest-environment jsdom
/**
 * Microsoft Teams, behind its own card.
 *
 * What an admin needs to be true: the three jobs are three tabs; Teams and
 * channels can be searched, filtered to one kind and sorted; standard channels
 * are shown and said to be unusable; a choice is one menu; and the People tab
 * opens on what differs, with "Follow Teams" and "Keep here" for hand moves.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, test, vi } from 'vitest';

import TeamsIntegration from './TeamsIntegration';
import type { Mirror, MirrorPerson, Source } from './TeamsMirror';

vi.mock('../api', () => ({ api: vi.fn(), ApiError: class extends Error {} }));

const { api } = await import('../api');

function person(over: Partial<MirrorPerson>): MirrorPerson {
  return {
    user_id: 1, name: 'Peter Parker', email: 'peter@acme.example', status: 'in_step',
    team_id: 4, team: 'Metropolis', office: null, teams_team_id: 4, teams_team: 'Metropolis',
    teams_choices: [], teams_office: null, m365_office: '', sources: ['Metropolis Sales Team'],
    office_differs_teams: false, office_differs_m365: false,
    ...over,
  };
}

function source(over: Partial<Source>): Source {
  return {
    id: 1, kind: 'team', name: 'Team', membership: null, parent_id: null, people: null,
    standard_channels: 0, linkable: true, gone: false, link: null,
    ...over,
  };
}

const MIRROR: Mirror = {
  available: true,
  auto: false,
  read_at: '2026-09-29T12:00:00Z',
  note: null,
  sources: [
    source({ id: 10, name: 'Metropolis Sales Team', people: 122, standard_channels: 1, link: { target: 'team', id: 4, name: 'Metropolis' } }),
    source({ id: 11, kind: 'channel', name: 'Closers', membership: 'private', parent_id: 10, people: 8 }),
    source({ id: 12, kind: 'channel', name: 'General', membership: 'standard', parent_id: 10, linkable: false }),
    source({ id: 20, name: 'Justice League', people: 126 }),
    source({ id: 30, name: 'Gotham', people: 35 }),
  ],
  teams: [{ id: 4, name: 'Metropolis' }, { id: 5, name: 'SMB' }],
  offices: [{ id: 7, name: 'Metropolis Office' }],
  people: [
    person({ user_id: 1, name: 'Peter Parker', status: 'would_move', team_id: null, team: null }),
    person({ user_id: 2, name: 'Clark Kent', status: 'moved_by_hand', team_id: 5, team: 'SMB' }),
    person({ user_id: 3, name: 'Diana Prince', status: 'in_step' }),
  ],
  office_changes: [],
  counts: {
    conflict: 0, moved_by_hand: 1, only_here: 0, would_move: 1, kept: 0, in_step: 1,
    not_linked: 0, not_in_m365: 0,
  },
  not_yet_here: 0,
};

function answer(mirror: Mirror = MIRROR, teamsOn = true) {
  vi.mocked(api).mockImplementation(((path: string) => {
    if (path.startsWith('/api/announcements')) {
      return Promise.resolve({ enabled: teamsOn, choices: [], destinations: [] });
    }
    if (path === '/api/offices' || path === '/api/teams') return Promise.resolve([]);
    return Promise.resolve(mirror);
  }) as never);
}

async function open(tab: 'Teams & offices' | 'People' = 'Teams & offices', mirror?: Mirror) {
  answer(mirror);
  render(<TeamsIntegration onClose={() => {}} />);
  await userEvent.click(await screen.findByRole('button', { name: new RegExp(`^${tab}`) }));
}

beforeEach(() => {
  // Braces matter: a function returned from beforeEach is run as a cleanup,
  // and mockReset returns the mock.
  vi.mocked(api).mockReset();
});

test('announcements, teams and offices, and people are three tabs', async () => {
  answer();
  render(<TeamsIntegration onClose={() => {}} />);

  expect(await screen.findByRole('button', { name: 'Announcements' })).toBeDefined();
  expect(screen.getByRole('button', { name: /^Teams & offices \(1\)/ })).toBeDefined();
  expect(screen.getByRole('button', { name: /^People/ })).toBeDefined();
});

test('without directory sync it says what to switch on', async () => {
  await open('Teams & offices', { ...MIRROR, available: false });

  expect(await screen.findByText(/Tenant user sync/)).toBeDefined();
});

test('nothing read yet says how to start', async () => {
  await open('Teams & offices', { ...MIRROR, sources: [] });

  expect(await screen.findByText(/Nothing read yet/)).toBeDefined();
});

test('the permission note is shown', async () => {
  await open('Teams & offices', { ...MIRROR, note: 'Add Channel.ReadBasic.All as APPLICATION permissions.' });

  expect(await screen.findByText(/APPLICATION permissions/)).toBeDefined();
});

test('in use comes first, and channels fold under their Team', async () => {
  await open();

  const rows = await screen.findAllByLabelText(/^Use .* as$/);
  expect(rows[0]!.getAttribute('aria-label')).toBe('Use Metropolis Sales Team as');
  expect(screen.queryByText('Closers')).toBeNull();

  await userEvent.click(screen.getByLabelText('Show channels in Metropolis Sales Team'));
  expect(screen.getByText('Closers')).toBeDefined();
});

test('searching a channel name opens its Team', async () => {
  await open();

  await userEvent.type(await screen.findByLabelText('Search Teams and channels'), 'clos');

  expect(screen.getByText('Closers')).toBeDefined();
  expect(screen.queryByText('Justice League')).toBeNull();
});

test('the Channels view lists only channels, and says where each lives', async () => {
  await open();

  await userEvent.click(await screen.findByRole('button', { name: 'Channels (2)' }));

  expect(screen.getByText('Closers')).toBeDefined();
  expect(screen.getByText(/Private channel in Metropolis Sales Team/)).toBeDefined();
  expect(screen.queryByText('Justice League')).toBeNull();
});

test('a standard channel is shown and says why it cannot be used', async () => {
  await open();
  await userEvent.click(await screen.findByRole('button', { name: 'Channels (2)' }));

  expect(screen.getByText('General')).toBeDefined();
  expect(screen.getByText('Same people as the Team')).toBeDefined();
  expect(screen.queryByLabelText('Use General as')).toBeNull();

  await userEvent.click(screen.getByLabelText('Hide standard channels'));
  expect(screen.queryByText('General')).toBeNull();
});

test('sorting by most people', async () => {
  await open();

  await userEvent.selectOptions(await screen.findByLabelText('Sort by'), 'people');

  const rows = screen.getAllByLabelText(/^Use .* as$/).map((r) => r.getAttribute('aria-label'));
  expect(rows).toEqual(['Use Justice League as', 'Use Metropolis Sales Team as', 'Use Gotham as']);
});

test('only ones in use', async () => {
  await open();

  await userEvent.click(await screen.findByLabelText(/Only ones in use/));

  expect(screen.getByText('Metropolis Sales Team')).toBeDefined();
  expect(screen.queryByText('Gotham')).toBeNull();
});

test('a team already following something is not offered twice', async () => {
  await open();

  const gotham = await screen.findByLabelText('Use Gotham as');
  const offered = within(gotham).getAllByRole('option').map((o) => o.textContent);
  expect(offered).not.toContain('Team: Metropolis');
  expect(offered).toContain('Team: SMB');
});

test('choosing an office sends it', async () => {
  await open();

  await userEvent.selectOptions(await screen.findByLabelText('Use Gotham as'), 'office:7');

  await waitFor(() =>
    expect(vi.mocked(api)).toHaveBeenCalledWith(
      '/api/admin/directory/mirror/sources/30',
      expect.objectContaining({ method: 'PUT', body: JSON.stringify({ use_as: 'office', id: 7 }) }),
    ),
  );
});

test('the People tab opens on what differs', async () => {
  await open('People');

  expect(await screen.findByText('Peter Parker')).toBeDefined();
  expect(screen.getByText('Clark Kent')).toBeDefined();
  expect(screen.queryByText('Diana Prince')).toBeNull();

  await userEvent.click(screen.getByRole('button', { name: /Everyone/ }));
  expect(screen.getByText('Diana Prince')).toBeDefined();
});

test('a hand move can follow Teams or be kept', async () => {
  await open('People');
  await screen.findByText('Clark Kent');

  await userEvent.click(screen.getByRole('button', { name: 'Keep here' }));

  await waitFor(() =>
    expect(vi.mocked(api)).toHaveBeenCalledWith(
      '/api/admin/directory/mirror/people/2/keep',
      expect.objectContaining({ method: 'POST' }),
    ),
  );
  expect(screen.getByRole('button', { name: 'Follow Teams' })).toBeDefined();
});

test('applying is one press, and says how many', async () => {
  await open('People');

  await userEvent.click(await screen.findByRole('button', { name: 'Apply 1 change' }));

  await waitFor(() =>
    expect(vi.mocked(api)).toHaveBeenCalledWith(
      '/api/admin/directory/mirror/apply',
      expect.objectContaining({ method: 'POST' }),
    ),
  );
});

test('switched off, it says so and where to switch it on', async () => {
  answer(MIRROR, false);
  const onOpenMicrosoft = vi.fn();
  render(<TeamsIntegration onClose={() => {}} onOpenMicrosoft={onOpenMicrosoft} />);

  expect(await screen.findByText(/Microsoft Teams is switched off/)).toBeDefined();
  await userEvent.click(screen.getByRole('button', { name: 'Switch it on in Microsoft 365' }));
  expect(onOpenMicrosoft).toHaveBeenCalled();
});

test('switched on, there is no notice', async () => {
  answer();
  render(<TeamsIntegration onClose={() => {}} />);

  await screen.findByRole('button', { name: 'Announcements' });
  expect(screen.queryByText(/Microsoft Teams is switched off/)).toBeNull();
});

