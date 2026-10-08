// @vitest-environment jsdom
/** Changing a contest while it runs, with a reason (6.14). */
import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, test, vi } from 'vitest';

import RunningChanges from './RunningChanges';

vi.mock('../api', () => ({ api: vi.fn() }));
vi.mock('../orgAppearance', () => ({ useOrgTimezone: () => 'UTC' }));

const { api } = await import('../api');

const CONTEST = {
  id: 4,
  prize: 'Steak dinner',
  ends_at: '2026-10-09T17:00:00Z',
  entity_type: 'user',
};

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation(async (path: string) =>
    (path === '/api/users'
      ? [
          { id: 1, full_name: 'Ann', team_name: null },
          { id: 2, full_name: 'Cat', team_name: null },
        ]
      : {}) as never,
  );
});

async function open(onSaved = vi.fn(async () => {})) {
  render(<RunningChanges contest={CONTEST} entrantIds={[1]} onClose={() => {}} onSaved={onSaved} />);
  await act(async () => {
    await Promise.resolve();
  });
  return onSaved;
}

const save = () => screen.getByRole('button', { name: 'Save changes' }) as HTMLButtonElement;

describe('changing a running contest', () => {
  test('asks for a change, then a reason, before it saves', async () => {
    await open();
    expect(save().disabled).toBe(true);
    expect(screen.getByText('Change the prize, the end, or who is in it.')).toBeDefined();

    fireEvent.change(screen.getByLabelText('Prize'), { target: { value: 'Weekend away' } });
    expect(screen.getByText(/Say why/)).toBeDefined();

    fireEvent.change(screen.getByLabelText('Why'), { target: { value: 'Sponsor upgraded it' } });
    expect(save().disabled).toBe(false);
  });

  test('will not cut it short', async () => {
    await open();
    fireEvent.change(screen.getByLabelText('Ends'), { target: { value: '2026-10-08T17:00' } });
    fireEvent.change(screen.getByLabelText('Why'), { target: { value: 'Wrap it up' } });
    expect(screen.getByText('A running contest can be extended but not cut short.')).toBeDefined();
    expect(save().disabled).toBe(true);
  });

  test('sends only what changed, with the reason', async () => {
    const onSaved = await open();
    fireEvent.change(screen.getByLabelText('Ends'), { target: { value: '2026-10-16T17:00' } });
    fireEvent.change(screen.getByLabelText('Why'), { target: { value: 'Another week' } });

    await act(async () => {
      fireEvent.click(save());
    });

    const patch = vi.mocked(api).mock.calls.find(([, init]) => (init as RequestInit)?.method === 'PATCH')!;
    expect(JSON.parse((patch[1] as RequestInit).body as string)).toEqual({
      ends_at: '2026-10-16T17:00:00.000Z',
      note: 'Another week',
    });
    expect(onSaved).toHaveBeenCalledWith('Contest updated: end extended');
  });
});
