import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { api } from '../api';
import { applyAppearance, type Appearance } from '../appearance';
import { forgetOrgAppearance } from '../orgAppearance';
import BrandFields from '../components/BrandFields';
import Field from '../components/Field';
import WebAddressField from '../components/WebAddressField';
import HostingOverview from '../components/HostingOverview';
import CustomRoles from '../components/CustomRoles';
import AuditExport from '../components/AuditExport';
import PageHeader from '../components/PageHeader';
import Select from '../components/Select';
import { zoneChoices, zoneLabel } from '../timezones';
import ActivityLog from '../components/ActivityLog';
import { Tab } from '../components/Tabs';
import { toast } from '../toast';
import { useAuth } from '../auth';

interface Organization {
  id: number;
  name: string;
  timezone: string;
  week_starts_on: number;
  fiscal_year_start_month: number;
  currency: string;
  /** Only what this organization chose. Sparse: absent means the built-in. */
  /** What an agent may set about themselves. */
  self_photo: boolean;
  self_details: boolean;
  self_walkup: boolean;
  /** Colleagues can open each other's profiles (9.5). */
  profiles_public: boolean;
  /** Password sign-in needs an authenticator code too. */
  require_mfa: boolean;
  /** Only admins and managers can sign in (Phase 28). */
  sign_in_leaders_only: boolean;
  /** Where people reach this deployment (11.7); null for the server's default. */
  public_url: string | null;
  /** `APP_URL` from the server, which applies while `public_url` is null. */
  public_url_default: string;
  /** A proxy of the organization's own in front (Phase 17); null for .env. */
  proxy_mode: 'direct' | 'proxy' | null;
  /** Wrong passwords allowed in five minutes; null for the defaults. */
  sign_in_limit_account: number | null;
  sign_in_limit_device: number | null;
  appearance: Record<string, unknown>;
  /** The same thing with every field filled, for placeholders. */
  appearance_resolved: Appearance;
}

const DAYS = [
  'Sunday',
  'Monday',
  'Tuesday',
  'Wednesday',
  'Thursday',
  'Friday',
  'Saturday',
];

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
];

const CURRENCIES = ['USD', 'CAD', 'GBP', 'EUR', 'AUD', 'NZD', 'ZAR', 'INR', 'SGD', 'MXN'];

