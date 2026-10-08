import { dayAndTime } from '../time';
import { useEffect, useRef, useState } from 'react';

import {
  dataSources,
  type Permission,
  type Provider,
  type SetupStart,
} from '../dataSources';
import ConnectorMark from './connectorMark';
import CopyField from './CopyField';
import Field from './Field';

/**
 * Connecting this deployment to a provider. Once, ever, per provider.
 *
 * **The one manual step in the whole integration story**, and it exists because
 * there is no hosted relay: GoalGetter runs on somebody else's server, so there is
 * no central service holding a Google client secret on their behalf. Every OAuth
 * provider requires the *software* to be identified before it will issue tokens,
 * and the callback address to be registered in advance — which is precisely what
 * stops somebody redirecting your authorisation code to their own server.
 *
 * **One form, one credential, everything it powers.** Signing in and reading a
 * spreadsheet used to be two forms on this page asking for the same client id and
 * the same secret from the same Entra app registration, neither aware of the
 * other. One app registration holds several redirect URIs and asks for scopes per
 * request, so it is one connection here.
 *
 * So the job is to make five minutes of console-clicking as short as possible:
 * numbered steps, a link straight to the right page, and **every** redirect URI and
 * permission presented with a copy button rather than described. A mismatched
 * redirect URI is the single most common failure, and the error a provider returns
 * for it does not say what it expected.
 *
 * **The steps come from the server.** They used to be a table in this file, which
 * meant the permissions an admin was told to grant lived in a different language
 * from the scopes actually requested. Now both come from `app/providers.py`, so
 * they cannot disagree.
 *
 * **And for Microsoft, most admins should never read them.** `QuickSetup` below
 * does the whole thing — see `app/entra.py` — leaving the form underneath it as
 * the path for a tenant that refuses, an admin without the role, and every
 * provider that cannot register itself. It stays first-class rather than becoming
 * a hidden fallback: a setup that only works when the happy path works is a setup
 * that strands people.
 *
 * Used in two places, deliberately the same component: inline in the connect flow
 * the first time somebody needs it, and on the Integrations page afterwards for
 * rotating a secret. Two forms would be two things to keep in step.
 */
