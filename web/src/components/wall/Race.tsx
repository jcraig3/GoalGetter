import MetricValue from '../MetricValue';
import { hasRing } from '../ring';
import { sessionImageUrl, type Entry, type ImageUrl, type Slide } from './types';
import { FacePicture, MarkLabel, markColour } from './entryLook';
import NobodyYet, { nobodyYet } from './NobodyYet';

/**
 * A race track: every entrant's piece in a lane, placed by how far along they
 * are.
 *
 * **A layout, not a separate design.** It reads the same ranked slide the
 * list and the podium read, and it honours everything they do — the
 * background behind it, the brand colour for the trails, the wall's type and
 * the panel style for the lanes. The themed boards this product was measured
 * against drop all of that, which is why they hide the background and colour
 * options entirely; here those options keep working.
 *
 * **Position comes from the server.** Each entry arrives with its share of the
 * finish line — or of the leader, when there is no line — worked out by
 * `app/game_boards.py`, so the rule has one home and this only draws it.
 *
 * **Eight lanes at most**, whatever the row count says. A track is read from
 * across the room, and past eight the lanes are too thin to tell apart from
 * three metres — the 10-foot rule rather than a setting.
 */
export const MAX_LANES = 8;

export default function Race({
  slide,
  imageUrl = sessionImageUrl,
  rows = 10,
  showValues = true,
}: {
  slide: Slide;
  imageUrl?: ImageUrl;
  rows?: number;
  showValues?: boolean;
}) {
  const lanes = slide.entries.slice(0, Math.min(rows, MAX_LANES));
  if (nobodyYet(slide) || lanes.length === 0) {
    return <NobodyYet slide={slide} />;
  }

  const format = { unit: slide.unit ?? 'count', decimal_places: slide.decimal_places, unit_label: slide.unit_label };
  const hasLine = slide.finish_line !== null && slide.finish_line !== undefined;

  return (
    <div>
      {/* What the far end means, said once above the track. "Leader" rather
          than "Finish" when there is no line, so nobody reads the front-runner
          as having crossed one. */}
      <div className="mb-3 flex justify-end text-wall-xl text-content-muted">
        {hasLine ? (
          <span>
            Finish ·{' '}
            <MetricValue value={slide.finish_line as string} format={format} />
          </span>
        ) : (
          <span>Measured against the leader</span>
        )}
      </div>

      <ol className="space-y-3">
        {lanes.map((entry) => (
          <Lane
            key={entry.entity_id}
            entry={entry}
            imageUrl={imageUrl}
            hasLine={hasLine}
            showValues={showValues}
            format={format}
          />
        ))}
      </ol>
    </div>
  );
}

function Lane({
  entry,
  imageUrl,
  hasLine,
  showValues,
  format,
}: {
  entry: Entry;
  imageUrl: ImageUrl;
  hasLine: boolean;
  showValues: boolean;
  format: { unit: string; decimal_places: number };
}) {
  const progress = Math.max(0, Math.min(entry.progress ?? 0, 1));
  const percent = progress * 100;

  return (
    <li className={`wall-panel flex items-center gap-6 px-6 py-3 ${entry.finished ? 'ring-2 ring-gold' : ''}`}>
      <span className="w-12 shrink-0 text-right text-wall-3xl tabular-nums text-content-subtle">
        {entry.rank}
      </span>
      <span className="w-[22%] shrink-0 truncate text-wall-3xl text-content">
        {entry.entity_name}
      </span>

      {/* The track. The piece is positioned inside a box one piece narrower
          than the lane, so at 100% it sits at the line rather than past it. */}
      <div className="relative h-[3.2em] min-w-0 flex-1 text-wall-base">
        <div className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 border-t-2 border-dashed border-content-subtle/40" />
        {/* The trail behind the piece, in the brand colour — the part that
            reads as movement from across the room. */}
        <div
          className="absolute left-0 top-1/2 h-[0.5em] -translate-y-1/2 rounded-full bg-brand/40 motion-safe:transition-[width] motion-safe:duration-1000"
          // Up to the middle of the piece. The piece's left edge is at `percent`
          // of a box 3.2em narrower than the lane, so its centre is that, less
          // the share of 3.2em the box lost, plus half a 3em piece.
          style={{ width: `calc(${percent}% - ${(progress * 3.2).toFixed(3)}em + 1.5em)` }}
        />
        <div className="absolute inset-y-0 left-0 right-[3.2em]">
          <div
            className="absolute top-1/2 -translate-y-1/2 motion-safe:transition-[left] motion-safe:duration-1000 motion-safe:ease-out"
            style={{ left: `${percent}%` }}
          >
            <Piece entry={entry} imageUrl={imageUrl} />
          </div>
        </div>
      </div>

      {/* The line itself: a chequered flag with a finish line, a plain post
          without one. */}
      <span
        aria-hidden="true"
        className={`h-[3em] w-[0.9em] shrink-0 rounded-sm text-wall-base ${hasLine ? 'chequered' : 'bg-content-subtle/30'}`}
      />

      {showValues && (
        <MetricValue
          value={entry.value}
          format={format}
          className="w-[7em] shrink-0 text-right text-wall-3xl text-content"
        />
      )}
    </li>
  );
}

