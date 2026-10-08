/**
 * An activity-log row, said as a sentence (review §9).
 *
 * The server stores a stable machine-readable action name; the wording lives
 * here. Renaming "user.suspended" in the database would invalidate every
 * historical row, so the identifier never changes and only these words do.
 *
 * Seventy-odd actions, so most are built from their own name — "the contest
 * “QA2 sprint”" from `competition.*` and `{name}` — and only the ones that read
 * wrong that way are spelled out. Anything unknown still reads as words, never
 * as `competition.changed_while_running (fields: ends_at,prize…)`.
 */

import { dayAndTime } from '../time';

export type Details = Record<string, unknown> | null;

/** What the object is called, by the first half of the action. */
const NOUN: Record<string, string> = {
  achievement_rule: 'celebration rule',
  announcement_destination: 'announcement destination',
  asset: 'asset',
  audit_stream: 'audit stream',
  badge: 'badge',
  channel: 'channel',
  competition: 'contest',
  data_source: 'data source',
  display: 'TV',
  game_token: 'game token',
  goal: 'goal',
  leaderboard: 'board',
  metric: 'metric',
  metric_fact: 'number',
  recognition: 'shout-out',
  report_schedule: 'report schedule',
  role: 'role',
  source_mapping: 'mapping',
  unlockable: 'unlockable',
  user: 'person',
  wheel: 'prize wheel',
};

/** A kind of thing, for the filter: "contest", "data source", "Microsoft 365". */
export function kindLabel(prefix: string): string {
  // Plain words for the last internal ones (P3-19).
  const special: Record<string, string> = {
    m365: 'Microsoft 365 groups',
    mfa: 'Two-step sign-in',
    oauth_client: 'Microsoft app',
    directory: 'Directory',
    image: 'Branding pictures',
    user_identity: 'Imported names',
    game_token: 'Game pieces',
    warehouse: 'Data warehouse',
    source_mapping: 'Data mappings',
    data_source: 'Data sources',
    walkup: 'Walk-up media',
    announcements: 'Microsoft Teams posts',
    announcement_destination: 'Announcement channels',
    teams: 'Microsoft Teams',
    team: 'Teams',
    hosting: 'Hosting',
    announcement: 'Announcements',
  };
  const said = special[prefix] ?? NOUN[prefix] ?? prefix.replace(/_/g, ' ');
  return said.replace(/^./, (c) => c.toUpperCase());
}

