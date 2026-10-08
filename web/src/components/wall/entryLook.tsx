import { avatarColour, initialsOf } from '../avatarColour';

/**
 * How a row on the wall is known at a glance: a person by their colour and
 * initials, a team by its own colour and short name (6.7).
 *
 * The server marks a team row with `is_team`, sends its `colour` and
 * `short_name` (null when unset), and puts its logo where a person's face
 * would be. A person's row looks as it always has.
 */
export interface Lookable {
  entity_name: string;
  /** Set by the server on a team row (6.7). The only thing that says so:
   *  every row carries `colour` and `short_name`, null on a person's. */
  is_team?: boolean;
  colour?: string | null;
  short_name?: string | null;
}

export function isTeamRow(entry: Lookable): boolean {
  return entry.is_team === true;
}

export function markColour(entry: Lookable): string {
  return entry.colour || avatarColour(entry.entity_name);
}

export function markLabel(entry: Lookable): string {
  return entry.short_name || initialsOf(entry.entity_name);
}

/**
 * The letters inside a mark, smaller when there are more than three — a short
 * name can be up to twelve, and initials are never more than two.
 */
export function MarkLabel({ entry }: { entry: Lookable }) {
  const label = markLabel(entry);
  return (
    <span style={{ fontSize: label.length > 3 ? `${Math.max(0.32, 2.4 / label.length)}em` : '1em' }}>
      {label}
    </span>
  );
}

/**
 * A picture standing in for a face: a person's photograph fills its circle; a
 * team's logo sits whole on the team's colour, inset so it never touches the
 * edge.
 *
 * **A badge with the logo inside, not a padded image.** Padding in percent is
 * a share of the row's width, not the picture's — so a logo padded "12%" in
 * a 1000-pixel row grew a 240-pixel border and turned a 56-pixel face into a
 * dinner plate. `className` sizes and shapes the outside either way.
 */
export function FacePicture({
  entry,
  src,
  className,
  style,
}: {
  entry: Lookable;
  src: string;
  className: string;
  style?: React.CSSProperties;
}) {
  if (!isTeamRow(entry)) {
    return (
      <img src={src} alt="" aria-hidden="true" style={style} className={`block object-cover ${className}`} />
    );
  }
  return (
    <span
      aria-hidden="true"
      data-team-mark=""
      style={{ backgroundColor: markColour(entry), ...style }}
      className={`grid place-items-center overflow-hidden ${className}`}
    >
      <img src={src} alt="" className="size-[76%] object-contain" />
    </span>
  );
}
