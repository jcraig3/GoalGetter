import { useCallback, useEffect, useState, type DragEvent, type FormEvent } from 'react';
import { Link, useParams } from 'react-router-dom';

import { api } from '../api';
import { toast } from '../toast';
import { useOrgAppearance } from '../orgAppearance';
import AppearanceFields from '../components/AppearanceFields';
import MediaField from '../components/MediaField';
import ScreenBackground from '../components/ScreenBackground';
import TimeField from '../components/TimeField';
import EmptyState from '../components/EmptyState';
import Field from '../components/Field';
import Modal from '../components/Modal';
import PageHeader from '../components/PageHeader';
import Select from '../components/Select';
import { AudiencePicker, ChannelForm } from './Channels';
import { CogIcon } from '../components/icons';
import { reorderIds, type DropAt } from './channelOrder';
import { ask } from '../confirm';
import Loading from '../components/Loading';
import PeoplePicker from '../components/PeoplePicker';
import {
  clockWords,
  describeSchedule,
  hhmm,
  ScheduleFields,
  type SlideSchedule,
} from '../components/RotationSchedule';
import Breadcrumb from '../components/Breadcrumb';
import WallPreview from '../components/wall/WallPreview';
import type { Slide } from '../components/wall/types';
import type { Appearance, Background } from '../appearance';
import PreviewOnTv from '../components/PreviewOnTv';

interface Screen {
  id: number;
  position: number;
  /** Its board or goal is archived, so it is not playing (P3-2). */
  archived?: boolean;
  kind: string;
  dwell_seconds: number;
  leaderboard_id: number | null;
  goal_id: number | null;
  competition_id: number | null;
  /** For a spotlight. Null alongside a board means "whoever is leading". */
  user_id: number | null;
  /** For a comparison: the boards it puts side by side, in order. */
  leaderboard_ids: number[];
  /** Only what this one screen chose. The last word in the chain. */
  appearance: Record<string, unknown>;
  url: string | null;
  media_start_seconds?: number | null;
  fit?: 'cover' | 'contain' | null;
  title: string | null;
  body: string | null;
  scope_type: string | null;
  scope_office_id: number | null;
  scope_team_id: number | null;
  /** When it plays (6.10). Null days is every day; times are "HH:MM:SS". */
  days: number[] | null;
  play_from: string | null;
  play_until: string | null;
  weight: number;
  label: string;
  audience_label: string;
}

interface Office {
  id: number;
  name: string;
}

interface Team {
  id: number;
  name: string;
}

interface Channel {
  id: number;
  name: string;
  scope_type: string;
  scope_office_id: number | null;
  scope_team_id: number | null;
  audience_label: string;
  allowed_ips: string[];
  /** Only what this channel itself chose; absent keys inherit. */
  appearance: Record<string, unknown>;
  quiet_mode?: 'off' | 'clock' | 'dark';
  quiet_from?: string | null;
  quiet_until?: string | null;
  quiet_weekends?: boolean;
  screens: Screen[];
  display_count: number;
}

/** Something that may go on *this* channel.
 *
 *  The server decides, so the picker and the validation cannot disagree — and
 *  the quiet failure that avoids is a picker omitting something the server
 *  would have accepted. */
interface Eligible {
  id: number;
  name: string;
  belongs_to: string;
}

const KINDS = [
  { value: 'leaderboard', label: 'Leaderboard' },
  { value: 'goal', label: 'Goal' },
  { value: 'competition', label: 'Competition' },
  { value: 'spotlight', label: 'Player spotlight' },
  { value: 'comparison', label: 'Side by side' },
  { value: 'achievements', label: 'Recent wins' },
  { value: 'message', label: 'Message' },
  { value: 'image', label: 'Picture or GIF' },
  { value: 'video', label: 'Video' },
] as const;

/** What each kind puts on the TV, under its name on the kind cards. */
const KIND_HINT: Record<string, string> = {
  leaderboard: 'A board, ranked',
  goal: 'Progress toward a goal',
  competition: 'A contest and its standings',
  spotlight: 'One person, up close',
  comparison: 'Two to four boards together',
  achievements: 'The latest wins',
  message: 'Your words, huge, in the middle',
  image: 'Fills the whole screen',
  video: 'YouTube or uploaded, full screen',
};

/** Kinds that are the whole screen: no background, header or styling. */
const FULL_SCREEN = new Set(['image', 'video']);

const KIND_LABEL: Record<string, string> = Object.fromEntries(
  KINDS.map((k) => [k.value, k.label]),
);

/**
 * The running order for one wall.
 *
 * Drag to reorder, using the browser's own drag events rather than a library:
 * this is a single vertical list of a handful of rows, and the smallest
 * capable drag library is larger than the whole page.
 *
 * **A reorder sends the whole order, not a move.** The editor already knows the
 * final arrangement, so there is never a half-applied shuffle to reason about,
 * and two people dragging at once end with one of the two orders rather than
 * an interleaving of both.
 */
