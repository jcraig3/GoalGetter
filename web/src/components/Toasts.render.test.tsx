// @vitest-environment jsdom
/**
 * "Goal created · View", for five seconds.
 *
 * There was no word at all after a save (review #5): a form closed and whether
 * the thing had saved was left to guesswork.
 */
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, test, vi } from 'vitest';

import { TOAST_MS, toast } from '../toast';
import Toasts from './Toasts';

afterEach(() => vi.useRealTimers());

function shell() {
  render(
    <MemoryRouter>
      <Toasts />
    </MemoryRouter>,
  );
}

test('says it, with a link to what was made, then goes', () => {
  vi.useFakeTimers();
  shell();

  act(() => toast('Goal created', { href: '/goals/7' }));

  expect(screen.getByText('Goal created')).toBeDefined();
  expect(screen.getByRole('link', { name: 'View' }).getAttribute('href')).toBe('/goals/7');

  act(() => {
    vi.advanceTimersByTime(TOAST_MS);
  });
  expect(screen.queryByText('Goal created')).toBeNull();
});

test('can be dismissed before then', async () => {
  shell();
  act(() => toast('Board saved'));

  await userEvent.click(screen.getByRole('button', { name: 'Dismiss' }));

  expect(screen.queryByText('Board saved')).toBeNull();
});

test('is read out politely, not as an alarm', () => {
  shell();
  act(() => toast('Rule created'));

  expect(screen.getByRole('status').textContent).toContain('Rule created');
});
