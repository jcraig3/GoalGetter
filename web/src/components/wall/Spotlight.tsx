import MetricValue from '../MetricValue';
import { avatarColour, initialsOf } from '../avatarColour';
import { ringStyle } from '../ring';
import { sessionImageUrl, type ImageUrl, type Slide } from './types';
import { useWallShape } from './WallStage';

/**
 * One person, large.
 *
 * **This replaces a workaround.** In a real account of 150 people, nearly every
 * hand-authored message screen turned out to be an image of one rep, made in an
 * image editor and uploaded — because the product had no template for it. Those
 * images go stale the moment somebody's numbers change, and nobody remembers to
 * remake them.
 *
 * **The face is the screen.** A room glancing up for two seconds should get
 * *who* before it gets any number, so the photograph is the largest thing here
 * and everything else is arranged around it. A spotlight built as a table with
 * one row would be a worse leaderboard rather than a different screen.
 */
export default function Spotlight({
  slide,
  imageUrl = sessionImageUrl,
}: {
  slide: Slide;
  imageUrl?: ImageUrl;
}) {
  const person = slide.person;
  // **Stacked on a portrait wall** (6.11): the face above, larger, and the
  // name and figures centred under it — side by side, a 1080-pixel screen
  // left the name a third of the width to sit in.
  const portrait = useWallShape() === 'portrait';
  if (!person) return null;

  const stat = slide.stats[0];

  return (
    <div
      data-spotlight-shape={portrait ? 'portrait' : 'landscape'}
      className={portrait ? 'flex flex-col items-center gap-12 text-center' : 'flex flex-wrap items-center gap-12'}
    >
      <Face
        name={person.name}
        digest={person.photo_digest}
        url={imageUrl}
        ring={person.ring}
        size={portrait ? 'size-96' : 'size-64'}
      />

      <div className={portrait ? 'w-full min-w-0' : 'min-w-0 flex-1'}>
        <p className="truncate text-wall-6xl font-semibold text-content">
          {person.name}
        </p>
        {/* The one layout with room under a name for a second line, so it is
            the one that carries a bought title. */}
        {person.title && (
          <p className="mt-2 truncate text-wall-3xl font-medium text-brand">
            {person.title}
          </p>
        )}
        {(person.job_title || person.team_name) && (
          <p className="mt-2 truncate text-wall-3xl text-content-muted">
            {[person.job_title, person.team_name].filter(Boolean).join(' · ')}
          </p>
        )}

        {stat && (
          <div
            className={`mt-8 flex flex-wrap items-baseline gap-x-10 gap-y-4 ${portrait ? 'justify-center' : ''}`}
          >
            <div>
              <MetricValue
                value={stat.value}
                format={{
                  unit: stat.unit ?? 'count',
                  decimal_places: stat.decimal_places,
                  unit_label: stat.unit_label,
                }}
                className="text-wall-7xl font-semibold tabular-nums text-brand"
              />
              <p className="mt-1 text-wall-2xl text-content-muted">{stat.label}</p>
            </div>
            <div>
              <p className="text-wall-7xl font-semibold tabular-nums text-content">
                {ordinal(stat.rank)}
              </p>
              <p className="mt-1 text-wall-2xl text-content-muted">
                {stat.of > 0 ? `of ${stat.of}` : 'on the board'}
              </p>
            </div>
            {/* A streak of one is "today", not a streak. Said as a number only
                once it means something somebody is keeping up. */}
            {slide.streak_days != null && slide.streak_days > 1 && (
              <div>
                <p className="text-wall-7xl font-semibold tabular-nums text-content">
                  {slide.streak_days}
                </p>
                <p className="mt-1 text-wall-2xl text-content-muted">days running</p>
              </div>
            )}
          </div>
        )}

        {slide.achievements.length > 0 && (
          <ul className={`mt-8 space-y-2 ${portrait ? 'text-left' : ''}`}>
            {slide.achievements.map((win) => (
              <li
                key={win.id}
                className="wall-panel truncate border-l-4 border-accent px-6 py-3 text-wall-2xl text-content"
              >
                {win.title}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/**
 * The photograph, or the letters.
 *
 * Not `Avatar`: that component tops out at 56px because it draws beside names
 * in tables, and this is the subject of the screen. The fallback behaviour is
 * the same and matters as much — most directories have photographs of some
 * people and not others, so initials are the ordinary case here too.
 */
function Face({
  name,
  digest,
  url,
  ring,
  size,
}: {
  name: string;
  digest: string | null | undefined;
  url: ImageUrl;
  ring?: string | null;
  size: string;
}) {
  if (digest) {
    return (
      <img
        src={url(digest)}
        alt=""
        aria-hidden="true"
        style={ringStyle(ring, '0.6em', '0.4em')}
        className={`${size} shrink-0 rounded-full border-4 border-brand object-cover`}
      />
    );
  }

  return (
    <span
      aria-hidden="true"
      style={{
        backgroundColor: avatarColour(name),
        ...ringStyle(ring, '0.08em', '0.05em'),
      }}
      className={`grid ${size} shrink-0 place-items-center rounded-full border-4 border-brand text-wall-8xl font-medium text-white`}
    >
      {initialsOf(name)}
    </span>
  );
}


/** "1st", "2nd", "3rd" — the way a person would read a rank aloud. */
export function ordinal(rank: number): string {
  const tens = rank % 100;
  if (tens >= 11 && tens <= 13) return `${rank}th`;
  const suffix = { 1: 'st', 2: 'nd', 3: 'rd' }[rank % 10] ?? 'th';
  return `${rank}${suffix}`;
}
