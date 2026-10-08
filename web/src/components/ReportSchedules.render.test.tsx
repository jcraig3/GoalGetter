// @vitest-environment jsdom
/**
 * Emailing the coaching digest, from the Reporting page.
 *
 * What has to be true: a schedule says when and to whom in words; one can be
 * made by choosing how often, when, and who; the test sends to the person
 * pressing it and says what happened; and a failing schedule says why.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, test, vi } from 'vitest';

import ReportSchedules, { whenLabel, type Schedule } from './ReportSchedules';

vi.mock('../api', () => ({ api: vi.fn(), ApiError: class extends Error {} }));

const { api } = await import('../api');

const SCHEDULE: Schedule = {
  id: 4, name: 'Monday digest', cadence: 'weekly', weekday: 0, hour: 8,
  recipients: [{ id: 1, name: 'Bruce Wayne', email: 'bruce@acme.example' }],
  enabled: true, last_sent_at: null, last_error: null,
};

function answer(schedules: Schedule[] = [SCHEDULE], extra: Record<string, unknown> = {}) {
  vi.mocked(api).mockImplementation(((path: string) => {
    if (path in extra) return Promise.resolve(extra[path]);
    if (path === '/api/reporting/schedules') return Promise.resolve(schedules);
    if (path === '/api/reporting/recipients') {
      return Promise.resolve([
        { id: 1, name: 'Bruce Wayne', email: 'bruce@acme.example' },
        { id: 2, name: 'Diana Prince', email: 'diana@acme.example' },
      ]);
    }
    return Promise.resolve({});
  }) as never);
}

beforeEach(() => {
  vi.mocked(api).mockReset();
});

test('when, in words', () => {
  expect(whenLabel({ cadence: 'weekly', weekday: 0, hour: 8 })).toBe('Every Monday at 8am');
  expect(whenLabel({ cadence: 'weekdays', weekday: null, hour: 13 })).toBe('Every weekday at 1pm');
  expect(whenLabel({ cadence: 'monthly', weekday: null, hour: 0 })).toBe('The 1st of each month at 12am');
});

test('a schedule says when and to whom', async () => {
  answer();
  render(<ReportSchedules />);

  expect(await screen.findByText(/Every Monday at 8am · to Bruce Wayne/)).toBeDefined();
});

test('one is made by choosing how often, when and who', async () => {
  answer([]);
  render(<ReportSchedules />);

  await userEvent.click(await screen.findByRole('button', { name: 'Schedule an email' }));
  await userEvent.selectOptions(screen.getByLabelText('How often'), 'weekdays');
  await userEvent.selectOptions(screen.getByLabelText('At'), '7');
  await userEvent.click(screen.getByLabelText(/Diana Prince/));
  await userEvent.click(screen.getByRole('button', { name: 'Save' }));

  await waitFor(() => {
    const call = vi.mocked(api).mock.calls.find(
      ([path, init]) => path === '/api/reporting/schedules' && (init as RequestInit)?.method === 'POST',
    );
    expect(JSON.parse((call![1] as RequestInit).body as string)).toMatchObject({
      cadence: 'weekdays', hour: 7, recipient_ids: [2],
    });
  });
});

test('the test sends to me and says what happened', async () => {
  answer([SCHEDULE], { '/api/reporting/schedules/4/send': { ok: false, error: 'No email is set up.' } });
  render(<ReportSchedules />);

  await userEvent.click(await screen.findByRole('button', { name: 'Send me a test' }));

  expect(await screen.findByText('No email is set up.')).toBeDefined();
});

test('a failing schedule says why', async () => {
  answer([{ ...SCHEDULE, last_error: 'The mail server refused.' }]);
  render(<ReportSchedules />);

  expect(await screen.findByText('The mail server refused.')).toBeDefined();
});

test('says when email is set up, and as whom (8.3)', async () => {
  answer([SCHEDULE], { '/api/reporting/mail': { ready: true, sending_from: 'goalgetter@acme.example' } });
  render(<ReportSchedules />);
  expect(await screen.findByText('Email is set up — sending from goalgetter@acme.example.')).toBeDefined();
});

test('and when it is not', async () => {
  answer([SCHEDULE], { '/api/reporting/mail': { ready: false, sending_from: null } });
  render(<ReportSchedules />);
  expect(await screen.findByText(/needs email set up under Integrations/)).toBeDefined();
});
