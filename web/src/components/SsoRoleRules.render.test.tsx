// @vitest-environment jsdom
/**
 * Roles from groups, in the sign-in settings.
 *
 * What has to be true: it cannot be switched on with no groups; a group can be
 * added with a role; and group names directory sync has read are suggested.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { beforeEach, expect, test, vi } from 'vitest';

import SsoRoleRules, { type RoleRule } from './SsoRoleRules';

vi.mock('../api', () => ({ api: vi.fn(), ApiError: class extends Error {} }));

const { api } = await import('../api');

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(api).mockResolvedValue({ group: [{ value: 'Sales Managers', people: 4 }] } as never);
});

function Harness({ start = [] as RoleRule[] }) {
  const [on, setOn] = useState(false);
  const [rules, setRules] = useState<RoleRule[]>(start);
  return (
    <>
      <SsoRoleRules enabled={on} rules={rules} onEnabled={setOn} onRules={setRules} />
      <output data-testid="rules">{JSON.stringify(rules)}</output>
    </>
  );
}

test('it cannot be switched on with no groups', () => {
  render(<Harness />);

  expect((screen.getByLabelText('Set roles from groups') as HTMLInputElement).disabled).toBe(true);
});

test('a group is added with a role', async () => {
  render(<Harness />);

  await userEvent.click(screen.getByRole('button', { name: 'Add a group' }));
  await userEvent.type(screen.getByLabelText('Group 1'), 'Sales Managers');
  await userEvent.selectOptions(screen.getByLabelText('Role for group 1'), 'manager');

  expect(JSON.parse(screen.getByTestId('rules').textContent!)).toEqual([
    { group: 'Sales Managers', role: 'manager' },
  ]);
  expect((screen.getByLabelText('Set roles from groups') as HTMLInputElement).disabled).toBe(false);
});

test('group names directory sync has read are suggested', async () => {
  const { container } = render(<Harness start={[{ group: '', role: 'agent' }]} />);

  await vi.waitFor(() =>
    expect(container.querySelector('#sso-known-groups option[value="Sales Managers"]')).not.toBeNull(),
  );
});
