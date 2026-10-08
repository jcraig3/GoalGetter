export interface TrendPoint {
  at: string;
  /** Null means "no honest number for this bucket" — not zero. */
  value: string | null;
}

export interface Trend {
  unit: string;
  cumulative: boolean;
  points: TrendPoint[];
}

/** Fewer than this and there is no shape to see, only a dot or a dash. */
const MIN_POINTS = 3;

const WIDTH = 100;
const HEIGHT = 28;

export interface Geometry {
  /** One polyline per unbroken run of known values. Gaps split them. */
  runs: string[];
  /** Where the last known value sits, for the "you are here" dot. */
  last: { x: number; y: number } | null;
  /** The y of the reference rule, when there is one. */
  referenceY: number | null;
}

/**
 * Turn a trend into SVG coordinates.
 *
 * Exported and pure so the tests can assert on the shape this draws rather
 * than on the markup around it. The last time a component's logic lived only
 * inside its render, the test that "covered" it had quietly reimplemented it,
 * and deleting the real code failed nothing.
 *
 * Returns null when there is nothing worth drawing.
 */
export function geometry(trend: Trend, reference?: number): Geometry | null {
  const values = trend.points.map((p) => (p.value === null ? null : Number(p.value)));
  const known = values.filter((v): v is number => v !== null);

  if (known.length < MIN_POINTS || values.length < 2) return null;

  const lowest = Math.min(...known, reference ?? Infinity);
  const highest = Math.max(...known, reference ?? -Infinity);

  // A cumulative line is anchored at zero, a per-bucket one to its own range —
  // see the component docstring for why those cannot be scaled alike.
  const floor = trend.cumulative ? Math.min(0, lowest) : lowest;
  // A flat line has no range to divide by. One is as good as any number here,
  // and puts the line through the middle of the box rather than at its edge.
  const span = highest - floor || 1;

  const x = (index: number) => (index / (values.length - 1)) * WIDTH;
  const y = (value: number) => HEIGHT - ((value - floor) / span) * HEIGHT;

  // Split at the gaps: each run of consecutive known values is its own
  // polyline, so a break in the data is a break in the drawing.
  const runs: string[] = [];
  let current: string[] = [];
  values.forEach((value, index) => {
    if (value === null) {
      if (current.length > 1) runs.push(current.join(' '));
      current = [];
      return;
    }
    current.push(`${x(index).toFixed(2)},${y(value).toFixed(2)}`);
  });
  if (current.length > 1) runs.push(current.join(' '));

  // Not `findLastIndex`: the project targets an older lib, and moving to a
  // newer one to save two lines would change what every other file compiles
  // against.
  let lastIndex = values.length - 1;
  while (lastIndex >= 0 && values[lastIndex] === null) lastIndex -= 1;
  const lastValue = lastIndex >= 0 ? (values[lastIndex] ?? null) : null;

  return {
    runs,
    last: lastValue === null ? null : { x: x(lastIndex), y: y(lastValue) },
    referenceY: reference === undefined ? null : y(reference),
  };
}

/**
 * A small chart with no axes, read for its shape rather than its values.
 *
 * Hand-drawn SVG rather than a charting library: this needs a polyline and a
 * dot, and the smallest capable library is well over 100 KB of JavaScript plus
 * a dependency to keep current. The whole component is shorter than its own
 * configuration would have been.
 *
 * **The vertical scale depends on what the line means**, which is why the API
 * sends `cumulative` rather than letting this guess:
 *
 * - A cumulative line is anchored at zero. It is a story about distance
 *   travelled toward a target, and starting the axis anywhere else would make
 *   a slow month look like a steep climb.
 * - A per-bucket line is scaled to its own range. It is a story about which
 *   days were busy, and anchoring at zero would flatten forty-to-fifty calls a
 *   day into a straight line at the top of the box — hiding the variation that
 *   is the only reason to draw it.
 *
 * Those two are read differently, so they must not be scaled identically.
 *
 * **Gaps break the line.** A null bucket means no data, and drawing straight
 * through it would invent a measurement nobody took.
 */
export default function Sparkline({
  trend,
  reference,
  label,
  className = '',
}: {
  trend: Trend;
  /** Drawn as a dashed rule — a goal's target. Included in the scale. */
  reference?: number;
  /** For screen readers. A chart with no text is otherwise invisible. */
  label: string;
  className?: string;
}) {
  const plot = geometry(trend, reference);
  if (plot === null) return null;

  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      // Stretches to the container's width; the viewBox does the scaling, so
      // no resize listener and no layout measurement.
      className={`h-7 w-full overflow-visible ${className}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={label}
    >
      {plot.referenceY !== null && (
        <line
          x1={0}
          x2={WIDTH}
          y1={plot.referenceY}
          y2={plot.referenceY}
          className="stroke-content-subtle"
          strokeWidth={1}
          strokeDasharray="3 3"
          // vector-effect keeps the stroke 1px wide despite the non-uniform
          // scaling that preserveAspectRatio="none" applies.
          vectorEffect="non-scaling-stroke"
        />
      )}

      {plot.runs.map((points) => (
        <polyline
          key={points}
          points={points}
          fill="none"
          className="stroke-brand"
          strokeWidth={1.5}
          strokeLinecap="round"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
      ))}

      {plot.last && (
        // Where it stands now. Without it the eye has to hunt for which end is
        // the present, and on a flat line the answer is not obvious.
        // A zero-length round-capped line, not a circle: under
        // preserveAspectRatio="none" a circle is stretched with the chart into
        // a long smear that ran past the card (P3-6). A non-scaling stroke
        // stays a dot whatever the width.
        <line
          x1={plot.last.x}
          y1={plot.last.y}
          x2={plot.last.x}
          y2={plot.last.y}
          strokeLinecap="round"
          strokeWidth={5}
          vectorEffect="non-scaling-stroke"
          className="stroke-brand"
        />
      )}
    </svg>
  );
}
