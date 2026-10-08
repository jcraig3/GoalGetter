// @vitest-environment jsdom
/** How GoalGetter is reached, at a glance (Phase 19). */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, expect, test, vi } from 'vitest';

import HostingOverview, { type Hosting } from './HostingOverview';

vi.mock('../api', () => ({ api: vi.fn(), ApiError: class extends Error {} }));
const { api } = await import('../api');

const ON: Hosting = {
  https: true,
  https_address: 'https://goals.internal',
  certificate: 'internal',
  root_certificate_url: 'http://goals.internal/goalgetter-root.crt',
  tv_address: 'http://goals.internal:8080',
  sso_redirect: 'https://goals.internal/api/auth/sso/callback',
  addresses_visible: true,
  you_appear_as: '192.168.1.55',
  connection: 'visible',
  front_door: null,
  sign_in_limits: [5, 20],
  web_address: 'https://goals.internal',
  web_address_from: 'https',
  certificate_valid_until: '2099-01-12T12:00:00Z',
  certificate_issuer: 'GoalGetter Local Authority',
  proxies_seen: 1,
};

function show(hosting: Partial<Hosting> = {}) {
  vi.mocked(api).mockResolvedValue({ ...ON, ...hosting } as never);
  render(<HostingOverview />);
}

beforeEach(() => {
  vi.mocked(api).mockReset();
});

test('GoalGetter’s own certificate renews itself: no date to worry about', async () => {
  show({ certificate_valid_until: new Date(Date.now() + 6 * 3600_000).toISOString() });
  expect(await screen.findByText('Renewed automatically')).toBeTruthy();
});

test('a Let’s Encrypt certificate shows until when', async () => {
  show({ certificate: 'letsencrypt', root_certificate_url: null });
  expect(await screen.findByText(/Valid until/)).toBeTruthy();
});

test('one line per fact: address, HTTPS, certificate, limits, you', async () => {
  show();
  expect(await screen.findByText('https://goals.internal')).toBeTruthy();
  expect(screen.getByText('On · GoalGetter’s own certificate')).toBeTruthy();
  expect(screen.getByText('Renewed automatically')).toBeTruthy();
  expect(screen.getByText('Per device and per account')).toBeTruthy();
  expect(screen.getByText('192.168.1.55')).toBeTruthy();
});

test('devices and TVs: the root certificate and the TV address to copy', async () => {
  show();
  const download = await screen.findByRole('link', { name: 'Download' });
  expect(download.getAttribute('href')).toBe('http://goals.internal/goalgetter-root.crt');
  expect(screen.getByText('http://goals.internal:8080/pair')).toBeTruthy();
  expect(screen.getByText('https://goals.internal/api/auth/sso/callback')).toBeTruthy();
});

test('HTTPS off: said in a word, with why it matters', async () => {
  show({
    https: false, certificate: null, root_certificate_url: null, tv_address: null,
    web_address: 'http://localhost:8080', web_address_from: 'env', certificate_valid_until: null,
  });
  expect(await screen.findByText('Off')).toBeTruthy();
  expect(screen.getByText(/Needed for other computers and Microsoft sign-in/)).toBeTruthy();
  expect(screen.queryByText('For devices and TVs')).toBeNull();
});

test('Docker hiding every device: per account only', async () => {
  show({ you_appear_as: null, connection: 'docker', addresses_visible: false });
  expect(await screen.findByText('Per account only')).toBeTruthy();
  expect(screen.getByText('Hidden by Docker')).toBeTruthy();
});

test('an expired certificate says so', async () => {
  show({ certificate_valid_until: '2020-01-01T00:00:00Z' });
  expect(await screen.findByText(/Expired/)).toBeTruthy();
});

test('through Cloudflare: its certificate, nothing to download', async () => {
  show({ certificate: 'cloudflare', root_certificate_url: null, tv_address: null });
  expect(await screen.findByText('On · Cloudflare')).toBeTruthy();
  expect(screen.queryByRole('link', { name: 'Download' })).toBeNull();
});

test('through a tunnel: whether it is connected, and why not', async () => {
  show({
    certificate: 'cloudflare', root_certificate_url: null, tv_address: null,
    tunnel: { state: 'problem', connections: 0, problem: 'The tunnel service isn’t running.' },
  });
  expect(await screen.findByText('Not connected')).toBeTruthy();
  expect(screen.getByText('The tunnel service isn’t running.')).toBeTruthy();
});

test('↻ checks again, and Change opens the guided change', async () => {
  show();
  await userEvent.click(await screen.findByRole('button', { name: 'Check again' }));
  await waitFor(() => expect(vi.mocked(api)).toHaveBeenCalledTimes(2));
  vi.mocked(api).mockResolvedValue({
    on: true, host: 'goals.internal', certificate: 'internal', dns_provider: '', has_dns_api_token: false,
    acme_email: '', front_door: null, has_tunnel_token: false, tunnel_id: null, https_port: 443, http_port: 80,
    app_port: 8080, files: null, env_connected: true, trial_until: null, undo_to: null, web_address_override: null,
  } as never);
  await userEvent.click(screen.getByRole('button', { name: 'Change' }));
  expect(await screen.findByText('How will people reach GoalGetter?')).toBeTruthy();
  expect(vi.mocked(api)).toHaveBeenLastCalledWith('/api/hosting/https');
});