export default function Settings() {
  const { refresh: refreshSession } = useAuth();
  const [org, setOrg] = useState<Organization | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // What the server last said, so "unsaved changes" can be worked out
  // rather than guessed at.
  const [original, setOriginal] = useState<Organization | null>(null);
  const [tab, setTab] = useState<SettingsTab>('general');
  // From the connection check, for the proxy choice's own check.
  const [proxiesSeen, setProxiesSeen] = useState<number | null>(null);
  // "Settings › Branding" in the palette lands on its tab (7.9).
  const [params] = useSearchParams();
  const asked = params.get('tab');
  useEffect(() => {
    if (asked && SETTINGS_TABS.some((t) => t.key === asked)) setTab(asked as SettingsTab);
  }, [asked]);

  // Straight from the browser rather than an endpoint returning ~600 zones.
  // Intl already knows the tz database, so shipping our own list would mean
  // maintaining a copy that goes stale.
  const timezones = useMemo(() => {
    let zones: string[];
    try {
      zones = Intl.supportedValuesOf('timeZone');
    } catch {
      zones = ['UTC'];
    }
    return zoneChoices(zones);
  }, []);

  useEffect(() => {
    api<Organization>('/api/organization')
      .then((o) => {
        setOrg(o);
        setOriginal(o);
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load settings.'));
  }, []);

  function set<K extends keyof Organization>(key: K, value: Organization[K]) {
    setOrg((o) => (o ? { ...o, [key]: value } : o));
  }

  /**
   * Branding edits, merged onto whatever else the appearance holds.
   *
   * **Merged, because the PATCH replaces.** The wall's own settings live in the
   * same object and are edited on the Appearance tab; sending only the brand
   * would silently erase every layout, background and type choice the moment
   * somebody changed the currency.
   */
  function setBrand(part: Record<string, unknown>) {
    setOrg((o) =>
      o ? { ...o, appearance: { ...o.appearance, ...part } } : o,
    );
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!org) return;
    setBusy(true);
    setError(null);
    try {
      const next = await api<Organization>('/api/organization', {
        method: 'PATCH',
        body: JSON.stringify({
          name: org.name,
          timezone: org.timezone,
          week_starts_on: org.week_starts_on,
          fiscal_year_start_month: org.fiscal_year_start_month,
          currency: org.currency,
          self_photo: org.self_photo,
          self_details: org.self_details,
          self_walkup: org.self_walkup,
          profiles_public: org.profiles_public,
          require_mfa: org.require_mfa,
          sign_in_leaders_only: org.sign_in_leaders_only,
          public_url: org.public_url ?? '',
          proxy_mode: org.proxy_mode ?? '',
          sign_in_limit_account: org.sign_in_limit_account,
          sign_in_limit_device: org.sign_in_limit_device,
          appearance: org.appearance,
        }),
      });
      setOrg(next);
      setOriginal(next);
      toast('Settings saved');
      // The header, the highlights and every per-item placeholder are showing
      // the old brand until this. Re-read rather than pushed, so a cleared
      // field comes back as the built-in default the server resolves it to.
      applyAppearance(next.appearance_resolved);
      forgetOrgAppearance();
      // Whether names are links is in the session (9.5): re-read it, so the
      // switch shows here without a reload.
      if (original && next.profiles_public !== original.profiles_public) void refreshSession();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save.');
    } finally {
      setBusy(false);
    }
  }

  if (!org) {
    return (
      <>
        <PageHeader title="Settings" />
        <p className="text-content-muted">{error ?? 'Loading…'}</p>
      </>
    );
  }

  // Only the form's tabs have anything to save; Roles and Activity save
  // themselves as they go.
  const formTab =
    tab === 'general' || tab === 'branding' || tab === 'people' || tab === 'signin' || tab === 'hosting';
  const dirty = JSON.stringify(org) !== JSON.stringify(original);
  const browser = Intl.DateTimeFormat().resolvedOptions().timeZone;

  return (
    <>
      <PageHeader
        title="Settings"
        description="Who your organization is, how it measures time and money, and who can do what."
      />

      {/* **Six pages, not one long one** (review §7): one 5,500-pixel page
          with a Save button for part of it and sections below it that saved
          themselves. */}
      <div className="mb-6 flex flex-wrap gap-1">
        {SETTINGS_TABS.map((t) => (
          <Tab key={t.key} active={tab === t.key} onClick={() => setTab(t.key)}>
            {t.label}
          </Tab>
        ))}
      </div>

      {formTab && (
      <form onSubmit={save} className="max-w-xl rounded-lg border border-edge bg-surface p-6">
        {tab === 'general' && (
          <>
        <Field
          label="Organization name"
          value={org.name}
          onChange={(v) => set('name', v)}
        />

        <div className="mt-6 space-y-4">
          <Select
            label="Timezone"
            value={org.timezone}
            onChange={(v) => set('timezone', v)}
            hint="Decides when a day starts and ends. A daily leaderboard must mean the same thing to everyone, so this is set once for the whole organization — not per person."
          >
            {/* In words, the usual ones first (review §7). One the browser
                does not list still shows, rather than reading as the first. */}
            {![...timezones.common, ...timezones.rest].some((z) => z.value === org.timezone) && (
              <option value={org.timezone}>{zoneLabel(org.timezone)}</option>
            )}
            <optgroup label="Common">
              {timezones.common.map((z) => (
                <option key={z.value} value={z.value}>
                  {z.label}
                </option>
              ))}
            </optgroup>
            <optgroup label="Everywhere else">
              {timezones.rest.map((z) => (
                <option key={z.value} value={z.value}>
                  {z.label}
                </option>
              ))}
            </optgroup>
          </Select>
          <Select
            label="Week starts on"
            value={String(org.week_starts_on)}
            onChange={(v) => set('week_starts_on', Number(v))}
            options={DAYS.map((d, i) => ({ value: String(i), label: d }))}
          />
          <Select
            label="Fiscal year starts in"
            value={String(org.fiscal_year_start_month)}
            onChange={(v) => set('fiscal_year_start_month', Number(v))}
            options={MONTHS.map((m, i) => ({ value: String(i + 1), label: m }))}
            hint="Used for quarterly and yearly goals."
          />
          <Select
            label="Currency"
            value={org.currency}
            onChange={(v) => set('currency', v)}
            options={CURRENCIES.map((c) => ({ value: c, label: c }))}
          />
        </div>

            {/* Said when whoever is changing it is somewhere else: an admin in
                Pacific setting up a New York floor reads every day boundary in
                New York time, and should know it (review §7). */}
            {browser !== org.timezone && (
              <p className="mt-4 rounded-md border border-edge px-3 py-2 text-sm text-content-muted">
                You are on {zoneLabel(browser)}; the organization is on {zoneLabel(org.timezone)}. Every
                day, week and deadline follows the organization&rsquo;s.
              </p>
            )}
        {/* Stated plainly because it is not obvious: these settings are not
            cosmetic. Changing the week start after months of data shifts every
            historical weekly boundary, so a past leaderboard can legitimately
            show different numbers than it did yesterday. */}
        <p className="mt-6 rounded-md border border-warning px-3 py-2 text-sm text-warning">
          Changing the week start or fiscal year re-slices past periods.
          Historical weekly and quarterly figures may shift. Best set once, at
          the start.
        </p>

          </>
        )}

        {tab === 'branding' && (
          <>
        {/* **Branding, with the rest of the company's details.** The Appearance
            tab decides how a television draws a leaderboard; this decides
            whose tool this is, which is as true of the app somebody uses at
            their desk as it is of a screen on a wall. */}
        <div>
          <h2 className="text-sm font-medium text-content">Branding</h2>
          <p className="mt-1 mb-4 text-xs text-content-subtle">
            Your mark and your colours, across the app and every wall.
          </p>
          <BrandFields
            chosen={org.appearance}
            resolved={org.appearance_resolved}
            onChange={setBrand}
          />
        </div>

          </>
        )}

        {tab === 'people' && (
          <>
        {/* **Three switches, not one.** A company wanting uniform headshots
            has said nothing about nicknames, and a floor that has heard one
            person's walk-up song nine hundred times has said nothing about
            either. */}
        <div className="space-y-3">
          <h2 className="text-sm font-medium text-content">
            What people may set about themselves
          </h2>
          <p className="text-xs text-content-subtle">
            Managers and administrators can always set these for anybody,
            including themselves. Turning one off only stops an agent changing
            their own.
          </p>
          <Switch
            label="Their own photograph"
            hint="Off suits a company that would rather keep one uniform set of headshots."
            on={org.self_photo}
            onChange={(v) => set('self_photo', v)}
          />
          <Switch
            label="Their nickname and birthday"
            hint="The two optional facts about them."
            on={org.self_details}
            onChange={(v) => set('self_details', v)}
          />
          <Switch
            label="Their walk-up media"
            hint="The clip that plays on a wall when they win — it is the one that plays out loud."
            on={org.self_walkup}
            onChange={(v) => set('self_walkup', v)}
          />
        </div>

        {/* Who sees a profile (9.5). The private half — goals and numbers —
            is never anybody else's business, whichever way this is set. */}
        <div className="mt-8 space-y-3 border-t border-edge pt-6">
          <h2 className="text-sm font-medium text-content">Profiles</h2>
          <Switch
            label="Colleagues can see each other's profiles"
            hint="Badges, wins, shout-outs and season points — what is announced anyway. Off, a profile is seen only by the person, their managers and admins, and names stop being links for everyone else. Goals and numbers are only ever seen by the person, their managers and admins."
            on={org.profiles_public ?? true}
            onChange={(v) => set('profiles_public', v)}
          />
        </div>
          </>
        )}

        {/* **How GoalGetter is reached** (Phase 17): the address, HTTPS, the
            connection check and a proxy in front, together — they are one
            question, asked when it is set up and when something breaks. */}
        {tab === 'hosting' && (
          <div>
            <HostingOverview onLoaded={(h) => setProxiesSeen(h.proxies_seen ?? null)} />
            {/* Folded away (Phase 19): most installs never touch these. */}
            <details className="mt-4 rounded-lg border border-edge">
              <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-content">
                Advanced
              </summary>
              <div className="space-y-6 border-t border-edge px-4 py-4">
                <WebAddressField
                  value={org.public_url}
                  saved={original?.public_url ?? null}
                  fallback={org.public_url_default}
                  onChange={(v) => set('public_url', v)}
                />
                <ProxyChoice
                  value={org.proxy_mode}
                  onChange={(v) => set('proxy_mode', v)}
                  proxiesSeen={proxiesSeen}
                />
              </div>
            </details>
          </div>
        )}

        {tab === 'signin' && (
        <div className="space-y-3">
          <h2 className="text-sm font-medium text-content">Sign-in</h2>
          <Switch
            label="Require two-step sign-in"
            hint="Signing in with a password also needs a code from an authenticator app. Anybody without one set up is walked through it straight after their password. Signing in with Microsoft is unaffected — it has its own."
            on={org.require_mfa ?? false}
            onChange={(v) => set('require_mfa', v)}
          />
          <Switch
            label="Only admins and managers can sign in"
            hint="Agents can’t sign in by any method — password or Microsoft — and anyone signed in is signed out. TVs keep working."
            on={org.sign_in_leaders_only ?? false}
            onChange={(v) => set('sign_in_leaders_only', v)}
          />
          <Unenrolled />

          {/* Phase 17, item 4. Empty means the defaults, which suit most. */}
          <h2 className="pt-4 text-sm font-medium text-content">Wrong-password limits</h2>
          <p className="text-xs text-content-subtle">
            How many wrong passwords in five minutes before signing in has to wait. Microsoft sign-in
            is not counted. Leave empty for the defaults.
          </p>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field
              label="For each account"
              numeric={{ decimals: 0, min: 3, max: 20 }}
              value={org.sign_in_limit_account === null ? '' : String(org.sign_in_limit_account)}
              onChange={(v) => set('sign_in_limit_account', v ? Number(v) : null)}
              placeholder="5"
              required={false}
              hint="3 to 20. Stops one account's password being guessed."
            />
            <Field
              label="For each device"
              numeric={{ decimals: 0, min: 10, max: 200 }}
              value={org.sign_in_limit_device === null ? '' : String(org.sign_in_limit_device)}
              onChange={(v) => set('sign_in_limit_device', v ? Number(v) : null)}
              placeholder="20"
              required={false}
              hint="10 to 200. Only works where GoalGetter can see devices’ addresses — Hosting tab."
            />
          </div>
        </div>

        )}

        {error && (
          <p role="alert" className="mt-4 rounded-md border border-danger px-3 py-2 text-sm text-danger">
            {error}
          </p>
        )}

        {/* **A save bar that appears when there is something to save**, and
            stays at the bottom of the screen while it does — whichever tab
            the change was made on (review §5). */}
        {dirty && (
          <div className="sticky bottom-0 -mx-6 -mb-6 mt-6 flex items-center gap-3 rounded-b-lg border-t border-edge bg-surface-raised px-6 py-3">
            <span className="flex-1 text-sm text-content-muted">Unsaved changes</span>
            <button
              type="button"
              onClick={() => setOrg(original)}
              className="rounded-md border border-edge px-3 py-1.5 text-sm text-content hover:bg-surface-hover"
            >
              Discard
            </button>
            <button
              type="submit"
              disabled={busy}
              className="rounded-md bg-brand px-4 py-1.5 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
            >
              {busy ? 'Saving…' : 'Save'}
            </button>
          </div>
        )}
      </form>
      )}

      {/* Staff photos in bulk moved to Organization → Assets, beside the
          other files the organization uploads. */}

      {tab === 'roles' && <CustomRoles />}

      {tab === 'activity' && (
        <>
          <ActivityLog />
          <AuditExport />
        </>
      )}
    </>
  );
}

type SettingsTab = 'general' | 'branding' | 'people' | 'signin' | 'hosting' | 'roles' | 'activity';

const SETTINGS_TABS: { key: SettingsTab; label: string }[] = [
  { key: 'general', label: 'General' },
  { key: 'branding', label: 'Branding' },
  { key: 'people', label: 'What people can set' },
  { key: 'signin', label: 'Sign-in & security' },
  { key: 'hosting', label: 'Hosting' },
  { key: 'roles', label: 'Roles' },
  { key: 'activity', label: 'Activity & export' },
];


/**
 * "Is there a proxy in front of GoalGetter?" (Phase 17, item 2).
 *
 * **Guarded on both sides.** The server refuses "Yes" unless the request that
 * sets it came through a proxy that passed an address along; this says so
 * before somebody tries. Set without one, anybody could choose the address
 * they appear to come from, and every per-device limit would be gone.
 */
function ProxyChoice({
  value,
  onChange,
  proxiesSeen,
}: {
  value: 'direct' | 'proxy' | null;
  onChange: (v: 'direct' | 'proxy' | null) => void;
  proxiesSeen: number | null;
}) {
  const choices: { key: 'direct' | 'proxy' | null; label: string; hint: string }[] = [
    { key: null, label: 'As set up on the server', hint: 'Right for every built-in option' },
    { key: 'direct', label: 'No', hint: 'People reach GoalGetter directly' },
    { key: 'proxy', label: 'Yes', hint: 'Our own proxy or load balancer is in front' },
  ];
  return (
    <fieldset className="mt-6 space-y-2 text-sm">
      <legend className="text-content-muted">A proxy in front of GoalGetter?</legend>
      {choices.map((choice) => (
        <label key={String(choice.key)} className="flex items-start gap-2">
          <input
            type="radio"
            name="proxy_mode"
            className="mt-1"
            checked={value === choice.key}
            onChange={() => onChange(choice.key)}
          />
          <span>
            <span className="text-content">{choice.label}</span>
            <span className="block text-xs text-content-subtle">{choice.hint}</span>
          </span>
        </label>
      ))}
      {value === 'proxy' && proxiesSeen !== null && proxiesSeen < 2 && (
        <p className="text-xs text-warning">
          No proxy is in front of this page, so “Yes” will be refused. Set it from your proxy’s address.
        </p>
      )}
    </fieldset>
  );
}

/** One yes-or-no, with the sentence that says what "no" costs. */
/**
 * Who signs in with a password and has not set up two-step yet.
 *
 * "Required" asks at the next password sign-in, so until then nothing on the
 * page shows it working — and an admin who signs in with Microsoft is never
 * asked at all (QA-32). Always shown, so the answer to "is this on?" is on the
 * page rather than in somebody's inbox.
 */
function Unenrolled() {
  const [people, setPeople] = useState<{ id: number; full_name: string }[] | null>(null);
  const { user } = useAuth();

  useEffect(() => {
    api<{ id: number; full_name: string }[]>('/api/auth/mfa/unenrolled')
      .then(setPeople)
      .catch(() => setPeople(null));
  }, []);

  if (people === null) return null;
  if (people.length === 0) {
    return (
      <p className="text-xs text-content-muted">
        Everybody who signs in with a password has an authenticator set up.
      </p>
    );
  }
  // **When it is you, the way to fix it** (8.4): an admin reading their own
  // name in this list had to go and find where two-step is set up.
  const me = people.some((p) => p.id === user?.id);
  if (me && people.length === 1) {
    return (
      <p className="text-xs text-content-muted">
        You are the only one who signs in with a password and has not set one up.{' '}
        <Link to="/account#two-step" className="text-brand hover:underline">
          Set it up now
        </Link>
      </p>
    );
  }
  const shown = people.slice(0, 5).map((p) => p.full_name);
  const more = people.length - shown.length;
  return (
    <p className="text-xs text-content-muted">
      {people.length === 1 ? '1 person signs' : `${people.length} people sign`} in with a
      password and {people.length === 1 ? 'has' : 'have'} not set one up yet
      {' '}— asked at their next sign-in while this is on: {shown.join(', ')}
      {more > 0 ? ` and ${more} more` : ''}.
      {me && (
        <>
          {' '}
          <Link to="/account#two-step" className="text-brand hover:underline">
            Set up yours now
          </Link>
        </>
      )}
    </p>
  );
}

function Switch({
  label,
  hint,
  on,
  onChange,
}: {
  label: string;
  hint: string;
  on: boolean;
  onChange: (on: boolean) => void;
}) {
  return (
    <label className="flex items-start gap-2 text-sm text-content">
      <input
        type="checkbox"
        checked={on}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 accent-brand"
      />
      <span>
        {label}
        <span className="block text-xs text-content-subtle">{hint}</span>
      </span>
    </label>
  );
}
