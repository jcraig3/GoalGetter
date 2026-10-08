import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';

import { api } from '../api';
import { toast } from '../toast';
import { useOrgAppearance } from '../orgAppearance';
import { Can, useAuth } from '../auth';
import AppearanceFields from '../components/AppearanceFields';
import EmptyState from '../components/EmptyState';
import Field from '../components/Field';
import { periodMismatch } from './metricSuggest';
import IconButton from '../components/IconButton';
import {
  ArchiveIcon,
  PencilIcon,
  RestoreIcon,
  TrashIcon,
} from '../components/icons';
import MetricValue from '../components/MetricValue';
import Modal from '../components/Modal';
import PageHeader from '../components/PageHeader';
import { ArchiveTabs } from '../components/Tabs';
import { type Entry } from '../components/LeaderboardTable';
import { ask } from '../confirm';
import Loading from '../components/Loading';
import EditorPreview from '../components/wall/EditorPreview';
import { useOpenFromUrl } from '../urlIntent';
import { archiveQuestion, wallWords } from '../wallUse';

export interface Board {
  id: number;
  name: string;
  metric_id: number;
  metric_name: string;
  unit: string;
  decimal_places: number;
  direction: string;
  entity_type: string;
  scope_type: string;
  scope_team_id: number | null;
  scope_team_name: string | null;
  scope_office_id: number | null;
  scope_office_name: string | null;
  period_type: string;
  display_limit: number | null;
  /** Where the race layout draws its flag. */
  finish_line: string | null;
  visibility: string;
  is_tv_enabled: boolean;
  rank_method: string;
  /** Only what this board itself chose; absent keys inherit. */
  appearance: Record<string, unknown>;
  archived: boolean;
  can_edit: boolean;
}

interface Results {
  leaderboard: Board;
  period_label: string;
  entries: Entry[];
  viewer_entry: Entry | null;
  total_entrants: number;
}

interface Metric {
  id: number;
  name: string;
  unit?: string;
  decimal_places?: number;
  unit_label?: string | null;
  direction?: string;
}

interface Team {
  id: number;
  name: string;
}

interface Office {
  id: number;
  name: string;
}

/** The fields of a metric a wall formats with, for an editor's sample. */
export function pickFormat(metric?: {
  unit?: string;
  decimal_places?: number;
  unit_label?: string | null;
  direction?: string;
}) {
  return metric
    ? {
        unit: metric.unit,
        decimal_places: metric.decimal_places,
        unit_label: metric.unit_label,
        direction: metric.direction,
      }
    : {};
}

export const BOARD_PERIODS = [
  { value: 'rolling_7', label: 'Last 7 days' },
  { value: 'rolling_30', label: 'Last 30 days' },
  { value: 'day', label: 'Today' },
  { value: 'week', label: 'This week' },
  { value: 'month', label: 'This month' },
  { value: 'quarter', label: 'This quarter' },
  { value: 'year', label: 'This year' },
] as const;

export function periodLabel(value: string): string {
  return BOARD_PERIODS.find((p) => p.value === value)?.label ?? value;
}

