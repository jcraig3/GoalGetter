import { dayAndTime } from '../time';
import { useCallback, useEffect, useState } from 'react';

import { api } from '../api';
import { ask } from '../confirm';
import Loading from './Loading';

interface Choice {
  key: string;
  label: string;
}

export interface Destination {
  id: number;
  kind: string;
  name: string;
  /** Picked from a list and posted through Microsoft, or a Workflows link. */
  via: 'graph' | 'workflow';
  link_hint: string;
  /** For a picked channel: "Metropolis Sales Team › Closers". */
  channel_label: string | null;
  team_external_id: string | null;
  channel_external_id: string | null;
  events: string[];
  office_id: number | null;
  team_id: number | null;
  enabled: boolean;
  last_sent_at: string | null;
  last_error: string | null;
  last_error_at: string | null;
  failing: boolean;
}

interface Listing {
  /** The master switch: off, nothing is posted to any channel. */
  enabled: boolean;
  choices: Choice[];
  destinations: Destination[];
}

interface Named {
  id: number;
  name: string;
}

/** Who posts into picked channels. */
interface Account {
  /** Whether Microsoft 365 is connected at all. */
  registered: boolean;
  connected: boolean;
  connected_as: string;
}

interface Choosable {
  id: string;
  name: string;
  membership?: string;
}

/**
 * Open Microsoft's sign-in in a small window and wait for it to finish.
 *
 * The same shape as the Excel sign-in: a message from our own callback page,
 * or the window being closed, which is how somebody says no.
 */
async function signInWindow(url: string): Promise<string | null> {
  const popup = window.open(url, 'gg_teams_oauth', 'width=520,height=680');
  if (!popup) {
    window.location.assign(url);
    return null;
  }
  return new Promise((resolve) => {
    let problem: string | null = null;
    function onMessage(event: MessageEvent) {
      if (event.origin !== window.location.origin) return;
      if (event.data?.source !== 'goalgetter-oauth') return;
      problem = event.data.result?.error ? String(event.data.result.error) : null;
      done();
    }
    const watch = window.setInterval(() => {
      if (popup.closed) done();
    }, 500);
    function done() {
      window.clearInterval(watch);
      window.removeEventListener('message', onMessage);
      resolve(problem);
    }
    window.addEventListener('message', onMessage);
  });
}

/**
 * Posting wins into Microsoft Teams channels — what to announce, and where.
 *
 * **Two ways to reach a channel.** Pick it from a list: one account signs in
 * once, and any channel it is in can be chosen — the way most people expect it
 * to work. Or paste a Workflows link made inside the channel, which needs no
 * account and no Microsoft 365 connection at all. Microsoft only lets an app
 * post to a channel *as somebody*, which is why picking needs the account.
 */
