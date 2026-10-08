import MetricValue from '../MetricValue';
import { ringStyle } from '../ring';
import { sessionImageUrl, type ImageUrl, type Slide } from './types';
import { PageDots, usePages } from './paging';
import { FacePicture, MarkLabel, markColour } from './entryLook';
import { useWallShape, type WallShape } from './WallStage';
import NobodyYet, { nobodyYet } from './NobodyYet';

/**
 * The top three on steps, and everybody else underneath.
 *
 * **A different question from the list, not a prettier version of it.** A ranked
 * list answers "where am I?" — you scan for your own name. A podium answers "who
 * won?", and a room glancing up for two seconds gets that without reading
 * anything. Both are worth having, which is why this is a layout rather than a
 * replacement.
 *
 * **Second, first, third — left to right.** That is where they stand on a real
 * podium, and putting first in the middle is what makes the shape readable at
 * distance: the tallest block is central and the eye lands on it before it has
 * read a single name or number.
 */
export default function Podium({
  slide,
  imageUrl = sessionImageUrl,
  rows = 10,
  showValues = true,
}: {
  slide: Slide;
  imageUrl?: ImageUrl;
  /** How many in total, steps included. Three or fewer is the podium alone. */
  rows?: number;
  showValues?: boolean;
}) {
  const [first, second, third] = slide.entries;
  const shape = useWallShape();
  const look = SHAPES[shape];
  // The steps are the first three, so the list underneath is whatever the row
  // count has left over. A count of 3 draws a podium and nothing below it,
  // which is the point of choosing 3.
  const {
    listRef,
    shown: rest,
    page,
    pages,
    listStyle,
  } = usePages(slide.entries.slice(3, Math.max(rows, 3)));

  // **Ordered for the eye, not for the data.** Rendering in rank order and
  // re-ordering with CSS would put the tab order and a screen reader's reading
  // order in the visual order too, which is wrong: first place is first.
  //
  // A board with one or two entrants is a real thing on a small team, so the
  // missing steps are dropped rather than left as holes.
  const steps = [second, first, third].filter(
    (entry): entry is Slide['entries'][number] => entry !== undefined,
  );

  if (nobodyYet(slide) || !first) {
    return <NobodyYet slide={slide} />;
  }

  return (
    <div>
      <div className="flex items-end justify-center gap-6">
        {steps.map((entry) => (
          <Step
            key={entry.entity_id}
            entry={entry}
            slide={slide}
            imageUrl={imageUrl}
            showValues={showValues}
            shape={shape}
          />
        ))}
      </div>

      {rest.length > 0 && (
        // Smaller and quieter: these are the people who did not make the
        // podium, and giving them the same weight as the winner would undo the
        // reason for choosing this layout.
        <ol ref={listRef} style={listStyle} className={look.list}>
          {rest.map((entry) => (
            <li
              key={entry.entity_id}
              className={`wall-panel flex items-center gap-5 ${look.row}`}
            >
              <span className={`w-12 shrink-0 tabular-nums text-content-subtle ${look.rowText}`}>
                {entry.rank}
              </span>
              <span className={`min-w-0 flex-1 truncate text-content ${look.rowText}`}>
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
                  className={`shrink-0 tabular-nums text-content-muted ${look.rowText}`}
                />
              )}
            </li>
          ))}
        </ol>
      )}
      <PageDots page={page} pages={pages} />
    </div>
  );
}

/**
 * Sizes, by the shape of the screen.
 *
 * **Portrait is a taller podium, not a narrower one** (6.11). A screen on its
 * side has the width for three steps and nothing more, and twice the height —
 * so the faces, names and steps grow, and the rest of the list underneath is
 * set large enough to fill the screen rather than huddle in its middle.
 */
const SHAPES: Record<
  WallShape,
  {
    step: string;
    face: string;
    mark: string;
    text: string;
    heights: Record<number, string>;
    rank: string;
    list: string;
    row: string;
    rowText: string;
  }
> = {
  landscape: {
    step: 'w-64',
    face: 'size-24',
    mark: 'text-wall-3xl',
    text: 'text-wall-3xl',
    // First is tallest by enough to read at distance.
    heights: { 1: '11rem', 2: '8rem', 3: '6rem' },
    rank: 'text-wall-5xl',
    list: 'mt-10 space-y-2',
    row: 'px-6 py-3',
    rowText: 'text-wall-2xl',
  },
  portrait: {
    step: 'w-72',
    face: 'size-40',
    mark: 'text-wall-5xl',
    text: 'text-wall-4xl',
    heights: { 1: '18rem', 2: '13rem', 3: '10rem' },
    rank: 'text-wall-7xl',
    list: 'mt-14 space-y-3',
    row: 'px-8 py-5',
    rowText: 'text-wall-3xl',
  },
};

const MEDAL: Record<number, string> = {
  1: 'text-gold',
  2: 'text-silver',
  3: 'text-bronze',
};

const BLOCK: Record<number, string> = {
  1: 'bg-gold/20 border-gold/40',
  2: 'bg-silver/20 border-silver/40',
  3: 'bg-bronze/20 border-bronze/40',
};

function Step({
  entry,
  slide,
  imageUrl,
  showValues,
  shape,
}: {
  entry: Slide['entries'][number];
  slide: Slide;
  imageUrl: ImageUrl;
  showValues: boolean;
  shape: WallShape;
}) {
  const rank = entry.rank;
  const look = SHAPES[shape];

  return (
    <div data-step={rank} className={`flex flex-col items-center ${look.step}`}>
      {entry.photo_digest ? (
        <FacePicture
          entry={entry}
          src={imageUrl(entry.photo_digest)}
          style={ringStyle(entry.ring, '0.3em', '0.2em')}
          className={`rounded-full border-4 ${look.face} ${
            rank === 1
              ? 'border-gold'
              : rank === 2
                ? 'border-silver'
                : 'border-bronze'
          }`}
        />
      ) : (
        <span
          aria-hidden="true"
          style={{
            backgroundColor: markColour(entry),
            ...ringStyle(entry.ring, '0.1em', '0.07em'),
          }}
          className={`grid place-items-center rounded-full border-4 font-medium text-white ${look.face} ${look.mark} ${
            rank === 1
              ? 'border-gold'
              : rank === 2
                ? 'border-silver'
                : 'border-bronze'
          }`}
        >
          <MarkLabel entry={entry} />
        </span>
      )}

      <p className={`mt-4 w-full truncate text-center text-content ${look.text}`}>
        {entry.entity_name}
      </p>
      {showValues && (
        <MetricValue
          value={entry.value}
          format={{
            unit: slide.unit ?? 'count',
            decimal_places: slide.decimal_places,
            unit_label: slide.unit_label,
          }}
          className={`mt-1 font-semibold tabular-nums text-content ${look.text}`}
        />
      )}

      <div
        style={{ height: look.heights[rank] ?? look.heights[3] }}
        className={`mt-4 flex w-full items-start justify-center rounded-t-xl border-x border-t pt-3 ${
          BLOCK[rank] ?? 'bg-surface border-edge'
        }`}
      >
        <span
          className={`font-bold tabular-nums ${look.rank} ${MEDAL[rank] ?? ''}`}
        >
          {rank}
        </span>
      </div>
    </div>
  );
}