export default function Leaderboards() {
  const [boards, setBoards] = useState<Board[] | null>(null);
  const [building, setBuilding] = useState(false);
  const [editing, setEditing] = useState<Board | null>(null);
  useOpenFromUrl('new', () => setBuilding(true));
  const [showArchived, setShowArchived] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      // Archiving a board used to be a one-way door: the Edit form offered it,
      // this list never asked for archived rows, and nothing could restore one —
      // so an archived board simply vanished. The API had `include_archived` and
      // `/restore` the whole time; the page just never used them.
      const all = await api<Board[]>(
        `/api/leaderboards?include_archived=${showArchived}`,
      );
      // A tab is its own list. `include_archived` means "both", which would show
      // live boards under Archived.
      setBoards(all.filter((b) => b.archived === showArchived));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load leaderboards.');
    }
  }, [showArchived]);

  async function setArchived(board: Board, archived: boolean) {
    setError(null);
    // Wall-aware, as delete is (P3-2): asked only when a TV would lose it.
    if (archived) {
      const question = await archiveQuestion('leaderboard', board.id, board.name);
      if (question && !(await ask(question, { confirmLabel: 'Archive' }))) return;
    }
    try {
      await api(
        `/api/leaderboards/${board.id}/${archived ? 'archive' : 'restore'}`,
        {
          method: 'POST',
        },
      );
      // Said, with the way back (P3-17).
      toast(
        archived ? `${board.name} archived` : `${board.name} restored`,
        undefined,
        archived ? { label: 'Undo', run: () => void setArchived(board, false) } : undefined,
      );
      await load();
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : `Could not ${archived ? 'archive' : 'restore'}.`,
      );
    }
  }

  async function remove(board: Board) {
    // Which TVs lose it, said before it goes (8.6).
    const onWalls = await wallWords('leaderboard', board.id);
    if (
      !await ask(
        `Delete "${board.name}" permanently?

This cannot be undone.${onWalls}`,
      )
    )
      return;
    setError(null);
    try {
      await api(`/api/leaderboards/${board.id}`, { method: 'DELETE' });
      toast('Board deleted');
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not delete.');
    }
  }

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <>
      <PageHeader
        title="Leaderboards"
        description="Who is ahead, for a metric over a period. Always live — updates as the numbers arrive."
        actions={
          <Can do="leaderboards.manage">
            <button
              onClick={() => {
                setEditing(null);
                setBuilding(true);
              }}
              className="rounded-md bg-brand px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover"
            >
              New board
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

      <ArchiveTabs showArchived={showArchived} onChange={setShowArchived} />

      {boards === null ? (
        <Loading />
      ) : boards.length === 0 ? (
        <EmptyState
          title={showArchived ? 'Nothing archived' : 'No leaderboards yet'}
          description={
            showArchived
              ? 'An archived board stops appearing anywhere — including on the TVs — and keeps its settings. Restore it and it picks up where it left off.'
              : 'A board is a saved question: which metric, over what window, among whom. Build one and it stays current on its own.'
          }
        />
      ) : (
        <div className="grid gap-4 [grid-template-columns:repeat(auto-fill,minmax(22rem,1fr))]">
          {boards.map((board) => (
            <BoardCard
              key={board.id}
              board={board}
              onEdit={() => {
                setBuilding(false);
                setEditing(board);
              }}
              onArchive={() => void setArchived(board, true)}
              onRestore={() => void setArchived(board, false)}
              onDelete={() => void remove(board)}
            />
          ))}
        </div>
      )}

      {(building || editing) && (
        <BoardForm
          board={editing}
          onClose={() => {
            setBuilding(false);
            setEditing(null);
          }}
          onSaved={async (saved) => {
            // With a way to it (8.2): a new board is somewhere to go next.
            toast(editing ? 'Board saved' : 'Board created', {
              href: `/leaderboards/${saved.id}`,
              label: 'View',
            });
            setBuilding(false);
            setEditing(null);
            await load();
          }}
        />
      )}
    </>
  );
}

/**
 * A board on the list, with its top three already filled in.
 *
 * A list of board *names* is a menu, not a dashboard. Fetching each board's
 * results costs one request per card, and there are a handful of boards — the
 * alternative is a page nobody learns anything from without clicking.
 */
