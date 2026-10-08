/**
 * The integrations API, in one place.
 *
 * Types *and* paths. Two pages read this API — the connect flow and a source's
 * own page — and a wire type declared twice is a wire type that drifts, while a
 * path written in eight places is eight chances to typo one. Everything here is
 * a thin call: no state, no caching, nothing clever.
 */

import { api } from './api';

export interface ConnectorOption {
  key: string;
  display_name: string;
  /** JSON Schema for the non-secret settings form. */
  config_schema: Record<string, unknown>;
  /** JSON Schema for the secrets form. */
  credential_schema: Record<string, unknown>;
  /** True when it is posted to rather than polled — an endpoint, not a form. */
  receives: boolean;
  /**
   * Present when this connector signs in to a provider, so setup shows a button
   * instead of a box to paste a token into.
   */
  oauth: { provider: string; provider_name: string } | null;
  /** How to get the credentials, in numbered steps. Empty when there is nothing
   *  to explain — a webhook generates its own. */
  setup_steps: string[];
}

export interface Mapping {
  id: number;
  metric_id: number;
  metric_name: string;
  enabled: boolean;
  value_field: string | null;
  occurred_at_field: string | null;
  subject_field: string;
  external_id_field: string | null;
  /** One fact per row per day, instead of one fact per row. */
  snapshot_daily: boolean;
  filters: Filter[];
  multiplier: string;
}

export interface Filter {
  field: string;
  op: string;
  value: string;
}

export interface Run {
  id: number;
  trigger: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  rows_read: number;
  rows_written: number;
  rows_quarantined: number;
  rows_skipped: number;
  conflicts: number;
  error: string | null;
}

export interface Source {
  id: number;
  name: string;
  connector: string;
  connector_name: string;
  enabled: boolean;
  config: Record<string, unknown>;
  interval_minutes: number;
  backfill_days: number;
  timezone: string | null;
  next_run_at: string | null;
  last_run_at: string | null;
  last_status: string | null;
  failure_count: number;
  credentials_set: boolean;
  connector_missing: boolean;
  /** Removed from the list; its facts still point here for provenance. */
  archived: boolean;
  /**
   * False means setup was never finished — a draft.
   *
   * Distinct from a source that was finished and later paused, which looks
   * identical from outside. Drafts are hidden and swept after a day.
   */
  activated: boolean;
  mappings: Mapping[];
  pending_identities: number;
  facts_written: number;
}

export interface SourceDetail extends Source {
  recent_runs: Run[];
  /**
   * Present only for a connector that is posted to rather than polled.
   *
   * The one credential the API returns, because an address nobody can read is an
   * address nobody can paste into their CRM. See the router's module docstring.
   */
  endpoint_url: string | null;
}

export interface SourceField {
  name: string;
  kind: string;
  samples: string[];
  /**
   * Every distinct value, when there are few enough for the column to be a
   * choice rather than data. Empty otherwise — which is how a category is told
   * apart from a name, and therefore what a column can be filtered on.
   */
  values?: string[];
}

export interface PreviewRow {
  outcome: 'written' | 'quarantined' | 'skipped' | 'error';
  source_values: Record<string, unknown>;
  subject_name: string | null;
  value: string | null;
  occurred_at: string | null;
  external_id: string | null;
  detail: string | null;
}

export interface Identity {
  id: number;
  external_identifier: string;
  pending_rows: number;
  last_seen_at: string | null;
}

export interface TestResult {
  ok: boolean;
  detail: string;
  info: Record<string, string>;
}

/**
 * One provider a connector in this build can sign in to, and whether this
 * deployment has registered an app with it yet.
 */
export interface Permission {
  name: string;
  /** 'delegated' | 'application' | '' when the provider makes no such split. */
  kind: string;
  /** Whether a tenant admin has to press "Grant admin consent" as well. */
  admin_consent: boolean;
  /** Which capability wants it, so the list explains itself. */
  needed_for: string;
  /** Whether the feature works without it, in reduced form. */
  optional: boolean;
}

