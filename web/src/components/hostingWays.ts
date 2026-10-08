/**
 * The ways people can reach GoalGetter, as the guided change offers them
 * (Phase 22), and how each maps onto the HTTPS settings.
 */

export interface HttpsSettings {
  on: boolean;
  host: string;
  certificate: 'internal' | 'letsencrypt' | 'files';
  dns_provider: '' | 'cloudflare' | 'duckdns';
  has_dns_api_token: boolean;
  acme_email: string;
  front_door: 'windows' | 'cloudflare' | null;
  has_tunnel_token: boolean;
  tunnel_id: string | null;
  https_port: number;
  http_port: number;
  app_port: number;
  files: { names: string[]; valid_until: string } | null;
  env_connected: boolean;
  trial_until: string | null;
  undo_to: { on: boolean; host: string; choice: string; redo: boolean } | null;
  web_address_override: string | null;
  /** `.env` can be read, even if not written (`env_connected`). */
  env_readable: boolean;
}

export interface TunnelStatus {
  state: 'off' | 'connecting' | 'connected' | 'problem';
  connections: number;
  problem: string | null;
}

export interface Check {
  key: string;
  state: 'ok' | 'warn' | 'fail' | 'wait';
  label: string;
  detail: string | null;
}

export type Way = 'internal' | 'company' | 'duckdns' | 'tunnel' | 'files' | 'off';

export const WAYS: { key: Way; label: string; hint: string; placeholder: string }[] = [
  { key: 'internal', label: 'Your network', hint: 'A name like goals.internal, with GoalGetter’s own certificate', placeholder: 'goals.internal' },
  { key: 'company', label: 'Your company’s domain', hint: 'goalgetter.company.com, with a free Let’s Encrypt certificate', placeholder: 'goalgetter.company.com' },
  { key: 'duckdns', label: 'A free DuckDNS name', hint: 'A trusted certificate without a domain of your own', placeholder: 'acme.duckdns.org' },
  { key: 'tunnel', label: 'Cloudflare tunnel', hint: 'Your domain through Cloudflare; no port opened', placeholder: 'goalgetter.company.com' },
  { key: 'files', label: 'A certificate from IT', hint: 'Two files from your IT department', placeholder: 'goalgetter.company.com' },
  { key: 'off', label: 'Plain HTTP', hint: 'This computer and TVs only; no Microsoft sign-in elsewhere', placeholder: '' },
];

export function wayLabel(way: Way): string {
  return WAYS.find((w) => w.key === way)?.label ?? way;
}

/** The way the saved settings amount to. */
export function wayOf(settings: Pick<HttpsSettings, 'on' | 'front_door' | 'certificate' | 'dns_provider'>): Way {
  if (!settings.on) return 'off';
  if (settings.front_door === 'cloudflare') return 'tunnel';
  if (settings.certificate === 'letsencrypt') return settings.dns_provider === 'duckdns' ? 'duckdns' : 'company';
  return settings.certificate === 'files' ? 'files' : 'internal';
}

/** What Undo goes back to, in a few words. */
export function undoLabel(undo: NonNullable<HttpsSettings['undo_to']>): string {
  if (!undo.on) return 'Plain HTTP';
  const way: Way =
    undo.choice === 'cloudflare' ? 'tunnel' : undo.choice === 'letsencrypt' ? 'company' : (undo.choice as Way);
  return `${wayLabel(way)} · ${undo.host}`;
}

export function addressOf(host: string, port: number, way: Way): string {
  // Through Cloudflare people reach Cloudflare, on 443 like any site.
  return `https://${host}${port === 443 || way === 'tunnel' ? '' : `:${port}`}`;
}
