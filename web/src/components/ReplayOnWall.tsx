import { useEffect, useState } from 'react';

import { api } from '../api';
import Modal from './Modal';
import Loading from './Loading';

/**
 * Put a win back on a television.
 *
 * **For the manager who missed it.** The best moment of the week happens while
 * the room is in a meeting, and the only record of it is a line in a feed
 * somebody has to be told to go and read. This is the one that puts it back
 * where people were going to see it.
 *
 * A picker rather than a single button, because a replay is aimed at a *room*:
 * playing a Phoenix win on Dallas's wall is the same mistake the audience rules
 * spend their time preventing, and nothing here knows which room somebody
 * means.
 */
interface Channel {
  id: number;
  name: string;
  audience_label: string;
  display_count: number;
}

export default function ReplayOnWall({
  notificationId,
  onClose,
}: {
  notificationId: number;
  onClose: () => void;
}) {
  const [channels, setChannels] = useState<Channel[] | null>(null);
  const [sent, setSent] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Channel[]>('/api/channels')
      .then(setChannels)
      .catch((e) =>
        setError(e instanceof Error ? e.message : 'Could not load channels.'),
      );
  }, []);

  async function play(channel: Channel) {
    setBusy(true);
    setError(null);
    try {
      await api(`/api/channels/${channel.id}/replay`, {
        method: 'POST',
        body: JSON.stringify({ notification_id: notificationId }),
      });
      setSent(channel.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not reach the screens.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Play on a wall"
      description="It takes over the TVs on that channel in a few seconds."
      onClose={onClose}
    >
      {error && (
        <p
          role="alert"
          className="mb-4 rounded-md border border-danger px-3 py-2 text-sm text-danger"
        >
          {error}
        </p>
      )}

      {channels === null && !error && (
        <Loading />
      )}

      {channels?.length === 0 && (
        <p className="text-sm text-content-muted">
          There are no channels yet, so there is nothing to play it on.
        </p>
      )}

      <ul className="space-y-2">
        {channels?.map((channel) => (
          <li
            key={channel.id}
            className="flex items-center gap-3 rounded-md border border-edge px-3 py-2"
          >
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm text-content">{channel.name}</p>
              <p className="text-xs text-content-subtle">
                {channel.audience_label}
                {/* **Said, because a channel with no television is a button
                    that appears to do nothing.** The request is still accepted
                    — a screen might be plugged in a minute later — so the
                    honest place to mention it is before the click. */}
                {channel.display_count === 0
                  ? ' · no TVs attached'
                  : ` · ${channel.display_count} TV${
                      channel.display_count === 1 ? '' : 's'
                    }`}
              </p>
            </div>
            <button
              type="button"
              disabled={busy}
              onClick={() => void play(channel)}
              className="shrink-0 rounded-md border border-edge px-3 py-1.5 text-sm text-content transition-colors hover:bg-surface-hover disabled:opacity-50"
            >
              {sent === channel.id ? 'Sent' : 'Play'}
            </button>
          </li>
        ))}
      </ul>
    </Modal>
  );
}
