// @vitest-environment jsdom
/** Changing how people reach GoalGetter, guided (Phase 22). */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import HostingChange from './HostingChange';
import type { Check, HttpsSettings } from './hostingWays';

vi.mock('../api', () => ({
  api: vi.fn(),
  ApiError: class ApiError extends Error {
    constructor(_status: number, message: string) {
      super(message);
    }
  },
}));
const { api } = await import('../api');

const PLAIN: HttpsSettings = {
  on: false,
  host: '',
  certificate: 'internal',
  dns_provider: '',
  has_dns_api_token: false,
  acme_email: '',
  front_door: null,
  has_tunnel_token: false,
  tunnel_id: null,
  https_port: 443,
  http_port: 80,
  app_port: 8080,
  files: null,
  env_connected: true,
  trial_until: null,
  undo_to: null,
  web_address_override: null,
  env_readable: true,
};

const SOON = new Date(Date.now() + 14 * 60_000).toISOString();

interface Answers {
  settings?: Partial<HttpsSettings>;
  checks?: Check[];
  trial?: { checks: Check[]; trial_until: string | null };
}

const onChanged = vi.fn();

function show(answers: Answers = {}) {
  let settings: HttpsSettings = { ...PLAIN, ...answers.settings };
  vi.mocked(api).mockImplementation((async (path: string, init?: RequestInit) => {
    const sent = init?.body ? JSON.parse(String(init.body)) : {};
    if (path === '/api/hosting/check') return { checks: answers.checks ?? [] };
    if (path === '/api/hosting/trial') return answers.trial ?? { checks: [], trial_until: settings.trial_until };
    if (path === '/api/hosting/https' && init?.method === 'PUT') {
      settings = { ...settings, on: sent.on, host: sent.host, trial_until: SOON, undo_to: { on: false, host: '', choice: 'internal', redo: false } };
      return { settings, problem: null };
    }
    if (path === '/api/hosting/keep') {
      settings = { ...settings, trial_until: null };
      return { settings, problem: null };
    }
    if (path === '/api/hosting/undo') {
      settings = sent.trial
        ? { ...settings, host: 'old.internal', on: true, trial_until: SOON }
        : { ...PLAIN, undo_to: { on: true, host: settings.host, choice: 'internal', redo: true } };
      return { settings, problem: null };
    }
    return settings;
  }) as never);
  render(<HostingChange onChanged={onChanged} onClose={() => undefined} />);
}

function sent(path: string) {
  const call = [...vi.mocked(api).mock.calls].reverse().find(([p]) => p === path);
  return call?.[1]?.body ? JSON.parse(String(call[1].body)) : null;
}