export default function TeamsSettings({
  onCount,
  kind = 'teams',
}: {
  /** Told how many channels are set up, so the panel can say whether it is on. */
  onCount?: (count: number) => void;
  /**
   * Which chat. Slack channels are reached through their incoming webhook
   * link only, and are not paused by the Microsoft Teams switch.
   */
  kind?: 'teams' | 'slack';
}) {
  const isTeams = kind === 'teams';
  const [listing, setListing] = useState<Listing | null>(null);
  const [offices, setOffices] = useState<Named[]>([]);
  const [teams, setTeams] = useState<Named[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Destination | 'new' | null>(null);
  const [tested, setTested] = useState<Record<number, string>>({});
  const [account, setAccount] = useState<Account | null>(null);
  const [accountBusy, setAccountBusy] = useState(false);

  const loadAccount = useCallback(() => {
    if (!isTeams) return;
    api<Account>('/api/announcements/account')
      .then(setAccount)
      .catch(() => setAccount(null));
  }, [isTeams]);

  async function signIn() {
    setAccountBusy(true);
    setError(null);
    try {
      const { url } = await api<{ url: string }>('/api/announcements/account', {
        method: 'POST',
      });
      const problem = await signInWindow(url);
      if (problem) setError(problem);
      loadAccount();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not start that sign-in.');
    } finally {
      setAccountBusy(false);
    }
  }

  async function signOut() {
    if (
      !await ask(
        `Stop posting as ${account?.connected_as || 'this account'}?\n\n` +
          'Picked channels are kept — they stop posting until an account is signed in again.',
      )
    ) {
      return;
    }
    setAccountBusy(true);
    try {
      await api('/api/announcements/account', { method: 'DELETE' });
      loadAccount();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not sign that out.');
    } finally {
      setAccountBusy(false);
    }
  }

  const load = useCallback(() => {
    api<Listing>(`/api/announcements/destinations?kind=${kind}`)
      .then((found) => {
        setListing(found);
        onCount?.(
          !isTeams || found.enabled ? found.destinations.filter((d) => d.enabled).length : 0,
        );
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load.'));
  }, [onCount, kind, isTeams]);

  useEffect(() => {
    load();
    loadAccount();
    api<Named[]>('/api/offices')
      .then(setOffices)
      .catch(() => setOffices([]));
    api<Named[]>('/api/teams')
      .then(setTeams)
      .catch(() => setTeams([]));
  }, [load, loadAccount]);

  async function test(destination: Destination) {
    setTested((t) => ({ ...t, [destination.id]: 'Sending…' }));
    try {
      const result = await api<{ ok: boolean; error: string | null }>(
        `/api/announcements/destinations/${destination.id}/test`,
        { method: 'POST' },
      );
      setTested((t) => ({
        ...t,
        [destination.id]: result.ok
          ? 'Sent — look in the channel.'
          : (result.error ?? 'It did not arrive.'),
      }));
    } catch (e) {
      setTested((t) => ({
        ...t,
        [destination.id]: e instanceof Error ? e.message : 'It did not arrive.',
      }));
    }
  }

  async function setOne(destination: Destination, on: boolean) {
    setError(null);
    try {
      await api(`/api/announcements/destinations/${destination.id}/enabled`, {
        method: 'PUT',
        body: JSON.stringify({ on }),
      });
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not change that.');
    }
  }

  async function remove(destination: Destination) {
    if (!await ask(`Stop posting to “${destination.name}”?`)) return;
    try {
      await api(`/api/announcements/destinations/${destination.id}`, {
        method: 'DELETE',
      });
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not remove.');
    }
  }

  if (!listing) {
    return error ? (
      <p role="alert" className="text-sm text-danger">
        {error}
      </p>
    ) : (
      <Loading />
    );
  }

  const label = (key: string) => listing.choices.find((c) => c.key === key)?.label ?? key;
  // The Microsoft Teams switch pauses Teams channels, and nothing else.
  const paused = isTeams && !listing.enabled;
  const whose = (d: Destination) =>
    d.office_id
      ? (offices.find((o) => o.id === d.office_id)?.name ?? 'One office')
      : d.team_id
        ? (teams.find((t) => t.id === d.team_id)?.name ?? 'One team')
        : 'Everyone';

  return (
    <div className="space-y-4">
      <p className="text-sm text-content-muted">
        Wins are posted into the channels you choose — which kinds, and whose, per channel.
        {!isTeams && ' Each Slack channel is added with its own incoming webhook link.'}
      </p>

      {isTeams && (
        <AccountStrip
          account={account}
          busy={accountBusy}
          onSignIn={() => void signIn()}
          onSignOut={() => void signOut()}
        />
      )}

      {error && (
        <p role="alert" className="rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      {listing.destinations.length > 0 && (
        <ul className="divide-y divide-edge rounded-md border border-edge">
          {listing.destinations.map((d) => (
            <li key={d.id} className="px-4 py-3">
              <div className="flex flex-wrap items-baseline justify-between gap-3">
                <label className="flex items-center gap-2">
                  {/* One press, in the list — not buried inside the edit form. */}
                  <input
                    type="checkbox"
                    checked={d.enabled}
                    disabled={paused}
                    onChange={(e) => void setOne(d, e.target.checked)}
                    aria-label={`Post to ${d.name}`}
                  />
                  <span className={d.enabled && !paused ? 'text-content' : 'text-content-muted'}>
                    {d.name}
                    {!d.enabled && <span className="ml-2 text-xs">off</span>}
                    {d.enabled && paused && <span className="ml-2 text-xs">paused</span>}
                  </span>
                </label>
                <div className="flex gap-3 text-sm">
                  <button
                    type="button"
                    onClick={() => void test(d)}
                    className="text-brand hover:underline"
                  >
                    Send a test
                  </button>
                  <button
                    type="button"
                    onClick={() => setEditing(d)}
                    className="text-content-muted hover:text-content"
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    onClick={() => void remove(d)}
                    className="text-content-muted hover:text-danger"
                  >
                    Remove
                  </button>
                </div>
              </div>
              <p className="mt-0.5 text-xs text-content-muted">
                {d.events.map(label).join(', ')} · {whose(d)} ·{' '}
                {d.via === 'graph'
                  ? d.channel_label
                  : `${isTeams ? 'Workflows link' : 'Webhook'} ${d.link_hint}`}
              </p>
              {/* The one fact worth leading with when it is true: the channel is
                  not getting its posts, and why. */}
              {d.failing && d.last_error && (
                <p className="mt-2 rounded-md border border-warning/40 bg-warning/10 px-2 py-1 text-xs text-content">
                  {d.last_error}
                </p>
              )}
              {!d.failing && d.last_sent_at && (
                <p className="mt-1 text-xs text-content-subtle">
                  Last posted {dayAndTime(d.last_sent_at)}
                </p>
              )}
              {tested[d.id] && (
                <p className="mt-1 text-xs text-content" aria-live="polite">
                  {tested[d.id]}
                </p>
              )}
              {editing !== 'new' && editing?.id === d.id && (
                <DestinationForm
                  kind={kind}
                  destination={d}
                  account={account}
                  choices={listing.choices}
                  offices={offices}
                  teams={teams}
                  onClose={() => setEditing(null)}
                  onSaved={() => {
                    setEditing(null);
                    load();
                  }}
                />
              )}
            </li>
          ))}
        </ul>
      )}

      {editing === 'new' ? (
        <DestinationForm
          kind={kind}
          account={account}
          choices={listing.choices}
          offices={offices}
          teams={teams}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            load();
          }}
        />
      ) : (
        <button
          type="button"
          onClick={() => setEditing('new')}
          className="rounded-md border border-edge px-4 py-2 text-sm text-content hover:border-brand"
        >
          {isTeams ? 'Add a Teams channel' : 'Add a Slack channel'}
        </button>
      )}
    </div>
  );
}

/** Who posts into picked channels, and the one button that changes it. */
function AccountStrip({
  account,
  busy,
  onSignIn,
  onSignOut,
}: {
  account: Account | null;
  busy: boolean;
  onSignIn: () => void;
  onSignOut: () => void;
}) {
  if (!account) return null;
  if (!account.registered) {
    return (
      <p className="rounded-md border border-edge px-3 py-2 text-sm text-content-muted">
        Connect Microsoft 365 to pick channels from a list. Until then, a channel is added with a
        Workflows link made inside it.
      </p>
    );
  }
  if (account.connected) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-edge px-3 py-2 text-sm">
        <span className="text-content-muted">
          Posting to picked channels as{' '}
          <strong className="text-content">
            {account.connected_as || 'the signed-in account'}
          </strong>
        </span>
        <span className="flex gap-3">
          <button
            type="button"
            disabled={busy}
            onClick={onSignIn}
            className="text-brand hover:underline disabled:opacity-60"
          >
            Change account
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={onSignOut}
            className="text-content-muted hover:text-danger disabled:opacity-60"
          >
            Sign out
          </button>
        </span>
      </div>
    );
  }
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-dashed border-edge px-3 py-3 text-sm">
      <p className="max-w-lg text-content-muted">
        <strong className="text-content">Pick channels from a list</strong> by signing in the
        account posts will come from. One made for this, such as “GoalGetter”, reads best — it can
        post only in Teams it is a member of.
      </p>
      <button
        type="button"
        disabled={busy}
        onClick={onSignIn}
        className="rounded-md bg-brand px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-60"
      >
        {busy ? 'Waiting…' : 'Sign in with Microsoft'}
      </button>
    </div>
  );
}