export default function ChannelEditor() {
  const { id } = useParams();
  const [channel, setChannel] = useState<Channel | null>(null);
  const [boards, setBoards] = useState<Eligible[]>([]);
  const [goals, setGoals] = useState<Eligible[]>([]);
  const [contests, setContests] = useState<Eligible[]>([]);
  const [people, setPeople] = useState<Eligible[]>([]);
  const [offices, setOffices] = useState<Office[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);
  const [adding, setAdding] = useState(false);
  const [settings, setSettings] = useState(false);
  const [editing, setEditing] = useState<Screen | null>(null);
  const [dragging, setDragging] = useState<number | null>(null);
  const [dropAt, setDropAt] = useState<DropAt | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Every slide as its TVs draw it, for the thumbnails and "Play rotation"
  // (8.5). Asked again whenever the slides change.
  const [rendered, setRendered] = useState<Record<number, Slide | null> | null>(null);
  const [playing, setPlaying] = useState(false);
  // Any change to a slide — added, moved, edited — changes this.
  const slideKey = JSON.stringify(channel?.screens ?? []);

  useEffect(() => {
    if (!channel) return;
    let stale = false;
    api<{ screen_id: number; slide: Slide | null }[]>(`/api/channels/${channel.id}/slides`)
      .then((all) => {
        if (!stale) setRendered(Object.fromEntries(all.map((r) => [r.screen_id, r.slide])));
      })
      .catch(() => !stale && setRendered({}));
    return () => {
      stale = true;
    };
    // The slides themselves — not every re-render of the channel.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channel?.id, slideKey]);

  async function restoreTarget(screen: Screen) {
    const path = screen.leaderboard_id
      ? `/api/leaderboards/${screen.leaderboard_id}/restore`
      : `/api/goals/${screen.goal_id}/restore`;
    try {
      await api(path, { method: 'POST' });
      toast(`${screen.label} restored — playing again`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not restore it.');
    }
  }

  const load = useCallback(async () => {
    try {
      const [all, eligible, o, tm] = await Promise.all([
        api<Channel[]>('/api/channels'),
        api<{
          leaderboards: Eligible[];
          goals: Eligible[];
          competitions: Eligible[];
          people: Eligible[];
        }>(`/api/channels/${id}/eligible`),
        api<Office[]>('/api/offices'),
        api<Team[]>('/api/teams'),
      ]);
      const found = all.find((c) => String(c.id) === id);
      if (!found) {
        setError('That channel no longer exists.');
        return;
      }
      setChannel(found);
      setBoards(eligible.leaderboards);
      setGoals(eligible.goals);
      setContests(eligible.competitions);
      setPeople(eligible.people);
      setOffices(o);
      setTeams(tm);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load this channel.');
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  async function reorder(ids: number[]) {
    // Applied locally first, so the row lands where it was dropped instead of
    // snapping back for the length of a round trip.
    setChannel((was) =>
      was
        ? {
            ...was,
            screens: ids
              .map((sid) => was.screens.find((s) => s.id === sid))
              .filter((s): s is Screen => Boolean(s)),
          }
        : was,
    );
    try {
      setChannel(
        await api<Channel>(`/api/channels/${id}/order`, {
          method: 'POST',
          body: JSON.stringify({ screen_ids: ids }),
        }),
      );
    } catch {
      setError('Could not save the new order.');
      await load();
    }
  }

  /** Which half of the row the cursor is in decides above or below.
   *
   *  Measured against the row's own box rather than tracked as an index, so it
   *  stays right when rows are different heights — a message screen is taller
   *  than a board. */
  function onDragOver(event: DragEvent, screen: Screen) {
    event.preventDefault();
    if (dragging === null || dragging === screen.id) {
      setDropAt(null);
      return;
    }
    const box = event.currentTarget.getBoundingClientRect();
    setDropAt({ id: screen.id, before: event.clientY < box.top + box.height / 2 });
  }

  /** Commit wherever the release happens.
   *
   *  Bound to the list, not to each row. Bound per row it only fired when the
   *  pointer was over another row at the moment of release — and dragging
   *  *downward* usually ends in the gap below one, or past the last row, where
   *  no row is under the cursor at all. That is why moving a screen down did
   *  nothing while moving one up worked: the drop event never reached us.
   */
  function onDrop(event: DragEvent) {
    event.preventDefault();
    const moving = dragging;
    const target = dropAt;
    setDragging(null);
    setDropAt(null);
    if (moving === null || target === null || !channel) return;

    void reorder(reorderIds(channel.screens.map((s) => s.id), moving, target));
  }

  /** Arrow keys on the handle, because native drag-and-drop has no keyboard
   *  equivalent at all — without this the running order is mouse-only. */
  function onHandleKey(event: React.KeyboardEvent, index: number) {
    if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return;
    if (!channel) return;
    event.preventDefault();

    const to = event.key === 'ArrowUp' ? index - 1 : index + 1;
    if (to < 0 || to >= channel.screens.length) return;

    const ids = channel.screens.map((s) => s.id);
    [ids[index], ids[to]] = [ids[to]!, ids[index]!];
    void reorder(ids);
  }

  async function remove(screen: Screen) {
    if (!await ask(`Remove "${screen.label}" from this channel?`)) return;
    try {
      setChannel(
        await api<Channel>(`/api/channels/${id}/screens/${screen.id}`, {
          method: 'DELETE',
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not remove that.');
    }
  }

  if (error && !channel) {
    return (
      <>
        <Back />
        <p role="alert" className="rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      </>
    );
  }

  if (!channel) return <Loading />;

  // A slide shown twice a cycle counts twice (6.10).
  const total = channel.screens.reduce((sum, s) => sum + s.dwell_seconds * (s.weight ?? 1), 0);

  return (
    <>
      <Back here={channel.name} />
      <PageHeader
        title={channel.name}
        description={
          `Showing data for ${channel.audience_label}. ` +
          (channel.display_count
            ? `Playing on ${channel.display_count} television${channel.display_count > 1 ? 's' : ''}.`
            : 'No televisions are playing this yet.') +
          nightWords(channel)
        }
        actions={
          <div className="flex items-center gap-2">
            {/* The cog, not a second page: the channel's name and audience are
                settings *of the thing being edited*, so they belong behind the
                same door as its screens. */}
            {/* Named, not a bare cog (8.5). */}
            <button
              type="button"
              onClick={() => setSettings(true)}
              className="inline-flex items-center gap-1.5 rounded-md border border-edge px-3 py-2 text-sm text-content hover:bg-surface-hover"
            >
              <CogIcon className="size-4" />
              Settings
            </button>
            {/* Beside "No televisions are playing this yet", the way to fix it
                (8.5), with this channel already chosen. */}
            {channel.display_count === 0 && (
              <Link
                to={`/channels?connect=1&channel=${channel.id}`}
                className="rounded-md border border-edge px-3 py-2 text-sm text-content hover:bg-surface-hover"
              >
                Connect a TV
              </Link>
            )}
            {channel.screens.length > 0 && (
              <button
                type="button"
                onClick={() => setPlaying(true)}
                className="rounded-md border border-edge px-3 py-2 text-sm text-content hover:bg-surface-hover"
              >
                ▶ Play rotation
              </button>
            )}
            <button
              onClick={() => setAdding(true)}
              className="rounded-md bg-brand px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover"
            >
              Add slide
            </button>
          </div>
        }
      />

      {error && (
        <p role="alert" className="mb-4 rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
      )}

      {channel.screens.length === 0 ? (
        <EmptyState
          title="Nothing on this channel"
          description="Add a leaderboard, a goal, a competition, or a message. Slides play in the order you arrange them."
        />
      ) : (
        <>
          <ol
            className="space-y-2"
            // The list owns the drop, so releasing in a gap between rows — or
            // below the last one — still lands. `preventDefault` here is what
            // makes the list a valid drop target at all; without it the
            // browser refuses the drop and nothing happens.
            onDragOver={(e) => e.preventDefault()}
            onDrop={onDrop}
          >
            {channel.screens.map((screen, index) => (
              <li
                key={screen.id}
                draggable
                onDragStart={() => setDragging(screen.id)}
                onDragEnd={() => {
                  setDragging(null);
                  setDropAt(null);
                }}
                onDragOver={(e) => onDragOver(e, screen)}
                className={`relative flex items-center gap-4 rounded-lg border border-edge bg-surface px-4 py-3 ${
                  dragging === screen.id ? 'opacity-40' : ''
                }`}
              >
                {/* The insertion line, in the gap between rows.
                    `pointer-events-none` matters: a line that swallowed the
                    dragover event would make the row beneath it stop
                    responding, and the indicator would stick. */}
                {dropAt?.id === screen.id && (
                  <span
                    aria-hidden="true"
                    className={`pointer-events-none absolute inset-x-0 h-0.5 rounded-full bg-brand ${
                      dropAt.before ? '-top-1.5' : '-bottom-1.5'
                    }`}
                  />
                )}

                <button
                  type="button"
                  aria-label={`Move ${screen.label}. Use the arrow keys, or drag.`}
                  onKeyDown={(e) => onHandleKey(e, index)}
                  className="shrink-0 cursor-grab rounded text-content-subtle hover:text-content focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand"
                >
                  <span aria-hidden="true">⠿</span>
                </button>
                {/* **What it looks like, not only what it is called** (8.5):
                    the real slide, small, from the same renderer as the TVs. */}
                {/* A picture, not content (P3-8): hidden from screen readers,
                    which read every name and score in it, and drawn without
                    the background photo, so slides that share one still
                    look different at this size. */}
                <div
                  aria-hidden="true"
                  inert
                  className="hidden w-32 shrink-0 overflow-hidden rounded border border-edge bg-bg sm:block [&_[data-wall-background]]:hidden"
                >
                  {rendered?.[screen.id] ? (
                    <WallPreview slide={rendered[screen.id]} channelName="" />
                  ) : (
                    <div className="flex aspect-video items-center justify-center bg-bg text-[0.6rem] text-content-subtle">
                      {rendered ? (screen.archived ? 'Archived' : 'Nothing to show yet') : ''}
                    </div>
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-content">{screen.label}</p>
                  {/* Not "Nothing to show yet", which reads as missing data:
                      it is archived, and one click brings it back (P3-2). */}
                  {screen.archived && (
                    <p className="text-xs text-warning">
                      Archived — not playing ·{' '}
                      <button
                        type="button"
                        onClick={() => void restoreTarget(screen)}
                        className="underline hover:text-content"
                      >
                        Restore
                      </button>
                    </p>
                  )}
                  <p className="text-xs text-content-subtle">
                    {KIND_LABEL[screen.kind] ?? screen.kind} · {screen.dwell_seconds}s
                    {/* Only when it differs from the channel — otherwise every
                        row would repeat the same word and it would stop being
                        the thing that catches the eye. */}
                    {screen.scope_type !== null && (
                      <span className="text-brand"> · {screen.audience_label}</span>
                    )}
                    {describeSchedule(screen) && (
                      <span className="text-brand"> · {describeSchedule(screen)}</span>
                    )}
                  </p>
                </div>
                <button
                  onClick={() => setEditing(screen)}
                  className="shrink-0 rounded-md border border-edge px-2 py-1 text-xs text-content-muted transition-colors hover:bg-surface-hover hover:text-content"
                >
                  Edit
                </button>
                <button
                  onClick={() => void remove(screen)}
                  className="shrink-0 rounded-md border border-edge px-2 py-1 text-xs text-content-muted transition-colors hover:border-danger hover:text-danger"
                >
                  Remove
                </button>
              </li>
            ))}
          </ol>

          {/* The number an admin actually wants: how long until a board they
              are looking for comes round again. */}
          <p className="mt-4 text-xs text-content-muted">
            One full rotation takes {Math.floor(total / 60)}m {total % 60}s.
          </p>
        </>
      )}

      {playing && rendered && (
        <PlayRotation
          slides={channel.screens
            .map((s) => ({ slide: rendered[s.id], dwell: s.dwell_seconds, label: s.label }))
            .filter((s): s is { slide: Slide; dwell: number; label: string } => Boolean(s.slide))}
          onClose={() => setPlaying(false)}
        />
      )}

      {settings && (
        <ChannelForm
          channel={channel}
          offices={offices}
          teams={teams}
          onClose={() => setSettings(false)}
          onSaved={async () => {
            toast('Channel saved');
            setError(null);
            setSettings(false);
            await load();
          }}
          onError={setError}
        />
      )}

      {(adding || editing) && (
        <ScreenForm
          channelId={channel.id}
          channelName={channel.name}
          screen={editing}
          boards={boards}
          goals={goals}
          contests={contests}
          people={people}
          offices={offices}
          teams={teams}
          onClose={() => {
            setAdding(false);
            setEditing(null);
          }}
          onSaved={(next) => {
            toast(editing ? 'Slide saved' : 'Slide added');
            setError(null);
            setAdding(false);
            setEditing(null);
            setChannel(next);
          }}
          onError={setError}
        />
      )}
    </>
  );
}

/** " Night mode: a clock from 7 pm to 7 am, and all weekend." — or nothing. */
function nightWords(channel: Channel): string {
  if (!channel.quiet_mode || channel.quiet_mode === 'off') return '';
  const what = channel.quiet_mode === 'dark' ? 'dark' : 'a clock';
  const from = hhmm(channel.quiet_from);
  const until = hhmm(channel.quiet_until);
  const hours = from && until ? ` from ${clockWords(from)} to ${clockWords(until)}` : '';
  const weekends = channel.quiet_weekends ? (hours ? ', and all weekend' : ' all weekend') : '';
  return ` Night mode: ${what}${hours}${weekends}.`;
}

function Back({ here }: { here?: string }) {
  return <Breadcrumb parent={{ to: '/channels', label: 'TVs & Channels' }} here={here} />;
}

function ScreenForm({
  channelId,
  channelName,
  screen,
  boards,
  goals,
  contests,
  people,
  offices,
  teams,
  onClose,
  onSaved,
  onError,
}: {
  channelId: number;
  channelName: string;
  screen: Screen | null;
  boards: Eligible[];
  goals: Eligible[];
  contests: Eligible[];
  people: Eligible[];
  offices: Office[];
  teams: Team[];
  onClose: () => void;
  onSaved: (channel: Channel) => void;
  onError: (message: string) => void;
}) {
  const [kind, setKind] = useState(screen?.kind ?? 'leaderboard');
  const [boardId, setBoardId] = useState(String(screen?.leaderboard_id ?? ''));
  const [goalId, setGoalId] = useState(String(screen?.goal_id ?? ''));
  const [contestId, setContestId] = useState(String(screen?.competition_id ?? ''));
  const [personId, setPersonId] = useState(String(screen?.user_id ?? ''));
  // Order matters — it is the order the panels are drawn in — so this is a
  // list that grows as boards are ticked, not a set derived from the options.
  const [panelIds, setPanelIds] = useState<number[]>(
    screen?.leaderboard_ids ?? [],
  );
  const [appearance, setAppearance] = useState<Record<string, unknown>>(
    screen?.appearance ?? {},
  );
  const inherited = useOrgAppearance();
  const [url, setUrl] = useState(screen?.url ?? '');
  const [title, setTitle] = useState(screen?.title ?? '');
  const [body, setBody] = useState(screen?.body ?? '');
  const [dwell, setDwell] = useState(String(screen?.dwell_seconds ?? 20));
  // A video screen's start and how long it plays (Phase 26). "Play for" is
  // the screen's time on the wall.
  const [startAt, setStartAt] = useState<number | null>(screen?.media_start_seconds ?? null);
  const [playFor, setPlayFor] = useState<number | null>(
    screen?.kind === 'video' ? screen.dwell_seconds : 30,
  );
  const [fit, setFit] = useState<'cover' | 'contain'>(screen?.fit === 'contain' ? 'contain' : 'cover');
  // '' means inherit the channel's audience, which is almost always right.
  const [scope, setScope] = useState(screen?.scope_type ?? '');
  const [officeId, setOfficeId] = useState(String(screen?.scope_office_id ?? ''));
  const [teamId, setTeamId] = useState(String(screen?.scope_team_id ?? ''));
  const [schedule, setSchedule] = useState<SlideSchedule>({
    days: screen?.days ?? null,
    from: hhmm(screen?.play_from),
    until: hhmm(screen?.play_until),
    weight: screen?.weight ?? 1,
  });
  const [busy, setBusy] = useState(false);

  // Already narrowed by the server to what this channel may show, using the
  // same rule that will validate the save.

  // One shape for saving and for previewing, so the preview is of exactly
  // what Save would send.
  const draft = JSON.stringify({
    kind,
    dwell_seconds: kind === 'video' ? playFor || 30 : Number(dwell) || 20,
    media_start_seconds: kind === 'video' ? startAt : null,
    fit: kind === 'image' ? fit : null,
    leaderboard_id:
      kind === 'leaderboard'
        ? Number(boardId)
        : kind === 'spotlight' && boardId
          ? Number(boardId)
          : null,
    user_id: kind === 'spotlight' && personId ? Number(personId) : null,
    leaderboard_ids: kind === 'comparison' ? panelIds : [],
    appearance,
    goal_id: kind === 'goal' ? Number(goalId) : null,
    competition_id: kind === 'competition' ? Number(contestId) : null,
    url: kind === 'image' || kind === 'video' ? url.trim() : null,
    title: title.trim() || null,
    body: kind === 'message' ? body.trim() || null : null,
    scope_type: scope || null,
    scope_office_id: scope === 'office' ? Number(officeId) : null,
    scope_team_id: scope === 'team' ? Number(teamId) : null,
    days: schedule.days,
    play_from: schedule.from || null,
    play_until: schedule.until || null,
    weight: schedule.weight,
  });

  // **The slide as this channel's walls would draw it, real numbers and all**
  // (5j), re-asked a moment after the form stops changing. A refusal is shown
  // as what is missing rather than as an error: half a form is the normal
  // state of a form being filled in.
  const [shown, setShown] = useState<Slide | null>(null);
  const [previewNote, setPreviewNote] = useState<string | null>(null);
  const missing =
    kind === 'leaderboard' && !boardId
      ? 'Choose a board to see it here.'
      : kind === 'goal' && !goalId
        ? 'Choose a goal to see it here.'
        : kind === 'competition' && !contestId
          ? 'Choose a competition to see it here.'
          : kind === 'spotlight' && !boardId && !personId
            ? 'Choose somebody, or a board to take the leader of.'
            : kind === 'comparison' && panelIds.length < 2
              ? 'Tick two or more boards to see them side by side.'
              : (kind === 'image' || kind === 'video') && !url.trim()
                ? kind === 'image'
                  ? 'Choose a picture to see it here.'
                  : 'Choose a video to see it here.'
                : kind === 'message' && !title.trim()
                  ? 'Write the message to see it here.'
                  : null;
  useEffect(() => {
    if (missing) {
      setShown(null);
      setPreviewNote(missing);
      return;
    }
    let stale = false;
    const timer = window.setTimeout(() => {
      api<Slide>(`/api/channels/${channelId}/screens/preview`, { method: 'POST', body: draft })
        .then((slide) => {
          if (stale) return;
          setShown(slide);
          setPreviewNote(null);
        })
        .catch((e) => {
          if (stale) return;
          setShown(null);
          setPreviewNote(e instanceof Error ? e.message : 'Nothing to show yet.');
        });
    }, 400);
    return () => {
      stale = true;
      window.clearTimeout(timer);
    };
  }, [channelId, draft, missing]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      const path = screen
        ? `/api/channels/${channelId}/screens/${screen.id}`
        : `/api/channels/${channelId}/screens`;
      onSaved(
        await api<Channel>(path, {
          method: screen ? 'PATCH' : 'POST',
          body: draft,
        }),
      );
    } catch (e) {
      onError(e instanceof Error ? e.message : 'Could not save that slide.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title={screen ? 'Edit slide' : 'Add slide'}
      description="One slide in this channel's rotation."
      onClose={onClose}
      side={
        <div>
          <p className="mb-2 text-caption uppercase tracking-wide text-content-subtle">
            On this channel&rsquo;s walls
          </p>
          {shown ? (
            <>
              <WallPreview
                slide={shown}
                appearance={shown.appearance as Appearance}
                channelName={channelName}
                turnable
                sound
              />
              <p className="mt-2 text-xs text-content-subtle">
                Real numbers, as a TV on this channel would draw them now.
                Changes show here before they are saved.
              </p>
            </>
          ) : (
            <div className="flex aspect-video items-center justify-center rounded-lg border border-dashed border-edge p-6 text-center text-sm text-content-muted">
              {previewNote ?? 'Loading…'}
            </div>
          )}
        </div>
      }
    >
      <form onSubmit={submit} className="space-y-4">
        <fieldset>
          <legend className="mb-2 text-sm text-content-muted">What’s on this screen</legend>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            {KINDS.map((k) => (
              <label
                key={k.value}
                className={`flex cursor-pointer flex-col rounded-md border p-2.5 text-sm transition-colors ${
                  kind === k.value ? 'border-brand bg-brand-subtle' : 'border-edge hover:bg-surface-hover'
                }`}
              >
                <input
                  type="radio"
                  name="screen-kind"
                  value={k.value}
                  checked={kind === k.value}
                  onChange={() => setKind(k.value)}
                  className="sr-only"
                />
                <span className="font-medium text-content">{k.label}</span>
                <span className="text-xs text-content-subtle">{KIND_HINT[k.value]}</span>
              </label>
            ))}
          </div>
        </fieldset>

        {kind === 'leaderboard' && (
          <Select label="Board" value={boardId} onChange={setBoardId}>
            <option value="">Choose a board…</option>
            {boards.map((board) => (
              <option key={board.id} value={board.id}>
                {board.name} · {board.belongs_to}
              </option>
            ))}
          </Select>
        )}

        {kind === 'competition' && (
          <Select label="Competition" value={contestId} onChange={setContestId}>
            <option value="">Choose a competition…</option>
            {contests.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} · {c.belongs_to}
              </option>
            ))}
          </Select>
        )}

        {kind === 'goal' && (
          <Select label="Goal" value={goalId} onChange={setGoalId}>
            <option value="">Choose a goal…</option>
            {goals.map((goal) => (
              <option key={goal.id} value={goal.id}>
                {goal.name}
              </option>
            ))}
          </Select>
        )}

        {kind === 'spotlight' && (
          <>
            {/* Nobody chosen is a real choice here, not a prompt: a spotlight
                with no person follows whoever is leading, which is the form
                that keeps itself up to date. */}
            <PeoplePicker
              label="Who"
              people={people.map((p) => ({
                id: p.id,
                full_name: p.name,
                email: '',
                team_name: p.belongs_to,
              }))}
              value={personId ? Number(personId) : null}
              onChange={(id) => setPersonId(id === null ? '' : String(id))}
              placeholder="Whoever is leading — or type a name"
              hint={personId ? undefined : 'Left empty, it shows whoever is leading the board.'}
            />
            <Select label="Board" value={boardId} onChange={setBoardId}>
              <option value="">
                {personId ? 'No numbers, just the person' : 'Choose a board…'}
              </option>
              {boards.map((board) => (
                <option key={board.id} value={board.id}>
                  {board.name} · {board.belongs_to}
                </option>
              ))}
            </Select>
            <p className="text-xs text-content-subtle">
              {personId && boardId
                ? 'That person, with their standing on that board.'
                : personId
                  ? 'Their photograph and what they have recently won.'
                  : boardId
                    ? 'Whoever leads that board right now, updated on every refresh.'
                    : 'Choose a person, a board, or both.'}
            </p>
          </>
        )}

        {kind === 'comparison' && (
          <div>
            <span className="block text-sm text-content-muted">
              Boards, in the order they are drawn
            </span>
            <div className="mt-1 max-h-56 space-y-1 overflow-y-auto rounded-md border border-edge p-2">
              {boards.map((board) => {
                const at = panelIds.indexOf(board.id);
                const chosen = at !== -1;
                // Four is where a television stops being readable from across
                // a room, so the rest go quiet rather than disappearing —
                // vanishing options read as a broken list.
                const full = panelIds.length >= 4 && !chosen;
                return (
                  <label
                    key={board.id}
                    className={`flex items-center gap-2 rounded px-2 py-1 text-sm ${
                      full
                        ? 'text-content-subtle'
                        : 'cursor-pointer text-content hover:bg-surface-hover'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={chosen}
                      disabled={full}
                      onChange={() =>
                        setPanelIds((current) =>
                          chosen
                            ? current.filter((id) => id !== board.id)
                            : [...current, board.id],
                        )
                      }
                      className="accent-brand"
                    />
                    {chosen && (
                      <span className="w-4 shrink-0 tabular-nums text-content-muted">
                        {at + 1}
                      </span>
                    )}
                    <span className="min-w-0 truncate">
                      {board.name} · {board.belongs_to}
                    </span>
                  </label>
                );
              })}
            </div>
            <p className="mt-1 text-xs text-content-subtle">
              {panelIds.length < 2
                ? 'Choose two to four. One board on its own is a leaderboard slide.'
                : `${panelIds.length} side by side, numbered in the order you ticked them.`}
            </p>
          </div>
        )}

        {kind === 'image' && (
          <>
            <MediaField
              label="The picture"
              value={url}
              onChange={setUrl}
              kinds={['image']}
              link="Or paste a link to a picture or GIF"
            />
            <fieldset className="text-sm">
              <legend className="mb-1 text-content-muted">On the screen</legend>
              <div className="flex flex-wrap gap-4">
                <label className="flex items-center gap-2">
                  <input type="radio" name="fit" checked={fit === 'cover'} onChange={() => setFit('cover')} />
                  <span className="text-content">Fill the screen</span>
                  <span className="text-xs text-content-subtle">edges may be cropped</span>
                </label>
                <label className="flex items-center gap-2">
                  <input type="radio" name="fit" checked={fit === 'contain'} onChange={() => setFit('contain')} />
                  <span className="text-content">Show all of it</span>
                </label>
              </div>
            </fieldset>
          </>
        )}

        {kind === 'video' && (
          <>
            <MediaField
              label="The video"
              value={url}
              onChange={setUrl}
              kinds={['video']}
              link="Or paste a YouTube link"
            />
            <div className="grid gap-4 sm:grid-cols-2">
              <TimeField
                label="Start at"
                seconds={startAt}
                onChange={setStartAt}
                placeholder="0:00"
                hint="Into the video — 0:40, or 40."
              />
              <TimeField
                label="Play for"
                seconds={playFor}
                onChange={setPlayFor}
                placeholder="0:30"
                min={5}
                max={3600}
                hint="Then the next screen."
              />
            </div>
            <p className="text-xs text-content-subtle">
              Fills the whole screen, with sound. Quiet while a celebration has the screen.
            </p>
          </>
        )}

        {(kind === 'message' || kind === 'achievements') && (
          <Field
            label={kind === 'message' ? 'Message' : 'Heading'}
            value={title}
            onChange={setTitle}
            maxLength={120}
            hint={
              kind === 'message'
                ? `The headline the room reads from across the office. ${title.length}/120 — a long one is drawn smaller, over two lines, to fit.`
                : 'Defaults to "Recent wins".'
            }
            required={kind === 'message'}
          />
        )}

        {kind === 'message' && (
          <Field
            label="More (optional)"
            value={body}
            onChange={setBody}
            maxLength={500}
            hint={`${body.length}/500 — the more there is, the smaller it is drawn.`}
            required={false}
          />
        )}

        {/* A goal already names one person or one team, so there is nothing
            left to narrow; a message and an image have no data at all. */}
        {(kind === 'leaderboard' || kind === 'achievements') && (
          <AudiencePicker
            scope={scope}
            setScope={setScope}
            officeId={officeId}
            setOfficeId={setOfficeId}
            teamId={teamId}
            setTeamId={setTeamId}
            offices={offices}
            teams={teams}
            inheritLabel="Same as the channel"
            hint="Leave as the channel's unless this one slide should show something wider."
          />
        )}


        {/* **The background, up front, and where it comes from** (Phase 26):
            "From the leaderboard “Sales floor”", with the choice to give this
            screen its own, starting from that one. A picture or a video is
            the whole screen, so it has none. */}
        {!FULL_SCREEN.has(kind) && (
          <div className="border-t border-edge pt-4">
            <p className="mb-2 text-sm font-medium text-content">Background</p>
            <ScreenBackground
              value={appearance.background as Background | undefined}
              onChange={(next) => {
                const rest = { ...appearance };
                if (next) rest.background = next;
                else delete rest.background;
                setAppearance(rest);
              }}
              inherited={(shown?.inherited?.background as Background | undefined) ?? inherited?.background}
              // Until the server can say (nothing chosen yet), the
              // organization's default is what it would have.
              source={
                shown
                  ? (shown.background_from ?? '')
                  : missing
                    ? inherited?.background?.kind && inherited.background.kind !== 'none'
                      ? 'your Appearance settings'
                      : ''
                    : undefined
              }
            />
          </div>
        )}

        {/* The last word in the chain for everything else. Its defaults are
            what this screen inherits — the leaderboard's own layout, say —
            rather than the organization's. */}
        {!FULL_SCREEN.has(kind) && kind !== 'message' && (
          <div className="border-t border-edge pt-4">
            <AppearanceFields
              kind={kind}
              chosen={appearance}
              inherited={(shown?.inherited as Appearance | undefined) ?? inherited}
              onChange={setAppearance}
              previewBeside
              withBackground={false}
            />
          </div>
        )}

        {/* When and how long, after what it looks like. */}
        <div className="space-y-4 border-t border-edge pt-4">
          {kind !== 'video' && (
            <Field
              label="Seconds on screen"
              value={dwell}
              onChange={setDwell}
              numeric={{ decimals: 0, min: 5, max: 3600 }}
              hint="A board is scanned in a few seconds; a message has to be read."
            />
          )}

          <ScheduleFields value={schedule} onChange={setSchedule} />
        </div>

        <PreviewOnTv
          disabled={Boolean(missing)}
          send={(displayId) =>
            api(`/api/channels/${channelId}/screens/preview/tv/${displayId}`, {
              method: 'POST',
              body: draft,
            })
          }
        />

        <div className="flex items-center gap-3 pt-2">
          <button
            type="submit"
            disabled={busy || schedule.days?.length === 0}
            className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
          >
            {busy ? 'Saving…' : screen ? 'Save' : 'Add'}
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

/**
 * The channel's slides in turn, each for its own time, as a TV plays them
 * (8.5) — so an admin sees the rotation without standing at a television.
 * Slides with nothing to show are skipped, as the TV skips them.
 */
export function PlayRotation({
  slides,
  onClose,
}: {
  slides: { slide: Slide; dwell: number; label: string }[];
  onClose: () => void;
}) {
  const [at, setAt] = useState(0);
  const [paused, setPaused] = useState(false);
  const current = slides[at % Math.max(slides.length, 1)];

  useEffect(() => {
    if (paused || slides.length < 2 || !current) return;
    const timer = window.setTimeout(() => setAt((i) => (i + 1) % slides.length), current.dwell * 1000);
    return () => window.clearTimeout(timer);
  }, [at, paused, slides.length, current]);

  return (
    <Modal title="Play rotation" description="Each slide for its own time, in order, as the TVs play them." onClose={onClose} wide>
      {current ? (
        <>
          <WallPreview slide={current.slide} channelName="" sound />
          <div className="mt-3 flex flex-wrap items-center justify-between gap-3 text-sm">
            <span className="text-content-muted">
              {at % slides.length + 1} of {slides.length} · {current.label} · {current.dwell}s
            </span>
            <span className="flex gap-2">
              <button
                type="button"
                onClick={() => setAt((i) => (i - 1 + slides.length) % slides.length)}
                className="rounded-md border border-edge px-3 py-1.5 text-content hover:bg-surface-hover"
              >
                Previous
              </button>
              <button
                type="button"
                onClick={() => setPaused((p) => !p)}
                className="rounded-md border border-edge px-3 py-1.5 text-content hover:bg-surface-hover"
              >
                {paused ? 'Play' : 'Pause'}
              </button>
              <button
                type="button"
                onClick={() => setAt((i) => (i + 1) % slides.length)}
                className="rounded-md border border-edge px-3 py-1.5 text-content hover:bg-surface-hover"
              >
                Next
              </button>
            </span>
          </div>
        </>
      ) : (
        <p className="text-sm text-content-muted">None of these slides has anything to show yet.</p>
      )}
    </Modal>
  );
}
