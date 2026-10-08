import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { api } from '../api';
import { toast } from '../toast';
import Modal from './Modal';
import PreviewOnTv from './PreviewOnTv';

/** What can be put on a TV from its own page. */
export type ShowKind = 'leaderboard' | 'goal' | 'competition';

interface Screen {
  kind: string;
  leaderboard_id: number | null;
  goal_id: number | null;
  competition_id: number | null;
}

interface Channel {
  id: number;
  name: string;
  display_count: number;
  screens: Screen[];
}

const ID_FIELD = {
  leaderboard: 'leaderboard_id',
  goal: 'goal_id',
  competition: 'competition_id',
} as const;

/** Whether a channel already plays this thing. */
export function playsIt(channel: Channel, kind: ShowKind, id: number): boolean {
  return channel.screens.some((s) => s.kind === kind && s[ID_FIELD[kind]] === id);
}

/** The slide this page's thing becomes, as the channel editor would make it. */
function slideFor(kind: ShowKind, id: number) {
  return { kind, [ID_FIELD[kind]]: id };
}

/**
 * "Show on a TV", finished (review §5).
 *
 * It used to drop you on the channel list to start over. Now it lists the
 * channels, says which already play this, adds it to one in a click, and
 * offers to show it on a TV first.
 */
export default function ShowOnTv({ kind, id, name }: { kind: ShowKind; id: number; name: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="rounded-md border border-edge px-3 py-1.5 text-sm text-content hover:bg-surface-hover"
      >
        Show on a TV
      </button>
      {open && <ShowOnTvDialog kind={kind} id={id} name={name} onClose={() => setOpen(false)} />}
    </>
  );
}

export function ShowOnTvDialog({
  kind,
  id,
  name,
  onClose,
}: {
  kind: ShowKind;
  id: number;
  name: string;
  onClose: () => void;
}) {
  const [channels, setChannels] = useState<Channel[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  useEffect(() => {
    api<Channel[]>('/api/channels')
      .then(setChannels)
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load the channels.'));
  }, []);

  async function add(channel: Channel) {
    setBusy(channel.id);
    setError(null);
    try {
      const after = await api<Channel>(`/api/channels/${channel.id}/screens`, {
        method: 'POST',
        body: JSON.stringify(slideFor(kind, id)),
      });
      setChannels((all) => all?.map((c) => (c.id === after.id ? after : c)) ?? null);
      toast(`${name} added to ${channel.name}`);
    } catch (e) {
      // The server's own reason: a Phoenix board on a Dallas channel, say.
      setError(e instanceof Error ? e.message : 'Could not add it.');
    } finally {
      setBusy(null);
    }
  }

  const first = channels?.[0];

  return (
    <Modal title="Show on a TV" description={`Add ${name} to a channel, and every TV playing it shows it.`} onClose={onClose}>
      {error && (
        <p role="alert" className="mb-3 rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}
      {channels === null && !error && <p className="text-sm text-content-muted">Loading…</p>}
      {channels?.length === 0 && (
        <p className="text-sm text-content-muted">
          There are no channels yet.{' '}
          <Link to="/channels" className="text-brand hover:underline">
            Make one in TVs &amp; Channels
          </Link>
        </p>
      )}
      {channels && channels.length > 0 && (
        <ul className="divide-y divide-edge rounded-md border border-edge">
          {channels.map((channel) => {
            const on = playsIt(channel, kind, id);
            return (
              <li key={channel.id} className="flex items-center justify-between gap-3 px-4 py-3 text-sm">
                <span>
                  <span className="text-content">{channel.name}</span>
                  <span className="block text-xs text-content-muted">
                    {channel.display_count === 0
                      ? 'No TVs playing it yet'
                      : `${channel.display_count} TV${channel.display_count === 1 ? '' : 's'}`}
                  </span>
                </span>
                {on ? (
                  <span className="rounded-full bg-success/15 px-2.5 py-1 text-xs text-success">Already on</span>
                ) : (
                  <button
                    type="button"
                    disabled={busy !== null}
                    onClick={() => void add(channel)}
                    className="rounded-md bg-brand px-3 py-1.5 text-white disabled:opacity-50"
                  >
                    {busy === channel.id ? 'Adding…' : 'Add'}
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {/* See it on the wall before it joins a rotation. Drawn as the first
          channel would draw it — the look is the channel's. */}
      {first && (
        <div className="mt-5">
          <p className="mb-2 text-sm text-content-muted">Or see it on one TV for a moment first:</p>
          <PreviewOnTv
            send={(displayId) =>
              api(`/api/channels/${first.id}/screens/preview/tv/${displayId}`, {
                method: 'POST',
                body: JSON.stringify(slideFor(kind, id)),
              })
            }
          />
        </div>
      )}
      <p className="mt-4 text-sm">
        <Link to="/channels" className="text-content-muted hover:text-content hover:underline">
          Open TVs &amp; Channels
        </Link>
      </p>
    </Modal>
  );
}
