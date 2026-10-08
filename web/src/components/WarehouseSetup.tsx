import { useEffect, useRef, useState } from 'react';

import Field from './Field';
import { Tab } from './Tabs';
import { warehouse, type WarehouseStatus } from '../warehouse';

/**
 * Connecting the warehouse, once, before any query is written.
 *
 * **The same shape as `ProviderSetup`, and for the same reason.** Six answers —
 * account, username, key, passphrase, warehouse, role — belong to the deployment,
 * not to the table somebody happens to be connecting. Asking them again for the
 * second query would be five of six repeated, and five chances for two sources to
 * disagree about which warehouse they mean.
 *
 * So this appears in place the first time it is needed, and disappears once
 * saved. Adding the fourth table is then a name and a query.
 *
 * **The key can be uploaded or pasted, and is text either way.** A `.p8` is a PEM
 * file; the browser reads an uploaded one and posts its contents exactly as a
 * pasted one would be. One endpoint, and the two paths cannot drift apart.
 *
 * **Two ways in, because one of them needs an admin.** A private key means
 * running `ALTER USER` in Snowflake, which most people setting this up for the
 * first time cannot do to their own account. A programmatic access token they can
 * issue themselves — so it is how a connection gets proven, and the key is what
 * it should end up on. The form says so rather than leaving both looking equal.
 *
 * **It is write-only once stored.** The API reports whether a credential is set
 * and never what it is, the same as every other secret here.
 */
