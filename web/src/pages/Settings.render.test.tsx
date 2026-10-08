// @vitest-environment jsdom
/**
 * Branding, saved from the Settings page.
 *
 * **The one bug worth a test here is silent and total.** The brand and the
 * wall's own settings live in one `appearance` object, and the PATCH replaces
 * it wholesale — so a Settings page that sent only its own fields would wipe
 * every layout, background and type choice the moment somebody changed a
 * colour, with no error and nothing on screen to notice.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, test, vi } from 'vitest';

import Settings from './Settings';

vi.mock('../api', () => ({
  api: vi.fn(),
  ApiError: class extends Error {},
}));

// Signed in as user 9, an admin.
vi.mock('../auth', () => ({ useAuth: () => ({ user: { id: 9 } }) }));
vi.mock('../components/ActivityLog', () => ({ default: () => null }));
vi.mock('../components/CustomRoles', () => ({ default: () => null }));
vi.mock('../components/AuditExport', () => ({ default: () => null }));

const { api } = await import('../api');

//: Everything the wall owns, which this page must carry through untouched.
const WALL = {
  ranked_layout: 'podium',
  background: { kind: 'solid', color: '#001122' },
  font: 'oswald',
};

const ORG = {
  id: 1,
  name: 'Acme',
  timezone: 'America/New_York',
  week_starts_on: 1,
  fiscal_year_start_month: 1,
  currency: 'USD',
  self_photo: true,
  self_details: true,
  self_walkup: false,
  appearance: { primary: '#ff0000', ...WALL },
  appearance_resolved: {
    logo: null,
    slogan: null,
    primary: '#ff0000',
    secondary: '#818cf8',
    accent: '#34d399',
    font: 'oswald',
    font_scale: 1,
    panel_opacity: 0.72,
    panel_blur: 12,
    panel_radius: 16,
    ranked_layout: 'podium',
    goal_layout: 'gauge',
    row_count: 10,
    show_values: true,
    name_display: 'full',
    end_time_format: 'default',
    milestones: 'all',
    background: { kind: 'solid', color: '#001122' },
  },
};

let unenrolled: { id: number; full_name: string }[] = [];

beforeEach(() => {
  unenrolled = [];
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation((async (url: string) =>
    url === '/api/auth/mfa/unenrolled' ? unenrolled : ORG) as never);
});

/** The body of the PATCH this page sent, decoded. */
function saved(): Record<string, unknown> {
  const call = vi
    .mocked(api)
    .mock.calls.find(([, init]) => init?.method === 'PATCH');
  return JSON.parse(String(call?.[1]?.body));
}

/** Make the page dirty without touching what a test is about, then save. */
async function saveAfterRenaming(user: ReturnType<typeof userEvent.setup>) {
  const name = await screen.findByLabelText('Organization name');
  await user.type(name, ' Inc');
  await user.click(screen.getByRole('button', { name: 'Save' }));
}

describe('Settings branding', () => {
  test('carries the wall settings through untouched', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><Settings /></MemoryRouter>);

    await saveAfterRenaming(user);

    await waitFor(() => expect(saved()).toBeTruthy());
    expect(saved().appearance).toMatchObject(WALL);
  });

  test('a colour change is merged, not sent alone', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><Settings /></MemoryRouter>);
    await user.click(await screen.findByRole('button', { name: 'Branding' }));
    const hex = await screen.findByLabelText('Primary hex');

    await user.clear(hex);
    await user.type(hex, '#00ff00');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(saved()).toBeTruthy());
    const appearance = saved().appearance as Record<string, unknown>;
    expect(appearance.primary).toBe('#00ff00');
    expect(appearance.ranked_layout).toBe('podium');
  });

  test('still sends the company details it has always sent', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><Settings /></MemoryRouter>);

    await saveAfterRenaming(user);

    await waitFor(() => expect(saved()).toBeTruthy());
    expect(saved()).toMatchObject({
      name: 'Acme Inc',
      timezone: 'America/New_York',
      currency: 'USD',
    });
  });

  test('carries the self-service switches through a save', async () => {
    // They sit in the same payload as the brand and the timezone, so a page
    // that forgot one would quietly re-open something an admin closed.
    const user = userEvent.setup();
    render(<MemoryRouter><Settings /></MemoryRouter>);

    await saveAfterRenaming(user);

    await waitFor(() => expect(saved()).toBeTruthy());
    expect(saved()).toMatchObject({
      self_photo: true,
      self_details: true,
      self_walkup: false,
    });
  });

  test('there is nothing to save until something changes, and Discard puts it back', async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><Settings /></MemoryRouter>);
    const name = await screen.findByLabelText('Organization name');
    expect(screen.queryByText('Unsaved changes')).toBeNull();

    await user.type(name, ' Inc');
    expect(screen.getByText('Unsaved changes')).toBeDefined();

    await user.click(screen.getByRole('button', { name: 'Discard' }));
    expect((name as HTMLInputElement).value).toBe('Acme');
    expect(screen.queryByText('Unsaved changes')).toBeNull();
  });
});

describe('Settings two-step sign-in (QA-32)', () => {
  test('names who signs in with a password and has not set it up', async () => {
    unenrolled = [
      { id: 1, full_name: 'Peter Parker' },
      { id: 2, full_name: 'Clark Kent' },
    ];
    render(<MemoryRouter><Settings /></MemoryRouter>);
    await userEvent.click(await screen.findByRole('button', { name: 'Sign-in & security' }));

    expect(
      await screen.findByText(/2 people sign in with a password and have not set one up yet/),
    ).toBeDefined();
    expect(screen.getByText(/Peter Parker, Clark Kent\./)).toBeDefined();
  });

  test('and says so when there is nobody left', async () => {
    render(<MemoryRouter><Settings /></MemoryRouter>);
    await userEvent.click(await screen.findByRole('button', { name: 'Sign-in & security' }));

    expect(
      await screen.findByText(
        'Everybody who signs in with a password has an authenticator set up.',
      ),
    ).toBeDefined();
  });

  test('when the only one left is you, says how to fix it (8.4)', async () => {
    unenrolled = [{ id: 9, full_name: 'Jayden Craig' }];
    render(<MemoryRouter><Settings /></MemoryRouter>);
    await userEvent.click(await screen.findByRole('button', { name: 'Sign-in & security' }));

    const link = await screen.findByRole('link', { name: 'Set it up now' });
    expect(link.getAttribute('href')).toBe('/account#two-step');
  });
});
