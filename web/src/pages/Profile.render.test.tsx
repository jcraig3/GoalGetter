// @vitest-environment jsdom
/** A person's profile (9.2): the page draws what the server sends, no more. */
import { act, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, expect, test, vi } from 'vitest';

import ProfilePage from './Profile';

vi.mock('../api', () => ({
  api: vi.fn(),
  ApiError: class extends Error {
    constructor(
      readonly status: number,
      message: string,
    ) {
      super(message);
    }
  },
}));
vi.mock('../auth', () => ({ useAuth: () => ({ user: { id: 1 }, can: () => true }) }));
vi.mock('./Achievements', () => ({ RecogniseForm: () => <p>Recognising</p> }));

const { api, ApiError } = await import('../api');

const PUBLIC = {
  person: {
    id: 7, name: 'Ann Andrews', photo_digest: null, job_title: 'Closer', team_name: 'Sales',
    office_name: 'Metropolis', ring: null, title: null,
  },
  is_me: false,
  season: { name: 'Q4', points: 120, rank: 2, of: 9, tier: 'Silver', next_tier: 'Gold', to_next_tier: 80 },
  badges: [{ badge_id: 1, name: 'Big ticket', icon: 'medal', reason: '', earned_at: '2026-10-02T12:00:00Z', times: 1 }],
  wins: [{
    id: 3, occasion: 'Big deal', title: 'Big deal', body: null, figure: '$12,400', from_name: null,
    created_at: new Date().toISOString(),
  }],
  private: null,
  can: { recognise: false, give_badge: false, edit: null },
};

// Braces matter: a function returned from beforeEach is run as its cleanup,
// and the spy itself is a function — it was being called once more after
// each test, which is where the 404 below went unhandled.
beforeEach(() => {
  vi.mocked(api).mockReset();
});

function open() {
  render(
    <MemoryRouter initialEntries={['/people/7']}>
      <Routes>
        <Route path="/people/:id" element={<ProfilePage />} />
      </Routes>
    </MemoryRouter>,
  );
}

test('a colleague sees what was earned, and no buttons they cannot use', async () => {
  vi.mocked(api).mockResolvedValue(PUBLIC as never);
  open();

  expect(await screen.findByRole('heading', { name: 'Ann Andrews' })).toBeDefined();
  expect(screen.getByText('Closer · Sales · Metropolis')).toBeDefined();
  expect(screen.getByText('Silver tier')).toBeDefined();
  expect(screen.getByText('2nd of 9')).toBeDefined();
  expect(screen.getByText('Big ticket')).toBeDefined();
  expect(screen.getByText('$12,400')).toBeDefined();
  expect(screen.queryByRole('button', { name: 'Recognise' })).toBeNull();
  expect(screen.queryByRole('link', { name: 'Edit' })).toBeNull();
  expect(screen.queryByLabelText('Private')).toBeNull();
});

test('their manager also sees goals and numbers, said as private', async () => {
  vi.mocked(api).mockResolvedValue({
    ...PUBLIC,
    private: {
      goals: [],
      numbers: [{
        board_id: 4, board_name: 'Deals board', metric_name: 'Deals', period_label: 'October 2026',
        value: '7', unit: 'count', decimal_places: 0, unit_label: null, rank: 1, of: 12, movement: 2,
      }],
      streak_days: 5,
    },
    can: { recognise: true, give_badge: true, edit: '/users/7' },
  } as never);
  open();

  expect(await screen.findByText('Only Ann, their managers and admins see this.')).toBeDefined();
  expect(screen.getByText('1st of 12')).toBeDefined();
  expect(screen.getByText('5-day streak')).toBeDefined();
  expect(screen.getByRole('button', { name: 'Recognise' })).toBeDefined();
  expect(screen.getByRole('link', { name: 'Edit' }).getAttribute('href')).toBe('/users/7');
});

test('a profile out of reach says so, without saying why it is this one', async () => {
  vi.mocked(api).mockImplementation(() => Promise.reject(new ApiError(404, 'Person not found.')));
  open();
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 20));
  });

  expect(screen.getByText('This profile isn’t available')).toBeDefined();
});
