import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { api } from '../api';
import { useAuth } from '../auth';
import LeaderboardTable, { type Entry } from '../components/LeaderboardTable';
import DataCurrency from '../components/DataCurrency';
import PageHeader from '../components/PageHeader';
import ShowOnTv from '../components/ShowOnTv';
import { BoardForm, VisibilityBadge, periodLabel, type Board } from './Leaderboards';
import WallPreview from '../components/wall/WallPreview';
import type { Slide } from '../components/wall/types';
import { toast } from '../toast';
import Loading from '../components/Loading';
import Breadcrumb from '../components/Breadcrumb';

interface Results {
  leaderboard: Board;
  period_label: string;
  period_start: string;
  period_end: string;
  entries: Entry[];
  viewer_entry: Entry | null;
  total_entrants: number;
}

export default function LeaderboardView() {
  const { id } = useParams();
  const { user } = useAuth();
  const [results, setResults] = useState<Results | null>(null);
  // The board as a wall draws it — podium, race or list, in its own look —
  // so the chosen layout is seen here and not only on a TV (QA-37).
  const [slide, setSlide] = useState<Slide | null>(null);
  const [editing, setEditing] = useState(false);
  const { can } = useAuth();
  const [anchor, setAnchor] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const query = anchor ? `?anchor=${anchor}` : '';
      setResults(await api<Results>(`/api/leaderboards/${id}/results${query}`));
      // Separate, and allowed to fail: the table is the page, the picture of
      // the wall is a bonus.
      api<Slide>(`/api/leaderboards/${id}/slide${query}`)
        .then(setSlide)
        .catch(() => setSlide(null));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load this board.');
    }
  }, [id, anchor]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error) {
    return (
      <>
        <PageHeader title="Leaderboard" />
        <p role="alert" className="rounded-md border border-danger px-3 py-2 text-sm text-danger">
          {error}
        </p>
        <Link to="/leaderboards" className="mt-4 inline-block text-sm text-brand hover:underline">
          Back to leaderboards
        </Link>
      </>
    );
  }

  if (!results) return <Loading />;

  const board = results.leaderboard;
  // A rolling window has no meaningful "previous page" to step through — it is
  // defined relative to today, so stepping back would produce a window with no
  // name anyone recognises.
  const steppable = !board.period_type.startsWith('rolling');

  function step(days: number) {
    const from = anchor ? new Date(anchor) : new Date(results!.period_start);
    from.setDate(from.getDate() + days);
    setAnchor(from.toISOString().slice(0, 10));
  }

  return (
    <>
      <Breadcrumb parent={{ to: '/leaderboards', label: 'Leaderboards' }} here={board.name} />
      <PageHeader
        title={board.name}
        description={`${board.metric_name} · ${
          board.entity_type === 'user'
            ? 'People ranked'
            : board.entity_type === 'team'
              ? 'Teams ranked'
              : 'Offices ranked'
        } · ${board.scope_team_name ?? board.scope_office_name ?? 'Whole organization'}`}
        actions={
          <div className="flex items-center gap-2">
            <VisibilityBadge visibility={board.visibility} />
            {can('leaderboards.manage') && (
              <button
                type="button"
                onClick={() => setEditing(true)}
                className="rounded-md border border-edge px-3 py-1.5 text-sm text-content hover:bg-surface-hover"
              >
                Edit
              </button>
            )}
            {can('integrations.manage') && board.visibility === 'org' && (
              <ShowOnTv kind="leaderboard" id={board.id} name={board.name} />
            )}
          </div>
        }
      />

      {slide && (
        <div className="mb-6 max-w-3xl">
          <WallPreview slide={slide} />
          <p className="mt-2 text-xs text-content-subtle">
            As a wall shows it. The table below has every row.
          </p>
        </div>
      )}

      {editing && (
        <BoardForm
          board={board as unknown as Board}
          onClose={() => setEditing(false)}
          onSaved={async () => {
            toast('Board saved');
            setEditing(false);
            await load();
          }}
        />
      )}

      {/* Directly under the title, because it qualifies every number below it.
          Silent unless there is something to say. */}
      <DataCurrency metricIds={[board.metric_id]} className="mb-4" />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        {/* A plain link, not a fetch-and-blob: the browser handles the
            download, the Content-Disposition filename is honoured, and the
            session cookie goes with it automatically. */}
        <a
          href={`/api/leaderboards/${id}/results.csv${anchor ? `?anchor=${anchor}` : ""}`}
          className="text-sm text-content-muted hover:text-content"
        >
          Export CSV
        </a>

        <div className="ml-auto flex items-center gap-2">
          {steppable && (
            <button
              onClick={() => step(-1)}
              aria-label="Previous period"
              className="rounded-md border border-edge px-2 py-1 text-sm text-content-muted transition-colors hover:bg-surface-hover hover:text-content"
            >
              ←
            </button>
          )}
          <span className="text-sm text-content">{results.period_label}</span>
          {steppable && (
            <>
              <button
                onClick={() => {
                  const from = new Date(results.period_end);
                  setAnchor(from.toISOString().slice(0, 10));
                }}
                aria-label="Next period"
                className="rounded-md border border-edge px-2 py-1 text-sm text-content-muted transition-colors hover:bg-surface-hover hover:text-content"
              >
                →
              </button>
              {anchor && (
                <button
                  onClick={() => setAnchor(null)}
                  className="rounded-md border border-edge px-2 py-1 text-xs text-content-muted transition-colors hover:bg-surface-hover hover:text-content"
                >
                  {periodLabel(board.period_type)}
                </button>
              )}
            </>
          )}
        </div>
      </div>

      <LeaderboardTable
        entries={results.entries}
        viewerEntry={results.viewer_entry}
        format={board}
        // A team board ranks teams, so "you" is your team's row rather than
        // your own — highlighting a user id against team ids would match
        // nothing, or worse, match the wrong team.
        // "You" is a different row per board kind. An office board is
        // highlighted by the server, which resolves the viewer's office through
        // their team — the client has no office id to compare against.
        viewerId={
          board.entity_type === 'user'
            ? (user?.id ?? null)
            : board.entity_type === 'team'
              ? (user?.team_id ?? null)
              : null
        }
        totalEntrants={results.total_entrants}
        people={board.entity_type === 'user'}
      />

      <p className="mt-3 text-xs text-content-subtle">
        Live. A correction or a late sync shows up here straight away.
      </p>
    </>
  );
}
