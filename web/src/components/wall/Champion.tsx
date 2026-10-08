import MetricValue from '../MetricValue';
import { ringStyle } from '../ring';
import { sessionImageUrl, type Entry, type ImageUrl, type Slide } from './types';
import { FacePicture, MarkLabel, markColour } from './entryLook';

/**
 * Who won, once a contest has settled.
 *
 * **A settled contest is a different question from a running one.** While it
 * runs, a room wants the table: where am I, who is close, how long is left.
 * Once it is over, the only question left is who won — and a table answers
 * that in the same size type as it answers "who came seventh".
 *
 * **No setting for it.** A contest that has finished cannot become unfinished,
 * so the choice would be between the right screen and a worse one, offered
 * permanently, to be got wrong once.
 */
export default function Champion({
  slide,
  imageUrl = sessionImageUrl,
}: {
  slide: Slide;
  imageUrl?: ImageUrl;
}) {
  const [winner, second, third] = slide.entries;

  if (!winner) {
    // A contest that settled with nobody in it. Rare, and a blank screen with
    // a prize written on it would be worse than saying so.
    return (
      <p className="text-wall-3xl text-content-muted">
        No result to show for this one.
      </p>
    );
  }

  return (
    <div className="flex flex-col items-center text-center">
      <p className="text-wall-2xl uppercase tracking-widest text-content-muted">
        Winner
      </p>

      <Face entry={winner} url={imageUrl} />

      <p className="mt-6 max-w-full truncate text-wall-7xl font-semibold text-content">
        {winner.entity_name}
      </p>

      <MetricValue
        value={winner.value}
        format={{
          unit: slide.unit ?? 'count',
          decimal_places: slide.decimal_places,
          unit_label: slide.unit_label,
        }}
        className="mt-2 text-wall-5xl font-semibold tabular-nums text-gold"
      />

      {slide.prize && (
        // Under the name, not above it. The prize is why anybody entered, and
        // it reads as the reward for the name above it rather than as a
        // heading for the screen.
        <p className="mt-4 text-wall-3xl text-accent">{slide.prize}</p>
      )}

      {(second || third) && (
        // Small, and only two. A podium's worth of runners-up is generous;
        // a full table underneath would put the champion back in a list.
        <ol className="mt-10 flex flex-wrap justify-center gap-8">
          {[second, third].filter(Boolean).map((entry) => (
            <li
              key={entry!.entity_id}
              className="flex items-baseline gap-3 text-wall-2xl text-content-muted"
            >
              <span
                className={`tabular-nums ${
                  entry!.rank === 2 ? 'text-silver' : 'text-bronze'
                }`}
              >
                {entry!.rank}
              </span>
              <span className="max-w-64 truncate">{entry!.entity_name}</span>
              <MetricValue
                value={entry!.value}
                format={{
                  unit: slide.unit ?? 'count',
                  decimal_places: slide.decimal_places,
                  unit_label: slide.unit_label,
                }}
                className="tabular-nums"
              />
            </li>
          ))}
        </ol>
      )}

      {slide.total_entrants > 3 && (
        <p className="mt-6 text-wall-xl text-content-subtle">
          of {slide.total_entrants} who entered
        </p>
      )}
    </div>
  );
}

/**
 * The winner's face, or their initials.
 *
 * Bordered in gold rather than the brand colour: this is the one screen in the
 * product where a literal colour carries meaning, and it is the same gold the
 * podium uses for first place.
 */
function Face({ entry, url }: { entry: Entry; url: ImageUrl }) {
  const shape = 'mt-6 size-56 shrink-0 rounded-full border-4 border-gold';

  if (entry.photo_digest) {
    return (
      <FacePicture
        entry={entry}
        src={url(entry.photo_digest)}
        style={ringStyle(entry.ring, '0.5em', '0.35em')}
        className={shape}
      />
    );
  }

  return (
    <span
      aria-hidden="true"
      style={{
        backgroundColor: markColour(entry),
        ...ringStyle(entry.ring, '0.08em', '0.05em'),
      }}
      className={`${shape} grid place-items-center text-wall-7xl font-medium text-white`}
    >
      <MarkLabel entry={entry} />
    </span>
  );
}