/** Team, then channel — both asked of Microsoft as the posting account. */
function ChannelPicker({
  team,
  channel,
  onTeam,
  onChannel,
}: {
  team: string;
  channel: string;
  onTeam: (id: string) => void;
  onChannel: (id: string, name: string) => void;
}) {
  const [teams, setTeams] = useState<Choosable[] | null>(null);
  const [channels, setChannels] = useState<Choosable[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Choosable[]>('/api/announcements/account/teams')
      .then(setTeams)
      .catch((e) => {
        setTeams([]);
        setError(e instanceof Error ? e.message : 'Could not list Teams.');
      });
  }, []);

  useEffect(() => {
    if (!team) {
      setChannels(null);
      return;
    }
    setChannels(null);
    api<Choosable[]>(`/api/announcements/account/teams/${encodeURIComponent(team)}/channels`)
      .then(setChannels)
      .catch((e) => {
        setChannels([]);
        setError(e instanceof Error ? e.message : 'Could not list channels.');
      });
  }, [team]);

  const field = 'mt-1 w-full rounded-md border border-edge bg-bg px-3 py-2 text-sm text-content';

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="block">
        <span className="text-sm text-content-muted">Team</span>
        <select
          value={team}
          onChange={(e) => onTeam(e.target.value)}
          className={field}
          disabled={teams === null}
        >
          <option value="">
            {teams === null ? 'Loading…' : teams.length ? 'Choose a Team' : 'No Teams found'}
          </option>
          {(teams ?? []).map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
      </label>
      <label className="block">
        <span className="text-sm text-content-muted">Channel</span>
        <select
          value={channel}
          onChange={(e) => {
            const found = (channels ?? []).find((c) => c.id === e.target.value);
            onChannel(e.target.value, found?.name ?? '');
          }}
          className={field}
          disabled={!team || channels === null}
        >
          <option value="">
            {!team ? 'Choose a Team first' : channels === null ? 'Loading…' : 'Choose a channel'}
          </option>
          {(channels ?? []).map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
              {c.membership && c.membership !== 'standard' ? ` (${c.membership})` : ''}
            </option>
          ))}
        </select>
      </label>
      {error && (
        <p role="alert" className="text-xs text-danger sm:col-span-2">
          {error}
        </p>
      )}
      {teams !== null && teams.length === 0 && !error && (
        <p className="text-xs text-content-subtle sm:col-span-2">
          The posting account is not in any Team yet. Add it to the Teams it should post in.
        </p>
      )}
    </div>
  );
}

