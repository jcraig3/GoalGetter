import { dayAndTime, dayMonth, dayName } from '../time';
import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';

import { api } from '../api';
import { toast } from '../toast';
import { Can, useAuth } from '../auth';
import DataCurrency from '../components/DataCurrency';
import CompetitionReportCard from '../components/CompetitionReportCard';
import MetricValue from '../components/MetricValue';
import Avatar from '../components/Avatar';
import PageHeader from '../components/PageHeader';
import ShowOnTv from '../components/ShowOnTv';
import { TrophyIcon } from '../components/icons';
import {
  canCancel,
  canDelete,
  canUnpublish,
  phaseHelp,
  phaseOf,
  place,
  remaining,
  statusLine,
  tickInterval,
  type Phase,
} from './competitionClock';
import { CompetitionForm, PhasePill, REPEAT_LABEL, repeatLine, type Competition } from './Competitions';
import { ask } from '../confirm';
import Loading from '../components/Loading';
import Breadcrumb from '../components/Breadcrumb';
import RunningChanges from '../components/RunningChanges';
import { wallWords } from '../wallUse';
import PersonLink from '../components/PersonLink';

interface Standing {
  entity_id: number;
  entity_name: string;
  rank: number;
  value: string;
  gap_to_next: string | null;
  final: boolean;
  /** A person's face, for the head-to-head (8.5). */
  photo_digest?: string | null;
}

interface Change {
  at: string;
  who: string | null;
  what: string;
  note: string;
}

interface Detail {
  competition: Competition;
  standings: Standing[];
  you: Standing | null;
  /** What changed while it ran, and why, newest first (6.14). */
  changes?: Change[];
}

interface Participant {
  id: number;
  entity_id: number;
  entity_name: string;
}