export interface Capability {
  key: string;
  name: string;
  detail: string;
  /** False for something designed but not built. Shown greyed, never hidden. */
  built: boolean;
  /** Derived from the feature itself, never stored — so it cannot drift. */
  active: boolean;
}

/**
 * The offer to create the app registration instead of describing it.
 *
 * Everything here is shown *before* anybody presses anything: what gets created,
 * who is allowed to, and whose name is on the consent screen. Learning any of the
 * three from a refusal afterwards is the worst version of this.
 */
export interface Bootstrap {
  app_name: string;
  minimum_role: string;
  /** Not our name — see the panel, which explains why it is Microsoft's. */
  consent_name: string;
  /** What the setup itself asks for, not what the connection ends up with. */
  scopes: string[];
  /** The sign-in modes this provider offers. Chosen before provisioning. */
  modes: string[];
  /**
   * Where an admin grants the one-time tenant-wide consent for the setup client.
   *
   * Shown while they sign in rather than after a failure, because there is no
   * failure to react to: without this consent the sign-in ends on Microsoft's
   * ordinary user prompt and the code just never completes.
   */
  consent_url: string;
}

/** The code to enter, and where. Both the provider's, neither ours. */
export interface SetupStart {
  user_code: string;
  verification_uri: string;
  interval: number;
  expires_in: number;
}

export interface SetupPoll {
  status: 'pending' | 'done';
  provider: Provider | null;
  granted: string[];
  /** Permissions the application asks for that this admin could not consent to. */
  pending: string[];
}

export interface Provider {
  provider: string;
  provider_name: string;
  /** Which connectors need it, so the page can say what connecting unlocks. */
  used_by: string[];
  scopes: string[];
  /** The same list, described for somebody standing in the admin console. */
  permissions: Permission[];
  /** How the sync and outgoing mail authenticate: 'application' | 'delegated'. */
  auth_mode: string;

  client_id: string | null;
  /** Whether a secret is stored. Never the secret. */
  client_secret_set: boolean;
  last_used_at: string | null;

  /** Microsoft's directory id. An empty label means this provider has none. */
  tenant_id: string | null;
  tenant_label: string;
  tenant_hint: string;

  /** Where sign-in discovers the provider. Derived from the tenant where it can be. */
  issuer: string | null;
  /** True when it cannot be derived and has to be typed. */
  issuer_required: boolean;

  /** What this one credential powers. */
  capabilities: Capability[];

  /** Every callback this connection needs registered, not just one. */
  redirect_uris: string[];
  where_to_get_it: string;
  setup_steps: string[];

  /** How to skip all of the above. Null for a provider that cannot. */
  bootstrap: Bootstrap | null;
}

const ROOT = '/api/data-sources';

/** One place that knows the URL shape, so a rename is one edit. */
const at = (id: number, suffix = '') => `${ROOT}/${id}${suffix}`;

