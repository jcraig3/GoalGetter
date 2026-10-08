import { useCallback, useEffect, useState, type ReactNode } from 'react';

import { api } from '../api';
import CopyValue from './CopyValue';
import HostingChange from './HostingChange';
import type { TunnelStatus } from './hostingWays';

export interface Hosting {
  https: boolean;
  https_address: string | null;
  certificate: 'internal' | 'letsencrypt' | 'files' | 'cloudflare' | null;
  root_certificate_url: string | null;
  tv_address: string | null;
  sso_redirect: string;
  addresses_visible?: boolean;
  you_appear_as: string | null;
  connection: 'visible' | 'docker' | 'unknown';
  front_door: string | null;
  sign_in_limits: number[];
  web_address: string;
  web_address_from: 'settings' | 'https' | 'env';
  certificate_valid_until: string | null;
  certificate_issuer: string | null;
  proxies_seen?: number;
  /** Through a Cloudflare tunnel: whether it is connected (Phase 21). */
  tunnel?: TunnelStatus | null;
  /** A change on trial, waiting to be kept or undone (Phase 22). */
  trial_until?: string | null;
  /** nginx's plain port, which TVs use. */
  app_port?: number;
}

const CERTIFICATE: Record<string, string> = {
  internal: 'GoalGetter’s own certificate',
  letsencrypt: 'Let’s Encrypt',
  files: 'Your certificate files',
  cloudflare: 'Cloudflare',
};

const FROM: Record<Hosting['web_address_from'], string> = {
  settings: 'set under Advanced',
  https: 'from HTTPS',
  env: 'from the server’s .env',
};

type Tone = 'good' | 'warn' | 'bad' | 'none';
const DOT: Record<Tone, string> = {
  good: 'bg-success',
  warn: 'bg-warning',
  bad: 'bg-danger',
  none: 'bg-content-subtle',
};

/** Days until a date; negative once it has passed. */
function daysUntil(iso: string): number {
  return Math.floor((new Date(iso).getTime() - Date.now()) / 86_400_000);
}

function longDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}

/**
 * How GoalGetter is reached, at a glance (Phase 19).
 *
 * **One card, one line per fact, a dot for how it stands.** It replaced a
 * stack of explanatory boxes: what people need is whether it is working, and
 * the one thing to copy. Detail is a click away, never on the page.
 */
