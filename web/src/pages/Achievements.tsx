import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { api } from '../api';
import { toast } from '../toast';
import { Can, useAuth } from '../auth';
import { useRefreshNotifications } from '../notifications';
import Avatar from '../components/Avatar';
import FeedThread, { type FeedComment, type Reaction } from '../components/FeedThread';
import EmptyState from '../components/EmptyState';
import Field from '../components/Field';
import MediaField from '../components/MediaField';
import Modal from '../components/Modal';
import PageHeader from '../components/PageHeader';
import ReplayOnWall from '../components/ReplayOnWall';
import { TrophyIcon } from '../components/icons';
import { ask } from '../confirm';
import { agoInWords } from '../time';
import AnnouncementsDashboard from '../components/AnnouncementsDashboard';
import { Tab } from '../components/Tabs';
import Loading from '../components/Loading';
import PeoplePicker from '../components/PeoplePicker';
import type { PickPerson } from '../components/peoplePick';
import Select from '../components/Select';
import MissingHint from '../components/MissingHint';
import PersonLink from '../components/PersonLink';

interface Achievement {
  id: number;
  event_key: string;
  about_name: string | null;
  about_photo_digest: string | null;
  about_user_id: number | null;
  title: string;
  body: string | null;
  link_url: string | null;
  created_at: string;
  from_name: string | null;
  /** From the whole floor (6.15). */
  reactions?: Reaction[];
  comments?: FeedComment[];
}

type Person = PickPerson;

interface Team {
  id: number;
  name: string;
}

function when(iso: string): string {
  return agoInWords(new Date(iso));
}

/**
 * What the organization is celebrating.
 *
 * Both kinds in one list: goals hit, which the system noticed, and shout-outs,
 * which somebody wrote. Splitting them by origin would leak an implementation
 * detail into the UI, and the written ones are usually the better story.
 *
 * **Org-wide, not scoped to the viewer** — unlike every other list here. These
 * are the same rows that go on a wall screen anybody walking past can read, so
 * "public" has to mean the same thing at a desk and in a corridor.
 */