export const dataSources = {
  connectors: () => api<ConnectorOption[]>('/api/connectors'),

  list: (includeArchived = false) =>
    api<Source[]>(includeArchived ? `${ROOT}?include_archived=true` : ROOT),
  read: (id: number) => api<SourceDetail>(at(id)),

  create: (body: {
    name: string;
    connector: string;
    interval_minutes?: number;
    backfill_days?: number;
  }) => api<SourceDetail>(ROOT, { method: 'POST', body: JSON.stringify(body) }),

  update: (id: number, body: Record<string, unknown>) =>
    api<SourceDetail>(at(id), { method: 'PATCH', body: JSON.stringify(body) }),

  /** Only possible before it has imported anything. Otherwise: `archive`. */
  remove: (id: number) => api<void>(at(id), { method: 'DELETE' }),

  /**
   * Remove the integration, keep its numbers.
   *
   * Forgets the credential, disables it, and hides it. Its facts stay and keep
   * counting — the plumbing goes, the measurements do not.
   */
  archive: (id: number) =>
    api<SourceDetail>(at(id, '/archive'), { method: 'POST' }),

  /** Brings back the row, its history and its mappings — not its credential. */
  restore: (id: number) =>
    api<SourceDetail>(at(id, '/restore'), { method: 'POST' }),

  setCredentials: (id: number, secrets: Record<string, string>) =>
    api<SourceDetail>(at(id, '/credentials'), {
      method: 'PUT',
      body: JSON.stringify({ secrets }),
    }),

  disconnect: (id: number) =>
    api<SourceDetail>(at(id, '/credentials'), { method: 'DELETE' }),

  /**
   * Begin a provider sign-in. Returns where to send the browser.
   *
   * A URL rather than a redirect because the caller is `fetch`: a 303 would be
   * followed inside the XHR and the consent screen would arrive as a JSON parse
   * error. The page opens it in a popup.
   */
  authorize: (id: number) =>
    api<{ url: string }>(at(id, '/authorize'), { method: 'POST' }),

  rotateEndpoint: (id: number) =>
    api<SourceDetail>(at(id, '/endpoint/rotate'), { method: 'POST' }),

  test: (id: number) => api<TestResult>(at(id, '/test'), { method: 'POST' }),

  fields: (id: number) => api<SourceField[]>(at(id, '/fields')),

  syncNow: (id: number) => api<Run>(at(id, '/sync'), { method: 'POST' }),

  addMapping: (id: number, body: Record<string, unknown>) =>
    api<SourceDetail>(at(id, '/mappings'), {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  editMapping: (id: number, mappingId: number, body: Record<string, unknown>) =>
    api<SourceDetail>(at(id, `/mappings/${mappingId}`), {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),

  removeMapping: (id: number, mappingId: number) =>
    api<SourceDetail>(at(id, `/mappings/${mappingId}`), { method: 'DELETE' }),

  preview: (id: number, mappingId: number) =>
    api<PreviewRow[]>(at(id, `/mappings/${mappingId}/preview`), {
      method: 'POST',
    }),

  identities: (id: number) => api<Identity[]>(at(id, '/identities')),

  /** "None of the rest are people here" — one call for the whole tail. */
  ignoreRestOfIdentities: (id: number) =>
    api<Identity[]>(at(id, '/identities/ignore-rest'), { method: 'POST' }),

  mapIdentity: (id: number, identityId: number, userId: number) =>
    api<Identity[]>(at(id, `/identities/${identityId}/map`), {
      method: 'POST',
      body: JSON.stringify({ user_id: userId }),
    }),

  ignoreIdentity: (id: number, identityId: number) =>
    api<Identity[]>(at(id, `/identities/${identityId}/ignore`), {
      method: 'POST',
    }),

  // ── App registrations: once per provider, per deployment ──

  providers: () => api<Provider[]>('/api/integrations/oauth-clients'),

  /**
   * Save a client id and secret.
   *
   * Omit `client_secret` to keep the stored one — which is how somebody fixes a
   * typo in the client id without going to find the secret again.
   */
  saveProvider: (
    provider: string,
    body: {
      client_id: string;
      client_secret?: string;
      tenant_id?: string;
      issuer?: string;
    },
  ) =>
    api<Provider>(`/api/integrations/oauth-clients/${provider}`, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),

  forgetProvider: (provider: string) =>
    api<void>(`/api/integrations/oauth-clients/${provider}`, {
      method: 'DELETE',
    }),

  /**
   * Ask the provider for a sign-in code, starting automatic registration.
   *
   * Called on the button press rather than on render: the code expires about
   * fifteen minutes later, and one fetched while the panel was merely open would
   * spend most of that being read.
   */
  startSetup: (provider: string, mode: string) =>
    api<SetupStart>(
      `/api/integrations/oauth-clients/${provider}/bootstrap?mode=${encodeURIComponent(mode)}`,
      { method: 'POST' },
    ),

  /**
   * Has the admin finished signing in?
   *
   * `pending` is the ordinary answer for most of this flow's life, so it is a
   * status rather than an error. Anything genuinely wrong — declined, expired,
   * refused by the tenant — throws, and the panel shows it beside the manual
   * steps that still work.
   */
  pollSetup: (provider: string) =>
    api<SetupPoll>(
      `/api/integrations/oauth-clients/${provider}/bootstrap/poll`,
      {
        method: 'POST',
      },
    ),
};