function BoardCard({
  board,
  onEdit,
  onArchive,
  onRestore,
  onDelete,
}: {
  board: Board;
  onEdit: () => void;
  onArchive: () => void;
  onRestore: () => void;
  onDelete: () => void;
}) {
  const { user } = useAuth();
  const [results, setResults] = useState<Results | null>(null);

  useEffect(() => {
    api<Results>(`/api/leaderboards/${board.id}/results`)
      .then(setResults)
      // Silent: one board failing must not take the page with it.
      .catch(() => setResults(null));
  }, [board.id]);

  const top = results?.entries.slice(0, 3) ?? [];

  return (
    <article
      className={`flex flex-col rounded-lg border border-edge bg-surface p-5 ${
        board.archived ? 'border-dashed opacity-70' : ''
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link
            to={`/leaderboards/${board.id}`}
            className="truncate font-medium text-content hover:text-brand"
          >
            {board.name}
          </Link>
          <p className="truncate text-xs text-content-subtle">
            {board.metric_name} · {periodLabel(board.period_type)}
            {board.scope_team_name && ` · ${board.scope_team_name}`}
            {board.scope_office_name && ` · ${board.scope_office_name}`}
            {board.entity_type === 'team' && ' · Teams ranked'}
            {board.entity_type === 'office' && ' · Offices ranked'}
          </p>
        </div>
        <VisibilityBadge visibility={board.visibility} />
      </div>

      <div className="mt-4 flex-1">
        {results === null ? (
          <p className="text-xs text-content-subtle">Loading…</p>
        ) : top.length === 0 ? (
          <p className="text-xs text-content-subtle">
            Nothing recorded for {results.period_label.toLowerCase()}.
          </p>
        ) : (
          <ol className="space-y-1.5">
            {top.map((entry) => (
              <li
                key={entry.entity_id}
                className={`flex items-baseline gap-2 text-sm ${
                  entry.entity_id === user?.id ? 'font-medium text-content' : ''
                }`}
              >
                <span
                  className={`w-4 shrink-0 tabular-nums ${
                    entry.rank === 1
                      ? 'text-gold'
                      : entry.rank === 2
                        ? 'text-silver'
                        : entry.rank === 3
                          ? 'text-bronze'
                          : 'text-content-subtle'
                  }`}
                >
                  {entry.rank}
                </span>
                <span className="min-w-0 flex-1 truncate text-content">
                  {entry.entity_name}
                </span>
                <MetricValue
                  value={entry.value}
                  format={board}
                  className="shrink-0 text-content-muted"
                />
              </li>
            ))}
          </ol>
        )}
      </div>

      <div className="mt-4 flex items-center gap-2 border-t border-edge pt-3">
        <Link
          to={`/leaderboards/${board.id}`}
          className="text-sm text-brand hover:underline"
        >
          View board
        </Link>
        {board.can_edit && (
          <span className="ml-auto flex items-center gap-1">
            {board.archived ? (
              // An archived board is out of the way, not being edited. Restoring
              // is the way back; delete stays for the ones archived by mistake.
              <>
                <IconButton
                  label="Restore"
                  icon={<RestoreIcon className="size-4" />}
                  onClick={onRestore}
                />
                <IconButton
                  label="Delete"
                  icon={<TrashIcon className="size-4" />}
                  danger
                  onClick={onDelete}
                />
              </>
            ) : (
              <>
                <IconButton
                  label="Edit"
                  icon={<PencilIcon className="size-4" />}
                  onClick={onEdit}
                />
                <IconButton
                  label="Archive"
                  icon={<ArchiveIcon className="size-4" />}
                  onClick={onArchive}
                />
              </>
            )}
          </span>
        )}
      </div>
    </article>
  );
}

export function VisibilityBadge({ visibility }: { visibility: string }) {
  const style =
    visibility === 'org'
      ? 'bg-success/15 text-success'
      : visibility === 'team'
        ? 'bg-brand-subtle text-content-muted'
        : 'bg-surface-raised text-content-subtle';
  const label =
    visibility === 'org'
      ? 'Everyone'
      : visibility === 'team'
        ? 'Team'
        : 'Private';
  return (
    <span
      className={`shrink-0 rounded-full px-2 py-0.5 text-xs ${style}`}
      title={
        visibility === 'org'
          ? 'Everyone in the organization can see this board, including agents'
          : visibility === 'team'
            ? 'Only the team it covers'
            : 'Only you and admins'
      }
    >
      {label}
    </span>
  );
}

export function BoardForm({
  board,
  onClose,
  onSaved,
}: {
  board: Board | null;
  onClose: () => void;
  onSaved: (saved: { id: number }) => Promise<void>;
}) {
  const { user, can } = useAuth();
  const isEdit = board !== null;
  const isAdmin = can('org.settings.edit');

  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);
  const [offices, setOffices] = useState<Office[]>([]);

  const [name, setName] = useState(board?.name ?? '');
  const [metricId, setMetricId] = useState(String(board?.metric_id ?? ''));
  const [entityType, setEntityType] = useState(board?.entity_type ?? 'user');
  const [scopeType, setScopeType] = useState(
    board?.scope_type ?? 'organization',
  );
  const [scopeTeamId, setScopeTeamId] = useState(
    String(board?.scope_team_id ?? user?.team_id ?? ''),
  );
  const [scopeOfficeId, setScopeOfficeId] = useState(
    String(board?.scope_office_id ?? ''),
  );
  const [periodType, setPeriodType] = useState(
    board?.period_type ?? 'rolling_30',
  );
  const [displayLimit, setDisplayLimit] = useState(
    String(board?.display_limit ?? 10),
  );
  const [finishLine, setFinishLine] = useState(
    board?.finish_line ? String(Number(board.finish_line)) : '',
  );
  // A manager cannot publish organization-wide, so the default has to be one
  // they can actually save — offering "Everyone" and rejecting it on submit
  // would be a form that lies about what it accepts.
  const [visibility, setVisibility] = useState(
    board?.visibility ?? (isAdmin ? 'org' : 'team'),
  );
  const [rankMethod, setRankMethod] = useState(board?.rank_method ?? 'rank');
  const [onTv, setOnTv] = useState(board?.is_tv_enabled ?? false);
  const [appearance, setAppearance] = useState<Record<string, unknown>>(
    board?.appearance ?? {},
  );
  const inherited = useOrgAppearance();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  //: Whether the chosen metric already covers a period of its own, and it is not
  //: this board's. See `periodMismatch`.
  const mismatch = periodMismatch(
    metrics.find((m) => String(m.id) === metricId)?.name ?? '',
    periodType,
  );

  useEffect(() => {
    Promise.all([
      api<Metric[]>('/api/metrics'),
      api<Team[]>('/api/teams'),
      api<Office[]>('/api/offices'),
    ])
      .then(([m, t, o]) => {
        setMetrics(m);
        setTeams(t);
        setOffices(o);
        setMetricId((v) => v || String(m[0]?.id ?? ''));
        setScopeOfficeId((v) => v || String(o[0]?.id ?? ''));
      })
      .catch((e) =>
        setError(e instanceof Error ? e.message : 'Could not load options.'),
      );
  }, []);

  // "Visible to the team" needs a team to mean, so the two move together
  // rather than letting the server refuse the pair.
  useEffect(() => {
    if (scopeType === 'organization' && visibility === 'team')
      setVisibility('org');
    if (scopeType === 'team' && visibility === 'org' && !isAdmin)
      setVisibility('team');
  }, [scopeType, visibility, isAdmin]);

  // A wall screen has no audience control, so only an org-visible board can go
  // on one. Clearing the flag when visibility narrows keeps the form from
  // submitting a combination the server refuses.
  useEffect(() => {
    if (visibility !== 'org') setOnTv(false);
  }, [visibility]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    // Enter in a field submits even with the button disabled; say it here,
    // as the app says everything else (Q2-30).
    if (!name.trim()) {
      setError('Give the board a name.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const body = {
        name,
        metric_id: Number(metricId),
        entity_type: entityType,
        scope_type: scopeType,
        scope_team_id: scopeType === 'team' ? Number(scopeTeamId) : null,
        scope_office_id: scopeType === 'office' ? Number(scopeOfficeId) : null,
        period_type: periodType,
        display_limit: displayLimit ? Number(displayLimit) : null,
        finish_line: finishLine.trim() === '' ? null : finishLine.trim(),
        visibility,
        rank_method: rankMethod,
        is_tv_enabled: onTv,
        appearance,
      };
      const saved = await api<{ id: number }>(
        isEdit ? `/api/leaderboards/${board.id}` : '/api/leaderboards',
        {
          method: isEdit ? 'PATCH' : 'POST',
          body: JSON.stringify(body),
        },
      );
      await onSaved(saved);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save the board.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title={isEdit ? 'Edit board' : 'New leaderboard'}
      description="Always live — it updates as the numbers arrive."
      onClose={onClose}
      wide
      side={
        <EditorPreview
          kind="leaderboard"
          title={name || metrics.find((m) => String(m.id) === metricId)?.name}
          chosen={appearance}
          inherited={inherited}
          // The sample follows the form: its unit, people or teams, period,
          // rows and finish line (7.4, Q2-3).
          sample={{
            ...pickFormat(metrics.find((m) => String(m.id) === metricId)),
            entity_type: entityType,
            period_label: BOARD_PERIODS.find((p) => p.value === periodType)?.label,
            rows: Number(displayLimit) > 0 ? Number(displayLimit) : undefined,
            finish_line: finishLine || null,
          }}
          // The form as it would be saved, drawn with real standings (8.7).
          real={
            metricId
              ? {
                  path: '/api/leaderboards/draft-slide',
                  body: {
                    name: name || 'Board',
                    metric_id: Number(metricId),
                    entity_type: entityType,
                    scope_type: scopeType,
                    scope_team_id: scopeType === 'team' ? Number(scopeTeamId) : null,
                    scope_office_id: scopeType === 'office' ? Number(scopeOfficeId) : null,
                    period_type: periodType,
                    display_limit: displayLimit ? Number(displayLimit) : null,
                    finish_line: finishLine.trim() === '' ? null : finishLine.trim(),
                    visibility,
                    rank_method: rankMethod,
                    is_tv_enabled: false,
                    appearance,
                  },
                }
              : null
          }
        />
      }
    >
      {/* The app's own messages, not the browser's bubble (Q2-30). */}
      <form onSubmit={submit} noValidate className="space-y-4">
        <Field label="Name" value={name} onChange={setName} maxLength={120} />

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-1 2xl:grid-cols-2">
          <Select
            label="Metric"
            value={metricId}
            onChange={setMetricId}
            options={metrics.map((m) => ({
              value: String(m.id),
              label: m.name,
            }))}
          />
          <Select
            label="Period"
            value={periodType}
            onChange={setPeriodType}
            options={BOARD_PERIODS.map((p) => ({
              value: p.value,
              label: p.label,
            }))}
            hint={
              periodType.startsWith('rolling')
                ? 'Always populated. A calendar board resets to near-empty on the 1st.'
                : undefined
            }
          />
        </div>

        {/* **The trap a pre-aggregated source sets.** Such a view carries the
            period in the column, so metrics built from it carry it in the name.
            Put "Amount This Month" on a weekly board and it shows a month of
            revenue under a weekly heading — every number wrong, every number
            plausible, and nothing downstream able to tell.

            A warning rather than a block: somebody may want exactly that, and a
            product that forbids what it cannot understand is worse than one that
            asks. */}
        {mismatch && (
          <p className="mt-4 rounded-md border border-warning px-3 py-2 text-sm text-warning">
            {mismatch}
          </p>
        )}

        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-1 2xl:grid-cols-2">
          <Select
            label="Rank"
            value={entityType}
            onChange={setEntityType}
            options={[
              { value: 'user', label: 'People' },
              { value: 'team', label: 'Teams' },
              { value: 'office', label: 'Offices' },
            ]}
          />
          <Select
            label="Among"
            value={scopeType}
            onChange={setScopeType}
            options={[
              { value: 'organization', label: 'The whole organization' },
              { value: 'team', label: 'One team' },
              // Scoping to an office is a cross-team decision, so it is only
              // offered to the people who can actually save it.
              ...(isAdmin ? [{ value: 'office', label: 'One office' }] : []),
            ]}
          />
          {scopeType === 'team' && (
            <Select
              label="Team"
              value={scopeTeamId}
              onChange={setScopeTeamId}
              options={teams.map((t) => ({
                value: String(t.id),
                label: t.name,
              }))}
            />
          )}
          {scopeType === 'office' && (
            <Select
              label="Office"
              value={scopeOfficeId}
              onChange={setScopeOfficeId}
              options={offices.map((o) => ({
                value: String(o.id),
                label: o.name,
              }))}
            />
          )}
          <Field
            label="Show top"
            value={displayLimit}
            onChange={setDisplayLimit}
            numeric={{ decimals: 0, min: 1, max: 500 }}
            hint="Everyone still counts; this only limits what is drawn."
          />
          <Field
            label="Finish line"
            value={finishLine}
            onChange={setFinishLine}
            numeric={{ decimals: 2, min: 0 }}
            required={false}
            hint="Optional. Where the race layout draws the flag — reach it and you have finished. Without one, the race is measured against whoever is leading."
          />
        </div>

        <div className="grid gap-4 border-t border-edge pt-4">
          <Select
            label="Who can see it"
            value={visibility}
            onChange={setVisibility}
            options={[
              ...(isAdmin
                ? [{ value: 'org', label: 'Everyone in the organization' }]
                : []),
              ...(scopeType === 'team'
                ? [{ value: 'team', label: 'The team' }]
                : []),
              { value: 'private', label: 'Only me' },
            ]}
          />
          <Select
            label="Ties"
            value={rankMethod}
            onChange={setRankMethod}
            options={[
              { value: 'rank', label: '1, 2, 2, 4 — nobody is third' },
              { value: 'dense_rank', label: '1, 2, 2, 3' },
            ]}
          />
        </div>

        {/* **One way onto a TV, and it is a channel.** A "Show on wall
            displays" box sat here and promised the board would appear on
            every screen — but nothing on a wall read it; a TV shows exactly
            its channel's slides (review §7). The box is gone, and this says
            where the real switch is. */}
        {visibility === 'org' && (
          <p className="text-xs text-content-subtle">
            To show it on a TV, add it as a slide to a channel under{' '}
            <Link to="/channels" className="text-brand hover:underline">
              TVs &amp; Channels
            </Link>
            . Only boards everyone can see can go on a wall — anyone walking past
            a screen can read it.
          </p>
        )}

        {visibility === 'org' && (
          // Said plainly, because it is the one place this product shows a
          // person data about colleagues they cannot otherwise see.
          <p className="rounded-md border border-warning px-3 py-2 text-xs text-warning">
            Everyone in the organization will see every name and score on this
            board, including agents. Their own detail pages stay private.
          </p>
        )}

        <div className="border-t border-edge pt-4">
          <AppearanceFields
            kind="leaderboard"
            chosen={appearance}
            inherited={inherited}
            onChange={setAppearance}
            previewBeside
          />
        </div>

        {error && (
          <p
            role="alert"
            className="rounded-md border border-danger px-3 py-2 text-sm text-danger"
          >
            {error}
          </p>
        )}

        <div className="flex items-center gap-3 pt-2">
          <button
            type="submit"
            disabled={
              busy ||
              !name ||
              !metricId ||
              (scopeType === 'team' && !scopeTeamId) ||
              (scopeType === 'office' && !scopeOfficeId)
            }
            className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
          >
            {busy ? 'Saving…' : isEdit ? 'Save changes' : 'Create board'}
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

export function Select({
  label,
  value,
  onChange,
  options,
  hint,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  hint?: string;
}) {
  const id = label.toLowerCase().replace(/\s+/g, '-');
  return (
    <div>
      <label htmlFor={id} className="block text-sm text-content-muted">
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        aria-describedby={hint ? `${id}-hint` : undefined}
        className="mt-1 w-full rounded-md border border-edge bg-bg px-3 py-2 text-content outline-none focus:border-brand"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
      {hint && (
        <p id={`${id}-hint`} className="mt-1 text-xs text-content-muted">
          {hint}
        </p>
      )}
    </div>
  );
}
