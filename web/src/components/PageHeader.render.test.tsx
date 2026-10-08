// @vitest-environment jsdom
/**
 * Where a page says what it is: the tab's title (QA-27) and the trail above a
 * detail page.
 */
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { expect, test } from 'vitest';

import Breadcrumb from './Breadcrumb';
import PageHeader from './PageHeader';

test('the browser tab names the page, and gives it back when it goes', () => {
  document.title = 'GoalGetter';
  const { unmount } = render(<PageHeader title="Goals" />);

  expect(document.title).toBe('Goals · GoalGetter');
  unmount();
  expect(document.title).toBe('GoalGetter');
});

test('a detail page says where it is as well as where back goes', () => {
  render(
    <MemoryRouter>
      <Breadcrumb parent={{ to: '/goals', label: 'Goals' }} here="Clark — Closed Deals" />
    </MemoryRouter>,
  );

  expect(screen.getByRole('link', { name: 'Goals' }).getAttribute('href')).toBe('/goals');
  expect(screen.getByText('Clark — Closed Deals').getAttribute('aria-current')).toBe('page');
});
