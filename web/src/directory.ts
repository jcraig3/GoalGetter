import { api } from './api';

/**
 * Syncing people from a company's own directory.
 *
 * Its own module rather than part of `dataSources`, because it is not a data
 * source: it writes to the people list, not to metrics, and the two share only a
 * provider connection. Putting them together would suggest a relationship the
 * backend deliberately does not have — see `app/directory/__init__.py`.
 */

export interface DirectoryRun {
  status: string;
  trigger: string;
  started_at: string;
  finished_at: string | null;
  people_seen: number;
  created: number;
  archived: number;
  needs_review: number;
  pending: number;
  applied: number;
  error: string | null;
}

export interface DirectoryStatus {
  /** Providers this build can read a directory from, connected or not. */
  available: string[];
  provider: string | null;
  enabled: boolean;
  /** False when there is no connection to switch on, so the page can point at
   *  Integrations instead of showing a switch that cannot be flipped. */
  connected: boolean;
  last_run: DirectoryRun | null;
  /** People waiting on a decision — the number the tab badge shows. */
  pending: number;
  /** Hours between reads. Set on the Integrations panel, beside the switch. */
  sync_hours: number;
  /** Whether the sync skips accounts holding no licence. */
  ignore_unlicensed: boolean;
  /** How this connection signs in: 'application' | 'delegated'. */
  auth_mode: string;
  /** Whose account it acts as, in delegated mode. */
  connected_as: string;
  account_connected: boolean;
  /** Whether this mode needs an account at all. False in application mode. */
  account_required: boolean;
  mail_enabled: boolean;
  mail_from: string;
}

/** One value a rule could match on, and how many people carry it. */
export interface DirectoryValue {
  value: string;
  people: number;
}

/**
 * What the directory actually contains, per field a rule matches on.
 *
 * Read off the people already staged rather than asked of the provider, because
 * these are the values that will be compared against — a department that exists
 * upstream but on nobody we read is a rule that matches nobody.
 */
export interface DirectoryValues {
  department: DirectoryValue[];
  job_title: DirectoryValue[];
  office: DirectoryValue[];
  group: DirectoryValue[];
}

export interface DirectoryRule {
  id: number;
  department: string;
  job_title: string;
  office: string;
  group: string;
  role: string;
  team_id: number | null;
}

export type RuleDraft = Omit<DirectoryRule, 'id'>;

export interface RulesResult {
  rules: DirectoryRule[];
  /** Pairs of positions whose conditions are identical. The second is
   *  unreachable — a mistake an admin cannot see by reading the list. */
  clashes: number[][];
}

export interface Difference {
  field: string;
  ours: string;
  theirs: string;
}

export interface DirectoryPerson {
  id: number;
  external_id: string;
  email: string;
  display_name: string;
  job_title: string;
  department: string;
  office_location: string;
  groups: string[];
  enabled: boolean;
  status: string;
  pending_reason: string;
  user_account_id: number | null;
  last_seen_at: string | null;
  /** Where the rules would put them — shown before approving, not after. */
  would_be_role: string;
  would_be_team_id: number | null;
  differences: Difference[];
}

const ROOT = '/api/admin/directory';

export const directory = {
  status: () => api<DirectoryStatus>(ROOT),

  values: () => api<DirectoryValues>(`${ROOT}/values`),

  startAccount: (provider: string) =>
    api<{ url: string }>(`${ROOT}/account?provider=${encodeURIComponent(provider)}`, {
      method: 'POST',
    }),

  forgetAccount: (provider: string) =>
    api<DirectoryStatus>(`${ROOT}/account?provider=${encodeURIComponent(provider)}`, {
      method: 'DELETE',
    }),

  /**
   * One real message, through Microsoft only.
   *
   * Never `mail.send`, which falls back to SMTP — right for an invitation and
   * wrong for a test, since a green result from the fallback would say this
   * setting works when it does not.
   */
  testMail: (provider: string, to: string) =>
    api<{ ok: boolean; detail: string }>(`${ROOT}/mail/test`, {
      method: 'POST',
      body: JSON.stringify({ provider, to }),
    }),

  setMail: (provider: string, enabled: boolean, mailFrom: string) =>
    api<DirectoryStatus>(`${ROOT}/mail`, {
      method: 'PUT',
      body: JSON.stringify({ provider, enabled, mail_from: mailFrom }),
    }),

  setEnabled: (
    provider: string,
    enabled: boolean,
    syncHours?: number,
    ignoreUnlicensed?: boolean,
  ) =>
    api<DirectoryStatus>(ROOT, {
      method: 'PUT',
      // Omitted when not given, which the endpoint reads as "leave it alone" —
      // so flicking the switch off and on does not reset the frequency to daily.
      body: JSON.stringify({
        provider,
        enabled,
        ...(syncHours === undefined ? {} : { sync_hours: syncHours }),
        ...(ignoreUnlicensed === undefined
          ? {}
          : { ignore_unlicensed: ignoreUnlicensed }),
      }),
    }),

  syncNow: () => api<DirectoryRun>(`${ROOT}/sync`, { method: 'POST' }),

  rules: () => api<RulesResult>(`${ROOT}/rules`),

  addRule: (body: RuleDraft) =>
    api<RulesResult>(`${ROOT}/rules`, { method: 'POST', body: JSON.stringify(body) }),

  editRule: (id: number, body: RuleDraft) =>
    api<RulesResult>(`${ROOT}/rules/${id}`, {
      method: 'PUT',
      body: JSON.stringify(body),
    }),

  removeRule: (id: number) =>
    api<RulesResult>(`${ROOT}/rules/${id}`, { method: 'DELETE' }),

  people: (status = 'pending') =>
    api<DirectoryPerson[]>(`${ROOT}/people?status=${encodeURIComponent(status)}`),

  /** Approve, decline, or return people to pending — always in bulk, because the
   *  first use is a whole company at once. */
  decide: (ids: number[], status: string) =>
    api<DirectoryPerson[]>(`${ROOT}/people/decide`, {
      method: 'POST',
      body: JSON.stringify({ ids, status }),
    }),
};
