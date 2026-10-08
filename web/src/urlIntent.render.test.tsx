// @vitest-environment jsdom
/** What the address asks a page to do on arrival (7.9). */
import { render, screen } from '@testing-library/react';
import { useState } from 'react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { expect, test } from 'vitest';

import { useFocusRow, useOpenFromUrl } from './urlIntent';

function Page() {
  const [open, setOpen] = useState(false);
  useOpenFromUrl('new', () => setOpen(true));
  useFocusRow(true);
  const at = useLocation();
  return (
    <>
      <p data-testid="form">{open ? 'open' : 'closed'}</p>
      <p data-testid="search">{at.search}</p>
      <ul>
        <li id="row-1">One</li>
        <li id="row-2">Two</li>
      </ul>
    </>
  );
}

test('?new opens the form once, and leaves the address clean', () => {
  render(
    <MemoryRouter initialEntries={['/teams?new=1']}>
      <Page />
    </MemoryRouter>,
  );

  expect(screen.getByTestId('form').textContent).toBe('open');
  expect(screen.getByTestId('search').textContent).toBe('');
});

test('?focus picks out its row', () => {
  render(
    <MemoryRouter initialEntries={['/teams?focus=2']}>
      <Page />
    </MemoryRouter>,
  );

  expect(document.getElementById('row-2')!.classList.contains('gg-focus-row')).toBe(true);
  expect(document.getElementById('row-1')!.classList.contains('gg-focus-row')).toBe(false);
  expect(screen.getByTestId('search').textContent).toBe('');
});