/**
 * The piece somebody moves: their own face, or the one they chose.
 *
 * Coloured with the ring they bought, if they wear one — the economy showing
 * up on the game board — and otherwise with their own avatar colour, so two
 * cars in adjacent lanes are still two people.
 */
function Piece({ entry, imageUrl }: { entry: Entry; imageUrl: ImageUrl }) {
  const colour = hasRing(entry.ring) ? entry.ring : markColour(entry);
  const token = entry.token ?? 'face';

  if (token === 'face') {
    const style = { outline: `0.15em solid ${colour}`, outlineOffset: '0.08em' };
    return entry.photo_digest ? (
      <FacePicture
        entry={entry}
        src={imageUrl(entry.photo_digest)}
        style={style}
        className="size-[3em] rounded-full"
      />
    ) : (
      <span
        aria-hidden="true"
        style={{ backgroundColor: markColour(entry), ...style }}
        className="grid size-[3em] place-items-center rounded-full text-[1.1em] font-semibold text-white"
      >
        <MarkLabel entry={entry} />
      </span>
    );
  }

  return (
    <svg
      viewBox="0 0 64 40"
      aria-hidden="true"
      className="block h-[3em] w-[4.8em] -translate-x-[0.9em]"
      data-token={token}
    >
      {RACE_PIECES[token]?.(colour) ?? RACE_PIECES.car!(colour)}
    </svg>
  );
}

/**
 * The pieces, drawn here rather than shipped as art.
 *
 * Simple silhouettes, deliberately: they are read at three metres, where
 * detail is noise and a shape is everything. Each takes the person's colour
 * for its body and the wall's own dark for its wheels.
 */
export const RACE_PIECES: Record<string, (colour: string) => React.ReactElement> = {
  car: (colour) => (
    <>
      <path d="M6 26 L10 17 Q12 13 17 13 L38 13 Q42 13 45 16 L52 22 L58 23 Q62 24 62 28 L62 31 L2 31 L2 28 Q2 26 6 26 Z" fill={colour} />
      <path d="M17 16 L37 16 L43 22 L14 22 Z" fill="rgba(255,255,255,0.55)" />
      <circle cx="16" cy="31" r="6" fill="#0b0e14" />
      <circle cx="16" cy="31" r="2.5" fill="#c9cdd6" />
      <circle cx="50" cy="31" r="6" fill="#0b0e14" />
      <circle cx="50" cy="31" r="2.5" fill="#c9cdd6" />
    </>
  ),
  truck: (colour) => (
    <>
      <rect x="2" y="9" width="36" height="21" rx="2" fill={colour} />
      <path d="M38 14 L50 14 L58 22 L62 23 L62 30 L38 30 Z" fill={colour} />
      <path d="M41 17 L49 17 L54 22 L41 22 Z" fill="rgba(255,255,255,0.55)" />
      <circle cx="13" cy="31" r="6" fill="#0b0e14" />
      <circle cx="13" cy="31" r="2.5" fill="#c9cdd6" />
      <circle cx="51" cy="31" r="6" fill="#0b0e14" />
      <circle cx="51" cy="31" r="2.5" fill="#c9cdd6" />
    </>
  ),
  bike: (colour) => (
    <>
      <circle cx="14" cy="28" r="9" fill="none" stroke="#0b0e14" strokeWidth="4" />
      <circle cx="50" cy="28" r="9" fill="none" stroke="#0b0e14" strokeWidth="4" />
      <path d="M14 28 L26 14 L42 14 L50 28 M26 14 L32 28 L42 14 M38 8 L46 8" fill="none" stroke={colour} strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
    </>
  ),
};
