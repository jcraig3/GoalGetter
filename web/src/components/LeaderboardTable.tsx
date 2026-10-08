import Avatar from './Avatar';
import MetricValue, { type MetricFormat } from './MetricValue';
import PersonLink from './PersonLink';

export interface Entry {
  rank: number;
  entity_id: number;
  entity_name: string;
  photo_digest?: string | null;
  ring?: string | null;
  team_name: string | null;
  value: string;
  movement: number | null;
}

/** Rank colour and label for the podium. Ranks below 3 get nothing. */
const PODIUM: Record<number, { tone: string; label: string }> = {
  1: { tone: 'text-gold', label: '1st' },
  2: { tone: 'text-silver', label: '2nd' },
  3: { tone: 'text-bronze', label: '3rd' },
};

/**
 * Places gained since the previous period.
 *
 * `null` is a new entrant, which is not the same as "did not move" — showing a
 * dash for both would claim they held their position when they did not have
 * one.
 */
function Movement({ places }: { places: number | null }) {
  if (places === null) {
    return <span className="text-xs text-content-subtle">new</span>;
  }
  if (places === 0) {
    // A dash rather than "0": the eye should skip everyone who stayed put, so
    // the ones who moved are what stands out.
    return (
      <span className="text-xs text-content-subtle" title="No change">
        –
      </span>
    );
  }

  const up = places > 0;
  return (
    <span
      className={`text-xs tabular-nums ${up ? 'text-success' : 'text-danger'}`}
      title={`${up ? 'Up' : 'Down'} ${Math.abs(places)} ${
        Math.abs(places) === 1 ? 'place' : 'places'
      } since last period`}
    >
      {/* A glyph plus the number, not a coloured number alone — colour is the
          only difference between up and down otherwise, and roughly one man in
          twelve cannot rely on it. */}
      {up ? '▲' : '▼'} {Math.abs(places)}
    </span>
  );
}

function Row({
  entry,
  format,
  isViewer,
  pinned,
  people = false,
}: {
  entry: Entry;
  format: MetricFormat;
  isViewer: boolean;
  pinned?: boolean;
  /** A board of people: each name opens their profile (9.3). */
  people?: boolean;
}) {
  const podium = PODIUM[entry.rank];

  return (
    <tr
      className={`border-b border-edge last:border-0 ${
        isViewer ? 'bg-brand-subtle' : ''
      } ${pinned ? 'border-t-2 border-t-edge' : ''}`}
    >
      <td className="px-4 py-3">
        <span
          className={`tabular-nums font-medium ${podium?.tone ?? 'text-content-subtle'}`}
          aria-label={podium ? podium.label : `Rank ${entry.rank}`}
        >
          {entry.rank}
        </span>
      </td>
      <td className="px-4 py-3">
        <div className="flex items-center gap-3">
          <Avatar
            name={entry.entity_name}
            digest={entry.photo_digest}
            ring={entry.ring}
          />
          <div className="min-w-0">
            <p className="truncate text-content">
              {people ? <PersonLink id={entry.entity_id}>{entry.entity_name}</PersonLink> : entry.entity_name}
              {isViewer && (
                <span className="ml-2 text-xs text-content-muted">
                  {/* On a team board the row is a team (Q2-16). */}
                  {entry.team_name === entry.entity_name ? 'your team' : 'you'}
                </span>
              )}
            </p>
            {/* Not the team's own name again under itself (Q2-16). */}
            {entry.team_name && entry.team_name !== entry.entity_name && (
              <p className="truncate text-xs text-content-subtle">
                {entry.team_name}
              </p>
            )}
          </div>
        </div>
      </td>
      <td className="px-4 py-3 text-right">
        <MetricValue value={entry.value} format={format} className="text-content" />
      </td>
      <td className="px-4 py-3 text-right">
        <Movement places={entry.movement} />
      </td>
    </tr>
  );
}

/**
 * The board itself.
 *
 * The most looked-at surface in the product, so the things it must never do:
 * hide where the viewer is, colour-code without a shape, or render an empty
 * board as though something broke.
 */
export default function LeaderboardTable({
  entries,
  viewerEntry,
  format,
  viewerId,
  totalEntrants,
  people = false,
}: {
  entries: Entry[];
  viewerEntry: Entry | null;
  format: MetricFormat;
  viewerId: number | null;
  totalEntrants: number;
  /** A board of people, whose names open their profiles (9.3). */
  people?: boolean;
}) {
  if (entries.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-edge px-6 py-12 text-center text-sm text-content-muted">
        Nothing recorded for this period yet.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-edge bg-surface">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-edge text-left text-caption uppercase tracking-wide text-content-subtle">
            <th className="px-4 py-3 font-medium">#</th>
            <th className="px-4 py-3 font-medium">Name</th>
            <th className="px-4 py-3 text-right font-medium">Score</th>
            <th className="px-4 py-3 text-right font-medium">Move</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((entry) => (
            <Row
              key={entry.entity_id}
              entry={entry}
              format={format}
              isViewer={entry.entity_id === viewerId}
              people={people}
            />
          ))}

          {/* Pinned below the cut, with a rule above it. Being 14th on a top-10
              board is exactly when a person most wants to know where they are,
              and scrolling a truncated board to find out is not an option. */}
          {viewerEntry && (
            <Row
              entry={viewerEntry}
              format={format}
              isViewer
              pinned
              people={people}
              key={`viewer-${viewerEntry.entity_id}`}
            />
          )}
        </tbody>
      </table>

      {totalEntrants > entries.length && (
        <p className="border-t border-edge px-4 py-2 text-xs text-content-subtle">
          Showing {entries.length} of {totalEntrants}.
        </p>
      )}
    </div>
  );
}
