import { describe, expect, it } from 'vitest';

import { geometry, type Geometry, type Trend } from './Sparkline';

/** The component's own coordinate maths, called directly. */
function trend(values: (number | null)[], cumulative = false): Trend {
  return {
    unit: 'day',
    cumulative,
    points: values.map((value, index) => ({
      at: `2026-08-${String(index + 1).padStart(2, '0')}T00:00:00Z`,
      value: value === null ? null : String(value),
    })),
  };
}

/** Coordinates are rounded to two decimals in the SVG output, deliberately —
 *  full precision would roughly double the size of every `points` attribute
 *  for sub-pixel differences nobody can see. The assertions below match that. */
const PRECISION = 2;

/** Every "x,y" pair in one run of a plot, as numbers.
 *
 *  Takes the plot and an index rather than a string, so the test never has to
 *  spell out a non-null assertion for something the assertions below would
 *  catch anyway. */
function pairs(plot: Geometry | null, run = 0): [number, number][] {
  expect(plot).not.toBeNull();
  const points = plot!.runs[run];
  expect(points).toBeDefined();
  return points!.split(' ').map((p) => p.split(',').map(Number) as [number, number]);
}

/** One point of one run. */
function at(plot: Geometry | null, index: number, run = 0): [number, number] {
  const point = pairs(plot, run)[index];
  expect(point).toBeDefined();
  return point!;
}

describe('nothing worth drawing', () => {
  it('renders nothing for a single point', () => {
    expect(geometry(trend([5]))).toBeNull();
  });

  it('renders nothing for two points', () => {
    // Two points is a straight line between them and says nothing a number
    // beside it does not already say.
    expect(geometry(trend([5, 9]))).toBeNull();
  });

  it('renders nothing when a period is almost entirely unknown', () => {
    expect(geometry(trend([null, 4, null, null, 7]))).toBeNull();
  });
});

describe('gaps', () => {
  it('breaks the line rather than drawing through a gap', () => {
    // Drawing straight across a null would invent a measurement nobody took.
    const plot = geometry(trend([1, 2, 3, null, 5, 6, 7]));
    expect(plot!.runs).toHaveLength(2);
    expect(pairs(plot, 0)).toHaveLength(3);
    expect(pairs(plot, 1)).toHaveLength(3);
  });

  it('keeps one run when there are no gaps', () => {
    expect(geometry(trend([1, 2, 3, 4]))!.runs).toHaveLength(1);
  });

  it('puts the marker on the last KNOWN value, not the last bucket', () => {
    // A month whose final days have not been synced yet still ends at the last
    // real number, not floating at whatever the axis bottom happens to be.
    const plot = geometry(trend([10, 20, 30, null, null]))!;
    const [x, y] = at(plot, 2);
    expect(plot.last).toEqual({ x, y });
  });
});

describe('vertical scale', () => {
  it('anchors a cumulative line at zero', () => {
    // The story is distance travelled. Starting the axis at the first value
    // would make any month look like a steep climb from nothing.
    const plot = geometry(trend([10, 20, 30], true))!;
    // 10 of a 0-30 range is a third up from the bottom of a 28-high box.
    expect(at(plot, 0)[1]).toBeCloseTo(28 - (10 / 30) * 28, PRECISION);
  });

  it('scales a per-bucket line to its own range', () => {
    // Forty-to-fifty calls a day anchored at zero is a flat line at the top,
    // which hides the variation that is the only reason to draw it.
    const plot = geometry(trend([40, 45, 50]))!;
    expect(at(plot, 0)[1]).toBe(28); // the low sits on the floor
    expect(at(plot, 2)[1]).toBe(0); //  the high sits on the ceiling
  });

  it('does not divide by zero on a flat line', () => {
    const plot = geometry(trend([7, 7, 7]))!;
    expect(pairs(plot).every(([, y]) => Number.isFinite(y))).toBe(true);
  });

  it('leaves room for a reference above every value', () => {
    // A target nobody is close to still has to be on the chart, or "will I
    // make it" has no visible answer.
    const plot = geometry(trend([1, 2, 3], true), 100)!;
    expect(plot.referenceY).toBe(0);
    expect(pairs(plot).every(([, y]) => y > 0)).toBe(true);
  });

  it('places a reference already beaten below the top', () => {
    const plot = geometry(trend([10, 60, 120], true), 100)!;
    expect(plot.referenceY!).toBeGreaterThan(0);
    expect(plot.last!.y).toBe(0);
  });
});

describe('horizontal placement', () => {
  it('spreads points evenly across the full width', () => {
    const plot = geometry(trend([1, 2, 3, 4, 5]))!;
    expect(pairs(plot).map(([x]) => x)).toEqual([0, 25, 50, 75, 100]);
  });

  it('keeps a gap in its own position rather than closing it up', () => {
    // The x of a point is its index in the period, so a quiet stretch stays
    // visibly wide instead of the chart shrinking to fit what it has.
    const plot = geometry(trend([1, 2, 3, null, null, 6, 7, 8]))!;
    const xs = pairs(plot, 1).map(([x]) => x);
    [(5 / 7) * 100, (6 / 7) * 100, 100].forEach((expected, index) => {
      expect(xs[index]).toBeCloseTo(expected, PRECISION);
    });
  });
});
