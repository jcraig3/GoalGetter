import { useCallback, useEffect, useState, type ReactNode } from 'react';

import { api, ApiError } from '../api';
import CertificateFiles from './CertificateFiles';
import CopyValue from './CopyValue';
import Field from './Field';
import {
  addressOf,
  undoLabel,
  wayLabel,
  wayOf,
  WAYS,
  type Check,
  type HttpsSettings,
  type Way,
} from './hostingWays';

type Step = 'how' | 'setup' | 'trying' | 'done';

const DOT: Record<Check['state'], string> = {
  ok: 'bg-success',
  warn: 'bg-warning',
  fail: 'bg-danger',
  wait: 'bg-content-subtle animate-pulse',
};

const PRIMARY =
  'rounded-md bg-brand px-4 py-1.5 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50';
const SECONDARY =
  'rounded-md border border-edge px-4 py-1.5 text-sm text-content transition-colors hover:bg-surface-hover disabled:opacity-50';

function message(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

/**
 * Changing how people reach GoalGetter, guided (Phase 22).
 *
 * **How → Set up → Try it.** Choose a way; fill in only what it needs, with
 * what has to be done outside GoalGetter as a checklist the server ticks off
 * where it can; then switch over **on trial**: the new setup runs beside the
 * old one, so nothing that worked stops working, while live checks — and this
 * very device — say whether it works. Keep makes it final; Undo, or fifteen
 * minutes without Keep, puts the old one back.
 */
export default function HostingChange({
  onChanged,
  onClose,
}: {
  /** After anything was switched, kept or undone, so the card looks again. */
  onChanged: () => void;
  onClose: () => void;
}) {
  const [saved, setSaved] = useState<HttpsSettings | null>(null);
  const [step, setStep] = useState<Step>('how');
  const [way, setWay] = useState<Way>('internal');
  const [host, setHost] = useState('');
  const [token, setToken] = useState('');
  const [email, setEmail] = useState('');
  const [tunnelToken, setTunnelToken] = useState('');
  const [checks, setChecks] = useState<Check[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const take = useCallback((found: HttpsSettings) => {
    setSaved(found);
    setWay(wayOf(found));
    setHost(found.host);
    setToken('');
    setEmail(found.acme_email);
    setTunnelToken('');
    setChecks(null);
  }, []);

  useEffect(() => {
    api<HttpsSettings>('/api/hosting/https')
      .then((found) => {
        take(found);
        if (found.trial_until) setStep('trying');
      })
      .catch((error) => setProblem(message(error, 'Couldn’t load the hosting settings.')));
  }, [take]);

  if (!saved) {
    return problem ? <p className="border-t border-edge px-4 py-3 text-sm text-danger">{problem}</p> : null;
  }

  if (saved.front_door === 'windows') {
    return (
      <div className="border-t border-edge px-4 py-3 text-sm">
        <p className="text-content">HTTPS is handled by the Windows front door.</p>
        <p className="mt-0.5 text-xs text-content-subtle">
          Its installer sets it up and removes it, as the Windows front door guide describes.
        </p>
      </div>
    );
  }

  const letsEncrypt = way === 'company' || way === 'duckdns';
  const provider = way === 'company' ? 'cloudflare' : way === 'duckdns' ? 'duckdns' : '';
  const name = host.trim().toLowerCase();

  function body() {
    return {
      on: way !== 'off',
      host: host.trim(),
      front_door: way === 'tunnel' ? 'cloudflare' : '',
      // A tunnel or plain HTTP leaves Caddy's certificate choice as it was.
      certificate: letsEncrypt ? 'letsencrypt' : way === 'files' || way === 'internal' ? way : saved!.certificate,
      dns_provider: provider,
      // Empty keeps a saved token; tokens are never sent back to be shown.
      dns_api_token: letsEncrypt && token.trim() ? token.trim() : null,
      acme_email: letsEncrypt ? email.trim() : '',
      tunnel_token: way === 'tunnel' && tunnelToken.trim() ? tunnelToken.trim() : null,
    };
  }

  async function check() {
    setBusy(true);
    setProblem(null);
    try {
      const found = await api<{ checks: Check[] }>('/api/hosting/check', {
        method: 'POST',
        body: JSON.stringify({ ...body(), seen_at: window.location.hostname }),
      });
      setChecks(found.checks);
    } catch (error) {
      setProblem(message(error, 'Couldn’t check that.'));
    } finally {
      setBusy(false);
    }
  }

  async function act(path: string, init: RequestInit, then: (settings: HttpsSettings) => void) {
    setBusy(true);
    setProblem(null);
    setNote(null);
    try {
      const result = await api<{ settings: HttpsSettings; problem: string | null }>(path, init);
      take(result.settings);
      if (result.problem) setProblem(`HTTPS didn’t take it: ${result.problem}`);
      then(result.settings);
      onChanged();
    } catch (error) {
      setProblem(message(error, 'Couldn’t do that.'));
    } finally {
      setBusy(false);
    }
  }

  async function clearWebAddress() {
    setBusy(true);
    setProblem(null);
    try {
      setSaved(await api<HttpsSettings>('/api/hosting/web-address', { method: 'DELETE' }));
      onChanged();
    } catch (error) {
      setProblem(message(error, 'Couldn’t clear the web address.'));
    } finally {
      setBusy(false);
    }
  }

  const switchOver = () =>
    act('/api/hosting/https', { method: 'PUT', body: JSON.stringify({ ...body(), trial: true }) }, () =>
      setStep('trying'),
    );
  const keep = () => act('/api/hosting/keep', { method: 'POST' }, () => setStep('done'));
  const undo = (trial: boolean) =>
    act('/api/hosting/undo', { method: 'POST', body: JSON.stringify({ trial }) }, (settings) => {
      if (trial) {
        setStep('trying');
      } else {
        setStep('how');
        setNote(`Undone. Back to ${settings.on ? `${wayLabel(wayOf(settings))} · ${settings.host}` : 'Plain HTTP'}.`);
      }
    });

  return (
    <div className="space-y-4 border-t border-edge px-4 py-4 text-sm">
      <Steps step={step} />

      {step === 'how' && (
        <How
          saved={saved}
          way={way}
          onWay={(next) => {
            setWay(next);
            setChecks(null);
          }}
          onNext={() => {
            setNote(null);
            setStep('setup');
          }}
          onUndo={() => void undo(true)}
          onClose={onClose}
          busy={busy}
          note={note}
        />
      )}

      {step === 'setup' && (
        <Setup
          saved={saved}
          way={way}
          host={host}
          onHost={(value) => {
            setHost(value);
            setChecks(null);
          }}
          token={token}
          onToken={(value) => {
            setToken(value);
            setChecks(null);
          }}
          email={email}
          onEmail={setEmail}
          tunnelToken={tunnelToken}
          onTunnelToken={(value) => {
            setTunnelToken(value);
            setChecks(null);
          }}
          onUploaded={(settings) => {
            setSaved(settings);
            setChecks(null);
          }}
          onClearWebAddress={() => void clearWebAddress()}
          checks={checks}
          busy={busy}
          ready={way === 'off' || name !== ''}
          onBack={() => setStep('how')}
          onCheck={() => void check()}
          onSwitch={() => void switchOver()}
        />
      )}

      {step === 'trying' && (
        <Trying
          saved={saved}
          busy={busy}
          onKeep={() => void keep()}
          onUndo={() => void undo(false)}
          onEnded={() =>
            // Undone by itself, or decided in .env: look again.
            api<HttpsSettings>('/api/hosting/https').then((found) => {
              take(found);
              setStep('how');
              setNote('The change wasn’t kept in time, so it was undone.');
              onChanged();
            })
          }
        />
      )}

      {step === 'done' && <Done saved={saved} onClose={onClose} />}

      {problem && <p className="text-danger">{problem}</p>}
    </div>
  );
}

function Steps({ step }: { step: Step }) {
  const order: [Step, string][] = [
    ['how', 'How'],
    ['setup', 'Set up'],
    ['trying', 'Try it'],
  ];
  const at = step === 'done' ? 3 : order.findIndex(([key]) => key === step);
  return (
    <ol className="flex gap-4 text-xs" aria-label="Steps">
      {order.map(([key, label], index) => (
        <li
          key={key}
          aria-current={index === at ? 'step' : undefined}
          className={index === at ? 'font-medium text-content' : index < at ? 'text-content-muted' : 'text-content-subtle'}
        >
          {index + 1} {label}
        </li>
      ))}
    </ol>
  );
}

// ── 1 How ────────────────────────────────────────────────────────────────────

function How({
  saved,
  way,
  onWay,
  onNext,
  onUndo,
  onClose,
  busy,
  note,
}: {
  saved: HttpsSettings;
  way: Way;
  onWay: (way: Way) => void;
  onNext: () => void;
  onUndo: () => void;
  onClose: () => void;
  busy: boolean;
  note: string | null;
}) {
  const now = wayOf(saved);
  return (
    <>
      {note && <p className="text-success">{note}</p>}
      <fieldset>
        <legend className="mb-2 text-content-muted">How will people reach GoalGetter?</legend>
        <div className="grid gap-2 sm:grid-cols-2">
          {WAYS.map((option) => (
            <label
              key={option.key}
              className={`flex cursor-pointer items-start gap-2 rounded-md border p-3 transition-colors ${
                way === option.key ? 'border-brand bg-brand-subtle' : 'border-edge hover:bg-surface-hover'
              }`}
            >
              <input
                type="radio"
                name="way"
                className="mt-1"
                checked={way === option.key}
                onChange={() => onWay(option.key)}
              />
              <span>
                <span className="text-content">{option.label}</span>
                {option.key === now && <span className="ml-2 text-xs text-content-subtle">now</span>}
                <span className="block text-xs text-content-subtle">{option.hint}</span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>

      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={onNext} className={PRIMARY}>
          Next
        </button>
        <button type="button" onClick={onClose} className={SECONDARY}>
          Close
        </button>
        {saved.undo_to && (
          <button
            type="button"
            onClick={onUndo}
            disabled={busy}
            className="ml-auto text-xs text-content-muted hover:text-content hover:underline"
          >
            {saved.undo_to.redo ? 'Redo' : 'Undo last change'}: back to {undoLabel(saved.undo_to)}
          </button>
        )}
      </div>

      <EnvNote saved={saved} />
      <OtherSetups />
    </>
  );
}

/** Whether `.env` and the app are kept in step, and what to do when not (P7-2). */
function EnvNote({ saved }: { saved: HttpsSettings }) {
  if (saved.env_connected) {
    return <p className="text-xs text-content-subtle">Kept in step with .env, both ways.</p>;
  }
  if (!saved.env_readable) {
    return <p className="text-xs text-content-subtle">No .env found: changes are kept in GoalGetter only.</p>;
  }
  return (
    <div className="text-xs text-warning">
      <p>GoalGetter can read .env but not write it: edits there are followed, changes here aren’t written to it.</p>
      <p className="mt-1 text-content-subtle">To fix it on Linux, in the GoalGetter folder:</p>
      <div className="mt-1">
        <CopyValue text="sudo chown 1000 .env" />
      </div>
    </div>
  );
}

function OtherSetups() {
  return (
    <details>
      <summary className="cursor-pointer text-content-muted">Other setups</summary>
      <ul className="mt-2 space-y-3">
        <li>
          <span className="text-content">Your own proxy</span>
          <span className="block text-xs text-content-subtle">
            IIS, nginx or a load balancer: point it at this server’s port 8080, then Advanced → A proxy in front →
            Yes.
          </span>
        </li>
        <li>
          <span className="text-content">The Windows front door</span>
          <span className="block text-xs text-content-subtle">
            Per-device limits on a Windows server. In the GoalGetter folder, as administrator:
          </span>
          <div className="mt-1 text-xs">
            <CopyValue text="powershell -ExecutionPolicy Bypass -File windows\install-front-door.ps1" />
          </div>
        </li>
      </ul>
    </details>
  );
}

// ── 2 Set up ─────────────────────────────────────────────────────────────────

function Setup({
  saved,
  way,
  host,
  onHost,
  token,
  onToken,
  email,
  onEmail,
  tunnelToken,
  onTunnelToken,
  onUploaded,
  onClearWebAddress,
  checks,
  busy,
  ready,
  onBack,
  onCheck,
  onSwitch,
}: {
  saved: HttpsSettings;
  way: Way;
  host: string;
  onHost: (value: string) => void;
  token: string;
  onToken: (value: string) => void;
  email: string;
  onEmail: (value: string) => void;
  tunnelToken: string;
  onTunnelToken: (value: string) => void;
  onUploaded: (settings: HttpsSettings) => void;
  onClearWebAddress: () => void;
  checks: Check[] | null;
  busy: boolean;
  ready: boolean;
  onBack: () => void;
  onCheck: () => void;
  onSwitch: () => void;
}) {
  const option = WAYS.find((w) => w.key === way)!;
  const name = host.trim().toLowerCase() || option.placeholder;
  const address = addressOf(name, saved.https_port, way);
  const found = (key: string) => checks?.find((c) => c.key === key);
  const failed = checks?.some((c) => c.state === 'fail') ?? false;
  const savedToken =
    saved.has_dns_api_token && saved.dns_provider === (way === 'duckdns' ? 'duckdns' : 'cloudflare');
  const ports = saved.https_port === 443 && saved.http_port === 80 ? '443,80' : `${saved.https_port},${saved.http_port}`;

  return (
    <>
      <p className="text-content">
        {option.label}{' '}
        <button type="button" onClick={onBack} className="ml-1 text-xs text-brand hover:underline">
          Change
        </button>
      </p>

      {way === 'off' ? (
        <p className="text-content-muted">
          HTTPS turns off. This computer and TVs keep working at the plain address, port {saved.app_port}.
        </p>
      ) : (
        <>
          <Field
            label="Name"
            value={host}
            onChange={onHost}
            placeholder={option.placeholder}
            allow={/^[A-Za-z0-9.-]*$/}
            maxLength={253}
            hint="What people type to open GoalGetter"
          />

          {(way === 'company' || way === 'duckdns') && (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field
                label={way === 'company' ? 'Cloudflare API token' : 'DuckDNS token'}
                type="password"
                value={token}
                onChange={onToken}
                autoComplete="off"
                required={!savedToken}
                placeholder={savedToken ? 'Saved' : undefined}
                hint={way === 'company' ? 'My Profile → API Tokens → Edit zone DNS' : 'At the top of duckdns.org'}
              />
              <Field
                label="Email (optional)"
                type="email"
                value={email}
                onChange={onEmail}
                required={false}
                hint="Let’s Encrypt writes here if a renewal fails"
              />
            </div>
          )}

          {way === 'files' && <CertificateFiles files={saved.files} onUploaded={onUploaded} />}

          {way === 'tunnel' && (
            <Field
              label="Tunnel token"
              type="password"
              value={tunnelToken}
              onChange={onTunnelToken}
              autoComplete="off"
              required={!saved.has_tunnel_token}
              placeholder={saved.has_tunnel_token ? 'Saved' : 'Paste the install command, or just the token'}
              hint={saved.tunnel_id ? `Tunnel ${saved.tunnel_id.slice(0, 8)}…` : undefined}
            />
          )}

          <div>
            <p className="mb-2 text-content-muted">Outside GoalGetter</p>
            <ul className="space-y-2.5">
              {way === 'tunnel' ? (
                <>
                  <Item>
                    In Cloudflare: <b className="font-normal text-content">Zero Trust → Networks → Tunnels → Create a tunnel</b>,
                    type Cloudflared.
                  </Item>
                  <Item check={found('tunnel_token')}>Copy the install command it shows into Tunnel token above.</Item>
                  <Item check={found('dns')}>
                    Under Public hostname, add {name} with service:
                    <div className="mt-1">
                      <CopyValue text="http://web:81" />
                    </div>
                  </Item>
                </>
              ) : (
                <>
                  <Item check={found('dns')}>
                    {way === 'duckdns'
                      ? `On duckdns.org, ${name} points at this server’s address`
                      : `A DNS record: ${name} → this server’s address`}
                  </Item>
                  {(way === 'company' || way === 'duckdns') && (
                    <Item check={found('token')}>
                      {way === 'company'
                        ? 'A Cloudflare API token that may edit this domain’s DNS'
                        : 'Your DuckDNS token'}
                    </Item>
                  )}
                  {way === 'files' && <Item check={found('files')}>Certificate files that cover {name}</Item>}
                  <Item>
                    Ports {ports.replace(',', ' and ')} open to your network
                    <details className="mt-1 text-xs">
                      <summary className="cursor-pointer text-content-subtle">Commands</summary>
                      <div className="mt-1 space-y-1">
                        <span className="block text-content-subtle">Windows, PowerShell as administrator</span>
                        <CopyValue
                          text={`New-NetFirewallRule -DisplayName GoalGetter -Direction Inbound -Protocol TCP -LocalPort ${ports} -Action Allow -Profile Domain,Private`}
                        />
                        <span className="block text-content-subtle">Linux</span>
                        <CopyValue text={`sudo ufw allow ${ports}/tcp`} />
                      </div>
                    </details>
                  </Item>
                </>
              )}
              {saved.web_address_override && saved.web_address_override !== address ? (
                <Item>
                  <span className="text-warning">
                    Advanced → Web address is {saved.web_address_override}; links and Microsoft sign-in keep using it.
                  </span>
                  <button
                    type="button"
                    onClick={onClearWebAddress}
                    disabled={busy}
                    className="mt-1 block text-xs text-brand hover:underline"
                  >
                    Use the HTTPS address instead
                  </button>
                </Item>
              ) : (
                <Item>
                  If people sign in with Microsoft, add in Azure → Authentication:
                  <div className="mt-1">
                    <CopyValue text={`${address}/api/auth/sso/callback`} />
                  </div>
                </Item>
              )}
            </ul>
          </div>
        </>
      )}

      {checks && checks.length > 0 && checks.every((c) => c.state === 'ok') && (
        <p className="text-success">Everything checked is ready.</p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {way !== 'off' && checks === null ? (
          <button type="button" onClick={onCheck} disabled={busy || !ready} className={PRIMARY}>
            {busy ? 'Checking…' : 'Check'}
          </button>
        ) : (
          <button type="button" onClick={onSwitch} disabled={busy || !ready} className={PRIMARY}>
            {busy ? 'Switching…' : failed ? 'Switch over anyway' : 'Switch over'}
          </button>
        )}
        {way !== 'off' && checks !== null && (
          <button type="button" onClick={onCheck} disabled={busy} className={SECONDARY}>
            Check again
          </button>
        )}
        <button type="button" onClick={onBack} className={SECONDARY}>
          Back
        </button>
        <span className="ml-auto text-xs text-content-subtle">Tried first; nothing that works now stops working.</span>
      </div>
    </>
  );
}

/** One thing to do, with how the check of it came out. */
function Item({ check, children }: { check?: Check; children: ReactNode }) {
  return (
    <li className="flex items-start gap-2">
      <span
        aria-hidden="true"
        className={`mt-1.5 size-2 shrink-0 rounded-full ${check ? DOT[check.state] : 'border border-edge'}`}
      />
      <span className="min-w-0 flex-1 text-content">
        {children}
        {check && (
          <span
            className={`block text-xs ${check.state === 'fail' ? 'text-danger' : check.state === 'warn' ? 'text-warning' : 'text-content-subtle'}`}
          >
            {check.label}
            {check.detail ? ` · ${check.detail}` : ''}
          </span>
        )}
      </span>
    </li>
  );
}

// ── 3 Try it ─────────────────────────────────────────────────────────────────

function useCountdown(until: string | null): string | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  if (!until) return null;
  const left = Math.max(0, Math.round((new Date(until).getTime() - now) / 1000));
  return `${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`;
}

/** Whether this device can open the address: its DNS, the firewall, and its
 *  trust in the certificate, all at once. */
async function opensHere(address: string): Promise<boolean> {
  const stop = new AbortController();
  const timer = setTimeout(() => stop.abort(), 4000);
  try {
    // no-cors: the answer can't be read from another address, but it arriving
    // at all is the point — a failure is a refused name, port or certificate.
    await fetch(`${address}/api/health`, { mode: 'no-cors', cache: 'no-store', signal: stop.signal });
    return true;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

function Trying({
  saved,
  busy,
  onKeep,
  onUndo,
  onEnded,
}: {
  saved: HttpsSettings;
  busy: boolean;
  onKeep: () => void;
  onUndo: () => void;
  onEnded: () => void;
}) {
  const way = wayOf(saved);
  const address = saved.on ? addressOf(saved.host, saved.https_port, way) : null;
  const [checks, setChecks] = useState<Check[]>([]);
  const [until, setUntil] = useState<string | null>(saved.trial_until);
  const [here, setHere] = useState<'wait' | 'ok' | 'fail'>('wait');
  const [asking, setAsking] = useState(false);
  const left = useCountdown(until);
  const failing = checks.find((c) => c.state === 'fail');

  useEffect(() => {
    let stopped = false;
    let reachable = false;
    async function look() {
      try {
        const found = await api<{ checks: Check[]; trial_until: string | null }>('/api/hosting/trial');
        if (stopped) return;
        if (!found.trial_until) {
          onEnded();
          return;
        }
        setChecks(found.checks);
        setUntil(found.trial_until);
      } catch {
        // Asked again in a moment.
      }
      if (address && !reachable) {
        reachable = await opensHere(address);
        if (!stopped) setHere(reachable ? 'ok' : 'fail');
      }
      if (!stopped) setTimeout(() => void look(), 3000);
    }
    void look();
    return () => {
      stopped = true;
    };
    // One loop for the life of the trial.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const root = `http://${saved.host}${saved.http_port === 80 ? '' : `:${saved.http_port}`}/goalgetter-root.crt`;
  const device: Check = {
    key: 'device',
    state: here,
    label:
      here === 'ok' ? 'Opens from this device' : here === 'fail' ? 'Doesn’t open from this device yet' : 'Opening it from this device…',
    detail:
      here === 'fail'
        ? way === 'internal'
          ? 'This device may not trust GoalGetter’s certificate yet, the name may not be in its DNS, or a firewall blocks the port.'
          : 'The name may not be in this device’s DNS yet, or a firewall blocks the port.'
        : null,
  };

  return (
    <>
      <p className="text-content">
        Trying {saved.on ? `${wayLabel(way)} · ${saved.host}` : 'Plain HTTP'}
        {left && <span className="ml-2 text-xs text-content-subtle">undone by itself in {left} unless kept</span>}
      </p>
      <p className="text-xs text-content-muted">Until you keep it, everything that worked before still works.</p>

      {address ? (
        <ul className="space-y-2.5">
          {checks.map((c) => (
            <Item key={c.key} check={c}>
              {null}
            </Item>
          ))}
          <Item check={device}>{null}</Item>
          {here === 'fail' && way === 'internal' && (
            <li className="pl-4 text-xs">
              <a href={root} className="text-brand hover:underline">
                Download the root certificate
              </a>
            </li>
          )}
        </ul>
      ) : (
        <p className="text-content-muted">Keep it to turn HTTPS off. Until then the HTTPS address still answers.</p>
      )}

      {address && (
        <a href={address} target="_blank" rel="noreferrer" className="inline-block text-brand hover:underline">
          Open {address}
        </a>
      )}

      {asking && failing ? (
        <div className="space-y-2">
          <p className="text-danger">{failing.label}. Keep it anyway?</p>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" onClick={onKeep} disabled={busy} className={PRIMARY}>
              Keep anyway
            </button>
            <button type="button" onClick={() => setAsking(false)} className={SECONDARY}>
              Not yet
            </button>
            <button type="button" onClick={onUndo} disabled={busy} className={SECONDARY}>
              Undo
            </button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          {/* Asked first when the server's own check says it isn't working (P7-7). */}
          <button type="button" onClick={failing ? () => setAsking(true) : onKeep} disabled={busy} className={PRIMARY}>
            Keep
          </button>
          <button type="button" onClick={onUndo} disabled={busy} className={SECONDARY}>
            Undo
          </button>
        </div>
      )}
    </>
  );
}

function Done({ saved, onClose }: { saved: HttpsSettings; onClose: () => void }) {
  const address = saved.on ? addressOf(saved.host, saved.https_port, wayOf(saved)) : null;
  const plain = `http://${window.location.hostname}:${saved.app_port}`;
  return (
    <>
      <p className="text-success">
        {address ? `Kept. GoalGetter is at ${address}.` : 'Kept. HTTPS is off.'}
      </p>
      <p className="text-xs text-content-muted">
        {address
          ? `The plain address, port ${saved.app_port}, now serves TVs only.`
          : 'GoalGetter is at its plain address again.'}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {address && window.location.origin !== address ? (
          <a href={address} className={PRIMARY}>
            Open {address}
          </a>
        ) : !address && window.location.origin !== plain ? (
          <a href={plain} className={PRIMARY}>
            Open {plain}
          </a>
        ) : null}
        <button type="button" onClick={onClose} className={SECONDARY}>
          Close
        </button>
      </div>
    </>
  );
}
