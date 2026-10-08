// @vitest-environment jsdom
/**
 * Custom roles, in Settings.
 *
 * What has to be true: a role says what it is based on and what it may not do;
 * a new one is made by ticking what to take away; and only people on the base
 * role are offered to join it.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, test, vi } from 'vitest';

import CustomRoles from './CustomRoles';

vi.mock('../api', () => ({ api: vi.fn(), ApiError: class extends Error {} }));

const { api } = await import('../api');

const CATALOGUE = {
  removable: {
    manager: [
      { key: 'competitions.manage', label: 'Run competitions' },
      { key: 'metrics.correct', label: 'Correct data' },
    ],
    admin: [{ key: 'integrations.manage', label: 'Manage integrations' }],
    agent: [],
  },
  roles: [
    { id: 3, name: 'Team lead', description: null, base_role: 'manager', removed: ['competitions.manage'], members: [{ id: 5, name: 'Diana Prince' }] },
  ],
};

const PEOPLE = [
  { id: 5, full_name: 'Diana Prince', org_role: 'manager', hidden: false },
  { id: 6, full_name: 'Clark Kent', org_role: 'manager', hidden: false },
  { id: 7, full_name: 'Peter Parker', org_role: 'agent', hidden: false },
];

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation(((path: string) =>
    Promise.resolve(path === '/api/roles' ? CATALOGUE : path === '/api/users' ? PEOPLE : {})) as never);
});

test('a role says what it is based on and what it may not do', async () => {
  render(<CustomRoles />);

  expect(await screen.findByText('Team lead')).toBeDefined();
  expect(screen.getByText('Run competitions')).toBeDefined();
  expect(screen.getByText(/Diana Prince/)).toBeDefined();
});

test('only people on the base role are offered', async () => {
  render(<CustomRoles />);

  const picker = await screen.findByLabelText('Add somebody to Team lead');
  const offered = within(picker).getAllByRole('option').map((o) => o.textContent);

  expect(offered).toContain('Clark Kent');
  expect(offered).not.toContain('Peter Parker');
  expect(offered).not.toContain('Diana Prince');
});

test('a new role is made by ticking what to take away', async () => {
  render(<CustomRoles />);

  await userEvent.click(await screen.findByRole('button', { name: 'New role' }));
  await userEvent.type(screen.getByPlaceholderText('Team lead'), 'Coach');
  await userEvent.click(screen.getByLabelText('Correct data'));
  await userEvent.click(screen.getByRole('button', { name: 'Save' }));

  await waitFor(() => {
    const call = vi.mocked(api).mock.calls.find(
      ([path, init]) => path === '/api/roles' && (init as RequestInit)?.method === 'POST',
    );
    expect(JSON.parse((call![1] as RequestInit).body as string)).toEqual({
      name: 'Coach', base_role: 'manager', removed: ['metrics.correct'],
    });
  });
});
