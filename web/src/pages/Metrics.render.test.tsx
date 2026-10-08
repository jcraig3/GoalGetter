// @vitest-environment jsdom
/**
 * Derived metrics on the Metrics page.
 *
 * What has to be true: a ratio is made by choosing what is divided by what; it
 * cannot be saved without both, or with the same metric twice; the table says
 * what a ratio is made of; and a ratio is never offered as one of its own parts.
 */
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, test, vi } from 'vitest';

import { recordable } from '../recordable';
import Metrics from './Metrics';

vi.mock('../api', () => ({ api: vi.fn(), ApiError: class extends Error {} }));
vi.mock('../auth', () => ({
  useAuth: () => ({ can: () => true }),
  Can: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

const { api } = await import('../api');

const METRICS = [
  { id: 1, key: 'deals_won', name: 'Deals won', description: null, unit: 'count', aggregation: 'count', direction: 'higher_is_better', decimal_places: 0, archived: false },
  { id: 2, key: 'deals_created', name: 'Deals created', description: null, unit: 'count', aggregation: 'count', direction: 'higher_is_better', decimal_places: 0, archived: false },
  { id: 3, key: 'close_rate', name: 'Close rate', description: null, unit: 'percent', aggregation: 'ratio', direction: 'higher_is_better', decimal_places: 1, archived: false, numerator_metric_id: 1, denominator_metric_id: 2 },
];

beforeEach(() => {
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation(((path: string) =>
    Promise.resolve(path.startsWith('/api/metrics?') ? METRICS : {})) as never);
});

function show() {
  render(
    <MemoryRouter>
      <Metrics />
    </MemoryRouter>,
  );
}

test('the table says what a ratio is made of', async () => {
  show();

  expect(await screen.findByText('Deals won ÷ Deals created')).toBeDefined();
});

test('a ratio is made by choosing what is divided by what', async () => {
  show();
  await userEvent.click(await screen.findByRole('button', { name: 'New metric' }));
  await userEvent.type(screen.getByLabelText('Name'), 'Win rate');
  await userEvent.selectOptions(screen.getByLabelText('How values add up'), 'ratio');

  const save = screen.getByRole('button', { name: 'Create metric' }) as HTMLButtonElement;
  expect(save.disabled).toBe(true);

  const divide = screen.getByLabelText('Divide');
  expect(within(divide).queryByRole('option', { name: 'Close rate' })).toBeNull();
  await userEvent.selectOptions(divide, '1');
  await userEvent.selectOptions(screen.getByLabelText('By'), '2');
  await userEvent.click(save);

  await waitFor(() => {
    const call = vi.mocked(api).mock.calls.find(
      ([path, init]) => path === '/api/metrics' && (init as RequestInit)?.method === 'POST',
    );
    expect(JSON.parse((call![1] as RequestInit).body as string)).toMatchObject({
      aggregation: 'ratio', numerator_metric_id: 1, denominator_metric_id: 2,
    });
  });
});

test('the same metric twice cannot be saved', async () => {
  show();
  await userEvent.click(await screen.findByRole('button', { name: 'New metric' }));
  await userEvent.type(screen.getByLabelText('Name'), 'Silly');
  await userEvent.selectOptions(screen.getByLabelText('How values add up'), 'ratio');
  await userEvent.selectOptions(screen.getByLabelText('Divide'), '1');
  await userEvent.selectOptions(screen.getByLabelText('By'), '1');

  expect((screen.getByRole('button', { name: 'Create metric' }) as HTMLButtonElement).disabled).toBe(true);
});

test('data-entry pickers leave ratios out', () => {
  expect(recordable(METRICS).map((m) => m.name)).toEqual(['Deals won', 'Deals created']);
});

test('says a metric in words, not keys (review §9)', async () => {
  const { unitWords, AGGREGATION_LABEL } = await import('./Metrics');
  expect(AGGREGATION_LABEL.sum).toBe('Total');
  expect(unitWords({ unit: 'currency', unit_label: null, decimal_places: 2 })).toBe('Money · 2 decimals');
  expect(unitWords({ unit: 'count', unit_label: 'deals', decimal_places: 0 })).toBe('Deals');
});

test('a name already taken is said on the Name field, and the header stays "New metric" (8.3)', async () => {
  vi.mocked(api).mockImplementation(((path: string, init?: RequestInit) => {
    if (path === '/api/metrics' && init?.method === 'POST') {
      return Promise.reject(new Error('There is already a metric called “Deals won”. Pickers would show two alike.'));
    }
    return Promise.resolve(path.startsWith('/api/metrics?') ? METRICS : {});
  }) as never);
  show();
  await screen.findByText('Deals won ÷ Deals created');

  await userEvent.click(screen.getByRole('button', { name: 'New metric' }));
  // Resting while the form is open, not turned into a Cancel.
  expect((screen.getByRole('button', { name: 'New metric' }) as HTMLButtonElement).disabled).toBe(true);
  await userEvent.type(screen.getByLabelText('Name'), 'Deals won');
  await userEvent.click(screen.getByRole('button', { name: /^(Create|Save)/ }));

  const alert = await screen.findByText(/There is already a metric called/);
  expect(alert.getAttribute('role')).toBe('alert');
  expect(screen.getByLabelText('Name').getAttribute('aria-invalid')).toBe('true');
});
