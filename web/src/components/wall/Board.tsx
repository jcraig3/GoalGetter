import MetricValue from '../MetricValue';
import NobodyYet, { nobodyYet } from './NobodyYet';
import { PageDots, usePages } from './paging';
import { hasRing, ringStyle } from '../ring';
import { sessionImageUrl, type ImageUrl, type Slide } from './types';
import { FacePicture, MarkLabel, isTeamRow, markColour } from './entryLook';
import { useWallShape } from './WallStage';

/**
 * A ranked list, at wall size.
 *
 * **Two sizes, one component.** A comparison puts the same list in a quarter
 * of the screen, and a second renderer for the small version would drift —
 * one would get a new medal colour and the other would not, and the panels on
 * a wall would stop matching the board in the slide before them.
 *
 * The sizes are explicit class maps rather than anything clever, because
 * "wall-4xl type in a 440-pixel column" is the failure this exists to prevent and it
 * is only visible when the two are written down next to each other.
 */
export type BoardSize = 'full' | 'panel';

const RANK: Record<BoardSize, string> = {
  full: 'w-16 text-wall-4xl',
  panel: 'w-8 text-wall-2xl',
};

const FACE: Record<BoardSize, string> = {
  full: 'size-14',
  panel: 'size-9',
};

/** A team badge's letters, to fit the face-sized circle it sits in. */
const MARK_TEXT: Record<BoardSize, string> = {
  full: 'text-xl',
  panel: 'text-xs',
};

const NAME: Record<BoardSize, string> = {
  full: 'text-wall-4xl',
  panel: 'text-wall-2xl',
};

const ROW: Record<BoardSize, string> = {
  full: 'gap-6 px-8 py-5',
  panel: 'gap-3 px-4 py-3',
};

const GAP: Record<BoardSize, string> = {
  full: 'space-y-3',
  panel: 'space-y-2',
};

/**
 * **The top three, larger, on a portrait wall** (6.11). A screen on its side
 * has height to spare and no width to put it in, so the extra room goes to
 * the people a room glances up to find: a bigger face, a bigger name, a
 * bigger figure. Everybody else keeps the ordinary row, so the list still
 * reads as one list.
 */
const HERO = {
  row: 'gap-6 px-8 py-7',
  face: 'size-24',
  mark: 'text-3xl',
  text: 'text-wall-5xl',
  rank: 'w-16 text-wall-5xl',
};

export default function Board({
  slide,
  imageUrl = sessionImageUrl,
  size = 'full',
  rows = 10,
  showValues = true,
  paged = false,
}: {
  slide: Pick<Slide, 'entries' | 'unit' | 'decimal_places' | 'unit_label'> &
    Partial<Pick<Slide, 'previous' | 'direction'>>;
  imageUrl?: ImageUrl;
  size?: BoardSize;
  /** How many to draw. The board decides who is on it; this decides how many
   *  fit on one television. */
  rows?: number;
  /** Positions only, for a room where the figures are commercially sensitive
   *  and the ranking is the motivating part. */
  showValues?: boolean;
  /** Show as many rows as fit and turn the page for the rest, rather than
   *  running off the bottom. Only for a board that is the whole slide. */
  paged?: boolean;
}) {
  const { listRef, shown, page, pages, listStyle } = usePages(
    slide.entries.slice(0, rows),
    paged,
  );
  const portrait = useWallShape() === 'portrait' && size === 'full' && paged;
  // The list said nothing when empty — a blank TV on the first of the month
  // (P3-1). Only for a board that is the whole slide; a comparison panel
  // keeps its own small space.
  if (size === 'full' && nobodyYet(slide)) return <NobodyYet slide={slide} />;
  return (
    <>
      <ol ref={listRef} style={listStyle} className={portrait ? 'space-y-4' : GAP[size]}>
        {shown.map((entry) => {
          const hero = portrait && entry.rank <= 3;
          return (
          <li
            key={entry.entity_id}
            data-hero={hero ? '' : undefined}
            className={`wall-panel flex items-center ${hero ? HERO.row : ROW[size]}`}
          >
            <span
              className={`shrink-0 font-semibold tabular-nums ${hero ? HERO.rank : RANK[size]} ${
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
            {/* Larger than in the app: this is read from across a room. */}
            {entry.photo_digest ? (
              <FacePicture
                entry={entry}
                src={imageUrl(entry.photo_digest)}
                style={ringStyle(entry.ring, '0.18em', '0.12em')}
                className={`shrink-0 rounded-full ${hero ? HERO.face : FACE[size]}`}
              />
            ) : isTeamRow(entry) ? (
              // **A team is known by its colour** (6.7): a badge with its short
              // name, where a person with no photograph shows nothing.
              <span
                aria-hidden="true"
                style={{ backgroundColor: markColour(entry) }}
                className={`grid shrink-0 place-items-center rounded-full font-semibold leading-none text-white ${
                  hero ? `${HERO.face} ${HERO.mark}` : `${FACE[size]} ${MARK_TEXT[size]}`
                }`}
              >
                <MarkLabel entry={entry} />
              </span>
            ) : (
              // **No face to go round, so the ring is drawn on its own.** This
              // layout shows faces only when there is a photograph, and most
              // people have none — without this, a ring would be invisible on
              // the most common screen for the majority of people who bought
              // one. Small, beside the name, and a ring rather than a dot so it
              // reads as the same thing.
              hasRing(entry.ring) && (
                <span
                  aria-hidden="true"
                  style={{ borderColor: entry.ring }}
                  className="size-[0.7em] shrink-0 rounded-full border-[0.16em]"
                />
              )
            )}
            <span
              className={`min-w-0 flex-1 truncate text-content ${hero ? HERO.text : NAME[size]}`}
            >
              {entry.entity_name}
            </span>
            {showValues && (
              <MetricValue
                value={entry.value}
                format={{
                  unit: slide.unit ?? 'count',
                  decimal_places: slide.decimal_places,
                  unit_label: slide.unit_label,
                }}
                className={`shrink-0 font-semibold tabular-nums text-content ${hero ? HERO.text : NAME[size]}`}
              />
            )}
          </li>
          );
        })}
      </ol>
      <PageDots page={page} pages={pages} />
    </>
  );
}