function DestinationForm({
  kind,
  destination,
  account,
  choices,
  offices,
  teams,
  onClose,
  onSaved,
}: {
  kind: 'teams' | 'slack';
  destination?: Destination;
  account: Account | null;
  choices: Choice[];
  offices: Named[];
  teams: Named[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const isTeams = kind === 'teams';
  // Picking needs the Microsoft account; Slack is a webhook link, always.
  const canPick = isTeams && !!account?.connected;
  const [via, setVia] = useState<'graph' | 'workflow'>(
    destination?.via ?? (canPick ? 'graph' : 'workflow'),
  );
  const [name, setName] = useState(destination?.name ?? '');
  // Filled from the channel's own name until somebody types one.
  const [named, setNamed] = useState(!!destination);
  const [link, setLink] = useState('');
  const [pickedTeam, setPickedTeam] = useState(destination?.team_external_id ?? '');
  const [pickedChannel, setPickedChannel] = useState(destination?.channel_external_id ?? '');
  const [events, setEvents] = useState<string[]>(
    destination?.events ?? [
      'goal.achieved',
      'goal.stretch',
      'recognition',
      'competition.won',
      'achievement',
    ],
  );
  const [scope, setScope] = useState(
    destination?.office_id
      ? `office:${destination.office_id}`
      : destination?.team_id
        ? `team:${destination.team_id}`
        : 'everyone',
  );
  const [enabled, setEnabled] = useState(destination?.enabled ?? true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await api(
        destination
          ? `/api/announcements/destinations/${destination.id}`
          : '/api/announcements/destinations',
        {
          method: destination ? 'PATCH' : 'POST',
          body: JSON.stringify({
            kind,
            name,
            via,
            ...(via === 'graph'
              ? {
                  team_external_id: pickedTeam,
                  channel_external_id: pickedChannel,
                }
              : // Absent on an edit unless a new one was pasted: the stored
                // link is never sent back, so there is nothing to re-send.
                link.trim()
                ? { webhook_url: link.trim() }
                : {}),
            events,
            office_id: scope.startsWith('office:') ? Number(scope.slice(7)) : null,
            team_id: scope.startsWith('team:') ? Number(scope.slice(5)) : null,
            enabled,
          }),
        },
      );
      onSaved();
    } catch (e) {
      // The server's words — for a bad link they say how to make a good one.
      setError(e instanceof Error ? e.message : 'Could not save.');
    } finally {
      setSaving(false);
    }
  }

  const field = 'mt-1 w-full rounded-md border border-edge bg-bg px-3 py-2 text-sm text-content';
  // A Workflows link is needed when there is not one already stored.
  const needsLink = via === 'workflow' && !(destination?.via === 'workflow');
  const ready =
    name.trim() &&
    events.length > 0 &&
    (via === 'graph' ? pickedTeam && pickedChannel : !needsLink || link.trim());

  return (
    <div className="mt-3 space-y-4 rounded-md border border-edge bg-surface-hover p-4">
      {isTeams && (
        <fieldset>
          <legend className="text-sm text-content-muted">Where to post</legend>
          <div className="mt-2 flex flex-wrap gap-4 text-sm text-content">
            <label
              className={`flex items-center gap-2 ${canPick || via === 'graph' ? '' : 'opacity-60'}`}
            >
              <input
                type="radio"
                name="via"
                checked={via === 'graph'}
                disabled={!canPick && via !== 'graph'}
                onChange={() => setVia('graph')}
              />
              Pick a channel
            </label>
            <label className="flex items-center gap-2">
              <input
                type="radio"
                name="via"
                checked={via === 'workflow'}
                onChange={() => setVia('workflow')}
              />
              Use a Workflows link
            </label>
          </div>
          {!canPick && (
            <p className="mt-1 text-xs text-content-subtle">
              Sign in an account above to pick channels from a list.
            </p>
          )}
        </fieldset>
      )}

      {via === 'graph' && canPick && (
        <ChannelPicker
          team={pickedTeam}
          channel={pickedChannel}
          onTeam={(id) => {
            setPickedTeam(id);
            setPickedChannel('');
          }}
          onChannel={(id, channelName) => {
            setPickedChannel(id);
            if (!named && channelName) setName(channelName.slice(0, 80));
          }}
        />
      )}
      {via === 'graph' && !canPick && destination?.channel_label && (
        <p className="text-sm text-content-muted">
          {destination.channel_label} — sign an account in above to post here or change it.
        </p>
      )}

      <label className="block">
        <span className="text-sm text-content-muted">Name</span>
        <input
          value={name}
          maxLength={80}
          onChange={(e) => {
            setName(e.target.value);
            setNamed(true);
          }}
          placeholder="Sales floor channel"
          className={field}
        />
      </label>

      {via === 'workflow' && (
        <label className="block">
          <span className="text-sm text-content-muted">
            {(isTeams ? 'Workflows link' : 'Incoming webhook link') +
              (needsLink ? '' : ' (leave empty to keep the current one)')}
          </span>
          <input
            value={link}
            onChange={(e) => setLink(e.target.value)}
            placeholder={
              isTeams
                ? 'https://…logic.azure.com/workflows/…'
                : 'https://hooks.slack.com/services/…'
            }
            className={field}
            autoComplete="off"
          />
          <span className="mt-1 block text-xs text-content-subtle">
            {isTeams ? (
              <>
                In the Teams channel: <strong>⋯</strong> → <strong>Workflows</strong> →{' '}
                <strong>Post to a channel when a webhook request is received</strong>. Finish the
                steps and copy the link it gives you.
              </>
            ) : (
              <>
                In Slack: add the <strong>Incoming Webhooks</strong> app, choose{' '}
                <strong>Add New Webhook to Workspace</strong>, pick the channel, and copy the link
                it gives you.
              </>
            )}{' '}
            It is stored encrypted and never shown again in full.
          </span>
        </label>
      )}

      <fieldset>
        <legend className="text-sm text-content-muted">What to announce</legend>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          {choices.map((choice) => (
            <label key={choice.key} className="flex items-center gap-2 text-sm text-content">
              <input
                type="checkbox"
                checked={events.includes(choice.key)}
                onChange={(e) =>
                  setEvents(
                    e.target.checked
                      ? [...events, choice.key]
                      : events.filter((key) => key !== choice.key),
                  )
                }
              />
              {choice.label}
            </label>
          ))}
        </div>
      </fieldset>

      <label className="block">
        <span className="text-sm text-content-muted">Whose wins</span>
        <select value={scope} onChange={(e) => setScope(e.target.value)} className={field}>
          <option value="everyone">Everyone</option>
          {offices.length > 0 && (
            <optgroup label="One office">
              {offices.map((o) => (
                <option key={`o${o.id}`} value={`office:${o.id}`}>
                  {o.name}
                </option>
              ))}
            </optgroup>
          )}
          {teams.length > 0 && (
            <optgroup label="One team">
              {teams.map((t) => (
                <option key={`t${t.id}`} value={`team:${t.id}`}>
                  {t.name}
                </option>
              ))}
            </optgroup>
          )}
        </select>
      </label>

      {destination && (
        <label className="flex items-center gap-2 text-sm text-content">
          <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          Posting to this channel
        </label>
      )}

      {error && (
        <p role="alert" className="rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => void save()}
          disabled={saving || !ready}
          className="rounded-md bg-brand px-4 py-2 text-sm text-white disabled:opacity-60"
        >
          {saving ? 'Saving…' : 'Save'}
        </button>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md px-4 py-2 text-sm text-content-muted hover:text-content"
        >
          Cancel
        </button>
      </div>
      <p className="text-xs text-content-subtle">
        A new channel starts from now — it is not sent every win from before it was added.
      </p>
    </div>
  );
}
