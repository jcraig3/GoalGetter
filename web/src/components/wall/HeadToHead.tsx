import MetricValue from '../MetricValue';
import { ringStyle } from '../ring';
import { FacePicture, MarkLabel, markColour } from './entryLook';
import { sessionImageUrl, type Entry, type ImageUrl, type Slide } from './types';

/**
 * A two-entrant contest on a wall, as the two sides facing each other (8.5).
 *
 * The contest's own page drew it this way and the wall drew a table with two
 * rows — one row of information, in the same type as "who came seventh". Two
 * faces and two big numbers is what a head-to-head is, and it reads from
 * across the room. The gap is said under whoever is behind.
 */
export default function HeadToHead({
  slide,
  imageUrl = sessionImageUrl,
  showValues = true,
}: {
  slide: Slide;
  imageUrl?: ImageUrl;
  showValues?: boolean;
}) {
  const [leader, chaser] = slide.entries;
  if (!leader || !chaser) return null;
  const format = {
    unit: slide.unit ?? 'count',
    decimal_places: slide.decimal_places,
    unit_label: slide.unit_label,
  };
  const gap = Math.abs(Number(leader.value) - Number(chaser.value));
  const tied = gap === 0;

  return (
    <div data-testid="head-to-head" className="grid grid-cols-[1fr_auto_1fr] items-stretch gap-10">
      <Side entry={leader} format={format} imageUrl={imageUrl} showValues={showValues} leading={!tied} />
      <span className="self-center text-wall-3xl font-semibold uppercase tracking-widest text-content-muted">vs</span>
      <Side entry={chaser} format={format} imageUrl={imageUrl} showValues={showValues} leading={false}>
        {showValues && !tied && (
          <p className="mt-4 text-wall-xl text-content-muted">
            <MetricValue value={String(gap)} format={format} /> behind
          </p>
        )}
      </Side>
      {tied && showValues && (
        <p className="col-span-3 text-center text-wall-2xl text-content-muted">Level</p>
      )}
    </div>
  );
}

function Side({
  entry,
  format,
  imageUrl,
  showValues,
  leading,
  children,
}: {
  entry: Entry;
  format: { unit: string; decimal_places: number; unit_label?: string | null };
  imageUrl: ImageUrl;
  showValues: boolean;
  leading: boolean;
  children?: React.ReactNode;
}) {
  return (
    <div
      className={`wall-panel flex flex-col items-center justify-center px-10 py-12 text-center ${
        leading ? 'ring-4 ring-gold/70' : ''
      }`}
    >
      {entry.photo_digest ? (
        <FacePicture
          entry={entry}
          src={imageUrl(entry.photo_digest)}
          className="size-56 rounded-full"
          style={ringStyle(entry.ring)}
        />
      ) : (
        <span
          aria-hidden="true"
          style={{ backgroundColor: markColour(entry), ...ringStyle(entry.ring) }}
          className="grid size-56 place-items-center rounded-full text-wall-4xl font-semibold text-white"
        >
          <MarkLabel entry={entry} />
        </span>
      )}
      <p className="mt-6 max-w-full truncate text-wall-3xl font-semibold text-content">{entry.entity_name}</p>
      {showValues && (
        <MetricValue
          value={entry.value}
          format={format}
          className="mt-3 text-wall-5xl font-bold tabular-nums text-content"
        />
      )}
      {children}
    </div>
  );
}
