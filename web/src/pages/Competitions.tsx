import { dateSpan } from '../time';
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';

import { api } from '../api';
import { toast } from '../toast';
import { useOrgAppearance, useOrgTimezone } from '../orgAppearance';
import { Can, useAuth } from '../auth';
import AppearanceFields from '../components/AppearanceFields';
import EmptyState from '../components/EmptyState';
import Field, { forInput } from '../components/Field';
import IconButton from '../components/IconButton';
import {
  CopyIcon,
  MedalIcon,
  PaletteIcon,
  PencilIcon,
  TrophyIcon,
} from '../components/icons';
import MetricValue from '../components/MetricValue';
import Modal from '../components/Modal';
import PageHeader from '../components/PageHeader';
import Select from '../components/Select';
import { Tab } from '../components/Tabs';
import {
  browserZone,
  fromLocalInput,
  zoneName,
  phaseLabel,
  phaseOf,
  phaseTone,
  remaining,
  statusLine,
  tabOf,
  tickInterval,
  toLocalInput,
  type Clock,
  type Phase,
} from './competitionClock';
import Loading from '../components/Loading';
import PeoplePicker from '../components/PeoplePicker';
import type { PickPerson } from '../components/peoplePick';
import EditorPreview from '../components/wall/EditorPreview';
import { pickFormat } from './Leaderboards';
import { competitionTemplates, type CompetitionTemplate } from './starterTemplates';
import { useOpenFromUrl } from '../urlIntent';

export interface Competition extends Clock {
  id: number;
  name: string;
  prize: string | null;
  metric_id: number;
  metric_name: string;
  unit: string;
  decimal_places: number;
  unit_label?: string | null;
  direction: string;
  entity_type: string;
  settlement_hours: number;
  closed_at: string | null;
  tie_break: string;
  min_participation: number | null;
  /** Where the race layout draws its flag. */
  finish_line: string | null;
  entrant_count: number;
  head_to_head: boolean;
  provisional: boolean;
  rules_editable: boolean;
  /** Running: the prize, a later end and late entrants may change, with a
   *  reason (6.14). */
  running_editable?: boolean;
  /** Only what this competition itself chose; absent keys inherit. */
  appearance: Record<string, unknown>;
  /** The series' first round — its own id for a one-off. */
  series_id: number | null;
  /** 1 for the first round. */
  round_number: number;
  /** How the series repeats, or null for a one-off. */
  repeat: Repeat | null;
  repeat_until: string | null;
}

export type Repeat = 'daily' | 'weekly' | 'monthly';

export const REPEAT_LABEL: Record<Repeat, string> = {
  daily: 'every day',
  weekly: 'every week',
  monthly: 'every month',
};

/** "Repeats every week · round 3", or nothing for a one-off. */
export function repeatLine(competition: Competition): string | null {
  if (!competition.repeat && competition.round_number <= 1) return null;
  const parts = [];
  if (competition.repeat) parts.push(`Repeats ${REPEAT_LABEL[competition.repeat]}`);
  parts.push(`round ${competition.round_number}`);
  return parts.join(' · ');
}

interface Metric {
  id: number;
  name: string;
  unit?: string;
  decimal_places?: number;
  unit_label?: string | null;
  direction?: string;
}

type Person = PickPerson;

interface Team {
  id: number;
  name: string;
}

interface Participant {
  id: number;
  entity_id: number;
  entity_name: string;
}

interface PreviewStanding {
  entity_id: number;
  entity_name: string;
  rank: number;
  value: string;
}

interface Preview {
  starts_at: string;
  ends_at: string;
  metric_name: string;
  unit: string;
  decimal_places: number;
  unit_label?: string | null;
  standings: PreviewStanding[];
  spread: number | null;
}

type TabName = 'live' | 'upcoming' | 'finished' | 'drafts';

const TABS: { name: TabName; label: string }[] = [
  { name: 'live', label: 'Live' },
  { name: 'upcoming', label: 'Upcoming' },
  { name: 'finished', label: 'Finished' },
  { name: 'drafts', label: 'Drafts' },
];

/** Tailwind classes per phase tone. Kept beside the pill that uses them. */
const TONE: Record<ReturnType<typeof phaseTone>, string> = {
  neutral: 'bg-content-subtle',
  info: 'bg-brand',
  live: 'bg-success',
  warning: 'bg-warning',
};

/**
 * A clock that re-renders only as often as the coarsest thing on screen needs.
 *
 * The interval comes from the *nearest* deadline in the list, so a page showing
 * one contest ending in forty seconds ticks per second while a page of month-long
 * contests ticks every ten minutes. A fixed one-second tick would be 600 renders
 * a minute producing identical pixels.
 */