export default function ProviderSetup({
  provider,
  onSaved,
  onForgotten,
  compact = false,
}: {
  provider: Provider;
  onSaved: (saved: Provider) => void;
  /**
   * The credential was removed. Absent in the connect flow, where there is
   * nothing to disconnect yet — which is also what hides the button there.
   */
  onForgotten?: () => void;
  /** Inside the connect flow, where the surrounding page already has a heading. */
  compact?: boolean;
}) {
  const [clientId, setClientId] = useState(provider.client_id ?? '');
  const [secret, setSecret] = useState('');
  const [tenant, setTenant] = useState(provider.tenant_id ?? '');
  const [issuer, setIssuer] = useState(provider.issuer ?? '');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // **The whole shape of this panel turns on one value.** Before there is a
  // credential it is a set of instructions; after, it is a status and a way out.
  // Showing both at once is what made a finished connection look unfinished.
  const connected = provider.client_secret_set && onForgotten !== undefined;
  const needsSecret = !provider.client_secret_set;
  const wantsTenant = provider.tenant_label !== '';
  const wantsIssuer = provider.issuer_required;

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const result = await dataSources.saveProvider(provider.provider, {
        client_id: clientId.trim(),
        // Omitted entirely when untouched, so saving a corrected client id does
        // not blank the stored secret. The API refuses an empty string rather
        // than treating it as "keep", so this has to be an omission.
        ...(secret ? { client_secret: secret } : {}),
        // These two are always sent when the provider asks for them: unlike the
        // secret they are readable, so the form shows the stored value and an
        // empty box genuinely means "clear it".
        ...(wantsTenant ? { tenant_id: tenant.trim() } : {}),
        ...(wantsIssuer ? { issuer: issuer.trim() } : {}),
      });
      setSecret('');
      onSaved(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save that.');
    } finally {
      setBusy(false);
    }
  }

  const credentials = (
    <form
      className="mt-5 space-y-4 border-t border-edge pt-5"
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      {wantsTenant && (
        <Field
          label={provider.tenant_label}
          value={tenant}
          onChange={setTenant}
          maxLength={200}
          hint={provider.tenant_hint}
        />
      )}
      {wantsIssuer && (
        <Field
          label="Issuer URL"
          value={issuer}
          onChange={setIssuer}
          maxLength={500}
          hint="The base URL its /.well-known/openid-configuration sits under."
        />
      )}
      <Field label="Client ID" value={clientId} onChange={setClientId} maxLength={500} />
      <Field
        label="Client secret"
        type="password"
        value={secret}
        onChange={setSecret}
        autoComplete="new-password"
        required={needsSecret}
        maxLength={2000}
        hint={
          provider.client_secret_set
            ? 'A secret is stored. Leave this empty to keep it.'
            : 'Copied from the provider. Stored encrypted and never shown again.'
        }
      />

      {error && (
        <p role="alert" className="rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="submit"
          disabled={busy || !clientId.trim() || (needsSecret && !secret)}
          className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy ? 'Saving…' : provider.client_secret_set ? 'Save' : 'Connect'}
        </button>
      </div>
    </form>
  );

  return (
    <div className="rounded-lg border border-edge bg-surface p-5">
      {!compact && (
        <div className="mb-4 flex items-center gap-3">
          <ConnectorMark connector={provider.provider} className="size-7" />
          <div>
            <p className="font-medium text-content">{provider.provider_name}</p>
            <p className="text-xs text-content-subtle">
              {connected ? 'Connected' : 'Not connected yet'}
            </p>
          </div>
        </div>
      )}

      {connected ? (
        <>
          <Connected provider={provider} onForgotten={onForgotten} />

          {/* **A connected provider still needs this.** Its permissions are not
              frozen: upgrading GoalGetter can add a capability, and the
              registration made before that upgrade asks for nothing on its
              behalf — which surfaces later as a 403 from an API call, pointing at
              nothing in particular. Re-running is idempotent by design: the same
              application is updated rather than duplicated, and a fresh secret is
              appended rather than replacing the working one.

              Hidden behind a disclosure rather than absent, because it is a
              repair rather than a step. */}
          {provider.bootstrap && (
            <details className="mt-5 border-t border-edge pt-4">
              <summary className="cursor-pointer text-sm text-content-muted hover:text-content">
                Re-run automatic setup
              </summary>
              <p className="mt-2 text-sm text-content-muted">
                Brings the application up to date with everything this connection
                now powers, and issues a fresh secret. Use it if a permission is
                being refused, or after an upgrade adds a capability. The existing
                application is updated, not replaced.
              </p>
              <QuickSetup provider={provider} onSaved={onSaved} />
            </details>
          )}

          {/* Behind a disclosure, because rotating a secret is a real thing
              somebody comes here to do and a rare one. Left open by default it
              would put two empty credential boxes under a working connection,
              which reads as "this is not finished" on a screen whose whole job
              is saying that it is. */}
          <details className="mt-5 border-t border-edge pt-4">
            <summary className="cursor-pointer text-sm text-content-muted hover:text-content">
              Update credentials
            </summary>
            <p className="mt-2 text-sm text-content-muted">
              For rotating the client secret, or correcting the client ID. Leave the
              secret empty to keep the stored one.
            </p>
            {credentials}
          </details>
        </>
      ) : (
        <>
          <p className="text-sm text-content-muted">
            Done <strong>once for the whole deployment</strong>, not per source — and
            one application covers everything this connection is used for.
          </p>

          {provider.bootstrap && (
            <>
              <QuickSetup provider={provider} onSaved={onSaved} />

              {/* A heading rather than a collapse. The manual path is not a hidden
                  fallback: three ordinary situations end up here — a tenant blocking
                  device sign-in, a tenant restricting Microsoft's own client, and an
                  admin without the role — and none of them should have to go looking
                  for it. */}
              <div className="mt-6 border-t border-edge pt-5">
                <p className="font-medium text-content">Or set it up by hand</p>
                <p className="mt-1 text-sm text-content-muted">
                  Same result, done in the admin console — for a directory that
                  refuses the above, or an account without the role.
                </p>
              </div>
            </>
          )}

          {provider.setup_steps.length > 0 && (
            <ol className="mt-4 list-decimal space-y-1 pl-5 text-sm text-content-muted">
              {provider.setup_steps.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ol>
          )}

          <div className="mt-4 space-y-4">
            <CopyField
              label={
                provider.redirect_uris.length > 1
                  ? 'Redirect URIs — add all of these'
                  : 'Redirect URI — paste this into the provider'
              }
              value={provider.redirect_uris.join('\n')}
              hint="They must match exactly. A mismatch is the most common setup failure, and the provider's error will not say what it expected."
            />
            {provider.permissions.length > 0 && <Permissions provider={provider} />}
          </div>

          {provider.where_to_get_it && (
            <a
              href={provider.where_to_get_it}
              target="_blank"
              rel="noreferrer noopener"
              className="mt-3 inline-block text-sm text-brand hover:underline"
            >
              Open the {provider.provider_name} console →
            </a>
          )}

          {credentials}
        </>
      )}
    </div>
  );
}

/**
 * A connection that is working, said in as few words as it takes.
 *
 * **Everything that got somebody here is gone from this view.** The setup steps,
 * both redirect URIs, the permission table, the client id and the secret box were
 * all still on screen after connecting, which made a finished job look unfinished
 * — and buried the two things somebody actually returns for: what this is doing,
 * and how to stop it.
 *
 * What replaces them is the capability list, which is the honest answer to "what
 * is it sharing?" — and it is read off the features themselves rather than off
 * this connection, so it cannot claim something the rest of the product disagrees
 * with.
 */
function Connected({
  provider,
  onForgotten,
}: {
  provider: Provider;
  onForgotten?: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const active = provider.capabilities.filter((c) => c.active);

  async function disconnect() {
    setBusy(true);
    setError(null);
    try {
      await dataSources.forgetProvider(provider.provider);
      onForgotten?.();
    } catch (e) {
      setBusy(false);
      setError(e instanceof Error ? e.message : 'Could not disconnect.');
    }
  }

  return (
    <div className="rounded-lg border border-success bg-success/5 p-4">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <p className="font-medium text-content">
          <span aria-hidden>✓ </span>Connected
        </p>
      </div>
      {/* The identifiers, for whoever is talking to Microsoft support — out of
          the way of everybody else (review #10). */}
      {(provider.tenant_id || provider.client_id) && (
        <details className="mt-1 text-xs text-content-subtle">
          <summary className="cursor-pointer">Details</summary>
          {provider.tenant_id && <p className="mt-1">Tenant <code>{provider.tenant_id}</code></p>}
          {provider.client_id && <p>Application <code>{provider.client_id}</code></p>}
        </details>
      )}

      <p className="mt-2 text-sm text-content-muted">
        {active.length > 0 ? 'Currently sharing' : 'Nothing is using it yet'}
      </p>
      {active.length > 0 && (
        <ul className="mt-1 space-y-1 text-sm">
          {active.map((capability) => (
            <li key={capability.key} className="flex items-start gap-2 text-content">
              <span aria-hidden className="mt-px w-4 shrink-0 text-center">
                ✓
              </span>
              <span className="min-w-0">{capability.name}</span>
            </li>
          ))}
        </ul>
      )}

      {/* What it *could* do, greyed. Without this a connection powering only
          sign-in looks like all there is, and the switches below it read as
          decoration. */}
      {provider.capabilities.some((c) => !c.active && c.built) && (
        <p className="mt-2 text-xs text-content-subtle">
          Available and off:{' '}
          {provider.capabilities
            .filter((c) => !c.active && c.built)
            .map((c) => c.name)
            .join(', ')}
          .
        </p>
      )}

      {provider.last_used_at && (
        <p className="mt-2 text-xs text-content-subtle">
          Last used {dayAndTime(provider.last_used_at)}
        </p>
      )}

      {/* **The question this view was missing.** The capability list above says
          what is switched on; this says what the application is *allowed* to do,
          which is the one somebody comes back months later to audit. Collapsed,
          because it is a question asked rarely and answered in detail. */}
      {provider.permissions.length > 0 && (
        <div className="mt-3">
          <Permissions provider={provider} />
        </div>
      )}

      {error && (
        <p role="alert" className="mt-3 rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      {confirming ? (
        <div className="mt-4 rounded-md border border-danger/50 bg-danger/5 p-3">
          <p className="text-sm text-content">
            Remove the stored credential for {provider.provider_name}?
          </p>
          {/* Said plainly because it is the surprising part, and because the
              alternative — cutting live sources off the moment somebody tidies up
              this screen — would be worse. Their tokens outlive the credential
              and then stop, which is a delayed failure somebody deserves warning
              about. */}
          <p className="mt-1 text-sm text-content-muted">
            Sign-in through {provider.provider_name} stops immediately. Data sources
            already connected keep working until their access expires, then fail —
            they are not removed. Reconnecting later needs the client ID and a new
            secret, or another run of the automatic setup.
          </p>
          <div className="mt-3 flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => void disconnect()}
              disabled={busy}
              className="rounded-md bg-danger px-3 py-2 text-sm font-medium text-white transition-colors hover:opacity-90 disabled:opacity-50"
            >
              {busy ? 'Disconnecting…' : 'Disconnect'}
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              disabled={busy}
              className="rounded-md px-3 py-2 text-sm text-content-muted transition-colors hover:text-content"
            >
              Keep it
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setConfirming(true)}
          className="mt-4 rounded-md border border-edge px-3 py-2 text-sm text-content-muted transition-colors hover:border-danger hover:text-danger"
        >
          Disconnect
        </button>
      )}
    </div>
  );
}

/**
 * What this connection turns on, and what each part costs in permissions.
 *
 * **A disclosure, grouped by feature, rather than a flat list always open.** Nine
 * permission strings under a heading answers "what do I paste into Entra" — a
 * question only the manual path asks, and the automatic one never does. The
 * question everybody has is *what am I switching on*, and the feature names answer
 * it in four lines.
 *
 * So the summary is the four features, and the strings are one click away for
 * whoever is standing in the admin console needing them.
 *
 * **The three pills survive the move**, because each is a thing that goes wrong
 * silently. `Files.Read.All` exists in Entra twice, once delegated and once as an
 * application permission, on different tabs, meaning different things — and this
 * integration has since shipped a registration holding the wrong one, which
 * consents cleanly, shows green, and is invisible to the token that needs it.
 * *admin consent* is a separate button nobody presses unless told. *optional*
 * says which ones can be declined with the feature still working, which is not
 * guessable from a name.
 */
function Permissions({ provider }: { provider: Provider }) {
  const consented = provider.permissions.some((p) => p.admin_consent);
  const optional = provider.permissions.some((p) => p.optional);

  // Grouped in the order the server sent them, which is catalogue order — so the
  // list reads sign-in, data, directory, mail rather than alphabetically.
  const features: { name: string; permissions: Permission[] }[] = [];
  for (const permission of provider.permissions) {
    const existing = features.find((f) => f.name === permission.needed_for);
    if (existing) existing.permissions.push(permission);
    else features.push({ name: permission.needed_for, permissions: [permission] });
  }

  return (
    <details className="rounded-md border border-edge">
      <summary className="cursor-pointer px-3 py-2 text-sm text-content">
        What this enables
        <span className="ml-2 text-xs text-content-subtle">
          {features.length} feature{features.length === 1 ? '' : 's'},{' '}
          {provider.permissions.length} permission
          {provider.permissions.length === 1 ? '' : 's'}
        </span>
      </summary>

      <div className="border-t border-edge px-3 py-2">
        {features.map((feature) => (
          <div key={feature.name} className="border-b border-edge py-2 last:border-0">
            <p className="text-sm text-content">{feature.name}</p>
            <ul className="mt-1 space-y-1">
              {feature.permissions.map((permission) => (
                <li
                  key={`${permission.kind}:${permission.name}`}
                  className="flex flex-wrap items-baseline gap-x-2 gap-y-1"
                >
                  <code className="min-w-0 break-all text-xs text-content-muted">
                    {permission.name}
                  </code>
                  {permission.kind && (
                    <span className="rounded-full bg-surface-hover px-2 py-0.5 text-xs text-content-muted">
                      {permission.kind}
                    </span>
                  )}
                  {permission.admin_consent && (
                    <span className="rounded-full bg-warning/15 px-2 py-0.5 text-xs text-warning">
                      admin consent
                    </span>
                  )}
                  {permission.optional && (
                    <span className="rounded-full bg-surface-hover px-2 py-0.5 text-xs text-content-subtle">
                      optional
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        ))}

        <p className="mt-2 text-xs text-content-subtle">
          {consented
            ? 'Adding these by hand? Press Grant admin consent afterwards — anything marked "admin consent" does nothing until you do, and delegated is not the same permission as application.'
            : 'Exactly what this connection asks for, and nothing more.'}
          {optional &&
            ' Optional ones can be declined; the feature works without them, with less.'}
        </p>
      </div>
    </details>
  );
}

/**
 * Creating the app registration instead of describing how to create one.
 *
 * **Two sentences and a button, by design.** An earlier version of this panel
 * explained everything it was about to do in four bullets before offering the
 * button, and reading it took longer than the setup does. What somebody needs in
 * order to decide is small: what appears in their directory, and whether they are
 * allowed to do it. Everything else — the scope list, whose name is on the consent
 * screen, why that name is not ours — matters only to the person who asks, so it
 * is one disclosure away rather than in front of everybody.
 *
 * The fine print is still *there*, and that is deliberate too. This asks an admin
 * to grant an application permission to write to their directory; hiding what it
 * asks for would be the wrong kind of clean.
 */
const STALLED_AFTER_SECONDS = 60;

function QuickSetup({
  provider,
  onSaved,
}: {
  provider: Provider;
  onSaved: (saved: Provider) => void;
}) {
  const bootstrap = provider.bootstrap!;
  const [code, setCode] = useState<SetupStart | null>(null);
  const [done, setDone] = useState<{ granted: string[]; pending: string[] } | null>(
    null,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Seconds spent waiting. **Not decoration.** A directory that has never granted
  // the setup consent refuses nothing — the admin lands on Microsoft's ordinary
  // user prompt and the code is simply never approved — so without this the panel
  // says "waiting" for a quarter of an hour and then blames the expiry.
  const [waited, setWaited] = useState(0);
  //: Which way the sync and mail will sign in. **Chosen before provisioning,
  //: because it decides what goes on the registration** — the two permission
  //: sets cannot share one, since consent is all-or-nothing and an admin who can
  //: grant every delegated permission can grant no app role.
  const [mode, setMode] = useState('application');


  // Polling outlives any single render and must stop when the panel closes —
  // otherwise a modal dismissed mid-flow keeps asking Microsoft about a code
  // nobody is entering, for a quarter of an hour.
  const live = useRef(true);
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
    };
  }, []);

  async function begin() {
    setBusy(true);
    setError(null);
    setDone(null);
    setWaited(0);
    try {
      const started = await dataSources.startSetup(provider.provider, mode);
      setCode(started);
      void poll(started);
    } catch (e) {
      setBusy(false);
      setError(e instanceof Error ? e.message : 'Could not start that.');
    }
  }

  async function poll(started: SetupStart) {
    // Microsoft's own interval and expiry, not ours. Polling faster than it asks
    // earns a rate limit; expiring sooner than it does would look like a bug.
    const until = Date.now() + started.expires_in * 1000;

    while (live.current && Date.now() < until) {
      await new Promise((resume) => setTimeout(resume, started.interval * 1000));
      if (!live.current) return;
      setWaited((seconds) => seconds + started.interval);

      try {
        const result = await dataSources.pollSetup(provider.provider);
        if (result.status === 'done' && result.provider) {
          setBusy(false);
          setCode(null);
          setDone({ granted: result.granted, pending: result.pending });
          onSaved(result.provider);
          return;
        }
      } catch (e) {
        // Declined, expired, or refused by the directory — all terminal, and all
        // worth showing beside the manual steps rather than retrying into.
        setBusy(false);
        setCode(null);
        setError(e instanceof Error ? e.message : 'That sign-in did not complete.');
        return;
      }
    }

    if (live.current) {
      setBusy(false);
      setCode(null);
      setError('That code expired before it was used. Start again.');
    }
  }

  if (done) {
    return (
      <div className="mt-4 rounded-lg border border-success bg-success/5 p-4">
        <p className="text-sm text-content">
          <span aria-hidden>✓ </span>
          <strong>{bootstrap.app_name}</strong> is registered in your directory.
          Nothing below needs filling in, and{' '}
          <strong>single sign-on works now</strong> — it needs nothing further.
        </p>

        {done.pending.length > 0 && (
          // Not an error, and phrased so nobody reads it as one: everything that
          // could be granted was.
          <p className="mt-2 text-sm text-content-muted">
            {done.pending.join(', ')} could not be consented to by this account.
            Everything else is working.
          </p>
        )}

        {/* **Nothing further for sync either.** It acts as the application
            rather than as an account, so the registration and its consent are the
            whole of it. There was a "choose the sync account" step here while the
            permissions were delegated; it bought an expiry date and no security,
            and it is gone.

            Mail is the exception and asks below, because sending as a shared
            mailbox genuinely wants a person's Send As rights behind it. */}
        <p className="mt-2 text-sm text-content-muted">
          {mode === 'delegated'
            ? 'One more step below: sign in the account the sync and mail act as.'
            : 'Tenant user sync and email are ready to switch on below.'}
        </p>
      </div>
    );
  }

  return (
    <div className="mt-4 rounded-lg border border-brand/40 bg-brand/5 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <p className="font-medium text-content">Set up automatically</p>
        <span className="rounded-full bg-brand/15 px-2 py-0.5 text-xs text-brand">
          Recommended
        </span>
      </div>

      <p className="mt-1.5 text-sm text-content-muted">
        Creates the application in your Microsoft directory — permissions, redirect
        URIs, admin consent and the client secret. Nothing to copy back.
      </p>

      {/* The one requirement worth interrupting for, because it is the only one
          somebody can fail on. "Active" carries real weight: a role held through
          Privileged Identity Management does nothing until it is activated, and
          until then Microsoft treats the holder as an ordinary user. */}
      <p className="mt-2 text-sm text-content">
        Needs an <strong>active {bootstrap.minimum_role}</strong> role — if yours
        comes from Privileged Identity Management, activate it first.
      </p>

      {/* **The one decision that cannot be changed afterwards without redoing
          this.** Both work; they fail differently, and which is right depends on
          a fact about the person setting it up — whether a Privileged Role
          Administrator is reachable. Asking is better than choosing for them and
          being wrong in a way that surfaces days later. */}
      <fieldset className="mt-3">
        <legend className="text-sm text-content">How should this sign in?</legend>
        <div className="mt-2 space-y-2">
          <label className="flex items-start gap-2 text-sm">
            <input
              type="radio"
              name="auth-mode"
              value="application"
              checked={mode === 'application'}
              onChange={() => setMode('application')}
              className="mt-1 accent-[var(--gg-brand)]"
            />
            <span>
              <span className="text-content">As the application</span>
              <span className="block text-xs text-content-muted">
                Nothing to sign in, nothing to expire, survives people leaving.
                Needs a <strong>Privileged Role Administrator</strong> to press
                consent once — a Cloud Application Administrator cannot.
              </span>
            </span>
          </label>
          <label className="flex items-start gap-2 text-sm">
            <input
              type="radio"
              name="auth-mode"
              value="delegated"
              checked={mode === 'delegated'}
              onChange={() => setMode('delegated')}
              className="mt-1 accent-[var(--gg-brand)]"
            />
            <span>
              <span className="text-content">As a service account</span>
              <span className="block text-xs text-content-muted">
                A <strong>{bootstrap.minimum_role}</strong> can set this up alone,
                start to finish. Costs one sign-in, and stops if that account is
                disabled or its password is reset.
              </span>
            </span>
          </label>
        </div>
      </fieldset>

      <details className="group mt-3">
        <summary className="cursor-pointer text-sm text-content-muted hover:text-content">
          What you&rsquo;ll approve
        </summary>
        <div className="mt-2 space-y-2 border-l border-edge pl-3 text-sm text-content-muted">
          <p>
            {bootstrap.scopes.map((scope, index) => (
              <span key={scope}>
                {index > 0 && ', '}
                <code className="break-all text-content">{scope}</code>
              </span>
            ))}{' '}
            — used once to create the application, then discarded.
          </p>
          {/* Said in advance because it genuinely looks wrong otherwise. The
              sign-in runs as Microsoft's own tooling, which is what removes the
              need for anything to have been registered before this point. */}
          <p>
            The consent screen says <strong>{bootstrap.consent_name}</strong>, not
            GoalGetter. That is Microsoft&rsquo;s own command-line client, and
            using it is what lets this work with nothing registered first.
          </p>
          {bootstrap.consent_url && (
            <p>
              The first time in a directory this needs a one-time tenant consent.
              Your role can grant it, but the sign-in screen cannot offer it — the
              link appears with the code.
            </p>
          )}
        </div>
      </details>

      {code ? (
        <div className="mt-3 rounded-md border border-edge bg-surface p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="font-mono text-2xl tracking-[0.25em] text-content">
              {code.user_code}
            </p>
            <a
              href={code.verification_uri}
              target="_blank"
              rel="noreferrer noopener"
              className="rounded-md bg-brand px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover"
            >
              Open Microsoft sign-in &rarr;
            </a>
          </div>

          <div className="mt-3">
            <CopyField label="Code" value={code.user_code} />
          </div>

          <p className="mt-3 text-xs text-content-subtle" role="status">
            Waiting for you to finish signing in&hellip; this page finishes on its
            own. The code lasts about {Math.round(code.expires_in / 60)} minutes.
          </p>

          {bootstrap.consent_url && (
            /* **The one failure that does not look like one.** Until a directory
               has granted this consent, an admin entering the code lands on
               Microsoft's ordinary user prompt — "ask an admin to grant
               permission" — with no way to grant it, even though their role
               allows it. Nothing is refused, so the code is never approved and
               the panel would otherwise wait until it expired.

               One line by default; it earns more room only once the silence has
               gone on long enough to mean something. */
            <p
              className={`mt-3 rounded-md px-3 py-2 text-xs ${
                waited >= STALLED_AFTER_SECONDS
                  ? 'bg-warning/10 text-content'
                  : 'text-content-subtle'
              }`}
            >
              {waited >= STALLED_AFTER_SECONDS
                ? 'Still nothing? This is almost always the reason — '
                : 'Microsoft says “Need admin approval”? '}
              <a
                href={bootstrap.consent_url}
                target="_blank"
                rel="noreferrer noopener"
                className="text-brand hover:underline"
              >
                grant this directory&rsquo;s one-time consent
              </a>
              , then start again. It is not a sign your account lacks the role.
            </p>
          )}
        </div>
      ) : (
        <button
          type="button"
          onClick={() => void begin()}
          disabled={busy}
          className="mt-3 rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy ? 'Starting…' : 'Create app registration'}
        </button>
      )}

      {error && (
        <p
          role="alert"
          className="mt-3 rounded-md border border-danger px-3 py-2 text-sm text-danger"
        >
          {error} You can still set this up by hand below.
        </p>
      )}
    </div>
  );
}
