// @vitest-environment jsdom
/** A name opens a profile only where profiles can be opened (9.3). */
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect, test, vi } from 'vitest';

import PersonLink from './PersonLink';

let open = true;
vi.mock('../auth', () => ({ useAuth: () => ({ can: (what: string) => what === 'people.view' && open }) }));

test('a link to the profile where the viewer can open profiles', () => {
  open = true;
  render(<MemoryRouter><PersonLink id={7}>Ann</PersonLink></MemoryRouter>);
  expect(screen.getByRole('link', { name: 'Ann' }).getAttribute('href')).toBe('/people/7');
});

test('plain text where they cannot, or there is nobody to link to', () => {
  open = false;
  render(<MemoryRouter><PersonLink id={7}>Ann</PersonLink><PersonLink id={null}>Sales</PersonLink></MemoryRouter>);
  expect(screen.queryByRole('link')).toBeNull();
  expect(screen.getByText('Ann')).toBeDefined();
});
