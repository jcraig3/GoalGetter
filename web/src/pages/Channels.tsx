import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';

import { api } from '../api';
import { toast } from '../toast';
import { useOrgAppearance } from '../orgAppearance';
import { Can, useAuth } from '../auth';
import EmptyState from '../components/EmptyState';
import AppearanceFields from '../components/AppearanceFields';
import Field from '../components/Field';
import IconButton from '../components/IconButton';
import Modal from '../components/Modal';
import { Tab } from '../components/Tabs';
import PageHeader from '../components/PageHeader';
import {
  CopyIcon,
  PencilIcon,
  RepeatIcon,
  TrashIcon,
  TvIcon,
} from '../components/icons';
import { ask } from '../confirm';
import { agoInWords } from '../time';
import Loading from '../components/Loading';
import ChannelTemplates from '../components/ChannelTemplates';
import { hhmm, QuietFields, type QuietSettings } from '../components/RotationSchedule';
import { useOpenFromUrl } from '../urlIntent';
import TvSoundHelp from '../components/TvSoundHelp';

interface Screen {
  id: number;
  kind: string;
  label: string;
  dwell_seconds: number;
}

interface Channel {
  id: number;
  name: string;
  scope_type: string;
  scope_office_id: number | null;
  scope_team_id: number | null;
  /** Only what this channel itself chose; absent keys inherit. */
  appearance: Record<string, unknown>;
  audience_label: string;
  allowed_ips: string[];
  /** Night mode (6.10). Times are "HH:MM:SS". */
  quiet_mode?: 'off' | 'clock' | 'dark';
  quiet_from?: string | null;
  quiet_until?: string | null;
  quiet_weekends?: boolean;
  screens: Screen[];
  display_count: number;
}

interface Office {
  id: number;
  name: string;
}

interface Team {
  id: number;
  name: string;
}

interface Display {
  id: number;
  name: string;
  channel_id: number;
  channel_name: string;
  last_seen_at: string | null;
  /** Its browser held a celebration's sound back (Phase 24). */
  sound_blocked?: boolean;
  revoked: boolean;
  created_at: string;
  url: string;
}

/** "never", or how long ago in words a room can act on. */
function lastSeen(iso: string | null): { text: string; live: boolean } {
  if (!iso) return { text: 'never connected', live: false };
  const minutes = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 10) return { text: 'live now', live: true };
  return { text: agoInWords(new Date(iso)), live: false };
}

/**
 * Channels, and the televisions playing them.
 *
 * A channel is **authored** now rather than derived. Through Phase 1 a display
 * pointed at an office and played whatever boards matched, ordered by name —
 * nobody chose the running order, and a board was the only thing a wall could
 * show. Now somebody builds the playlist and points screens at it.
 */