export default function HostingOverview({
  onLoaded,
}: {
  /** For the Advanced section's proxy choice, which checks against it. */
  onLoaded?: (hosting: Hosting) => void;
} = {}) {
  const [hosting, setHosting] = useState<Hosting | null>(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    try {
      const found = await api<Hosting>('/api/hosting');
      setHosting(found);
      onLoaded?.(found);
      // A change waiting to be kept or undone opens where that is decided.
      if (found.trial_until) setEditing(true);
    } catch {
      setHosting(null);
    } finally {
      setBusy(false);
    }
    // Once per mount; ↻ asks again.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (!hosting) return null;

  const [perAccount, perDevice] = hosting.sign_in_limits;
  const local = /\/\/(localhost|127\.)/.test(hosting.web_address);
  const seen = hosting.connection === 'visible';
  const perDeviceOn = seen || Boolean(hosting.addresses_visible);
  const days = hosting.certificate_valid_until ? daysUntil(hosting.certificate_valid_until) : null;
  // GoalGetter's own certificates last hours and are renewed long before
  // they run out: a date would always look about to expire.
  const selfRenewing = hosting.certificate === 'internal';

  return (
    <div className="space-y-4">
      <section className="rounded-lg border border-edge">
        <header className="flex items-center justify-between gap-3 border-b border-edge px-4 py-3">
          <h2 className="text-sm font-medium text-content">How GoalGetter is reached</h2>
          <button
            type="button"
            onClick={() => setEditing((was) => !was)}
            aria-expanded={editing}
            className="rounded-md border border-edge px-3 py-1 text-sm text-content transition-colors hover:bg-surface-hover"
          >
            Change
          </button>
        </header>

        <dl className="divide-y divide-edge text-sm">
          <Row
            tone={hosting.https ? 'good' : local ? 'none' : 'warn'}
            label="Address"
            value={<span className="font-mono">{hosting.web_address}</span>}
            note={FROM[hosting.web_address_from]}
          />
          <Row
            tone={hosting.https ? 'good' : 'warn'}
            label="HTTPS"
            value={
              hosting.https
                ? `On · ${hosting.certificate ? CERTIFICATE[hosting.certificate] : ''}`
                : 'Off'
            }
            note={hosting.https ? undefined : 'Needed for other computers and Microsoft sign-in'}
          />
          {hosting.tunnel && (
            <Row
              tone={hosting.tunnel.state === 'connected' ? 'good' : hosting.tunnel.state === 'connecting' ? 'warn' : 'bad'}
              label="Tunnel"
              value={
                hosting.tunnel.state === 'connected'
                  ? 'Connected'
                  : hosting.tunnel.state === 'connecting'
                    ? 'Connecting…'
                    : 'Not connected'
              }
              note={
                hosting.tunnel.state === 'connected'
                  ? `${hosting.tunnel.connections} connections to Cloudflare`
                  : (hosting.tunnel.problem ?? undefined)
              }
            />
          )}
          {hosting.https && (
            <Row
              tone={days === null ? 'none' : days < 0 ? 'bad' : days < 14 && !selfRenewing ? 'warn' : 'good'}
              label="Certificate"
              value={
                hosting.certificate_valid_until
                  ? days !== null && days < 0
                    ? `Expired ${longDate(hosting.certificate_valid_until)}`
                    : selfRenewing
                      ? 'Renewed automatically'
                      : `Valid until ${longDate(hosting.certificate_valid_until)}`
                  : 'Not reachable yet'
              }
              note={hosting.certificate_issuer ?? undefined}
            />
          )}
          <Row
            tone={perDeviceOn ? 'good' : 'warn'}
            label="Sign-in limits"
            value={perDeviceOn ? 'Per device and per account' : 'Per account only'}
            note={
              perDeviceOn
                ? `${perDevice} per device · ${perAccount} per account, in 5 min`
                : 'This server can’t see devices’ addresses'
            }
          />
          <Row
            tone={seen ? 'good' : 'none'}
            label="You appear as"
            value={
              seen ? <span className="font-mono">{hosting.you_appear_as}</span> : 'Unknown'
            }
            note={
              seen
                ? undefined
                : hosting.connection === 'docker'
                  ? 'Hidden by Docker'
                  : 'No address to see'
            }
            action={
              <button
                type="button"
                onClick={() => void load()}
                disabled={busy}
                aria-label="Check again"
                title="Check again"
                className="rounded p-1 text-content-muted transition-colors hover:bg-surface-hover hover:text-content disabled:opacity-50"
              >
                <span aria-hidden="true">↻</span>
              </button>
            }
          />
        </dl>

        {editing && <HostingChange onChanged={() => void load()} onClose={() => setEditing(false)} />}
      </section>

      {hosting.https && (hosting.root_certificate_url || hosting.tv_address || hosting.certificate === 'cloudflare') && (
        <section className="rounded-lg border border-edge">
          <h2 className="border-b border-edge px-4 py-3 text-sm font-medium text-content">For devices and TVs</h2>
          <dl className="divide-y divide-edge text-sm">
            {hosting.root_certificate_url && (
              <Row
                label="Root certificate"
                value={
                  <a href={hosting.root_certificate_url} className="text-brand hover:underline">
                    Download
                  </a>
                }
                note={<TrustSteps />}
              />
            )}
            {hosting.tv_address && (
              <Row label="TVs" value={<CopyValue text={`${hosting.tv_address}/pair`} />} />
            )}
            {hosting.certificate === 'cloudflare' && (
              <Row label="TVs" value={`The HTTPS address, or the server’s own address :${hosting.app_port ?? 8080}/pair`} />
            )}
          </dl>
        </section>
      )}

      <section className="rounded-lg border border-edge">
        <dl className="text-sm">
          <Row label="Microsoft redirect" value={<CopyValue text={hosting.sso_redirect} />} note="Add in Azure → Authentication" />
        </dl>
      </section>
    </div>
  );
}

function Row({
  tone,
  label,
  value,
  note,
  action,
}: {
  tone?: Tone;
  label: string;
  value: ReactNode;
  note?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-start gap-3 px-4 py-3">
      {tone ? (
        <span aria-hidden="true" className={`mt-1.5 size-2 shrink-0 rounded-full ${DOT[tone]}`} />
      ) : (
        <span aria-hidden="true" className="size-2 shrink-0" />
      )}
      <dt className="w-32 shrink-0 text-content-muted">{label}</dt>
      <dd className="min-w-0 flex-1">
        <div className="break-words text-content">{value}</div>
        {note && <div className="mt-0.5 text-xs text-content-subtle">{note}</div>}
      </dd>
      {action}
    </div>
  );
}

function TrustSteps() {
  return (
    <details>
      <summary className="cursor-pointer text-brand">How to trust it</summary>
      <ul className="mt-1 space-y-0.5">
        <li>Company PCs: IT pushes it as a trusted root (Group Policy or Intune)</li>
        <li>Windows: open it → Install → Local Machine → Trusted Root Certification Authorities</li>
        <li>Mac: open it in Keychain Access → System → Always Trust</li>
        <li>iPhone: install the profile, then General → About → Certificate Trust Settings</li>
        <li>Android: Security → Encryption & credentials → Install a certificate → CA</li>
      </ul>
    </details>
  );
}
