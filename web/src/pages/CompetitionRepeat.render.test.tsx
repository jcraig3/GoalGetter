// @vitest-environment jsdom
/**
 * Repeating competitions, from the form and the card.
 *
 * What has to be true: a new contest can be set to repeat and the choice is
 * sent; a one-off says nothing about rounds; a repeating round says how it
 * repeats and which round it is.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, test, vi } from 'vitest';

import { CompetitionForm, repeatLine, type Competition } from './Competitions';

vi.mock('../api', () => ({ api: vi.fn(), ApiError: class extends Error {} }));
vi.mock('../components/AppearanceFields', () => ({ default: () => null }));
vi.mock('../orgAppearance', () => ({
  useOrgAppearance: () => ({}),
  useOrgTimezone: () => 'America/New_York',
}));

const { api } = await import('../api');

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation(((path: string) => {
    if (path === '/api/metrics') return Promise.resolve([{ id: 7, name: 'Calls' }]);
    if (path === '/api/users') return Promise.resolve([]);
    if (path === '/api/teams') return Promise.resolve([]);
    return Promise.resolve({ id: 99 });
  }) as never);
});

function competition(over: Partial<Competition>): Competition {
  return { round_number: 1, repeat: null, repeat_until: null, ...over } as Competition;
}

test('a one-off says nothing about rounds', () => {
  expect(repeatLine(competition({}))).toBeNull();
});

test('a repeating round says how and which', () => {
  expect(repeatLine(competition({ repeat: 'weekly', round_number: 3 }))).toBe(
    'Repeats every week · round 3',
  );
});

test('a round of a series that stopped still says which round it was', () => {
  expect(repeatLine(competition({ round_number: 4 }))).toBe('round 4');
});

test('a new contest can be set to repeat', async () => {
  render(<CompetitionForm competition={null} onClose={() => {}} onSaved={() => {}} />);

  await userEvent.type(await screen.findByLabelText('Name'), 'Weekly sprint');
  await userEvent.selectOptions(screen.getByLabelText('Repeat'), 'weekly');
  await userEvent.type(screen.getByLabelText('Last round starts by'), '2026-12-31');
  await userEvent.click(screen.getByRole('button', { name: 'Save as draft' }));

  await waitFor(() => {
    const call = vi.mocked(api).mock.calls.find(
      ([path, init]) => path === '/api/competitions' && (init as RequestInit)?.method === 'POST',
    );
    expect(call).toBeDefined();
    expect(JSON.parse((call![1] as RequestInit).body as string)).toMatchObject({
      repeat: 'weekly',
      repeat_until: '2026-12-31',
    });
  });
  // A long form typed into key by key: under a full parallel run it has gone
  // past the default five seconds.
}, 15_000);