beforeEach(() => {
  vi.mocked(api).mockReset();
  onChanged.mockReset();
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({}));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function toSetup(way: RegExp, name?: string) {
  await userEvent.click(await screen.findByLabelText(way));
  await userEvent.click(screen.getByRole('button', { name: 'Next' }));
  if (name) await userEvent.type(screen.getByLabelText(/^Name/), name);
}

test('how: the ways, with the one in use marked', async () => {
  show();
  expect(await screen.findByText('How will people reach GoalGetter?')).toBeTruthy();
  for (const label of ['Your network', 'Your company’s domain', 'A free DuckDNS name', 'Cloudflare tunnel', 'A certificate from IT', 'Plain HTTP']) {
    expect(screen.getByText(label)).toBeTruthy();
  }
  expect(screen.getByText('now')).toBeTruthy();
});

test('set up: the name, and a checklist of what is outside GoalGetter', async () => {
  show();
  await toSetup(/Your network/, 'goals.internal');
  expect(screen.getByText('A DNS record: goals.internal → this server’s address')).toBeTruthy();
  expect(screen.getByText(/Ports 443 and 80 open/)).toBeTruthy();
  expect(screen.getByText('https://goals.internal/api/auth/sso/callback')).toBeTruthy();
  expect(screen.getByText(/sudo ufw allow 443,80\/tcp/)).toBeTruthy();
});

test('check ticks the list off, then offers to switch over', async () => {
  show({ checks: [{ key: 'dns', state: 'ok', label: 'goals.internal → 192.168.1.5', detail: 'The address you’re on' }] });
  await toSetup(/Your network/, 'goals.internal');
  await userEvent.click(screen.getByRole('button', { name: 'Check' }));
  expect(await screen.findByText(/goals.internal → 192.168.1.5 · The address you’re on/)).toBeTruthy();
  expect(sent('/api/hosting/check')).toMatchObject({ on: true, host: 'goals.internal', seen_at: window.location.hostname });
  expect(screen.getByRole('button', { name: 'Switch over' })).toBeTruthy();
  expect(screen.getByText('Everything checked is ready.')).toBeTruthy();
});

test('a failed check still lets you try it', async () => {
  show({ checks: [{ key: 'token', state: 'fail', label: 'Cloudflare doesn’t accept this token', detail: null }] });
  await toSetup(/Your company’s domain/, 'goalgetter.acme.com');
  await userEvent.type(screen.getByLabelText(/Cloudflare API token/), 'tok');
  await userEvent.click(screen.getByRole('button', { name: 'Check' }));
  expect(await screen.findByRole('button', { name: 'Switch over anyway' })).toBeTruthy();
  expect(sent('/api/hosting/check')).toMatchObject({ certificate: 'letsencrypt', dns_provider: 'cloudflare', dns_api_token: 'tok' });
});

test('switching over is a trial, with live checks and this device', async () => {
  show({
    trial: {
      checks: [{ key: 'served', state: 'ok', label: 'HTTPS answers · GoalGetter Local Authority', detail: 'Valid until 12 Jan 2027' }],
      trial_until: SOON,
    },
  });
  await toSetup(/Your network/, 'goals.internal');
  await userEvent.click(screen.getByRole('button', { name: 'Check' }));
  await userEvent.click(await screen.findByRole('button', { name: 'Switch over' }));
  expect(sent('/api/hosting/https')).toMatchObject({ on: true, host: 'goals.internal', trial: true });
  expect(await screen.findByText(/HTTPS answers · GoalGetter Local Authority/)).toBeTruthy();
  expect(await screen.findByText('Opens from this device')).toBeTruthy();
  expect(screen.getByText(/undone by itself in 1[34]:\d\d unless kept/)).toBeTruthy();
  expect(vi.mocked(fetch)).toHaveBeenCalledWith('https://goals.internal/api/health', expect.objectContaining({ mode: 'no-cors' }));
});

test('keep makes it final', async () => {
  show({ settings: { on: true, host: 'goals.internal', trial_until: SOON }, trial: { checks: [], trial_until: SOON } });
  await userEvent.click(await screen.findByRole('button', { name: 'Keep' }));
  expect(await screen.findByText('Kept. GoalGetter is at https://goals.internal.')).toBeTruthy();
  expect(screen.getByText(/port 8080, now serves TVs only/)).toBeTruthy();
  expect(onChanged).toHaveBeenCalled();
});

test('undo puts the old setup back', async () => {
  show({ settings: { on: true, host: 'goals.internal', trial_until: SOON }, trial: { checks: [], trial_until: SOON } });
  await userEvent.click(await screen.findByRole('button', { name: 'Undo' }));
  expect(await screen.findByText('Undone. Back to Plain HTTP.')).toBeTruthy();
  expect(sent('/api/hosting/undo')).toEqual({ trial: false });
});

test('this device not opening it: why, and the root certificate', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
  show({ settings: { on: true, host: 'goals.internal', trial_until: SOON }, trial: { checks: [], trial_until: SOON } });
  expect(await screen.findByText(/Doesn’t open from this device yet · This device may not trust/)).toBeTruthy();
  expect(screen.getByRole('link', { name: 'Download the root certificate' }).getAttribute('href')).toBe(
    'http://goals.internal/goalgetter-root.crt',
  );
});

test('a trial nobody kept, undone by itself, says so', async () => {
  show({ settings: { on: true, host: 'goals.internal', trial_until: SOON }, trial: { checks: [], trial_until: null } });
  expect(await screen.findByText('The change wasn’t kept in time, so it was undone.')).toBeTruthy();
});

test('undo last change is tried like any change', async () => {
  show({ settings: { on: true, host: 'new.internal', undo_to: { on: true, host: 'old.internal', choice: 'internal', redo: false } } });
  await userEvent.click(await screen.findByRole('button', { name: 'Undo last change: back to Your network · old.internal' }));
  expect(sent('/api/hosting/undo')).toEqual({ trial: true });
  expect(await screen.findByRole('button', { name: 'Keep' })).toBeTruthy();
});

