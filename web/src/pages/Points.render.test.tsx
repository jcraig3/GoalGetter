// @vitest-environment jsdom
/**
 * The points page, as somebody reads it.
 *
 * The arithmetic is tested next door in `pointsCopy.test.ts`. What is worth
 * asserting here is the thing the whole feature turns on: that the season and
 * its clock are on screen above the table, and that the number people are
 * ranked on is this season's rather than the lifetime one. A page that showed
 * a lifetime total next to a rank would be the exact product this was designed
 * against.
 */
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, test, vi } from 'vitest';

import Points from './Points';

vi.mock('../api', () => ({
  api: vi.fn(),
  ApiError: class extends Error {},
}));

vi.mock('../auth', () => ({
  useAuth: () => ({
    user: { id: 2, full_name: 'Peter Parker', capabilities: [] },
    can: () => false,
  }),
  Can: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock('../components/Avatar', () => ({ default: () => null }));
vi.mock('../components/SeasonAdmin', () => ({ default: () => null }));
vi.mock('../components/PointValues', () => ({ default: () => null }));
vi.mock('../components/TierLadder', () => ({ default: () => null }));
vi.mock('../components/BadgeAdmin', () => ({ default: () => null }));
vi.mock('../components/BadgeShelf', () => ({ default: () => null }));
vi.mock('../components/GiveBadge', () => ({ default: () => null }));
vi.mock('../components/CosmeticAdmin', () => ({ default: () => null }));
vi.mock('../components/WheelAdmin', () => ({ default: () => null }));
vi.mock('../components/PrizeHandover', () => ({ default: () => null }));
vi.mock('../components/PrizeWheel', () => ({ default: () => null }));
vi.mock('../components/Shop', () => ({ default: () => null }));

const { api } = await import('../api');

function future(days: number) {
  const when = new Date();
  when.setDate(when.getDate() + days);
  return when.toISOString().slice(0, 10);
}

const SEASON = {
  id: 1,
  name: 'Q1 2028',
  starts_on: future(-30),
  ends_on: future(30),
  closed_at: null,
};

const TABLE = {
  season: SEASON,
  standings: [
    { user_id: 1, name: 'Clark Kent', points: 900, rank: 1, tier: 'Gold' },
    { user_id: 2, name: 'Peter Parker', points: 500, rank: 2, tier: 'Silver' },
  ],
};

const ME = {
  season: SEASON,
  points: 500,
  rank: 2,
  lifetime: 9300,
  tier: 'Silver',
  next_tier: 'Gold',
  to_next_tier: 400,
  wallet: 350,
  ring: '#f5b301',
  title: 'The Closer',
  statement: [
    {
      id: 1,
      points: 100,
      event_key: 'goal.achieved',
      subject_type: 'goal',
      subject_id: 7,
      reason: 'Hit Calls this month',
      created_at: '2028-02-01T10:00:00Z',
    },
    {
      id: 2,
      points: -50,
      event_key: 'manual',
      subject_type: 'user',
      subject_id: 3,
      reason: 'Awarded in error',
      created_at: '2028-02-02T10:00:00Z',
    },
  ],
};

function routes(answers: Record<string, unknown>) {
  vi.mocked(api).mockImplementation((path: string) => {
    const key = Object.keys(answers).find((prefix) => path.startsWith(prefix));
    if (key === undefined) return Promise.reject(new Error(`no stub: ${path}`));
    const answer = answers[key];
    return answer instanceof Error
      ? Promise.reject(answer)
      : Promise.resolve(answer as never);
  });
}

function show() {
  render(
    <MemoryRouter>
      <Points />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.mocked(api).mockReset();
});

test('the season and its clock sit above the table', async () => {
  // **The sentence the whole feature turns on.** A season with no visible
  // clock is a season nobody is racing against, which makes it an ordinary
  // running total with a name.
  routes({ '/api/points/standings': TABLE, '/api/points/me': ME });
  show();

  expect(await screen.findByText('Q1 2028')).toBeTruthy();
  expect(screen.getByText(/weeks left|days left|Last day/)).toBeTruthy();
});

test('my balance is this season, and my rank beside it', async () => {
  routes({ '/api/points/standings': TABLE, '/api/points/me': ME });
  show();

  // Scoped to the headline: 500 is legitimately on screen twice, once as the
  // balance and once as this person's row in the table below.
  const headline = (await screen.findByText('You have')).parentElement;

  expect(headline?.textContent).toContain('500');
  expect(headline?.textContent).toContain('2nd');
});

test('the lifetime figure is never the one ranked', async () => {
  // It appears, because a career total is a fact worth showing. It appears
  // labelled, and nowhere near the rank.
  routes({ '/api/points/standings': TABLE, '/api/points/me': ME });
  show();

  expect(await screen.findByText('9,300 all time')).toBeTruthy();
});

test('the gap shown is to the next place, not to first', async () => {
  // "400 behind 1st" here because 1st is the next place. The helper is what
  // makes this right on a longer table; this checks it reached the screen.
  routes({ '/api/points/standings': TABLE, '/api/points/me': ME });
  show();

  expect(await screen.findByText('400 behind 1st.')).toBeTruthy();
});

test('the statement marks a correction as one', async () => {
  routes({ '/api/points/standings': TABLE, '/api/points/me': ME });
  show();

  expect(await screen.findByText('+100')).toBeTruthy();
  expect(screen.getByText('−50')).toBeTruthy();
  expect(screen.getByText('Awarded in error')).toBeTruthy();
});

test('no season says so rather than showing a zero', async () => {
  // A zero would look like a balance somebody spent.
  routes({
    '/api/points/standings': { season: null, standings: [] },
    '/api/points/me': {
      season: null, points: 0, rank: null, lifetime: 0, statement: [],
      tier: null, next_tier: null, to_next_tier: null,
      wallet: 0, ring: null, title: null,
    },
  });
  show();

  expect(await screen.findByText('The season has not started')).toBeTruthy();
});

test('a season with nobody on the board yet says that too', async () => {
  routes({
    '/api/points/standings': { season: SEASON, standings: [] },
    '/api/points/me': { ...ME, points: 0, rank: null, statement: [] },
  });
  show();

  expect(
    await screen.findByText('Nobody has scored yet this season'),
  ).toBeTruthy();
});

test('a failed load says so rather than showing an empty league', async () => {
  routes({ '/api/points/standings': new Error('Could not load.') });
  show();

  const alert = await screen.findByRole('alert');

  expect(alert.textContent).toContain('Could not load.');
});

test('the rung somebody holds, and what it would take to move up', async () => {
  // The badge rewards what already happened; the distance is the reason to do
  // something this week, so both are on the balance card together.
  routes({ '/api/points/standings': TABLE, '/api/points/me': ME });
  show();

  // Scoped to the balance card: Silver is legitimately on screen twice, as
  // this person's badge and as their row in the table below.
  const card = (await screen.findByText('You have')).parentElement;

  expect(card?.textContent).toContain('Silver');
  expect(card?.textContent).toContain('400 to Gold.');
});

test('the table says what each person holds', async () => {
  routes({ '/api/points/standings': TABLE, '/api/points/me': ME });
  show();

  await screen.findByText('Clark Kent');

  expect(screen.getByText('Gold')).toBeTruthy();
});

test('no ladder set up shows no rung and no distance', async () => {
  // Tiers are optional in a way seasons are not, and an absent ladder must
  // not leave a stray "to null" on the page.
  routes({
    '/api/points/standings': {
      season: SEASON,
      standings: [
        { user_id: 2, name: 'Peter Parker', points: 500, rank: 1, tier: null },
      ],
    },
    '/api/points/me': {
      ...ME, rank: 1, tier: null, next_tier: null, to_next_tier: null,
    },
  });
  show();

  await screen.findByText('Peter Parker');

  expect(screen.queryByText(/ to /)).toBeNull();
});

test('the balance card shows what can be spent, labelled apart from the rank', async () => {
  // Two numbers on purpose: the table ranks what was earned, the wallet is
  // what can be spent, and they must not be mistaken for each other.
  routes({ '/api/points/standings': TABLE, '/api/points/me': ME });
  show();

  const card = (await screen.findByText('You have')).parentElement;

  expect(card?.textContent).toContain('350 to spend');
  expect(card?.textContent).toContain('The Closer');
});