export default function Achievements() {
  const { can } = useAuth();
  // **Two tabs** (Phase 25): the feed of wins and shout-outs, for everyone,
  // and the announcements dashboard, for whoever can send announcements.
  const [params, setParams] = useSearchParams();
  const tab = params.get('tab') === 'announcements' && can('announcements.send') ? 'announcements' : 'feed';
  const showTab = (next: 'feed' | 'announcements') =>
    setParams(next === 'feed' ? {} : { tab: next }, { replace: true });
  const [feed, setFeed] = useState<Achievement[] | null>(null);
  // Narrowing what is shown, in the browser (review §7).
  const [who, setWho] = useState('');
  const [kind, setKind] = useState('');
  const [sending, setSending] = useState(false);
  //: Which win a channel is being chosen for, by notification id.
  const [replaying, setReplaying] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const refreshBell = useRefreshNotifications();

  const load = useCallback(async () => {
    try {
      setFeed(await api<Achievement[]>('/api/achievements'));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load achievements.');
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function remove(achievement: Achievement) {
    if (
      !await ask(
        `Remove "${achievement.title}"? It disappears from every screen.`,
      )
    )
      return;
    try {
      await api(`/api/recognition/${achievement.id}`, { method: 'DELETE' });
      toast('Recognition removed');
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not remove that.');
    }
  }

  const typed = who.trim().toLowerCase();
  const shown = (feed ?? []).filter((a) => {
    const key = a.event_key;
    const group =
      key === 'recognition'
        ? 'recognition'
        : key.startsWith('goal.')
          ? 'goal'
          : key.startsWith('competition.')
            ? 'competition'
            : key.startsWith('achievement:')
              ? 'achievement'
              : key.startsWith('person.')
                ? 'occasion'
                : 'other';
    return (
      (!kind || group === kind) &&
      (!typed || `${a.about_name ?? ''} ${a.from_name ?? ''}`.toLowerCase().includes(typed))
    );
  });

  return (
    <>
      <PageHeader
        title="Announcements"
        description="Goals hit, people recognised, and announcements for the TVs."
        actions={
          tab === 'feed' && <Can do="recognition.send">
            <button
              onClick={() => setSending(true)}
              className="rounded-md bg-brand px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover"
            >
              Recognise someone
            </button>
          </Can>
        }
      />

      {error && (
        <p
          role="alert"
          className="mb-4 rounded-md border border-danger px-3 py-2 text-sm text-danger"
        >
          {error}
        </p>
      )}

      {can('announcements.send') && (
        <div className="mb-4 flex gap-2">
          <Tab active={tab === 'feed'} onClick={() => showTab('feed')}>
            Wins & shout-outs
          </Tab>
          <Tab active={tab === 'announcements'} onClick={() => showTab('announcements')}>
            Announcements
          </Tab>
        </div>
      )}

      {tab === 'announcements' ? (
        <AnnouncementsDashboard />
      ) : (
        <>
          {feed === null ? (
            <Loading />
          ) : feed.length === 0 ? (
            <EmptyState
              title="Nothing yet"
              description="Goals that get hit turn up here on their own. Recognition is the other half — it is the part a person has to write."
            />
          ) : (
            <>
            <div className="mb-4 grid gap-3 sm:grid-cols-2">
              <Field label="Who" value={who} onChange={setWho} required={false} placeholder="A name" />
              <Select
                label="What"
                value={kind}
                onChange={setKind}
                options={[
                  { value: '', label: 'Everything' },
                  { value: 'recognition', label: 'Recognition' },
                  { value: 'goal', label: 'Goals hit' },
                  { value: 'competition', label: 'Competitions won' },
                  { value: 'achievement', label: 'Celebration rules' },
                  { value: 'occasion', label: 'Birthdays and anniversaries' },
                ]}
              />
            </div>
            {shown.length === 0 && (
              <p className="text-sm text-content-muted">Nothing matches those filters.</p>
            )}
            <ul className="space-y-3">
              {shown.map((achievement) => (
                <li
                  key={achievement.id}
                  className="flex items-start gap-4 rounded-lg border border-edge bg-surface p-4"
                >
                  {achievement.about_user_id !== null ? (
                    <Avatar
                      name={achievement.about_name ?? ''}
                      digest={achievement.about_photo_digest}
                    />
                  ) : (
                    // A team has no face. The trophy keeps the row aligned with
                    // the ones that do rather than leaving a ragged left edge.
                    <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-brand-subtle">
                      <TrophyIcon className="size-4 text-brand" />
                    </span>
                  )}

                  <div className="min-w-0 flex-1">
                    <p className="text-content">
                      <PersonLink id={achievement.about_user_id} className="font-medium">
                        {achievement.about_name}
                      </PersonLink>
                      {achievement.from_name ? ' — ' : ' '}
                      {achievement.title}
                    </p>
                    <p className="mt-0.5 text-xs text-content-subtle">
                      {achievement.from_name
                        ? `recognised by ${achievement.from_name} · ${when(achievement.created_at)}`
                        : `${achievement.body ? `${achievement.body} · ` : ''}${when(achievement.created_at)}`}
                      {achievement.link_url && (
                        <>
                          {' · '}
                          <Link
                            to={achievement.link_url}
                            className="text-brand hover:underline"
                          >
                            view
                          </Link>
                        </>
                      )}
                    </p>
                    <FeedThread
                      entryId={achievement.id}
                      reactions={achievement.reactions ?? []}
                      comments={achievement.comments ?? []}
                    />
                  </div>

                  {/* **For the manager who missed it.** The best moment of the
                      week happens while the room is in a meeting, and the only
                      record of it is this line in a feed. */}
                  {can('integrations.manage') && (
                    <button
                      onClick={() => setReplaying(achievement.id)}
                      className="shrink-0 rounded-md border border-edge px-2 py-1 text-xs text-content-muted transition-colors hover:border-brand hover:text-content"
                    >
                      Play on wall
                    </button>
                  )}

                  {/* Only shout-outs can be taken back. Nobody gets to un-hit a
                      target, so a detected achievement has no control here. */}
                  {achievement.from_name && can('recognition.send') && (
                    <button
                      onClick={() => void remove(achievement)}
                      className="shrink-0 rounded-md border border-edge px-2 py-1 text-xs text-content-muted transition-colors hover:border-danger hover:text-danger"
                    >
                      Remove shout-out
                    </button>
                  )}
                </li>
              ))}
            </ul>
            </>
          )}
        </>
      )}

      {replaying !== null && (
        <ReplayOnWall
          notificationId={replaying}
          onClose={() => setReplaying(null)}
        />
      )}

      {sending && (
        <RecogniseForm
          onClose={() => setSending(false)}
          onSent={async () => {
            toast('Recognition sent');
            refreshBell();
            setError(null);
            setSending(false);
            await load();
          }}
          onError={setError}
        />
      )}
    </>
  );
}

export function RecogniseForm({
  onClose,
  onSent,
  onError,
  userId,
}: {
  onClose: () => void;
  onSent: () => Promise<void>;
  onError: (message: string | null) => void;
  /** Somebody already chosen — from a "Recognise" beside their name (6.13). */
  userId?: number;
}) {
  const [people, setPeople] = useState<Person[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);
  // "user:12" or "team:3" — exactly one of the two is ever chosen.
  const [target, setTarget] = useState(userId ? `user:${userId}` : '');
  const [targetKind, setTargetKind] = useState<'user' | 'team'>('user');
  const { user: me } = useAuth();
  const [message, setMessage] = useState('');
  const [mediaUrl, setMediaUrl] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    // Already scoped by the API to people this person can see, so the list is
    // the same set the server would accept.
    Promise.all([api<Person[]>('/api/users'), api<Team[]>('/api/teams')])
      .then(([p, t]) => {
        setPeople(p);
        setTeams(t);
      })
      .catch(() => onError('Could not load the list of people.'));
  }, [onError]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    // A failure from last time is not true of this attempt (QA-4).
    onError(null);
    try {
      await api('/api/recognition', {
        method: 'POST',
        body: JSON.stringify({
          ...(target.startsWith('team:')
            ? { team_id: Number(target.slice(5)) }
            : { user_id: Number(target.slice(5)) }),
          message,
          // Omitted rather than sent empty, so the server falls back to their
          // own walk-up media instead of storing a blank override.
          media_url: mediaUrl.trim() || null,
        }),
      });
      await onSent();
    } catch (e) {
      onError(e instanceof Error ? e.message : 'Could not send that.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Recognise someone"
      // Where it will be seen, said before it is sent (8.3).
      description="It reaches them, everyone sees it on the Recognition feed, and it plays on the TVs of any channel that shows recognition."
      onClose={onClose}
    >
      <form onSubmit={submit} className="space-y-4">
        {/* A person or a team, one of the two — so a choice between them, then
            the right picker for each. Hundreds of people want typing (review
            #1); a handful of teams is fine as a list. */}
        <div className="flex gap-4 text-sm" role="radiogroup" aria-label="Recognise">
          {(['user', 'team'] as const).map((kind) => (
            <label key={kind} className="flex items-center gap-2 text-content">
              <input
                type="radio"
                name="recognise-kind"
                checked={targetKind === kind}
                onChange={() => {
                  setTargetKind(kind);
                  setTarget('');
                }}
              />
              {kind === 'user' ? 'A person' : 'A team'}
            </label>
          ))}
        </div>

        {targetKind === 'user' ? (
          <PeoplePicker
            label="Who"
            people={people}
            value={target.startsWith('user:') ? Number(target.slice(5)) : null}
            onChange={(id) => setTarget(id === null ? '' : `user:${id}`)}
            hint={
              // Allowed, and paid nothing on purpose — but it should not be a
              // surprise (QA-34).
              target === `user:${me?.id}`
                ? "You won't earn points for recognising yourself."
                : undefined
            }
          />
        ) : (
          <Select
            label="Which team"
            value={target.startsWith('team:') ? target : ''}
            onChange={setTarget}
            options={[
              { value: '', label: 'Choose a team…' },
              ...teams.map((team) => ({ value: `team:${team.id}`, label: team.name })),
            ]}
          />
        )}

        <Field
          label="What they did"
          value={message}
          onChange={setMessage}
          maxLength={200}
          hint="Be specific. 'Turned around the Henderson account after two months' is worth reading; 'great work' is not."
        />

        <MediaField
          label="Play something (optional)"
          value={mediaUrl}
          onChange={setMediaUrl}
          kinds={['audio', 'video', 'image']}
          link="Or paste a YouTube link or GIF"
          hint="For this one occasion. Leave empty and their own walk-up media plays."
        />

        <div className="flex items-center gap-3 pt-2">
          <button
            type="submit"
            disabled={busy || !target || !message.trim()}
            className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
          >
            {busy ? 'Sending…' : 'Send'}
          </button>
          <MissingHint checks={[[!target, 'Choose who it is for.'], [!message.trim(), 'Say what they did.']]} />
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