test('a tunnel: Cloudflare’s steps, the token, and the service to copy', async () => {
  show({ checks: [{ key: 'tunnel_token', state: 'ok', label: 'Looks like a tunnel token', detail: 'Tunnel 6ff42ae2…' }] });
  await toSetup(/Cloudflare tunnel/, 'goalgetter.acme.com');
  expect(screen.getByText('http://web:81')).toBeTruthy();
  await userEvent.type(screen.getByLabelText(/Tunnel token/), 'cloudflared service install eyJhIjoiMSJ9');
  await userEvent.click(screen.getByRole('button', { name: 'Check' }));
  expect(await screen.findByText(/Looks like a tunnel token · Tunnel 6ff42ae2…/)).toBeTruthy();
  expect(sent('/api/hosting/check')).toMatchObject({ front_door: 'cloudflare', tunnel_token: 'cloudflared service install eyJhIjoiMSJ9' });
});

test('plain HTTP switches over without a check', async () => {
  show({ settings: { on: true, host: 'goals.internal' } });
  await toSetup(/Plain HTTP/);
  await userEvent.click(screen.getByRole('button', { name: 'Switch over' }));
  await waitFor(() => expect(sent('/api/hosting/https')).toMatchObject({ on: false, trial: true }));
});

test('a web address set under Advanced is pointed out', async () => {
  show({ settings: { web_address_override: 'https://old.acme.com' } });
  await toSetup(/Your network/, 'goals.internal');
  expect(screen.getByText(/Advanced → Web address is https:\/\/old.acme.com/)).toBeTruthy();
});

test('the Windows front door is changed with its own setup', async () => {
  show({ settings: { on: true, host: 'goals.internal', front_door: 'windows' } });
  expect(await screen.findByText('HTTPS is handled by the Windows front door.')).toBeTruthy();
});


// ── Phase 23 (QA pass 7) ─────────────────────────────────────────────────────

test('after an undo, going back is called a redo (P7-8)', async () => {
  show({ settings: { on: true, host: 'goals.internal', undo_to: { on: true, host: 'new.internal', choice: 'internal', redo: true } } });
  expect(await screen.findByRole('button', { name: 'Redo: back to Your network · new.internal' })).toBeTruthy();
});

test('a .env that can be read but not written is said, with the fix (P7-2)', async () => {
  show({ settings: { env_connected: false, env_readable: true } });
  expect(await screen.findByText(/can read .env but not write it/)).toBeTruthy();
  expect(screen.getByText('sudo chown 1000 .env')).toBeTruthy();
});

test('kept in step, said quietly', async () => {
  show();
  expect(await screen.findByText('Kept in step with .env, both ways.')).toBeTruthy();
});

test('keep asks first when the live check says it isn’t working (P7-7)', async () => {
  show({
    settings: { on: true, host: 'goals.acme.com', front_door: 'cloudflare', trial_until: SOON },
    trial: { checks: [{ key: 'tunnel', state: 'fail', label: 'The tunnel isn’t connected', detail: 'nope' }], trial_until: SOON },
  });
  await screen.findByText(/The tunnel isn’t connected/);
  await userEvent.click(screen.getByRole('button', { name: 'Keep' }));
  expect(screen.getByText('The tunnel isn’t connected. Keep it anyway?')).toBeTruthy();
  expect(vi.mocked(api).mock.calls.some(([p]) => p === '/api/hosting/keep')).toBe(false);
  await userEvent.click(screen.getByRole('button', { name: 'Keep anyway' }));
  await waitFor(() => expect(vi.mocked(api).mock.calls.some(([p]) => p === '/api/hosting/keep')).toBe(true));
});

test('the web address set under Advanced is cleared in one press (P7-1)', async () => {
  show({ settings: { web_address_override: 'http://localhost:8090' } });
  await toSetup(/Your network/, 'goals.internal');
  // Answered by address rather than by order: under load another request
  // can come first, and a one-off answer would go to it instead.
  const answer = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(((path: string, init?: RequestInit) =>
    path === '/api/hosting/web-address'
      ? Promise.resolve({ ...PLAIN, web_address_override: null })
      : answer(path, init)) as never);
  await userEvent.click(screen.getByRole('button', { name: 'Use the HTTPS address instead' }));
  expect(vi.mocked(api)).toHaveBeenCalledWith('/api/hosting/web-address', { method: 'DELETE' });
  expect(await screen.findByText('https://goals.internal/api/auth/sso/callback')).toBeTruthy();
});

test('the Windows firewall command opens office networks only (P7-11)', async () => {
  show();
  await toSetup(/Your network/, 'goals.internal');
  expect(screen.getByText(/-Profile Domain,Private/)).toBeTruthy();
});
