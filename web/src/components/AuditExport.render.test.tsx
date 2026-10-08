// @vitest-environment jsdom
/**
 * The activity log, out of GoalGetter.
 *
 * What has to be true: the downloads carry the chosen range; a stream is set up
 * with an address and a credential; a saved stream shows its address as a hint
 * only, and says when it is failing.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, test, vi } from 'vitest';

import AuditExport from './AuditExport';

vi.mock('../api', () => ({ api: vi.fn(), ApiError: class extends Error {} }));

const { api } = await import('../api');

beforeEach(() => {
  vi.mocked(api).mockReset();
});

test('the downloads carry the chosen range', async () => {
  vi.mocked(api).mockResolvedValue(null as never);
  render(<AuditExport />);

  await userEvent.type(screen.getByLabelText('From'), '2026-09-01');

  expect(screen.getByRole('link', { name: 'Download CSV' }).getAttribute('href')).toBe(
    '/api/audit/export?format=csv&since=2026-09-01',
  );
});

test('a stream is set up with an address and a credential', async () => {
  vi.mocked(api).mockImplementation(((_path: string, init?: RequestInit) =>
    Promise.resolve(init?.method === 'PUT' ? { enabled: true, format: 'splunk', url_hint: 'x', header_name: 'Authorization', header_set: true, last_sent_at: null, last_error: null, last_error_at: null } : null)) as never);
  render(<AuditExport />);

  await userEvent.type(await screen.findByPlaceholderText(/services\/collector/), 'https://splunk.acme.example/services/collector');
  await userEvent.selectOptions(screen.getByLabelText('Format'), 'splunk');
  await userEvent.type(screen.getByPlaceholderText('Splunk <token>'), 'Splunk abc');
  await userEvent.click(screen.getByRole('button', { name: 'Start sending' }));

  await waitFor(() => {
    const call = vi.mocked(api).mock.calls.find(([, init]) => (init as RequestInit)?.method === 'PUT');
    expect(JSON.parse((call![1] as RequestInit).body as string)).toMatchObject({
      url: 'https://splunk.acme.example/services/collector', format: 'splunk', header_value: 'Splunk abc',
    });
  });
});

test('a saved stream shows a hint and says when it is failing', async () => {
  vi.mocked(api).mockResolvedValue({
    enabled: true, format: 'json', url_hint: 'siem.acme.example/…lector', header_name: 'Authorization',
    header_set: true, last_sent_at: null, last_error: 'The collector answered 503.', last_error_at: null,
  } as never);
  render(<AuditExport />);

  expect(await screen.findByText('siem.acme.example/…lector')).toBeDefined();
  expect(screen.getByText('The collector answered 503.')).toBeDefined();
});