/** Whole phrases for the actions their parts say badly. */
const WHOLE: Record<string, string> = {
  'user.invited': 'invited',
  'user.invite_resent': 'reissued an invitation for',
  'user.role_changed': 'changed the role of',
  'user.team_changed': 'changed the team of',
  'user.suspended': 'suspended',
  'user.reactivated': 'reactivated',
  'user.hidden': 'hid',
  'user.unhidden': 'unhid',
  // **Kept, because the log is history.** Rows written before hiding was called
  // hiding still say `user.archived`, and rewriting them to match today's
  // vocabulary would be editing the record.
  'user.archived': 'archived',
  'user.restored': 'restored',
  'user.profile_set': 'updated the profile of',
  'user.photo_set': 'set the photo of',
  'user.photo_reverted': 'put back the directory photo of',
  'user.photo_matched': 'matched a photo to',
  'user.photos_bulk': 'set photos in bulk:',
  'metric.defaults_seeded': 'restored the default metrics',
  'competition.changed_while_running': 'changed the running contest',
  'display.reload_requested': 'asked to reload the TV',
  'display.previewed': 'previewed on the TV',
  'channel.replayed': 'replayed on the channel',
  'data_source.synced': 'ran the data source',
  'directory.sync': 'synced the directory',
  'directory.decide': 'decided on directory people',
  'directory.mail': 'changed directory email',
  'image.background_uploaded': 'uploaded a background',
  'image.logo_uploaded': 'uploaded a logo',
  'mfa.enabled': 'turned on two-step sign-in',
  'mfa.disabled': 'turned off two-step sign-in',
  'mfa.reset': 'reset two-step sign-in for',
  'mfa.recovery_codes': 'made new recovery codes',
  'password.changed': 'changed their password',
  'password.reset_completed': 'reset their password',
  'password.reset_issued': 'issued a password reset link for',
  'password.temporary_set': 'set a temporary password for',
  'password.chosen': 'chose their own password',
  'announcements.switched': 'switched announcements',
  'badge.awarded': 'gave the badge',
  'recognition.sent': 'sent a shout-out to',
  'feed.comment_removed': 'removed a comment',
  'm365.linked': 'linked a Microsoft 365 group',
  'm365.unlinked': 'unlinked a Microsoft 365 group',
  'warehouse.saved': 'saved the warehouse connection',
  'warehouse.forgotten': 'forgot the warehouse connection',
  'oauth_client.provisioned': 'set up the Microsoft app',
  'walkup.changed': 'changed the walk-up of',
  'team.mirror_moved': 'moved, following Microsoft Teams,',
  'team.mirror_kept': 'kept a team out of Microsoft Teams syncing',
  'team.mirror_linked': 'linked a team to Microsoft Teams',
  'team.mirror_auto': 'let Microsoft Teams set teams',
  'teams.switched': 'switched Microsoft Teams posting',
  'user_identity.mapped': 'matched an imported name to a person',
  'user_identity.ignored': 'ignored an imported name',
  'user_identity.ignored_rest': 'ignored the remaining imported names from',
  'hosting.https_changed': 'changed how GoalGetter is reached',
  'hosting.change_kept': 'kept the hosting change',
  'hosting.change_undone': 'undid the hosting change',
  // By GoalGetter itself (Phase 23): a trial nobody kept, an edit in .env.
  'hosting.change_expired': 'undid a hosting change nobody kept',
  'hosting.changed_in_env': 'followed a hosting change made in .env',
  'hosting.certificate_uploaded': 'uploaded certificate files',
  'hosting.web_address_cleared': 'cleared the web address',
  'announcement.created': 'made the announcement',
  'announcement.updated': 'changed the announcement',
  'announcement.deleted': 'deleted the announcement',
  'announcement.sent': 'sent the announcement',
};

/** Verbs that read better than the stored word. */
const VERB: Record<string, string> = {
  changed_while_running: 'changed while running',
  prize_created: 'added a prize to',
  prize_deleted: 'removed a prize from',
  prize_given: 'handed over a prize from',
  member_added: 'added somebody to',
  member_removed: 'removed somebody from',
  reload_requested: 'asked to reload',
  saved: 'saved',
};

/** Detail keys that name the thing — said in the sentence, not after it. */
const NAMES = ['name', 'label', 'person', 'recipient', 'team'];

/** Things that belong to somebody: "deleted the goal for ann@…", not "the goal ann@…". */
const FOR_SOMEBODY = new Set(['goal', 'metric_fact']);

/** Detail keys nobody reading the log can use. */
const HIDDEN = new Set(['token', 'url', 'granted', 'pending', 'problems', 'connector']);

/** Field names said as words: "ends_at" is "end". */
const FIELD: Record<string, string> = {
  ends_at: 'end',
  starts_at: 'start',
  team_id: 'team',
  office_id: 'office',
  org_role: 'role',
  target_value: 'target',
  occurred_at: 'when',
  spin_cost: 'spin cost',
  facts_kept: 'numbers kept',
  accounts_created: 'accounts made',
  use_as: 'used as',
  recipient: 'to',
  subject: 'for',
};

const words = (key: string) => FIELD[key] ?? key.replace(/_id$/, '').replace(/_/g, ' ');

/** Stored values said as words: "user" as "people" (P3-19). */
const VALUE: Record<string, Record<string, string>> = {
  entity_type: { user: 'people', team: 'teams', office: 'offices' },
  visibility: { org: 'everyone', team: 'the team', private: 'only its maker' },
  period: { day: 'daily', week: 'weekly', month: 'monthly', quarter: 'quarterly', year: 'yearly' },
};

/**
 * Metric keys by their names — "sales_feed_amount_today" is "Sales Feed
 * Amount Today" (P3-19). Filled by the page from the metrics it can read.
 */
