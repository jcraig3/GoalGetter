// @vitest-environment jsdom
/**
 * The way from a fresh install to a first wall (review #4): in order, each
 * step linked, the next one marked, and gone when everything is done.
 */
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect, test } from 'vitest';

import SetupChecklist, { type SetupStep } from './SetupChecklist';

const step = (key: string, done: boolean, link = `/${key}`): SetupStep => ({
  key,
  label: `Do ${key}`,
  done,
  link,
  detail: '',
});

function show(steps: SetupStep[]) {
  return render(
    <MemoryRouter>
      <SetupChecklist steps={steps} />
    </MemoryRouter>,
  );
}

test('counts what is done and points at the first thing left', () => {
  show([step('data', true), step('people', false), step('teams', false)]);

  expect(screen.getByText('1 of 3 done')).toBeDefined();
  const next = screen.getByText('Next →').closest('a');
  expect(next?.getAttribute('href')).toBe('/people');
});

test('says done and to-do in words, not only with a tick', () => {
  show([step('data', true), step('people', false)]);

  expect(screen.getByText(/Do data/).textContent).toContain('— done');
  expect(screen.getByText(/Do people/).textContent).toContain('— to do');
});

test('is gone once everything is done', () => {
  const { container } = show([step('data', true), step('people', true)]);

  expect(container.textContent).toBe('');
});
