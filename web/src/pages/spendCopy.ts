/**
 * The arithmetic and wording around spending.
 *
 * Kept out of the components for the same reason as the rest of the economy's
 * sentences: a wheel whose slices do not add up to a circle, or odds that say
 * "1 in 0", are the kind of wrong that looks finished.
 */

export interface Item {
  id: number;
  name: string;
  kind: 'ring' | 'title';
  value: string;
  price: number;
  enabled: boolean;
  owned: boolean;
  equipped: boolean;
  owners: number;
}

export interface Shop {
  wallet: number;
  items: Item[];
}

export interface Segment {
  id: number;
  label: string;
  kind: 'points' | 'prize' | 'nothing';
  points: number;
  chance: number;
  stock: number | null;
}

export interface Spin {
  id: number;
  label: string;
  kind: 'points' | 'prize' | 'nothing';
  cost: number;
  points_won: number;
  given_at: string | null;
  created_at: string;
  prize_id: number | null;
  winner_name: string | null;
}

export interface Wheel {
  enabled: boolean;
  spin_cost: number;
  segments: Segment[];
  wallet: number;
  recent: Spin[];
}

export interface Prize {
  id: number;
  label: string;
  kind: 'points' | 'prize' | 'nothing';
  points: number;
  weight: number;
  stock: number | null;
  enabled: boolean;
}

/**
 * A chance, said the way people read odds.
 *
 * **"1 in 40" for the rare ones, a percentage for the rest.** "2.5%" is
 * correct and nobody feels it; "1 in 40" is the same number and everybody
 * does. Above one in ten the percentage reads better, and "1 in 1.3" reads
 * worse than "75%".
 */
export function chanceLabel(chance: number): string {
  if (chance <= 0) return 'never';
  if (chance >= 1) return 'every time';
  if (chance <= 0.1) return `1 in ${Math.round(1 / chance)}`;
  return `${Math.round(chance * 100)}%`;
}

/** How many points short, or 0 when it can be afforded. */
export function shortBy(wallet: number, price: number): number {
  return Math.max(price - wallet, 0);
}

/**
 * What a spin won, in a sentence.
 *
 * A miss says so plainly. Dressing a loss up as "almost!" on a screen
 * somebody just paid to use is the move that makes a wheel feel like a
 * machine designed to take points.
 */
export function wonLabel(spin: Spin): string {
  if (spin.kind === 'points') return `You won ${spin.points_won.toLocaleString()} points.`;
  if (spin.kind === 'prize') return `You won ${spin.label}! Your manager will hand it over.`;
  return `${spin.label} — nothing this time.`;
}

export interface Slice {
  segment: Segment;
  /** Degrees clockwise from the top. */
  start: number;
  end: number;
}

/**
 * The wheel as slices, sized by their true chance.
 *
 * **The picture is drawn from the odds, so it cannot disagree with them.** A
 * wheel with eight equal slices and a hidden weighting underneath is exactly
 * the slot machine this product refuses to be — a slice that looks like an
 * eighth and comes up one time in a hundred is a lie told in geometry.
 */
export function slices(segments: Segment[]): Slice[] {
  const total = segments.reduce((sum, s) => sum + s.chance, 0);
  if (total <= 0) return [];
  let at = 0;
  return segments.map((segment) => {
    const size = (segment.chance / total) * 360;
    const slice = { segment, start: at, end: at + size };
    at += size;
    return slice;
  });
}

/**
 * How far to turn the wheel so the pointer at the top lands on `prizeId`.
 *
 * Adds whole turns to wherever it already is, so it always spins forward and
 * always lands in the middle of the slice rather than on an edge somebody
 * could argue about. `from` is the current rotation in degrees.
 */
export function landOn(
  all: Slice[],
  prizeId: number | null,
  from: number,
  turns = 5,
): number {
  const slice = all.find((s) => s.segment.id === prizeId);
  if (!slice) return from + turns * 360;
  const middle = (slice.start + slice.end) / 2;
  // The wheel turns clockwise, so to bring `middle` to the top it has to end
  // at (360 - middle), measured from a fresh turn.
  const settled = ((from % 360) + 360) % 360;
  const target = (360 - middle) % 360;
  const extra = (target - settled + 360) % 360;
  return from + turns * 360 + extra;
}
