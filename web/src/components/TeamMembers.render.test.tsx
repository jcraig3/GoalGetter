// @vitest-environment jsdom
/**
 * Who is on a team, from the Teams page.
 *
 * What has to be true: only this team's people are listed, adding and
 * removing go through the same bulk "assign team" the People page uses, and a
 * team following Microsoft Teams says that hand edits are kept — and who
 * Microsoft Teams puts here that is not here.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, test, vi } from 'vitest';

import TeamMembers, { type Member } from './TeamMembers';

vi.mock('../api', () => ({ api: vi.fn(), ApiError: class extends Error {} }));

const { api } = await import('../api');

function member(id: number, full_name: string, team_id: number | null, team_name: string | null = null): Member {
  return { id, full_name, email: `${(full_name.split(' ')[0] ?? '').toLowerCase()}@acme.example`, org_role: 'agent', team_id, team_name, hidden: false };
}

const PEOPLE = [
  member(1, 'Peter Parker', 4, 'Phoenix'),
  member(2, 'Clark Kent', 5, 'SMB'),
  member(3, 'Diana Prince', null),
];

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(api).mockResolvedValue({ changed: 1, skipped: [] } as never);
});

function show(extra: Partial<Parameters<typeof TeamMembers>[0]> = {}) {
  const onChanged = vi.fn();
  render(
    <TeamMembers
      teamId={4}
      teamName="Phoenix"
      follows={null}
      people={PEOPLE}
      canEdit
      onChanged={onChanged}
      {...extra}
    />,
  );
  return onChanged;
}

test('only this team is listed', () => {
  show();

  expect(screen.getByText('Peter Parker')).toBeDefined();
  expect(screen.queryByText('Clark Kent')).toBeNull();
});

test('removing somebody unassigns them', async () => {
  const onChanged = show();

  await userEvent.click(screen.getByLabelText('Remove Peter Parker from Phoenix'));

  await waitFor(() => expect(onChanged).toHaveBeenCalled());
  expect(vi.mocked(api)).toHaveBeenCalledWith(
    '/api/users/bulk',
    expect.objectContaining({ body: JSON.stringify({ ids: [1], action: 'assign_team', team_id: null }) }),
  );
});

test('adding somebody finds them by name and says where they are now', async () => {
  show();

  await userEvent.type(screen.getByLabelText('Add someone to Phoenix'), 'clark');
  expect(screen.getByText('on SMB')).toBeDefined();
});

test('adding somebody from another team asks before moving them', async () => {
  // QA-8: it used to take them off their old team without a word.
  show();

  await userEvent.type(screen.getByLabelText('Add someone to Phoenix'), 'clark');
  await userEvent.click(screen.getByRole('button', { name: /Clark Kent/ }));

  expect(screen.getByText('Clark Kent is on SMB. Move them to Phoenix?')).toBeDefined();
  expect(vi.mocked(api)).not.toHaveBeenCalled();

  await userEvent.click(screen.getByRole('button', { name: 'Move' }));

  expect(vi.mocked(api)).toHaveBeenCalledWith(
    '/api/users/bulk',
    expect.objectContaining({ body: JSON.stringify({ ids: [2], action: 'assign_team', team_id: 4 }) }),
  );
});

test('cancelling a move leaves them where they are', async () => {
  show();

  await userEvent.type(screen.getByLabelText('Add someone to Phoenix'), 'clark');
  await userEvent.click(screen.getByRole('button', { name: /Clark Kent/ }));
  await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));

  expect(screen.queryByText(/Move them to Phoenix/)).toBeNull();
  expect(vi.mocked(api)).not.toHaveBeenCalled();
});

test('somebody on no team is added straight away, since nothing is lost', async () => {
  show();

  await userEvent.type(screen.getByLabelText('Add someone to Phoenix'), 'diana');
  await userEvent.click(screen.getByRole('button', { name: /Diana Prince/ }));

  expect(vi.mocked(api)).toHaveBeenCalledWith(
    '/api/users/bulk',
    expect.objectContaining({ body: JSON.stringify({ ids: [3], action: 'assign_team', team_id: 4 }) }),
  );
});

test('without permission there is nothing to press', () => {
  show({ canEdit: false });

  expect(screen.queryByText('Remove')).toBeNull();
  expect(screen.queryByLabelText('Add someone to Phoenix')).toBeNull();
});

test('a team that follows Microsoft Teams says hand edits are kept', async () => {
  vi.mocked(api).mockResolvedValue({
    people: [
      { user_id: 2, name: 'Clark Kent', status: 'moved_by_hand', team_id: 5, team: 'SMB', teams_team_id: 4 },
    ],
  } as never);
  show({ follows: 'Phoenix Sales' });

  expect(screen.getByText(/kept as a hand move/)).toBeDefined();
  expect(await screen.findByText(/Clark Kent · SMB/)).toBeDefined();
});