export default function CompetitionDetail() {
  const { id } = useParams();
  const { can } = useAuth();
  const navigate = useNavigate();
  const [detail, setDetail] = useState<Detail | null>(null);
  const [participants, setParticipants] = useState<Participant[]>([]);
  const [editing, setEditing] = useState(false);
  const [changing, setChanging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(() => new Date());

  const load = useCallback(async () => {
    try {
      const [d, p] = await Promise.all([
        api<Detail>(`/api/competitions/${id}`),
        api<Participant[]>(`/api/competitions/${id}/participants`),
      ]);
      setDetail(d);
      setParticipants(p);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load this competition.');
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  const phase: Phase = detail ? phaseOf(detail.competition) : 'finished';
  const deadline = detail
    ? phase === 'upcoming'
      ? detail.competition.starts_at
      : phase === 'provisional'
        ? detail.competition.settles_at
        : detail.competition.ends_at
    : null;
  const interval = tickInterval(deadline ? remaining(deadline, now) : 0);

  useEffect(() => {
    if (phase === 'finished' || phase === 'cancelled' || phase === 'draft') return;
    const timer = setInterval(() => setNow(new Date()), interval);
    return () => clearInterval(timer);
  }, [interval, phase]);

  async function act(path: string, confirmation?: string) {
    if (confirmation && !await ask(confirmation)) return;
    setError(null);
    setBusy(true);
    try {
      await api(`/api/competitions/${id}/${path}`, { method: 'POST' });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That did not work.');
    } finally {
      setBusy(false);
    }
  }

  async function destroy() {
    // Which TVs lose it, said before it goes (8.6).
    const onWalls = await wallWords('competition', Number(id));
    if (
      !await ask(
        `Delete this competition?\n\nThis cannot be undone. Nothing came of it, so there is no result to lose.${onWalls}`,
      )
    )
      return;
    setError(null);
    setBusy(true);
    try {
      await api(`/api/competitions/${id}`, { method: 'DELETE' });
      toast('Competition deleted');
      void navigate('/competitions');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not delete it.');
      setBusy(false);
    }
  }

  if (detail === null) {
    return (
      <>
        <PageHeader title="Competition" />
        {error ? (
          <p role="alert" className="text-danger">
            {error}
          </p>
        ) : (
          <Loading />
        )}
      </>
    );
  }

  const { competition, standings, you } = detail;
  const format = { unit: competition.unit, decimal_places: competition.decimal_places, unit_label: competition.unit_label };
  const unranked = participants.length - standings.length;

  return (
    <>
      <Breadcrumb parent={{ to: '/competitions', label: 'Competitions' }} here={competition.name} />
      <PageHeader
        title={competition.name}
        description={[competition.metric_name, repeatLine(competition), statusLine(competition, now)]
          .filter(Boolean)
          .join(' · ')}
        actions={
          // A draft or a cancelled contest has nothing a wall could show.
          can('integrations.manage') && phase !== 'draft' && phase !== 'cancelled' ? (
            <ShowOnTv kind="competition" id={competition.id} name={competition.name} />
          ) : undefined
        }
      />

      {/* A live contest is the worst place for stale numbers: somebody is
          watching the ranking change. A settled one is frozen, so its figures
          are final and there is nothing to be current about. */}
      {competition.closed_at === null && (
        <DataCurrency metricIds={[competition.metric_id]} className="mb-4" />
      )}

      {error && (
        <p
          role="alert"
          className="mb-4 rounded-md border border-danger px-3 py-2 text-sm text-danger"
        >
          {error}
        </p>
      )}

      <Can do="competitions.manage">
        <LifecycleBar
          phase={phase}
          competition={competition}
          busy={busy}
          onEdit={() => setEditing(true)}
          onChangeRunning={() => setChanging(true)}
          onPublish={() => void act('publish')}
          onUnpublish={() =>
            void act(
              'unpublish',
              phase === 'running'
                ? 'Pull this back to a draft?\n\nIt stops being visible to entrants while you fix it. Nothing is lost — no result has been frozen.'
                : 'Pull this back to a draft? Entrants will not see it until you publish it again.',
            )
          }
          onSettle={() =>
            void act(
              'close',
              'Freeze the result now, without waiting for late data?\n\nThis cannot be undone, and the winner will be announced.',
            )
          }
          onCancel={() =>
            void act(
              'cancel',
              'Cancel this competition?\n\nIt stops with no winner and no result is recorded. You can pull it back to a draft afterwards.',
            )
          }
          onDelete={() => void destroy()}
        />
      </Can>

      {competition.prize && (
        <p className="mb-4 flex items-center gap-2 text-content">
          <TrophyIcon className="size-5 text-content-muted" />
          {competition.prize}
        </p>
      )}

      {competition.head_to_head && standings.length === 2 ? (
        <HeadToHead
          standings={standings}
          format={format}
          people={competition.entity_type === 'user'}
          cancelled={phase === 'cancelled'}
        />
      ) : (
        <StandingsTable
          standings={standings}
          format={format}
          highlight={you?.entity_id ?? null}
          people={competition.entity_type === 'user'}
        />
      )}

      {/* Somebody left out of the table is owed an explanation. Silently omitting
          them is the hole `min_participation` opened by choosing "unranked" over
          "last" — the right call, but only if the page says so. */}
      {unranked > 0 && competition.min_participation !== null && (
        <p className="mt-3 text-sm text-content-muted">
          {unranked} {unranked === 1 ? 'entrant is' : 'entrants are'} not ranked —{' '}
          {unranked === 1 ? 'they recorded' : 'each recorded'} fewer than{' '}
          {competition.min_participation} data points, which is the minimum this
          competition counts.
        </p>
      )}

      {/* Pinned, and only once the viewer has dropped far enough down to have lost
          sight of themselves. Repeating row 2 directly under row 2 is clutter. */}
      {you && you.rank > 3 && (
        <div className="sticky bottom-4 mt-4 rounded-lg border border-brand bg-surface p-4 shadow-lg">
          <div className="flex items-baseline justify-between gap-4">
            <span className="text-sm text-content">
              <span className="mr-2 tabular-nums text-content-muted">{you.rank}</span>
              You
            </span>
            <span className="flex items-baseline gap-3">
              {you.gap_to_next && (
                <span className="text-xs text-content-muted">
                  <MetricValue value={you.gap_to_next} format={format} /> behind{' '}
                  {place(you.rank - 1)}
                </span>
              )}
              <MetricValue value={you.value} format={format} className="text-content" />
            </span>
          </div>
        </div>
      )}

      {(competition.repeat || competition.round_number > 1) && (
        <Rounds
          competition={competition}
          canManage={can('competitions.manage')}
          onChanged={() => void load()}
        />
      )}

      {/* **What changed while it ran, and why** (6.14) — to everybody who can
          see the contest, not only whoever manages it: a prize that moved or
          an end that slipped is the room's business. */}
      {(detail.changes ?? []).length > 0 && (
        <section className="mt-8" aria-labelledby="running-changes">
          <h2 id="running-changes" className="text-h2 text-content">
            Changed while running
          </h2>
          <ul className="mt-3 divide-y divide-edge rounded-lg border border-edge">
            {(detail.changes ?? []).map((change) => (
              <li key={`${change.at}-${change.what}`} className="px-4 py-3 text-sm">
                <p className="text-content">{change.what}</p>
                <p className="mt-0.5 text-content-muted">&ldquo;{change.note}&rdquo;</p>
                <p className="mt-1 text-xs text-content-subtle">
                  {change.who ?? 'Somebody'} ·{' '}
                  {dayAndTime(change.at)}
                </p>
              </li>
            ))}
          </ul>
        </section>
      )}

      {competition.rules_editable && can('competitions.manage') && (
        <section className="mt-8">
          <h2 className="text-h2 text-content">Entrants</h2>
          <p className="mt-1 text-sm text-content-muted">
            {competition.entrant_count < 2
              ? 'A competition needs at least two entrants before it can be published.'
              : 'Fixed once the contest starts — somebody joining halfway through has less time to win it. Use Edit to change who is in it.'}
          </p>
          <ul className="mt-3 divide-y divide-edge rounded-lg border border-edge">
            {participants.map((participant) => (
              <li key={participant.id} className="px-4 py-2.5 text-sm text-content">
                {competition.entity_type === 'user' ? (
                  <PersonLink id={participant.entity_id}>{participant.entity_name}</PersonLink>
                ) : (
                  participant.entity_name
                )}
              </li>
            ))}
            {participants.length === 0 && (
              <li className="px-4 py-3 text-sm text-content-muted">
                Nobody entered yet. Use Edit to choose who competes.
              </li>
            )}
          </ul>
        </section>
      )}

      {/* Where a manager already is when they ask whether this is on for a
          good number. Behind the same capability as the reporting tab, so an
          agent who may watch the contest does not get a panel that 403s. */}
      {/* Not for a cancelled contest, which will not finish (P3-10). */}
      {phase !== 'cancelled' && (
        <Can do="reporting.view">
          <div className="mt-8">
            {/* Not its name again: the page is already titled with it. */}
            <CompetitionReportCard competitionId={competition.id} heading="How it is going" />
          </div>
        </Can>
      )}


      {changing && (
        <RunningChanges
          contest={competition}
          entrantIds={participants.map((p) => p.entity_id)}
          onClose={() => setChanging(false)}
          onSaved={async (said) => {
            toast(said);
            setChanging(false);
            await load();
          }}
        />
      )}

      {editing && (
        <CompetitionForm
          competition={competition}
          onClose={() => setEditing(false)}
          onSaved={async () => {
            toast('Competition saved');
            setEditing(false);
            await load();
          }}
        />
      )}
    </>
  );
}

/**
 * Where this competition is in its life, and the ways out of it.
 *
 * The lifecycle used to be a red X icon beside a Publish button, which left two
 * questions unanswered: *can anyone see this yet*, and *how do I undo it*. Both
 * matter more than the space they cost. Publishing was effectively one-way, so a
 * contest with the wrong metric could only be cancelled — and it then sat in
 * Finished for good.
 *
 * **Words, not icons.** Icons are right for actions repeated down a list of rows.
 * A state transition happens once, changes what a room full of people can see,
 * and is worth reading before clicking.
 */
function LifecycleBar({
  phase,
  competition,
  busy,
  onEdit,
  onChangeRunning,
  onPublish,
  onUnpublish,
  onSettle,
  onCancel,
  onDelete,
}: {
  phase: Phase;
  competition: Competition;
  busy: boolean;
  onEdit: () => void;
  onChangeRunning: () => void;
  onPublish: () => void;
  onUnpublish: () => void;
  onSettle: () => void;
  onCancel: () => void;
  onDelete: () => void;
}) {
  const tooFew = competition.entrant_count < 2;

  return (
    <div className="mb-6 rounded-lg border border-edge bg-surface p-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <PhasePill phase={phase} />
          <p className="mt-2 text-sm text-content-muted">{phaseHelp(phase)}</p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {competition.rules_editable && <Secondary onClick={onEdit}>Edit</Secondary>}
          {competition.running_editable && (
            <Secondary onClick={onChangeRunning}>Change while running</Secondary>
          )}

          {phase === 'draft' && (
            <Primary onClick={onPublish} disabled={busy || tooFew}>
              Publish
            </Primary>
          )}
          {phase === 'provisional' && (
            <Primary onClick={onSettle} disabled={busy}>
              Settle now
            </Primary>
          )}

          {canUnpublish(phase) && (
            <Secondary onClick={onUnpublish} disabled={busy}>
              Back to draft
            </Secondary>
          )}
          {canCancel(phase) && (
            <Destructive onClick={onCancel} disabled={busy}>
              Cancel contest
            </Destructive>
          )}
          {canDelete(phase) && (
            <Destructive onClick={onDelete} disabled={busy}>
              Delete
            </Destructive>
          )}
        </div>
      </div>

      {phase === 'draft' && tooFew && (
        <p className="mt-3 border-t border-edge pt-3 text-sm text-warning">
          {competition.entrant_count === 0
            ? 'Choose at least two entrants before publishing.'
            : 'One more entrant and this can be published.'}
        </p>
      )}

      {phase === 'provisional' && (
        <p className="mt-3 border-t border-edge pt-3 text-sm text-content-muted">
          Waiting is the safer option: announcing a winner and then changing it is
          worse than a day&apos;s delay.
        </p>
      )}
    </div>
  );
}

function Primary({
  onClick,
  disabled,
  children,
}: {
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="rounded-md bg-brand px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
    >
      {children}
    </button>
  );
}

function Secondary({
  onClick,
  disabled,
  children,
}: {
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="rounded-md border border-edge px-3 py-2 text-sm text-content transition-colors hover:bg-surface-hover disabled:opacity-50"
    >
      {children}
    </button>
  );
}

/** Red on hover rather than always, so a row of actions is not a wall of alarm. */
function Destructive({
  onClick,
  disabled,
  children,
}: {
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      // Red before the hover, so it never reads as a form's Cancel (Q2-28).
      className="rounded-md border border-danger/50 px-3 py-2 text-sm text-danger transition-colors hover:bg-danger/10 disabled:opacity-50"
    >
      {children}
    </button>
  );
}

function StandingsTable({
  standings,
  format,
  highlight,
  people = false,
}: {
  /** Entrants are people, whose names open their profiles (9.3). */
  people?: boolean;
  standings: Standing[];
  format: { unit: string; decimal_places: number };
  highlight: number | null;
}) {
  if (standings.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-edge px-4 py-8 text-center text-content-muted">
        No entrants yet, so there is nothing to rank.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-edge">
      <table className="w-full text-sm">
        <thead className="bg-surface text-left text-content-muted">
          <tr>
            <th className="w-12 px-4 py-2 font-medium">#</th>
            <th className="px-4 py-2 font-medium">Entrant</th>
            <th className="px-4 py-2 text-right font-medium">Total</th>
            {/* Not "behind the leader". "$4,100 behind 6th" is something somebody
                can do today; "$45,300 behind 1st" is a reason to stop trying. */}
            <th className="px-4 py-2 text-right font-medium">Behind next</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-edge">
          {standings.map((row) => (
            <tr
              key={row.entity_id}
              className={row.entity_id === highlight ? 'bg-brand/5' : undefined}
            >
              <td className="px-4 py-2.5 tabular-nums text-content-muted">{row.rank}</td>
              <td className="px-4 py-2.5 text-content">
                {people ? <PersonLink id={row.entity_id}>{row.entity_name}</PersonLink> : row.entity_name}
              </td>
              <td className="px-4 py-2.5 text-right">
                <MetricValue value={row.value} format={format} className="text-content" />
              </td>
              <td className="px-4 py-2.5 text-right text-content-muted">
                {row.gap_to_next ? (
                  <MetricValue value={row.gap_to_next} format={format} />
                ) : (
                  '—'
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Two entrants, side by side.
 *
 * A ranked list of two is a table with one row of information in it. Two large
 * numbers facing each other is what the contest actually is, and it reads from
 * across a room — which matters, because this is the shape that goes on a wall.
 */
function HeadToHead({
  standings,
  format,
  people = false,
  cancelled = false,
}: {
  people?: boolean;
  /** Nobody is "behind" in a contest that was called off (P3-10), or in a tie (P4-3). */
  cancelled?: boolean;
  standings: Standing[];
  format: { unit: string; decimal_places: number };
}) {
  const [leader, chaser] = standings;
  // The caller only reaches this with exactly two rows, but the compiler cannot
  // know that from an array type — and a silent `!` here would be the one place
  // a shorter list rendered as blank panels instead of a table.
  if (!leader || !chaser) {
    return <StandingsTable standings={standings} format={format} highlight={null} />;
  }
  // **Level is level** (P4-3): at $0 each the page said "Test User is $0
  // behind" while the wall said "Level". Nobody leads a tie, and nothing at
  // all is "no scores yet".
  const level = Number(leader.value) === Number(chaser.value);
  const nothingYet = level && Number(leader.value) === 0;
  return (
    <div className="grid gap-4 sm:grid-cols-[1fr_auto_1fr]">
      <Side entrant={leader} format={format} leading={!level} people={people} />
      <div className="flex flex-col items-center justify-center text-content-muted">
        <span className="text-sm uppercase tracking-wide">vs</span>
        {level && (
          <span className="mt-1 text-sm text-content">{nothingYet ? 'No scores yet' : 'Level'}</span>
        )}
      </div>
      <Side
        entrant={chaser}
        format={format}
        leading={false}
        people={people}
        noBehind={cancelled || level}
      />
    </div>
  );
}

function Side({
  entrant,
  format,
  leading,
  people = false,
  noBehind = false,
}: {
  people?: boolean;
  /** Called off, or level: nobody is behind (P3-10, P4-3). */
  noBehind?: boolean;
  entrant: Standing;
  format: { unit: string; decimal_places: number };
  leading: boolean;
}) {
  return (
    <div
      className={`rounded-lg border p-6 text-center ${
        leading ? 'border-brand bg-brand/5' : 'border-edge bg-surface'
      }`}
    >
      {/* Faces, as the review asked (8.5): two people facing each other. */}
      <div className="mb-3 flex justify-center">
        <Avatar name={entrant.entity_name} digest={entrant.photo_digest ?? null} size="lg" />
      </div>
      <p className="truncate text-content-muted">
        {people ? <PersonLink id={entrant.entity_id}>{entrant.entity_name}</PersonLink> : entrant.entity_name}
      </p>
      <p className="mt-2 text-h1 text-content">
        <MetricValue value={entrant.value} format={format} />
      </p>
      {!leading && !noBehind && entrant.gap_to_next && (
        <p className="mt-2 text-sm text-content-muted">
          {entrant.entity_name} is <MetricValue value={entrant.gap_to_next} format={format} /> behind
        </p>
      )}
    </div>
  );
}

interface Round {
  id: number;
  round_number: number;
  starts_at: string;
  ends_at: string;
  state: string;
  winner: string | null;
}

/**
 * Every round of a repeating contest, and who won each.
 *
 * **Each round is its own contest**, so this is a list of links rather than one
 * long table: last week's winner stays last week's winner. Stopping keeps every
 * round already made — an upcoming one can still be cancelled on its own page.
 */
function Rounds({
  competition,
  canManage,
  onChanged,
}: {
  competition: Competition;
  canManage: boolean;
  onChanged: () => void;
}) {
  const [rounds, setRounds] = useState<Round[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Round[]>(`/api/competitions/${competition.id}/rounds`)
      .then(setRounds)
      .catch(() => setRounds([]));
  }, [competition.id, competition.repeat]);

  async function stop() {
    if (
      !await ask(
        'Stop repeating?\n\nNo more rounds are made. Rounds already made — including an upcoming one — are kept; cancel that one on its own page if it should not run.',
      )
    )
      return;
    setBusy(true);
    setError(null);
    try {
      await api(`/api/competitions/${competition.id}/repeat`, {
        method: 'PUT',
        body: JSON.stringify({ repeat: null }),
      });
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not change that.');
    } finally {
      setBusy(false);
    }
  }

  const when = (value: string) => dayName(value);

  return (
    <section className="mt-8">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 className="text-h2 text-content">Rounds</h2>
        {canManage && competition.repeat && (
          <button
            type="button"
            disabled={busy}
            onClick={() => void stop()}
            className="text-sm text-content-muted hover:text-danger disabled:opacity-60"
          >
            Stop repeating
          </button>
        )}
      </div>
      <p className="mt-1 text-sm text-content-muted">
        {competition.repeat
          ? `Runs ${REPEAT_LABEL[competition.repeat]}${
              competition.repeat_until
                ? `, with the last round starting by ${dayMonth(competition.repeat_until)}`
                : ''
            }. Each round is its own contest, copied from the one before — edit the upcoming round to change the ones after it.`
          : 'No longer repeating. These rounds were run.'}
      </p>
      {error && (
        <p role="alert" className="mt-2 text-sm text-danger">
          {error}
        </p>
      )}
      {rounds === null ? (
        <p className="mt-3 text-sm text-content-muted">Loading…</p>
      ) : (
        <ul className="mt-3 divide-y divide-edge rounded-lg border border-edge">
          {rounds.map((round) => (
            <li key={round.id}>
              <Link
                to={`/competitions/${round.id}`}
                className={`flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 text-sm transition-colors hover:bg-surface-hover ${
                  round.id === competition.id ? 'bg-surface-hover' : ''
                }`}
              >
                <span className="text-content">
                  Round {round.round_number}
                  <span className="ml-2 text-content-muted">
                    {when(round.starts_at)} – {when(round.ends_at)}
                  </span>
                </span>
                <span className="text-content-muted">
                  {round.winner ? (
                    <span className="inline-flex items-center gap-1 text-content">
                      <TrophyIcon className="size-4 text-content-muted" />
                      {round.winner}
                    </span>
                  ) : (
                    round.state
                  )}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