const metricNames = new Map<string, string>();
export function knowMetricNames(metrics: { key: string; name: string }[]): void {
  for (const m of metrics) metricNames.set(m.key, m.name);
}

/**
 * Keys that hold an amount, so a whole number among them is grouped like the
 * rest of the app says it (P4-13): "target: 1000" and "target: 1,000" sat in
 * neighbouring rows. Only these, because a year or a count of days is not
 * "2,026".
 */
const AMOUNT = /(^|_)(target|value|amount|points|threshold|figure|current)(_|$)/;

function sayAmount(key: string, value: unknown): string {
  const text = String(value ?? '');
  if (AMOUNT.test(key) && /^-?\d+(\.\d+)?$/.test(text)) return Number(text).toLocaleString();
  return say(value);
}

function say(value: unknown): string {
  // null is a real value here — "no team" — so it must render as something,
  // not as an empty gap that reads like a rendering bug.
  if (value === null || value === undefined || value === '') return 'none';
  if (Array.isArray(value)) return value.map(say).join(', ') || 'none';
  if (value === true || value === 'True') return 'on';
  if (value === false || value === 'False') return 'off';
  const text = String(value);
  // "500.0000" is 500, and a stored timestamp is a date like any other.
  if (/^-?\d+\.\d+$/.test(text)) return Number(text).toLocaleString();
  if (/^\d{4}-\d{2}-\d{2}T/.test(text)) return dayAndTime(text);
  return text;
}

/** {"from": x, "to": y} — a change, as opposed to a scalar detail. */
function isChange(value: unknown): value is { from?: unknown; to?: unknown } {
  return typeof value === 'object' && value !== null && !Array.isArray(value) && 'to' in value;
}

/** Which detail names the thing, if any. */
function nameKey(details: Details): string | undefined {
  return NAMES.find((k) => typeof details?.[k] === 'string' && (details[k] as string).length > 0);
}

/** The word before the person the row is about, if it needs one. */
export function targetWord(action: string): string {
  return FOR_SOMEBODY.has(action.split('.')[0] ?? '') ? 'for ' : '';
}

/** "changed the running contest “QA2 sprint”", without who did it. */
export function what(action: string, details: Details): string {
  const key = nameKey(details);
  const named = key ? ` “${details![key] as string}”` : '';

  const whole = WHOLE[action];
  if (whole) return `${whole}${named}`;

  const dot = action.indexOf('.');
  const thing = dot > 0 ? action.slice(0, dot) : '';
  const verb = dot > 0 ? action.slice(dot + 1) : action;
  const noun = NOUN[thing] ?? thing.replace(/_/g, ' ');
  const said = VERB[verb] ?? verb.replace(/_/g, ' ');
  return noun ? `${said} the ${noun}${named}` : `${said}${named}`;
}

/** What else the row says, in words: "end: … → …", "fields: enabled". */
export function extras(details: Details, hasTarget = false): string[] {
  if (!details) return [];
  const named = nameKey(details);
  return Object.entries(details).flatMap(([key, value]) => {
    if (key === named || HIDDEN.has(key)) return [];
    // Said already, by the person's address after the verb.
    if (key === 'subject' && hasTarget) return [];
    // An id on its own is a number nobody can look up from here.
    if (key.endsWith('_id') && !isChange(value)) return [];
    // A sentence already, written when it happened.
    if (key === 'what' || key === 'note') return value ? [say(value)] : [];
    if (isChange(value)) {
      return [`${words(key)}: ${sayAmount(key, value.from)} → ${sayAmount(key, value.to)}`];
    }
    if (key === 'fields') return [`changed ${say(value).replace(/_/g, ' ')}`];
    if ((key === 'metric' || key === 'key') && typeof value === 'string' && metricNames.has(value)) {
      return [`metric: ${metricNames.get(value)}`];
    }
    const plain = typeof value === 'string' ? VALUE[key]?.[value] : undefined;
    return [`${words(key)}: ${plain ?? sayAmount(key, value)}`];
  });
}
