// @vitest-environment jsdom
/** Jump to anything (6.16). */
import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import CommandPalette, { matchPages } from './CommandPalette';

vi.mock('../api', () => ({ api: vi.fn() }));
// An agent can do none of the actions; everyone else here can do them all.
let role = 'admin';
vi.mock('../auth', () => ({ useAuth: () => ({ can: () => role === 'admin' }) }));
const { api } = await import('../api');

const PAGES = [
  { to: '/', label: 'Home' },
  { to: '/goals', label: 'Goals' },
  { to: '/settings', label: 'Settings' },
];

const RESULTS = {
  people: [{ id: 3, name: 'Ann Andrews', detail: 'Sales', photo_digest: null }],
  boards: [{ id: 7, name: 'Deals board', detail: null }],
  goals: [],
  competitions: [{ id: 2, name: 'October sprint', detail: 'active' }],
  channels: [],
};

function Where() {
  const at = useLocation();
  return <p data-testid="where">{at.pathname + at.search}</p>;
}

beforeEach(() => {
  role = 'admin';
  vi.useFakeTimers();
  vi.mocked(api).mockReset();
  vi.mocked(api).mockResolvedValue(RESULTS as never);
});
afterEach(() => vi.useRealTimers());

function open(onClose = vi.fn()) {
  render(
    <MemoryRouter initialEntries={['/']}>
      <CommandPalette open onClose={onClose} pages={PAGES} />
      <Routes>
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>,
  );
  return onClose;
}

async function type(text: string) {
  fireEvent.change(screen.getByRole('combobox'), { target: { value: text } });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(200);
  });
}

describe('the palette', () => {
  test('lists the pages before anything is typed', () => {
    open();
    expect(screen.getAllByRole('option').map((o) => o.textContent)).toEqual(['Home', 'Goals', 'Settings']);
  });

  test('searches a moment after typing, grouped, contests in words', async () => {
    open();
    await type('an');
    expect(vi.mocked(api)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(api).mock.calls[0]![0]).toBe('/api/search?q=an');
    expect(screen.getByText('People')).toBeDefined();
    expect(screen.getByText('Leaderboards')).toBeDefined();
    expect(screen.getByText('Running')).toBeDefined();
  });

  test('arrow keys move, Enter opens and closes', async () => {
    const onClose = open();
    await type('an');
    const box = screen.getByRole('combobox');
    fireEvent.keyDown(box, { key: 'ArrowDown' });
    expect(screen.getAllByRole('option')[1]!.getAttribute('aria-selected')).toBe('true');
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(screen.getByTestId('where').textContent).toBe('/leaderboards/7');
    expect(onClose).toHaveBeenCalled();
  });

  test('Escape closes', () => {
    const onClose = open();
    fireEvent.keyDown(screen.getByRole('combobox'), { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });
});

describe('matching pages', () => {
  test('by other words too (P4-11): "new" finds Connect a TV, "password" finds yours', () => {
    const list = [
      { to: '/channels?connect=1', label: 'Connect a TV', also: 'new tv' },
      { to: '/account', label: 'Change your password', also: 'password account' },
    ];
    expect(matchPages(list, 'new').map((p) => p.label)).toEqual(['Connect a TV']);
    expect(matchPages(list, 'password').map((p) => p.label)).toEqual(['Change your password']);
  });

  test('a match in the title outranks one in the other words (P5-11)', () => {
    const list = [
      { to: '/users?invite=1', label: 'Invite people', also: 'temporary password' },
      { to: '/account', label: 'Change your password', also: 'account' },
    ];
    expect(matchPages(list, 'password').map((p) => p.label)).toEqual(['Change your password', 'Invite people']);
  });

  test('by name, those starting with it first', () => {
    expect(matchPages([{ to: '/a', label: 'Points setup' }, { to: '/b', label: 'Settings' }], 'set').map((p) => p.label)).toEqual([
      'Settings',
      'Points setup',
    ]);
  });
});

describe('everything with a name (7.9)', () => {
  test('a team opens its list with the row picked out', async () => {
    vi.mocked(api).mockResolvedValue({
      ...RESULTS,
      people: [],
      boards: [],
      competitions: [],
      teams: [{ id: 13, name: 'Metropolis Sales Team', detail: 'Metropolis' }],
    } as never);
    open();
    await type('metropolis');

    expect(screen.getByText('Teams')).toBeDefined();
    fireEvent.click(screen.getByText('Metropolis Sales Team'));
    expect(screen.getByTestId('where').textContent).toBe('/teams?focus=13');
  });

  test('"new" lists what you can make, and "brand" finds a settings tab', async () => {
    vi.mocked(api).mockResolvedValue({ people: [], boards: [], goals: [], competitions: [], channels: [] } as never);
    open();
    await type('new');
    expect(screen.getByText('Actions')).toBeDefined();
    expect(screen.getByText('New goal')).toBeDefined();

    await type('brand');
    fireEvent.click(screen.getByText('Branding'));
    expect(screen.getByTestId('where').textContent).toBe('/settings?tab=branding');
  });

  test('offers an agent no action they cannot take', async () => {
    role = 'agent';
    vi.mocked(api).mockResolvedValue({ people: [], boards: [], goals: [], competitions: [], channels: [] } as never);
    open();
    await type('new');
    expect(screen.queryByText('Actions')).toBeNull();
  });
});