function useNow(deadlines: string[]): Date {
  const [now, setNow] = useState(() => new Date());

  const soonest = deadlines.reduce(
    (best, at) => Math.min(best, remaining(at, now)),
    Number.POSITIVE_INFINITY,
  );
  const interval = tickInterval(Number.isFinite(soonest) ? soonest : 0);

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), interval);
    return () => clearInterval(timer);
  }, [interval]);

  return now;
}

export function PhasePill({ phase }: { phase: Phase }) {
  return (
    <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-edge px-2 py-0.5 text-xs text-content-muted">
      <span className={`size-1.5 rounded-full ${TONE[phaseTone(phase)]}`} />
      {phaseLabel(phase)}
    </span>
  );
}

export default function Competitions() {
  const { can } = useAuth();
  const [competitions, setCompetitions] = useState<Competition[] | null>(null);
  const [tab, setTab] = useState<TabName>('live');
  const [creating, setCreating] = useState(false);
  const [template, setTemplate] = useState<CompetitionTemplate | null>(null);
  useOpenFromUrl('new', () => setCreating(true));
  const [editing, setEditing] = useState<Competition | null>(null);
  const [restyling, setRestyling] = useState<Competition | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function duplicate(competition: Competition) {
    try {
      const copy = await api<Competition>(
        `/api/competitions/${competition.id}/duplicate`,
        { method: 'POST' },
      );
      // Into Drafts and straight into the editor: a copy always needs its
      // dates looked at, which is the one thing that cannot be inherited.
      setTab('drafts');
      setEditing(copy);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not duplicate that.');
    }
  }

  const load = useCallback(async () => {
    try {
      setCompetitions(await api<Competition[]>('/api/competitions'));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load competitions.');
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const shown = useMemo(
    () => (competitions ?? []).filter((c) => tabOf(c) === tab),
    [competitions, tab],
  );

  // Only the deadlines actually on screen. A finished contest has no countdown,
  // so including it would pin the tick rate to a date in the past.
  const deadlines = shown
    .filter((c) => ['upcoming', 'running', 'provisional'].includes(phaseOf(c)))
    .map((c) =>
      phaseOf(c) === 'upcoming'
        ? c.starts_at
        : phaseOf(c) === 'running'
          ? c.ends_at
          : c.settles_at,
    );
  const now = useNow(deadlines);

  // Counts on the tabs, so an empty "Live" does not look like a broken page when
  // there are four contests sitting in Drafts.
  const counts = useMemo(() => {
    const tally: Record<TabName, number> = { live: 0, upcoming: 0, finished: 0, drafts: 0 };
    for (const competition of competitions ?? []) tally[tabOf(competition)] += 1;
    return tally;
  }, [competitions]);

  return (
    <>
      <PageHeader
        title="Competitions"
        description="Time-boxed contests between people or teams. A result is frozen when the contest settles, so a later correction to the underlying data cannot change who won."
        actions={
          <Can do="competitions.manage">
            <button
              onClick={() => {
                setEditing(null);
                setCreating(true);
              }}
              className="rounded-md bg-brand px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover"
            >
              New competition
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

      <div className="mb-4 flex flex-wrap gap-2">
        {TABS.map(({ name, label }) => (
          <Tab key={name} active={tab === name} onClick={() => setTab(name)}>
            {label}
            {counts[name] > 0 && (
              <span className="ml-1.5 text-content-muted">{counts[name]}</span>
            )}
          </Tab>
        ))}
      </div>

      {competitions === null ? (
        <Loading />
      ) : shown.length === 0 ? (
        <EmptyState
          title={emptyTitle(tab)}
          description={
            competitions.length === 0 && can('competitions.manage')
              ? `${emptyDescription(tab)} Start from one of these:`
              : emptyDescription(tab)
          }
          action={
            // Offered while there are none at all: once there is one, the
            // form itself offers them.
            competitions.length === 0 && can('competitions.manage') ? (
              <CompetitionTemplateButtons
                onPick={(t) => {
                  setEditing(null);
                  setTemplate(t);
                  setCreating(true);
                }}
              />
            ) : undefined
          }
        />
      ) : (
        <div className="grid gap-4 [grid-template-columns:repeat(auto-fill,minmax(20rem,1fr))]">
          {shown.map((competition) => (
            <CompetitionCard
              key={competition.id}
              competition={competition}
              now={now}
              canManage={can('competitions.manage')}
              onEdit={() => {
                setCreating(false);
                setEditing(competition);
              }}
              onRestyle={() => setRestyling(competition)}
              onDuplicate={() => void duplicate(competition)}
            />
          ))}
        </div>
      )}

      {restyling && (
        <RestyleForm
          competition={restyling}
          onClose={() => setRestyling(null)}
          onSaved={async () => {
            toast('Appearance saved');
            setRestyling(null);
            await load();
          }}
        />
      )}

      {(creating || editing) && (
        <CompetitionForm
          competition={editing}
          template={editing ? null : template}
          onClose={() => {
            setCreating(false);
            setEditing(null);
            setTemplate(null);
          }}
          onSaved={async (landedIn) => {
            toast(editing ? 'Competition saved' : 'Competition created');
            setCreating(false);
            setEditing(null);
            setTemplate(null);
            if (landedIn) setTab(landedIn);
            await load();
          }}
        />
      )}
    </>
  );
}

function emptyTitle(tab: TabName): string {
  if (tab === 'live') return 'Nothing running';
  if (tab === 'upcoming') return 'Nothing scheduled';
  if (tab === 'drafts') return 'No drafts';
  return 'Nothing finished yet';
}

function emptyDescription(tab: TabName): string {
  if (tab === 'live') return 'Contests appear here once they start.';
  if (tab === 'upcoming')
    return 'A published contest waits here until its start date, which is what builds the anticipation.';
  if (tab === 'drafts')
    return 'A draft is yours to configure. Nobody else sees it until you publish it.';
  return 'Settled contests keep their result exactly as it stood when they closed.';
}

function CompetitionCard({
  competition,
  now,
  canManage,
  onEdit,
  onRestyle,
  onDuplicate,
}: {
  competition: Competition;
  now: Date;
  canManage: boolean;
  onEdit: () => void;
  onRestyle: () => void;
  onDuplicate: () => void;
}) {
  const phase = phaseOf(competition);
  const dimmed = phase === 'cancelled' || phase === 'draft';

  return (
    <article
      className={`flex flex-col rounded-lg border border-edge bg-surface p-5 ${
        dimmed ? 'border-dashed opacity-70' : ''
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link
            to={`/competitions/${competition.id}`}
            className="block truncate font-medium text-content hover:text-brand"
          >
            {competition.name}
          </Link>
          <p className="mt-0.5 truncate text-sm text-content-muted">
            {competition.metric_name}
            {' · '}
            {entrantCount(competition)}
          </p>
          {repeatLine(competition) && (
            <p className="mt-0.5 truncate text-xs text-content-subtle">{repeatLine(competition)}</p>
          )}
        </div>
        <PhasePill phase={phase} />
      </div>

      {/* The status line carries the countdown, and is the one part of the card
          that changes on its own. */}
      <p
        className={`mt-3 text-sm ${
          phase === 'provisional' ? 'text-warning' : 'text-content-muted'
        }`}
      >
        {statusLine(competition, now)}
      </p>

      {competition.prize && (
        <p className="mt-3 flex items-center gap-1.5 text-sm text-content">
          <TrophyIcon className="size-4 shrink-0 text-content-muted" />
          <span className="truncate">{competition.prize}</span>
        </p>
      )}

      <div className="mt-4 flex items-center justify-between gap-2 border-t border-edge pt-3">
        <Link
          to={`/competitions/${competition.id}`}
          className="text-sm text-content-muted hover:text-brand"
        >
          {phase === 'draft' ? 'Set up' : 'Standings'} →
        </Link>
        {/* Edit is offered only where it would work. Once a contest is running
            its rules are locked server-side, and a pencil that opens a form of
            disabled fields is worse than no pencil. */}
        <div className="flex items-center gap-1">
          {/* A running contest is exactly when somebody wants to restyle it —
              it is on the wall this week. Its rules stay locked; how it is
              drawn was never one of them. */}
          {canManage && (phase === 'running' || phase === 'provisional') && (
            <IconButton
              label="Appearance"
              icon={<PaletteIcon className="size-4" />}
              onClick={onRestyle}
            />
          )}
          {canManage && competition.rules_editable && (
            <IconButton
              label="Edit"
              icon={<PencilIcon className="size-4" />}
              onClick={onEdit}
            />
          )}
          {/* **The commonest competition is the last one** — a monthly sprint
              between the same fourteen people, rebuilt by retyping it and
              re-ticking the entrants, which is where somebody misses one. */}
          {canManage && (
            <IconButton
              label="Duplicate"
              icon={<CopyIcon className="size-4" />}
              onClick={onDuplicate}
            />
          )}
        </div>
      </div>
    </article>
  );
}

/** "3 entrants" / "1 team", pluralised for whichever kind this contest is. */
function entrantCount(competition: Competition): string {
  const n = competition.entrant_count;
  if (competition.entity_type === 'team') return `${n} ${n === 1 ? 'team' : 'teams'}`;
  return `${n} ${n === 1 ? 'entrant' : 'entrants'}`;
}

const TIE_BREAKS = [
  { value: 'earliest_to_reach', label: 'Whoever got there first wins' },
  { value: 'shared_rank', label: 'Let them share the place' },
];

/** Fewer than this cannot be published — matches MIN_ENTRANTS on the server. */
const MIN_ENTRANTS = 2;

/**
 * One form for creating and editing.
 *
 * Editing had no UI at all for a while: the PATCH endpoint existed and nothing
 * called it, so a typo in a contest name meant cancelling it and starting again.
 *
 * The two save buttons on create are the point of the layout. "Save as draft"
 * and "Save & publish" make the difference explicit at the moment it matters,
 * rather than leaving somebody to find a Publish button on another page and
 * wonder why nobody could see their contest.
 */
/**
 * How a running contest looks, and nothing else about it.
 *
 * **A separate form rather than the edit form with most of it greyed out.**
 * Once a contest starts, its entrants, dates and metric are locked — opening
 * the full editor would present eight fields that refuse to change and one
 * that does not, and leave the person to work out which is which.
 */
function RestyleForm({
  competition,
  onClose,
  onSaved,
}: {
  competition: Competition;
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [appearance, setAppearance] = useState<Record<string, unknown>>(
    competition.appearance ?? {},
  );
  const inherited = useOrgAppearance();
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSaving(true);
    try {
      // Only `appearance` is sent. The PATCH treats every field present as a
      // change, so including the unchanged rules would be refused for a
      // contest that has started.
      await api(`/api/competitions/${competition.id}`, {
        method: 'PATCH',
        body: JSON.stringify({ appearance }),
      });
      await onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save the appearance.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      title={`Appearance — ${competition.name}`}
      description="How this contest is drawn on a wall. Its rules and entrants are locked while it runs."
      onClose={onClose}
      wide
      side={
        <EditorPreview
          kind="competition"
          title={competition.name}
          chosen={appearance}
          inherited={inherited}
          sample={{
            unit: competition.unit,
            decimal_places: competition.decimal_places,
            unit_label: competition.unit_label,
            direction: competition.direction,
            entity_type: competition.entity_type,
            prize: competition.prize,
            ends_at: competition.ends_at,
          }}
        />
      }
    >
      <form onSubmit={(e) => void submit(e)} className="space-y-4">
        <AppearanceFields
          kind="competition"
          chosen={appearance}
          inherited={inherited}
          onChange={setAppearance}
          previewBeside
        />

        {error && (
          <p
            role="alert"
            className="rounded-md border border-danger px-3 py-2 text-sm text-danger"
          >
            {error}
          </p>
        )}

        <div className="flex items-center justify-end gap-2 border-t border-edge pt-4">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-edge px-3 py-2 text-sm text-content transition-colors hover:bg-surface-hover"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={saving}
            className="rounded-md bg-brand px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </form>
    </Modal>
  );
}

export function CompetitionForm({
  competition,
  template,
  onClose,
  onSaved,
}: {
  competition: Competition | null;
  /** What a new contest starts from (6.4). Ignored when editing. */
  template?: CompetitionTemplate | null;
  onClose: () => void;
  onSaved: (landedIn?: TabName) => void | Promise<void>;
}) {
  const editing = competition !== null;

  const [name, setName] = useState(competition?.name ?? '');
  const [metricId, setMetricId] = useState(
    competition ? String(competition.metric_id) : '',
  );
  const [entityType, setEntityType] = useState(competition?.entity_type ?? 'user');
  const [entrants, setEntrants] = useState<number[]>([]);
  // **Instants, not what the inputs show.** The inputs are in the
  // organization's zone, which arrives a moment after the form opens; holding
  // the instant means its arrival redraws the inputs and never moves the
  // contest. Empty while a field is cleared.
  const zone = useOrgTimezone() ?? browserZone();
  const [startsAt, setStartsAt] = useState(
    competition?.starts_at ?? defaultStart(zone),
  );
  const [endsAt, setEndsAt] = useState(competition?.ends_at ?? defaultEnd(zone));
  // The defaults are 9am and 5pm *there*, so they are worked out again when
  // the organization's zone arrives — unless somebody has already chosen.
  const datesChosen = useRef(competition !== null);
  useEffect(() => {
    if (datesChosen.current) return;
    setStartsAt(defaultStart(zone));
    setEndsAt(defaultEnd(zone));
  }, [zone]);
  const [prize, setPrize] = useState(competition?.prize ?? '');
  const [settlementHours, setSettlementHours] = useState(
    String(competition?.settlement_hours ?? 24),
  );
  const [tieBreak, setTieBreak] = useState(competition?.tie_break ?? 'earliest_to_reach');
  const [finishLine, setFinishLine] = useState(
    competition?.finish_line ? String(Number(competition.finish_line)) : '',
  );
  const [minParticipation, setMinParticipation] = useState(
    forInput(competition?.min_participation),
  );
  const [appearance, setAppearance] = useState<Record<string, unknown>>(
    competition?.appearance ?? {},
  );
  const [repeat, setRepeat] = useState<Repeat | ''>(competition?.repeat ?? '');
  const [repeatUntil, setRepeatUntil] = useState(competition?.repeat_until ?? '');
  const inherited = useOrgAppearance();

  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [people, setPeople] = useState<Person[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);
  //: What the entrant list looked like when the form opened, so saving can send
  //: the difference rather than the whole set — participants are their own
  //: endpoints, not a field on the competition.
  const [wasEntered, setWasEntered] = useState<Participant[]>([]);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    void (async () => {
      try {
        const [m, u, t] = await Promise.all([
          api<Metric[]>('/api/metrics'),
          api<Person[]>('/api/users'),
          api<Team[]>('/api/teams'),
        ]);
        setMetrics(m);
        setPeople(u);
        setTeams(t);
        if (!editing && m[0]) setMetricId(String(m[0].id));

        if (competition) {
          const current = await api<Participant[]>(
            `/api/competitions/${competition.id}/participants`,
          );
          setWasEntered(current);
          setEntrants(current.map((p) => p.entity_id));
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Could not load the options.');
      }
    })();
  }, [competition, editing]);

  // Switching between people and teams invalidates whoever was picked — the ids
  // mean something different now, and keeping them would enter team 4 as person 4.
  function changeEntityType(next: string) {
    setEntityType(next);
    setEntrants([]);
    setPreview(null);
  }

  /** A starter (6.4): its name, who competes, its dates, prize and repeat. */
  function startFrom(t: CompetitionTemplate) {
    setName(t.name);
    if (t.entity_type !== entityType) changeEntityType(t.entity_type);
    datesChosen.current = true;
    setStartsAt(t.starts_at);
    setEndsAt(t.ends_at);
    setPrize(t.prize);
    setRepeat(t.repeat);
    setPreview(null);
  }
  const started = useRef(false);
  useEffect(() => {
    if (!editing && template && !started.current) {
      started.current = true;
      startFrom(template);
    }
    // Once, on opening.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [template]);

  const candidates = teams.map((t) => ({ id: t.id, label: t.name }));

  function toggle(id: number) {
    setPreview(null);
    setEntrants((current) =>
      current.includes(id) ? current.filter((x) => x !== id) : [...current, id],
    );
  }

  function window(): { starts_at: string; ends_at: string } | null {
    if (!startsAt || !endsAt) return null;
    return { starts_at: startsAt, ends_at: endsAt };
  }

  async function showPreview() {
    const dates = window();
    if (!dates || entrants.length === 0 || !metricId) return;
    setError(null);
    setPreviewing(true);
    try {
      setPreview(
        await api<Preview>('/api/competitions/preview', {
          method: 'POST',
          body: JSON.stringify({
            metric_id: Number(metricId),
            entity_type: entityType,
            entity_ids: entrants,
            ...dates,
          }),
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not build the preview.');
    } finally {
      setPreviewing(false);
    }
  }

  function fields(dates: { starts_at: string; ends_at: string }) {
    return {
      name,
      prize: prize.trim() === '' ? null : prize.trim(),
      settlement_hours: Number(settlementHours),
      tie_break: tieBreak,
      min_participation:
        minParticipation.trim() === '' ? null : Number(minParticipation),
      finish_line: finishLine.trim() === '' ? null : finishLine.trim(),
      appearance,
      ...dates,
    };
  }

  /** Add and remove only what changed. */
  async function syncEntrants(competitionId: number) {
    const before = new Set(wasEntered.map((p) => p.entity_id));
    const after = new Set(entrants);

    for (const participant of wasEntered) {
      if (!after.has(participant.entity_id)) {
        await api(
          `/api/competitions/${competitionId}/participants/${participant.id}`,
          { method: 'DELETE' },
        );
      }
    }
    for (const id of entrants) {
      if (!before.has(id)) {
        await api(`/api/competitions/${competitionId}/participants`, {
          method: 'POST',
          body: JSON.stringify({ entity_id: id }),
        });
      }
    }
  }

  async function submit(event: FormEvent, publish: boolean) {
    event.preventDefault();
    const dates = window();
    if (!dates) {
      setError('Give the competition a start and an end.');
      return;
    }
    setError(null);
    setSaving(true);
    try {
      if (editing && competition) {
        await api(`/api/competitions/${competition.id}`, {
          method: 'PATCH',
          body: JSON.stringify(fields(dates)),
        });
        await syncEntrants(competition.id);
        // Repeating belongs to the series, so it has its own endpoint — and
        // is only sent when it changed.
        if (
          (repeat || null) !== competition.repeat ||
          (repeat && (repeatUntil || null) !== competition.repeat_until)
        ) {
          await api(`/api/competitions/${competition.id}/repeat`, {
            method: 'PUT',
            body: JSON.stringify({ repeat: repeat || null, until: repeat && repeatUntil ? repeatUntil : null }),
          });
        }
        // Landed on the tab the contest is actually on: one published with a
        // start already past is live, not upcoming (QA-13).
        const published = publish
          ? await api<Competition>(`/api/competitions/${competition.id}/publish`, {
              method: 'POST',
            })
          : null;
        await onSaved(published ? tabOf(published) : undefined);
        return;
      }

      const made = await api<Competition>('/api/competitions', {
        method: 'POST',
        body: JSON.stringify({
          ...fields(dates),
          metric_id: Number(metricId),
          entity_type: entityType,
          entity_ids: entrants,
          repeat: repeat || null,
          repeat_until: repeat && repeatUntil ? repeatUntil : null,
        }),
      });
      const published = publish
        ? await api<Competition>(`/api/competitions/${made.id}/publish`, { method: 'POST' })
        : null;
      await onSaved(published ? tabOf(published) : 'drafts');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save the competition.');
    } finally {
      setSaving(false);
    }
  }

  const tooFew = entrants.length < MIN_ENTRANTS;
  // Publishing only means something from a draft. An already-scheduled contest
  // being edited has nothing left to publish.
  const publishable = !editing || phaseOf(competition) === 'draft';

  return (
    <Modal
      title={editing ? `Edit ${competition.name}` : 'New competition'}
      description={
        editing
          ? 'Changes apply immediately. Entrants and rules are locked once the contest starts.'
          : 'Save it as a draft to keep working on it, or publish it now and the entrants will see it.'
      }
      onClose={onClose}
      wide
      side={
        <EditorPreview
          kind="competition"
          title={name}
          chosen={appearance}
          inherited={inherited}
          // The prize, the end, and who is actually in it (7.4, Q2-3).
          sample={{
            ...pickFormat(metrics.find((m) => String(m.id) === metricId)),
            entity_type: entityType,
            prize: prize.trim() || null,
            ends_at: endsAt || null,
            entrants: entrants
              .map((id) =>
                entityType === 'team'
                  ? teams.find((t) => t.id === id)?.name
                  : people.find((p) => p.id === id)?.full_name,
              )
              .filter((n): n is string => Boolean(n)),
          }}
        />
      }
    >
      <form onSubmit={(e) => void submit(e, false)} className="space-y-5">
        {error && (
          <p
            role="alert"
            className="rounded-md border border-danger px-3 py-2 text-sm text-danger"
          >
            {error}
          </p>
        )}

        {!editing && (
          <div>
            <p className="mb-2 text-xs text-content-subtle">Start from</p>
            <CompetitionTemplateButtons onPick={startFrom} />
          </div>
        )}

        <Field label="Name" value={name} onChange={setName} maxLength={120} autoFocus />

        <div className="grid gap-4 sm:grid-cols-2">
          {/* Metric and entity type are fixed after creation: the server refuses
              them, and they would change what every number already on the page
              means. */}
          {editing ? (
            <>
              <Fixed label="Metric" value={competition.metric_name} />
              <Fixed
                label="Who competes"
                value={competition.entity_type === 'team' ? 'Teams' : 'People'}
              />
            </>
          ) : (
            <>
              <Select
                label="Metric"
                value={metricId}
                onChange={(value) => {
                  setMetricId(value);
                  setPreview(null);
                }}
                options={metrics.map((m) => ({ value: String(m.id), label: m.name }))}
              />
              <Select
                label="Who competes"
                value={entityType}
                onChange={changeEntityType}
                options={[
                  { value: 'user', label: 'People' },
                  { value: 'team', label: 'Teams' },
                ]}
              />
            </>
          )}
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="Starts"
            type="datetime-local"
            value={startsAt ? toLocalInput(startsAt, zone) : ''}
            onChange={(value) => {
              datesChosen.current = true;
              setStartsAt(fromLocalInput(value, zone) ?? '');
              setPreview(null);
            }}
          />
          <Field
            label="Ends"
            type="datetime-local"
            value={endsAt ? toLocalInput(endsAt, zone) : ''}
            onChange={(value) => {
              datesChosen.current = true;
              setEndsAt(fromLocalInput(value, zone) ?? '');
              setPreview(null);
            }}
          />
          <p className="-mt-2 text-xs text-content-muted sm:col-span-2">
            Times are {zoneName(zone)}, the organization&rsquo;s timezone.
          </p>
        </div>

        {/* **Repeating makes rounds, not one long contest.** Each round is its own
            competition with its own winner; the next is made as soon as the
            current one starts, copied from it — so editing the upcoming round is
            how the series changes. */}
        <div className="grid gap-4 sm:grid-cols-2">
          <Select
            label="Repeat"
            value={repeat}
            onChange={(value) => setRepeat(value as Repeat | '')}
            options={[
              { value: '', label: 'Never — a one-off' },
              { value: 'daily', label: 'Every day' },
              { value: 'weekly', label: 'Every week' },
              { value: 'monthly', label: 'Every month' },
            ]}
            hint={
              editing && (competition?.round_number ?? 1) > 1
                ? 'Applies to the whole series this round belongs to.'
                : 'Each round is its own contest with its own winner, at the same time of day.'
            }
          />
          {repeat && (
            <Field
              label="Last round starts by"
              type="date"
              value={repeatUntil}
              onChange={setRepeatUntil}
              required={false}
              hint="Optional. Leave empty to keep going until you stop it."
            />
          )}
        </div>

        <Field
          label="Prize"
          value={prize}
          onChange={setPrize}
          maxLength={200}
          required={false}
          hint="Optional, and the reason anyone looks twice. Shown everywhere the competition appears."
        />

        <fieldset className="rounded-md border border-edge p-4">
          <legend className="px-1 text-sm text-content-muted">
            Entrants{entrants.length > 0 && ` · ${entrants.length} chosen`}
          </legend>
          <p className="mb-3 text-xs text-content-muted">
            Named explicitly rather than filtered, so nobody joins or leaves the
            contest because they changed team halfway through.
          </p>
          {entityType === 'user' ? (
            // Typed, not ticked: this was a column of 461 checkboxes (review
            // #1). A whole team, or everybody a search finds, is one choice.
            <PeoplePicker
              multiple
              label="Who is in it"
              people={people}
              value={entrants}
              onChange={(ids) => {
                setPreview(null);
                setEntrants(ids);
              }}
            />
          ) : (
          <div className="max-h-48 space-y-1 overflow-y-auto">
            {candidates.length === 0 ? (
              <p className="text-sm text-content-muted">Nothing to choose from yet.</p>
            ) : (
              candidates.map((candidate) => (
                <label
                  key={candidate.id}
                  className="flex cursor-pointer items-center gap-2 rounded px-2 py-1 text-sm text-content hover:bg-surface-hover"
                >
                  <input
                    type="checkbox"
                    checked={entrants.includes(candidate.id)}
                    onChange={() => toggle(candidate.id)}
                    className="accent-brand"
                  />
                  {candidate.label}
                </label>
              ))
            )}
          </div>
          )}
        </fieldset>

        <fieldset className="rounded-md border border-edge p-4">
          <legend className="px-1 text-sm text-content-muted">Scoring rules</legend>
          <div className="grid gap-4 sm:grid-cols-2">
            <Select
              label="If two entrants tie"
              value={tieBreak}
              onChange={setTieBreak}
              options={TIE_BREAKS}
              hint="A contest with a prize usually needs a decisive winner."
            />
            <Field
              label="Settlement window (hours)"
              value={settlementHours}
              onChange={setSettlementHours}
              numeric={{ decimals: 0, min: 0, max: 168 }}
              hint="How long to wait after the end before freezing the result, so a deal that syncs late still counts."
            />
            <Field
              label="Minimum data points"
              value={minParticipation}
              onChange={setMinParticipation}
              numeric={{ decimals: 0, min: 1 }}
              required={false}
              hint="Optional. Below this an entrant is left unranked rather than placed last. Worth setting for an average, pointless for a total."
            />
            <Field
              label="Finish line"
              value={finishLine}
              onChange={setFinishLine}
              numeric={{ decimals: 2, min: 0 }}
              required={false}
              hint="Optional. Where the race layout draws the flag — reach it and you have finished. Without one, the race is measured against whoever is leading. It can be moved while the contest runs — it decides where the flag is, not who wins."
            />
          </div>
        </fieldset>

        <div className="rounded-md border border-edge p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm text-content">How this would have looked last time</p>
              <p className="text-xs text-content-muted">
                The same entrants and metric, over an equally long window that has
                already happened.
              </p>
            </div>
            <button
              type="button"
              onClick={() => void showPreview()}
              disabled={previewing || entrants.length === 0 || !metricId}
              className="rounded-md border border-edge px-3 py-1.5 text-sm text-content transition-colors hover:bg-surface-hover disabled:opacity-50"
            >
              {previewing ? 'Working…' : 'Check'}
            </button>
          </div>

          {preview && <PreviewTable preview={preview} />}
        </div>

        <div className="border-t border-edge pt-4">
          <AppearanceFields
            kind="competition"
            chosen={appearance}
            inherited={inherited}
            onChange={setAppearance}
            previewBeside
          />
        </div>

        <div className="flex flex-wrap items-center justify-end gap-2 border-t border-edge pt-4">
          {tooFew && publishable && (
            // Said before they reach for the button, not after the server refuses
            // it. Two entrants is the difference between a contest and a notice.
            <p className="mr-auto text-xs text-content-muted">
              {entrants.length === 0
                ? 'Choose at least two entrants to publish.'
                : 'One more entrant and this can be published.'}
            </p>
          )}
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-edge px-3 py-2 text-sm text-content transition-colors hover:bg-surface-hover"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={saving}
            className="rounded-md border border-edge px-3 py-2 text-sm text-content transition-colors hover:bg-surface-hover disabled:opacity-50"
          >
            {saving ? 'Saving…' : editing ? 'Save changes' : 'Save as draft'}
          </button>
          {publishable && (
            <button
              type="button"
              onClick={(e) => void submit(e, true)}
              disabled={saving || tooFew}
              className="rounded-md bg-brand px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
            >
              Save &amp; publish
            </button>
          )}
        </div>
      </form>
    </Modal>
  );
}

/** A value the form shows but cannot change, styled to hold the layout. */
function Fixed({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="block text-sm text-content-muted">{label}</span>
      <p className="mt-1 rounded-md border border-edge bg-bg px-3 py-2 text-content">
        {value}
      </p>
    </div>
  );
}

function PreviewTable({ preview }: { preview: Preview }) {
  const format = { unit: preview.unit, decimal_places: preview.decimal_places, unit_label: preview.unit_label };
  const empty = preview.standings.every((row) => Number(row.value) === 0);

  return (
    <div className="mt-4 border-t border-edge pt-4">
      <p className="mb-2 text-xs text-content-muted">
        {dateSpan(preview.starts_at, preview.ends_at)}
      </p>

      {empty ? (
        <p className="text-sm text-content-muted">
          Nobody recorded anything on {preview.metric_name} in that window. Either
          the data has not been flowing for long, or this is the wrong metric for
          these entrants.
        </p>
      ) : (
        <>
          <ol className="space-y-1">
            {preview.standings.map((row) => (
              <li
                key={row.entity_id}
                className="flex items-baseline justify-between gap-3 text-sm"
              >
                <span className="truncate text-content">
                  <span className="mr-2 tabular-nums text-content-muted">{row.rank}</span>
                  {row.entity_name}
                </span>
                <MetricValue value={row.value} format={format} className="text-content" />
              </li>
            ))}
          </ol>

          {preview.spread !== null && (
            <p className="mt-3 flex items-start gap-1.5 text-xs text-content-muted">
              <MedalIcon className="mt-0.5 size-3.5 shrink-0" />
              <span>
                The leader did {preview.spread}× the bottom of the field.{' '}
                {preview.spread >= 3
                  ? 'That is a walkover rather than a contest — consider narrowing the field or splitting it in two.'
                  : 'Close enough that most of the field has a reason to try.'}
              </span>
            </p>
          )}
        </>
      )}
    </div>
  );
}

/** `days` from today where the organization is, at a wall-clock time there. */
function daysFromNow(days: number, clock: string, zone: string): string {
  const today = toLocalInput(new Date().toISOString(), zone);
  const day = new Date(
    Date.UTC(+today.slice(0, 4), +today.slice(5, 7) - 1, +today.slice(8, 10) + days),
  )
    .toISOString()
    .slice(0, 10);
  return fromLocalInput(`${day}T${clock}`, zone) ?? new Date().toISOString();
}

/** Tomorrow at 9am, which is the start somebody almost always wants. */
function defaultStart(zone: string): string {
  return daysFromNow(1, '09:00', zone);
}

/** Two weeks after that — long enough to matter, short enough to stay watched. */
function defaultEnd(zone: string): string {
  return daysFromNow(15, '17:00', zone);
}

/**
 * The starter contests, as buttons (6.4). Dates are worked out when they are
 * shown, in the organization's own timezone, so "next Friday" is its Friday.
 */
function CompetitionTemplateButtons({ onPick }: { onPick: (t: CompetitionTemplate) => void }) {
  const zone = useOrgTimezone() ?? browserZone();
  return (
    <div className="flex flex-wrap justify-center gap-2 sm:justify-start">
      {competitionTemplates(new Date(), zone).map((t) => (
        <button
          key={t.key}
          type="button"
          onClick={() => onPick(t)}
          title={t.blurb}
          className="rounded-full border border-edge px-3 py-1 text-sm text-content transition-colors hover:border-brand hover:bg-surface-hover"
        >
          {t.name}
        </button>
      ))}
    </div>
  );
}
