import { useCallback, useEffect, useState } from 'react';

import { api, ApiError } from '../api';
import { agoInWords } from '../time';
import AnnouncementEditor, { type Announcement } from './AnnouncementEditor';
import { ask } from '../confirm';
import Modal from './Modal';
import { toast } from '../toast';

interface ChannelChoice {
  id: number;
  name: string;
}

/**
 * The announcements dashboard (Phase 25): every announcement made for the
 * TVs, ready to change or send again. "Lunch is here" is made once and sent
 * every lunchtime.
 */
export default function AnnouncementsDashboard() {
  const [items, setItems] = useState<Announcement[] | null>(null);
  const [editing, setEditing] = useState<Announcement | 'new' | null>(null);
  const [sending, setSending] = useState<Announcement | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setItems(await api<Announcement[]>('/api/tv-announcements'));
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : 'Couldn’t load the announcements.');
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function remove(item: Announcement) {
    if (!(await ask(`Delete "${item.title}"? It can't be sent again.`))) return;
    try {
      await api(`/api/tv-announcements/${item.id}`, { method: 'DELETE' });
      toast('Announcement deleted');
      await load();
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : 'Couldn’t delete that.');
    }
  }

  return (
    <section aria-label="Announcements">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-content-muted">Made once, sent whenever you like. Each one takes over the TVs it's sent to.</p>
        <button
          type="button"
          onClick={() => setEditing('new')}
          className="rounded-md bg-brand px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover"
        >
          New announcement
        </button>
      </div>

      {problem && <p className="mb-3 text-sm text-danger">{problem}</p>}

      {items === null ? (
        <p className="text-sm text-content-muted">Loading…</p>
      ) : items.length === 0 ? (
        <div className="rounded-lg border border-dashed border-edge p-8 text-center text-sm text-content-muted">
          No announcements yet. Make one to put on the TVs — “Lunch is here”, “All-hands at 3”.
        </div>
      ) : (
        <ul className="divide-y divide-edge rounded-lg border border-edge bg-surface">
          {items.map((item) => (
            <li key={item.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
              <Swatch item={item} />
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium text-content">{item.title}</p>
                <p className="truncate text-xs text-content-subtle">
                  {item.times_sent === 0
                    ? 'Not sent yet'
                    : `Sent ${item.times_sent === 1 ? 'once' : `${item.times_sent} times`} · last ${agoInWords(new Date(item.last_sent_at!))}`}
                  {' · '}
                  {item.hold_seconds}s on screen
                </p>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setSending(item)}
                  className="rounded-md bg-brand px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-brand-hover"
                >
                  Send
                </button>
                <button
                  type="button"
                  onClick={() => setEditing(item)}
                  className="rounded-md border border-edge px-3 py-1.5 text-sm text-content transition-colors hover:bg-surface-hover"
                >
                  Edit
                </button>
                <button
                  type="button"
                  onClick={() => void remove(item)}
                  className="rounded-md px-2 py-1.5 text-sm text-content-muted transition-colors hover:text-danger"
                >
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {editing && (
        <AnnouncementEditor
          editing={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={(saved, sendNow) => {
            setEditing(null);
            toast(editing === 'new' ? 'Announcement saved' : 'Changes saved');
            void load();
            if (sendNow) setSending(saved);
          }}
        />
      )}
      {sending && (
        <SendDialog
          item={sending}
          onClose={() => setSending(null)}
          onSent={() => {
            setSending(null);
            void load();
          }}
        />
      )}
    </section>
  );
}

/** A glimpse of its look: its colour, or a mark for a picture or video. */
function Swatch({ item }: { item: Announcement }) {
  const bg = item.background;
  const style =
    bg?.kind === 'solid' && bg.color
      ? { background: bg.color }
      : bg?.kind === 'gradient' && bg.color
        ? { background: `linear-gradient(135deg, ${bg.color}, ${bg.color_to ?? bg.color})` }
        : undefined;
  const mark = bg?.kind === 'youtube' || bg?.kind === 'video' ? '▶' : bg?.kind === 'image' ? '▣' : '';
  return (
    <span
      aria-hidden="true"
      style={style}
      className="flex h-10 w-16 shrink-0 items-center justify-center rounded border border-edge bg-surface-raised text-content-subtle"
    >
      {mark}
    </span>
  );
}

/** Where it goes: every TV, or the channels picked. */
function SendDialog({ item, onClose, onSent }: { item: Announcement; onClose: () => void; onSent: () => void }) {
  const [channels, setChannels] = useState<ChannelChoice[] | null>(null);
  const [everywhere, setEverywhere] = useState(true);
  const [picked, setPicked] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    api<ChannelChoice[]>('/api/tv-announcements/channels')
      .then(setChannels)
      .catch(() => setChannels([]));
  }, []);

  async function send() {
    setBusy(true);
    setProblem(null);
    try {
      await api(`/api/tv-announcements/${item.id}/send`, {
        method: 'POST',
        body: JSON.stringify({ channel_ids: everywhere ? null : picked }),
      });
      toast(everywhere ? 'Sent to every TV' : `Sent to ${picked.length === 1 ? 'one channel' : `${picked.length} channels`}`);
      onSent();
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : 'Couldn’t send that.');
      setBusy(false);
    }
  }

  return (
    <Modal title={`Send “${item.title}”`} description="It takes over the screens now, for its time, then they carry on." onClose={onClose}>
      <fieldset className="space-y-2 text-sm">
        <legend className="sr-only">Where</legend>
        <label className="flex items-center gap-2">
          <input type="radio" name="where" checked={everywhere} onChange={() => setEverywhere(true)} />
          <span className="text-content">Every TV</span>
        </label>
        <label className="flex items-center gap-2">
          <input type="radio" name="where" checked={!everywhere} onChange={() => setEverywhere(false)} />
          <span className="text-content">Chosen channels</span>
        </label>
        {!everywhere && (
          <div className="ml-6 space-y-1">
            {channels === null ? (
              <p className="text-content-muted">Loading…</p>
            ) : channels.length === 0 ? (
              <p className="text-content-muted">No channels yet.</p>
            ) : (
              channels.map((channel) => (
                <label key={channel.id} className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={picked.includes(channel.id)}
                    onChange={(e) =>
                      setPicked((was) => (e.target.checked ? [...was, channel.id] : was.filter((id) => id !== channel.id)))
                    }
                  />
                  <span className="text-content">{channel.name}</span>
                </label>
              ))
            )}
          </div>
        )}
      </fieldset>
      {problem && <p className="mt-3 text-sm text-danger">{problem}</p>}
      <div className="mt-5 flex gap-2">
        <button
          type="button"
          onClick={() => void send()}
          disabled={busy || (!everywhere && picked.length === 0)}
          className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
        >
          {busy ? 'Sending…' : 'Send now'}
        </button>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md border border-edge px-4 py-2 text-sm text-content transition-colors hover:bg-surface-hover"
        >
          Cancel
        </button>
      </div>
    </Modal>
  );
}