export default function Channels() {
  const { can } = useAuth();
  const navigate = useNavigate();
  const [channels, setChannels] = useState<Channel[] | null>(null);
  const [displays, setDisplays] = useState<Display[]>([]);
  const [offices, setOffices] = useState<Office[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);
  const [creatingChannel, setCreatingChannel] = useState(false);
  const [templating, setTemplating] = useState(false);
  const [creatingDisplay, setCreatingDisplay] = useState(false);
  useOpenFromUrl('new', () => setCreatingChannel(true));
  useOpenFromUrl('connect', () => setCreatingDisplay(true));
  const [params] = useSearchParams();
  const [error, setError] = useState<string | null>(null);
  //: Which screen was just asked to reload, so the button can say so.
  const [reloading, setReloading] = useState<number | null>(null);

  const isAdmin = can('integrations.manage');

  const load = useCallback(async () => {
    try {
      if (!isAdmin) {
        setChannels([]);
        return;
      }
      const [c, d, o, t] = await Promise.all([
        api<Channel[]>('/api/channels'),
        api<Display[]>('/api/displays'),
        api<Office[]>('/api/offices'),
        api<Team[]>('/api/teams'),
      ]);
      setChannels(c);
      setDisplays(d);
      setOffices(o);
      setTeams(t);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load channels.');
    }
  }, [isAdmin]);

  useEffect(() => {
    void load();
  }, [load]);

  /** No archive for channels — nothing historical points at one, so deleting
   *  is the only retirement it needs. The API still refuses while a television
   *  plays it, and says how many. */

  async function reassign(display: Display, channelId: number) {
    try {
      await api(`/api/displays/${display.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ channel_id: channelId }),
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not move that TV.');
    }
  }

  async function askReload(display: Display) {
    try {
      await api(`/api/displays/${display.id}/reload`, { method: 'POST' });
      // Not immediate, and the label says so: the screen finds out when it
      // next polls, which is within its refresh interval.
      setReloading(display.id);
      window.setTimeout(() => setReloading(null), 4000);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not reach that TV.');
    }
  }

  async function duplicate(channel: Channel) {
    try {
      const copy = await api<Channel>(
        `/api/channels/${channel.id}/duplicate`,
        { method: 'POST' },
      );
      // Straight into the copy: somebody duplicated it to change something,
      // and the list would leave them hunting for which of two similar names
      // is the new one.
      navigate(`/channels/${copy.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not duplicate that.');
    }
  }

  async function remove(channel: Channel) {
    if (
      !await ask(
        `Delete "${channel.name}"? Its ${channel.screens.length} slide${
          channel.screens.length === 1 ? '' : 's'
        } go with it, and this cannot be undone.`,
      )
    )
      return;

    setError(null);
    try {
      await api(`/api/channels/${channel.id}`, { method: 'DELETE' });
      toast('Channel deleted');
      await load();
    } catch (e) {
      // Shown verbatim: the refusal names how many screens are in the way,
      // which is the actionable part.
      setError(e instanceof Error ? e.message : 'Could not delete that.');
    }
  }

  async function revoke(display: Display) {
    if (
      !await ask(
        `Revoke "${display.name}"? Its link stops working for good, and within a few seconds the television shows a pairing code instead — enter it under Connect a TV to put that screen back.`,
      )
    )
      return;
    setError(null);
    try {
      await api(`/api/displays/${display.id}/revoke`, { method: 'POST' });
      toast('TV revoked — it now shows a pairing code');
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not revoke.');
    }
  }

  // **A revoked television can leave the list.** It stays refused either way —
  // the link is dead — so keeping the row forever only buries the live ones
  // (QA-17). The activity log keeps the record.
  async function forget(display: Display) {
    if (!await ask(`Remove "${display.name}" from the list? Its link already does not work.`)) return;
    setError(null);
    try {
      await api(`/api/displays/${display.id}`, { method: 'DELETE' });
      toast('Removed from the list');
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not remove that.');
    }
  }

  return (
    <>
      <PageHeader
        title="TVs & Channels"
        description="What plays on the walls, and which TVs are connected. A channel is a playlist of slides; a TV plays one channel."
        actions={
          <Can do="integrations.manage">
            <div className="flex gap-2">
              <button
                onClick={() => setCreatingChannel(true)}
                className="rounded-md bg-brand px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover"
              >
                New channel
              </button>
              <button
                onClick={() => setTemplating(true)}
                className="rounded-md border border-edge px-3 py-2 text-sm text-content transition-colors hover:bg-surface-hover"
              >
                From a template
              </button>
              <button
                onClick={() => setCreatingDisplay(true)}
                className="rounded-md border border-edge px-3 py-2 text-sm text-content transition-colors hover:bg-surface-hover"
              >
                Connect a TV
              </button>
            </div>
          </Can>
        }
      />

      {error && (
        <p role="alert" className="mb-4 rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      <Can do="integrations.manage">
        <section className="mb-8">
          <h2 className="mb-3 text-caption uppercase tracking-wide text-content-subtle">
            Channels
          </h2>

          {channels === null ? (
            <Loading />
          ) : channels.length === 0 ? (
            <EmptyState
              title="No channels yet"
              description="A channel is an ordered playlist — leaderboards, goals, messages — that televisions point at. The quickest start is a template, filled from what you have now."
              action={
                <button
                  type="button"
                  onClick={() => setTemplating(true)}
                  className="rounded-md bg-brand px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover"
                >
                  Start from a template
                </button>
              }
            />
          ) : (
            <div className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(20rem,1fr))]">
              {channels.map((channel) => (
                <div
                  key={channel.id}
                  className="flex flex-col rounded-lg border border-edge bg-surface p-4"
                >
                  <div className="flex items-start justify-between gap-2">
                    <Link
                      to={`/channels/${channel.id}`}
                      className="min-w-0 truncate font-medium text-content hover:text-brand"
                    >
                      {channel.name}
                    </Link>
                    <div className="flex shrink-0 gap-1">
                      {/* Edit is the way in to arranging screens, and the
                          settings cog lives in there — one door rather than two
                          links doing nearly the same thing. */}
                      <IconButton
                        label="Edit"
                        icon={<PencilIcon className="size-4" />}
                        onClick={() => navigate(`/channels/${channel.id}`)}
                      />
                      {/* **The second wall is almost the first one.** A floor
                          with two televisions wants the same rotation with one
                          board swapped, and building it screen by screen is a
                          dozen forms to reach a difference of one. */}
                      <IconButton
                        label="Duplicate"
                        icon={<CopyIcon className="size-4" />}
                        onClick={() => void duplicate(channel)}
                      />
                      <IconButton
                        label="Delete"
                        icon={<TrashIcon className="size-4" />}
                        onClick={() => void remove(channel)}
                        danger
                      />
                    </div>
                  </div>

                  {/* The audience, said plainly. It is the thing that stops one
                      office's numbers turning up on another's wall, so it is
                      worth seeing without opening the channel. */}
                  <p className="mt-1 text-xs">
                    <span
                      className={
                        channel.scope_type === 'organization'
                          ? 'text-content-subtle'
                          : 'text-brand'
                      }
                    >
                      {channel.audience_label}
                    </span>
                    <span className="text-content-subtle">
                      {' · '}
                      {channel.screens.length} slide
                      {channel.screens.length === 1 ? '' : 's'}
                      {' · '}
                      {channel.display_count} TV
                      {channel.display_count === 1 ? '' : 's'}
                    </span>
                  </p>

                  {channel.screens.length > 0 && (
                    <p className="mt-3 truncate text-xs text-content-muted">
                      {channel.screens.map((s) => s.label).join(' · ')}
                    </p>
                  )}


                </div>
              ))}
            </div>
          )}
        </section>

        <section>
          <h2 className="mb-3 text-caption uppercase tracking-wide text-content-subtle">
            Connected TVs
          </h2>

          {displays.length === 0 ? (
            <EmptyState
              title="No TVs yet"
              description="A TV link signs a television in on its own. Open it once on the TV and leave it there."
            />
          ) : (
            <div className="overflow-x-auto rounded-lg border border-edge bg-surface">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-edge text-left text-caption uppercase tracking-wide text-content-subtle">
                    <th className="px-4 py-3 font-medium">TV</th>
                    <th className="px-4 py-3 font-medium">Playing</th>
                    <th className="px-4 py-3 font-medium">Last seen</th>
                    <th className="px-4 py-3" />
                  </tr>
                </thead>
                <tbody>
                  {displays.map((display) => {
                    const seen = lastSeen(display.last_seen_at);
                    return (
                      <tr
                        key={display.id}
                        className={`border-b border-edge last:border-0 ${
                          display.revoked ? 'opacity-50' : ''
                        }`}
                      >
                        <td className="px-4 py-3 text-content">{display.name}</td>
                        <td className="px-4 py-3">
                          {/* **Reassigning beats revoking and re-pairing.** A
                              television showing the wrong channel used to be a
                              job with a ladder: revoke, make a new display,
                              walk to the screen, type a new URL. The token was
                              never the thing that was wrong. */}
                          {display.revoked ? (
                            <span className="text-content-muted">
                              {display.channel_name}
                            </span>
                          ) : (
                            <select
                              value={display.channel_id}
                              aria-label={`Channel for ${display.name}`}
                              onChange={(e) =>
                                void reassign(display, Number(e.target.value))
                              }
                              className="rounded-md border border-edge bg-bg px-2 py-1 text-sm text-content outline-none focus:border-brand"
                            >
                              {(channels ?? []).map((channel) => (
                                <option key={channel.id} value={channel.id}>
                                  {channel.name}
                                </option>
                              ))}
                            </select>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          {display.revoked ? (
                            <span className="text-xs text-content-subtle">revoked</span>
                          ) : (
                            <>
                              <span
                                className={`text-xs ${
                                  seen.live ? 'text-success' : 'text-content-subtle'
                                }`}
                              >
                                {seen.text}
                              </span>
                              {display.sound_blocked && (
                                <span className="block text-xs text-warning">Sound off</span>
                              )}
                            </>
                          )}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex justify-end gap-1">
                            {display.revoked && (
                              <IconButton
                                label="Remove from list"
                                icon={<TrashIcon className="size-4" />}
                                onClick={() => void forget(display)}
                              />
                            )}
                            {!display.revoked && (
                              <>
                                <IconButton
                                  label="Open"
                                  icon={<TvIcon className="size-4" />}
                                  href={display.url}
                                />
                                <CopyLink url={display.url} />
                                {/* For the browser open since a deploy three
                                    weeks ago, and for the one that has wedged.
                                    Both look identical from a desk. */}
                                <IconButton
                                  label={
                                    reloading === display.id
                                      ? 'Asked'
                                      : 'Reload TV'
                                  }
                                  icon={<RepeatIcon className="size-4" />}
                                  onClick={() => void askReload(display)}
                                />
                                <IconButton
                                  label="Revoke"
                                  icon={<TrashIcon className="size-4" />}
                                  onClick={() => void revoke(display)}
                                  danger
                                />
                              </>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          <TvSoundHelp tvs={(displays ?? []).filter((d) => d.sound_blocked && !d.revoked)} />

          {/* Said once, where the links are. */}
          <p className="mt-3 text-xs text-content-muted">
            A display link is the whole credential — anyone who has it can see
            that channel, so treat it like a door code rather than a web page.
            It only ever grants that one channel, read-only, and only boards
            visible to everyone. Revoking it stops that TV straight away, and it shows a pairing code instead.
          </p>
        </section>
      </Can>

      {templating && (
        <ChannelTemplates
          onClose={() => setTemplating(false)}
          onMade={(id) => {
            setTemplating(false);
            navigate(`/channels/${id}`);
          }}
        />
      )}

      {creatingChannel && (
        <ChannelForm
          channel={null}
          offices={offices}
          teams={teams}
          onClose={() => setCreatingChannel(false)}
          onSaved={async () => {
            toast('Channel created');
            setError(null);
            setCreatingChannel(false);
            await load();
          }}
          onError={setError}
        />
      )}

      {creatingDisplay && channels && (
        <DisplayForm
          channels={channels}
          initialChannel={params.get('channel') ?? ''}
          onClose={() => setCreatingDisplay(false)}
          onCreated={async (said: string) => {
            toast(said);
            setError(null);
            setCreatingDisplay(false);
            // Opened from a channel's page: back to it, not left on the list
            // with "?channel=18" in the address (P3-16).
            const from = params.get('channel');
            if (from) {
              void navigate(`/channels/${from}`);
              return;
            }
            await load();
          }}
          onError={setError}
        />
      )}
    </>
  );
}

/** Copy a television's link, for sending to whoever is standing at it. */
function CopyLink({ url }: { url: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access can be refused over plain HTTP. Open still works and
      // its address bar has the URL, so there is no dead end to report.
    }
  }

  return (
    <IconButton
      label={copied ? 'Copied' : 'Copy link'}
      icon={<CopyIcon className="size-4" />}
      onClick={() => void copy()}
    />
  );
}

/**
 * A channel's name and, more importantly, its audience.
 *
 * The audience is what stops one office's numbers turning up on another
 * office's wall. Set once here, inherited by every screen — so a wall is right
 * by default and spillover is something somebody chose rather than something
 * they forgot.
 */
export function ChannelForm({
  channel,
  offices,
  teams,
  onClose,
  onSaved,
  onError,
}: {
  channel: Channel | null;
  offices: Office[];
  teams: Team[];
  onClose: () => void;
  onSaved: () => Promise<void>;
  onError: (message: string) => void;
}) {
  const [name, setName] = useState(channel?.name ?? '');
  const [scope, setScope] = useState(channel?.scope_type ?? 'organization');
  const [officeId, setOfficeId] = useState(String(channel?.scope_office_id ?? ''));
  const [teamId, setTeamId] = useState(String(channel?.scope_team_id ?? ''));
  // One per line, which is how people paste a list of addresses.
  const [allowed, setAllowed] = useState((channel?.allowed_ips ?? []).join('\n'));
  // Whether this host can see screens' addresses at all (P6-1). Null until
  // asked, or for somebody who cannot ask: then nothing extra is said.
  const [addressesVisible, setAddressesVisible] = useState<boolean | null>(null);
  useEffect(() => {
    api<{ addresses_visible?: boolean }>('/api/hosting')
      .then((h) => setAddressesVisible(h.addresses_visible ?? true))
      .catch(() => setAddressesVisible(null));
  }, []);
  const [appearance, setAppearance] = useState<Record<string, unknown>>(
    channel?.appearance ?? {},
  );
  const inherited = useOrgAppearance();
  const [quiet, setQuiet] = useState<QuietSettings>({
    mode: channel?.quiet_mode ?? 'off',
    from: hhmm(channel?.quiet_from),
    until: hhmm(channel?.quiet_until),
    weekends: channel?.quiet_weekends ?? false,
  });
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await api(channel ? `/api/channels/${channel.id}` : '/api/channels', {
        method: channel ? 'PATCH' : 'POST',
        body: JSON.stringify({
          name,
          scope_type: scope,
          scope_office_id: scope === 'office' ? Number(officeId) : null,
          scope_team_id: scope === 'team' ? Number(teamId) : null,
          allowed_ips: allowed
            .split('\n')
            .map((line) => line.trim())
            .filter(Boolean),
          appearance,
          quiet_mode: quiet.mode,
          quiet_from: quiet.mode === 'off' ? null : quiet.from || null,
          quiet_until: quiet.mode === 'off' ? null : quiet.until || null,
          quiet_weekends: quiet.mode !== 'off' && quiet.weekends,
        }),
      });
      await onSaved();
    } catch (e) {
      onError(e instanceof Error ? e.message : 'Could not save that.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title={channel ? 'Channel settings' : 'New channel'}
      description="A playlist for a wall, and who it is about."
      onClose={onClose}
    >
      <form onSubmit={submit} className="space-y-4">
        <Field
          label="Name"
          value={name}
          onChange={setName}
          maxLength={120}
          hint="Where it plays. 'Phoenix sales floor' beats 'Channel 2'."
        />

        <AudiencePicker
          scope={scope}
          setScope={setScope}
          officeId={officeId}
          setOfficeId={setOfficeId}
          teamId={teamId}
          setTeamId={setTeamId}
          offices={offices}
          teams={teams}
          hint="Every slide on this channel shows only this group, unless a slide is set otherwise."
        />

        <div>
          <label htmlFor="allowed" className="block text-sm text-content-muted">
            Only watchable from (optional)
          </label>
          <textarea
            id="allowed"
            value={allowed}
            onChange={(e) => setAllowed(e.target.value)}
            rows={3}
            placeholder={'203.0.113.0/24\n198.51.100.7'}
            className="mt-1 w-full rounded-md border border-edge bg-bg px-3 py-2 font-mono text-sm text-content outline-none focus:border-brand"
          />
          <p className="mt-1 text-xs text-content-muted">
            {/* Said plainly, because the consequence of getting it wrong is a
                dark television and somebody standing in front of it. */}
            One address or range per line. Leave empty and the link works from
            anywhere. A display link is visible on a wall all day, so this is
            what makes a photograph of it useless outside the office.
          </p>
          {addressesVisible === false && (
            <p className="mt-2 rounded-md border border-warning px-3 py-2 text-xs text-warning">
              This server cannot see screens’ addresses (Docker Desktop hides them), so a list here
              would turn every TV away. Leave it empty on this server.
            </p>
          )}
        </div>

        <QuietFields value={quiet} onChange={setQuiet} />

        {/* **The venue layer.** A wall in a lobby and a wall on the sales
            floor want different things from the same boards — initials rather
            than surnames, fewer rows, a quieter background — and that belongs
            to the room the screen is in rather than to each thing shown on
            it. */}
        <div className="border-t border-edge pt-4">
          <AppearanceFields
            kind="leaderboard"
            chosen={appearance}
            inherited={inherited}
            onChange={setAppearance}
          />
        </div>

        <div className="flex items-center gap-3 pt-2">
          <button
            type="submit"
            disabled={busy || !name.trim()}
            className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
          >
            {busy ? 'Saving…' : channel ? 'Save' : 'Create'}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-edge px-4 py-2 text-sm text-content-muted transition-colors hover:bg-surface-hover hover:text-content"
          >
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  );
}

/** Shared by the channel form and the per-screen override, so the two can
 *  never drift into offering different choices. */
export function AudiencePicker({
  scope,
  setScope,
  officeId,
  setOfficeId,
  teamId,
  setTeamId,
  offices,
  teams,
  hint,
  inheritLabel,
}: {
  scope: string;
  setScope: (value: string) => void;
  officeId: string;
  setOfficeId: (value: string) => void;
  teamId: string;
  setTeamId: (value: string) => void;
  offices: Office[];
  teams: Team[];
  hint?: string;
  /** Present on the per-screen override, where "" means inherit. */
  inheritLabel?: string;
}) {
  return (
    <div>
      <label htmlFor="audience" className="block text-sm text-content-muted">
        Shows data for
      </label>
      <select
        id="audience"
        value={scope}
        onChange={(e) => setScope(e.target.value)}
        className="mt-1 w-full rounded-md border border-edge bg-bg px-3 py-2 text-content outline-none focus:border-brand"
      >
        {inheritLabel && <option value="">{inheritLabel}</option>}
        <option value="organization">Everyone</option>
        <option value="office">One office</option>
        <option value="team">One team</option>
      </select>
      {hint && <p className="mt-1 text-xs text-content-muted">{hint}</p>}

      {scope === 'office' && (
        <select
          value={officeId}
          onChange={(e) => setOfficeId(e.target.value)}
          aria-label="Office"
          className="mt-2 w-full rounded-md border border-edge bg-bg px-3 py-2 text-content outline-none focus:border-brand"
        >
          <option value="">Choose an office…</option>
          {offices.map((office) => (
            <option key={office.id} value={office.id}>
              {office.name}
            </option>
          ))}
        </select>
      )}

      {scope === 'team' && (
        <select
          value={teamId}
          onChange={(e) => setTeamId(e.target.value)}
          aria-label="Team"
          className="mt-2 w-full rounded-md border border-edge bg-bg px-3 py-2 text-content outline-none focus:border-brand"
        >
          <option value="">Choose a team…</option>
          {teams.map((team) => (
            <option key={team.id} value={team.id}>
              {team.name}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}

function DisplayForm({
  channels,
  initialChannel = '',
  onClose,
  onCreated,
  onError,
}: {
  channels: Channel[];
  /** Chosen already when it was opened from a channel's own page (8.5). */
  initialChannel?: string;
  onClose: () => void;
  onCreated: (said: string) => Promise<void>;
  onError: (message: string) => void;
}) {
  // **Pairing first, because it is the path that works on a television.**
  // A link has to be typed in with a remote control, which is thirty
  // characters at four arrow presses each; a code goes the other way, read off
  // the screen by eye. The link is still here for a browser somebody can
  // paste into.
  const [mode, setMode] = useState<'pair' | 'link'>('pair');
  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [channelId, setChannelId] = useState(initialChannel);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      const channelName = channels.find((c) => String(c.id) === channelId)?.name;
      if (mode === 'pair') {
        await api('/api/displays/pair', {
          method: 'POST',
          body: JSON.stringify({
            code,
            name,
            channel_id: Number(channelId),
          }),
        });
        // Said as what happened (Q2-22): it is on, and playing something.
        await onCreated(`${name || 'TV'} connected — playing ${channelName ?? 'its channel'}`);
      } else {
        await api('/api/displays', {
          method: 'POST',
          body: JSON.stringify({ name, channel_id: Number(channelId) }),
        });
        await onCreated('TV link created — open it on the TV');
      }
    } catch (e) {
      onError(e instanceof Error ? e.message : 'Could not add the display.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Connect a TV"
      description="A television signs itself in — by code, or by a link you paste."
      onClose={onClose}
    >
      <form onSubmit={submit} className="space-y-4">
        <div className="flex gap-2">
          <Tab active={mode === 'pair'} onClick={() => setMode('pair')}>
            Pair with a code
          </Tab>
          <Tab active={mode === 'link'} onClick={() => setMode('link')}>
            Create a link
          </Tab>
        </div>

        {mode === 'pair' ? (
          <Field
            label="Code on the TV"
            value={code}
            onChange={setCode}
            maxLength={16}
            hint="Open /pair on the television and read the four characters it shows."
          />
        ) : (
          <p className="rounded-md border border-edge px-3 py-2 text-xs text-content-muted">
            Use this when you can paste a link into the television's browser.
            Otherwise pair it — typing thirty characters with a remote is the
            worst part of setting a screen up.
          </p>
        )}

        <Field
          label="Name"
          value={name}
          onChange={setName}
          maxLength={120}
          hint="Where it is. 'Phoenix TV by the stairs' beats 'Display 3' when somebody has to revoke it."
        />

        <div>
          <label htmlFor="channel" className="block text-sm text-content-muted">
            Plays
          </label>
          <select
            id="channel"
            value={channelId}
            onChange={(e) => setChannelId(e.target.value)}
            className="mt-1 w-full rounded-md border border-edge bg-bg px-3 py-2 text-content outline-none focus:border-brand"
          >
            <option value="">Choose a channel…</option>
            {channels.map((channel) => (
              <option key={channel.id} value={channel.id}>
                {channel.name}
              </option>
            ))}
          </select>
          {/* No default. Through Phase 1 a missing office meant "everything";
              a channel is something somebody built, so there is nothing
              sensible to fall back to. */}
          <p className="mt-1 text-xs text-content-muted">
            Several televisions can play the same channel.
          </p>
        </div>

        <p className="rounded-md border border-warning px-3 py-2 text-xs text-warning">
          The link is shown in the list afterwards and can be copied at any
          time. Treat it like a door code: anyone who has it can watch that
          channel.
        </p>

        <div className="flex items-center gap-3 pt-2">
          <button
            type="submit"
            disabled={
              busy || !name || !channelId || (mode === 'pair' && !code.trim())
            }
            className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
          >
            {busy
              ? 'Adding…'
              : mode === 'pair'
                ? 'Connect TV'
                : 'Create link'}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-edge px-4 py-2 text-sm text-content-muted transition-colors hover:bg-surface-hover hover:text-content"
          >
            Cancel
          </button>
        </div>
      </form>
    </Modal>
  );
}