export default function WarehouseSetup({
  onConnected,
  compact = false,
  canDisconnect = false,
}: {
  /** Called with the new status whenever it is saved. */
  onConnected?: (status: WarehouseStatus) => void;
  /** Inside the connect flow, where the page already has a heading. */
  compact?: boolean;
  /**
   * Whether to offer disconnecting.
   *
   * **Off in the query wizard.** The same component appears there as context —
   * "this is what your query will run against" — and a button that severs the
   * connection for every source in the deployment has no business sitting beside
   * a half-written query. Disconnecting is a deployment decision, so it lives
   * where the deployment is managed.
   */
  canDisconnect?: boolean;
}) {
  const [status, setStatus] = useState<WarehouseStatus | null>(null);
  const [account, setAccount] = useState('');
  const [username, setUsername] = useState('');
  const [wh, setWh] = useState('');
  const [role, setRole] = useState('');
  const [database, setDatabase] = useState('');

  // **Only sent when touched.** Left alone, the stored credential stays — an
  // admin fixing a typo in the warehouse name must not have to find the .p8
  // again.
  const [key, setKey] = useState('');
  const [passphrase, setPassphrase] = useState('');
  const [keyName, setKeyName] = useState('');
  const [token, setToken] = useState('');

  // Which credential this form is offering to set. Follows what is stored, so
  // reopening a token connection does not present an empty key box as the state
  // of things.
  const [method, setMethod] = useState<'key' | 'token'>('key');

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [probe, setProbe] = useState<{ ok: boolean; detail: string } | null>(
    null,
  );
  const [editing, setEditing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const file = useRef<HTMLInputElement>(null);

  const load = () =>
    warehouse
      .read()
      .then((next) => {
        setStatus(next);
        setAccount(next.account);
        setUsername(next.username);
        setWh(next.warehouse);
        setRole(next.role);
        setDatabase(next.database);
        setMethod(next.token_set ? 'token' : 'key');
        return next;
      })
      .catch(() => setStatus(null));

  useEffect(() => {
    void load();
  }, []);

  if (status === null) return null;

  // Already on the status: how many sources hang off this connection, which is
  // the only number that makes disconnecting a decision rather than a guess.
  const queries = status.queries;

  if (!status.available) {
    return (
      <p className="rounded-md border border-warning px-3 py-2 text-sm text-warning">
        This build does not ship the Snowflake driver, so a connection here
        could never run. Rebuild the API image with{' '}
        <code>--build-arg API_EXTRAS=&quot;[snowflake]&quot;</code>.
      </p>
    );
  }

  async function save() {
    setBusy(true);
    setError(null);
    setProbe(null);
    try {
      const next = await warehouse.save({
        account: account.trim(),
        username: username.trim(),
        warehouse: wh.trim(),
        role: role.trim(),
        database: database.trim(),
        // Omitted entirely when untouched — the API treats absent as "keep".
        // Only the selected method is ever sent: storing one credential clears
        // the others server-side, so sending both would make which one wins
        // depend on the order the API happens to apply them.
        ...(method === 'token'
          ? token.trim()
            ? { token: token.trim() }
            : {}
          : key
            ? { private_key: key, key_passphrase: passphrase }
            : {}),
      });
      setKey('');
      setKeyName('');
      setToken('');
      setEditing(false);
      setStatus(next);
      onConnected?.(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save that.');
    } finally {
      setBusy(false);
    }
  }

  async function test() {
    setBusy(true);
    setProbe(null);
    try {
      setProbe(await warehouse.test());
    } catch (e) {
      setProbe({
        ok: false,
        detail: e instanceof Error ? e.message : 'Could not reach it.',
      });
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    setBusy(true);
    setError(null);
    try {
      await warehouse.forget();
      setConfirming(false);
      setEditing(false);
      setProbe(null);
      const next = await load();
      if (next) onConnected?.(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not disconnect.');
    } finally {
      setBusy(false);
    }
  }

  async function readFile(chosen: File) {
    setKeyName(chosen.name);
    setKey(await chosen.text());
    setError(null);
  }

  // Connected and not being edited: say so in one line and get out of the way.
  if (status.connected && !editing) {
    return (
      <div className="rounded-lg border border-edge bg-surface p-4">
        <div className="flex flex-wrap items-center gap-3">
          <span aria-hidden className="text-success">
            ✓
          </span>
          <div className="min-w-40 flex-1">
            <p className="text-sm text-content">
              Connected to <strong>{status.account}</strong> as{' '}
              {status.username}
            </p>
            <p className="text-xs text-content-subtle">
              {[
                status.warehouse && `warehouse ${status.warehouse}`,
                status.role && `role ${status.role}`,
                status.database && `database ${status.database}`,
                status.private_key_set
                  ? 'key-pair'
                  : status.token_set
                    ? 'access token'
                    : 'password',
              ]
                .filter(Boolean)
                .join(' · ')}
            </p>
            {status.token_set && (
              <p className="mt-1 text-xs text-warning">
                Access tokens expire, and one issued with a network-policy
                bypass can stop working sooner. Move this to a private key
                before people rely on it.
              </p>
            )}
          </div>
          <button
            type="button"
            onClick={() => void test()}
            disabled={busy}
            className="shrink-0 rounded-md border border-edge px-3 py-2 text-sm text-content transition-colors hover:bg-surface-hover disabled:opacity-50"
          >
            {busy ? 'Checking…' : 'Test'}
          </button>
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="shrink-0 text-xs text-content-muted underline transition-colors hover:text-content"
          >
            Change
          </button>
          {canDisconnect && (
            <button
              type="button"
              onClick={() => setConfirming(true)}
              className="shrink-0 text-xs text-content-muted underline transition-colors hover:text-danger"
            >
              Disconnect
            </button>
          )}
        </div>

        {/* **What it costs, before the button that does it.** Forgetting the
            credential leaves every query in place — their SQL and their column
            mappings are still correct and expensive to rebuild — so the honest
            warning is that they stop running, not that they are lost. */}
        {confirming && (
          <div className="mt-3 rounded-md border border-danger p-3">
            <p className="text-sm font-medium text-content">
              Disconnect this warehouse?
            </p>
            <p className="mt-1 text-sm text-content-muted">
              {queries === 0
                ? 'Nothing is reading from it yet.'
                : `${queries} ${queries === 1 ? 'query stops' : 'queries stop'} running at the next sync.`}{' '}
              The {queries === 1 ? 'query itself is' : 'queries themselves are'}{' '}
              kept, along with everything already imported — reconnecting starts
              them again. You will need the credential once more.
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
        )}

        {error && (
          <p
            role="alert"
            className="mt-3 rounded-md border border-danger px-3 py-2 text-sm text-danger"
          >
            {error}
          </p>
        )}

        {probe && (
          <p
            role="status"
            className={`mt-3 rounded-md border px-3 py-2 text-sm ${
              probe.ok
                ? 'border-success text-success'
                : 'border-danger text-danger'
            }`}
          >
            {probe.detail}
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-edge bg-surface p-4">
      {!compact && (
        <p className="mb-4 text-sm text-content-muted">
          Done <strong>once for the whole deployment</strong>. Every query you
          add afterwards runs against this connection.
        </p>
      )}

      <div className="space-y-4">
        <Field
          label="Account identifier"
          value={account}
          onChange={setAccount}
          maxLength={200}
          placeholder="ab12345.us-east-1"
          hint="Required. From your Snowflake URL, without .snowflakecomputing.com."
        />
        <Field
          label="Username"
          value={username}
          onChange={setUsername}
          maxLength={200}
          hint="Required. A role with read access — GoalGetter never writes."
        />

        {/* **Two credentials, not two equal credentials.** A key needs `ALTER
            USER`, which whoever is setting this up often cannot run on their own
            account; a token they can mint themselves. So the token is how this
            gets proven and the key is where it should land, and the form says
            which is which rather than presenting a neutral pair. */}
        <div>
          <span className="block text-sm text-content">Authenticate with</span>
          <div className="mt-1 flex gap-2">
            <Tab active={method === 'key'} onClick={() => setMethod('key')}>
              Private key
            </Tab>
            <Tab active={method === 'token'} onClick={() => setMethod('token')}>
              Access token
            </Tab>
          </div>
        </div>

        {method === 'key' ? (
          <div>
            <label className="block text-sm text-content" htmlFor="wh-key">
              Private key
            </label>
            <p className="mt-1 text-xs text-content-subtle">
              The <code>.p8</code> file Snowflake was given the public half of.
              {status.private_key_set && !key
                ? ' One is stored — leave this empty to keep it.'
                : ''}
            </p>

            <div className="mt-2 flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={() => file.current?.click()}
                className="rounded-md border border-edge px-3 py-2 text-sm text-content transition-colors hover:bg-surface-hover"
              >
                Upload a file
              </button>
              <input
                ref={file}
                type="file"
                accept=".p8,.pem,.key,text/plain"
                hidden
                onChange={(e) => {
                  const chosen = e.target.files?.[0];
                  if (chosen) void readFile(chosen);
                }}
              />
              <span className="text-xs text-content-subtle">
                {keyName ? `${keyName} — ready to save` : 'or paste it below'}
              </span>
            </div>

            <textarea
              id="wh-key"
              value={key}
              onChange={(e) => {
                setKey(e.target.value);
                setKeyName('');
              }}
              rows={4}
              spellCheck={false}
              placeholder="-----BEGIN PRIVATE KEY-----&#10;…&#10;-----END PRIVATE KEY-----"
              className="mt-2 w-full rounded-md border border-edge bg-bg px-3 py-2 font-mono text-xs text-content outline-none placeholder:text-content-subtle focus:border-brand"
            />

            <div className="mt-4">
              <Field
                label="Key passphrase"
                type="password"
                value={passphrase}
                onChange={setPassphrase}
                maxLength={500}
                autoComplete="new-password"
                hint="Only if the key file is encrypted. Most are not."
              />
            </div>
          </div>
        ) : (
          <div>
            <Field
              label="Access token"
              type="password"
              value={token}
              onChange={setToken}
              maxLength={4000}
              autoComplete="new-password"
              hint={
                status.token_set && !token
                  ? 'One is stored — leave this empty to keep it. Snowflake → your profile → Programmatic access tokens.'
                  : 'Snowflake → your profile → Programmatic access tokens.'
              }
            />

            {/* **The warning belongs next to the field, not in a doc nobody
                reads.** A token is the easy way in and the one that stops
                working by itself, so the moment somebody chooses it is the
                moment to say what they are choosing. */}
            <p className="mt-3 rounded-md border border-warning px-3 py-2 text-xs text-warning">
              <strong>Tokens are temporary.</strong> They expire, and one
              created with the “grant temporary access” network-policy bypass
              can stop working sooner still — syncs then fail until somebody
              issues another. Good for proving the connection works.{' '}
              <strong>A private key is the one to keep.</strong> It needs{' '}
              <code>ALTER USER</code> in Snowflake, so it is worth asking
              whoever administers your account for a service user once you know
              this reads what you want.
            </p>
          </div>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="Warehouse"
            value={wh}
            onChange={setWh}
            maxLength={200}
            placeholder="ANALYTICS_WH"
            hint="Recommended. Blank inherits the user’s default, which may not exist — naming one makes a failed test mean the credential, not the setup."
          />
          <Field
            label="Role"
            value={role}
            onChange={setRole}
            maxLength={200}
            hint="Optional. Blank uses the user’s default role."
          />
        </div>

        <Field
          label="Database"
          value={database}
          onChange={setDatabase}
          maxLength={200}
          hint="Optional. Just the name, like ANALYTICS — the query comes in step 2."
        />
      </div>

      {error && (
        <p
          role="alert"
          className="mt-4 rounded-md border border-danger px-3 py-2 text-sm text-danger"
        >
          {error}
        </p>
      )}

      <div className="mt-5 flex flex-wrap items-center gap-3 border-t border-edge pt-4">
        <button
          type="button"
          onClick={() => void save()}
          disabled={
            busy ||
            !account.trim() ||
            !username.trim() ||
            // **Judged per method, not across all of them.** A connection stored
            // by key, switched to the token tab and saved with the box empty,
            // would otherwise save happily and go on authenticating by key —
            // the form claiming one thing and the driver doing another.
            (method === 'token'
              ? !status.token_set && !token.trim()
              : !status.private_key_set && !status.password_set && !key.trim())
          }
          className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
        >
          {busy ? 'Saving…' : status.connected ? 'Save' : 'Connect'}
        </button>
        {status.connected && (
          <button
            type="button"
            onClick={() => {
              setEditing(false);
              void load();
            }}
            className="rounded-md border border-edge px-4 py-2 text-sm text-content-muted transition-colors hover:bg-surface-hover hover:text-content"
          >
            Cancel
          </button>
        )}
      </div>
    </div>
  );
}
