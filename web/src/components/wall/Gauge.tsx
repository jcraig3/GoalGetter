import MetricValue from '../MetricValue';
import type { Slide } from './types';

/**
 * One number, and how far round the dial it has got.
 *
 * **The screen a floor can pull toward together.** A ranked list is a comparison
 * between people; a gauge is one number the whole room owns, which is the only
 * shape that works for "we are trying to hit £250,000 this month". It is also
 * the screen with the least to read — a semicircle at a glance says "most of the
 * way" without anybody parsing a figure.
 *
 * **Drawn as an arc rather than a bar**, because a bar at wall scale is a thin
 * line across a wide screen and reads as a progress indicator for something
 * loading. A dial fills the height it is given and looks like an instrument.
 */
export default function Gauge({ slide }: { slide: Slide }) {
  // Clamped for the drawing, not for the label. Somebody at 130% should see
  // 130% written down — that is the good news — while the needle stops at the
  // end of the dial, because there is no more dial.
  const percent = slide.percent ?? 0;
  const swept = Math.max(0, Math.min(percent, 100));

  const hit = slide.status === 'hit' || percent >= 100;

  return (
    <div className="flex flex-col items-center">
      <div className="relative w-full max-w-3xl">
        <svg viewBox="0 0 200 112" className="w-full" aria-hidden="true">
          {/* The track: the whole dial, dim. */}
          <path
            d={ARC}
            fill="none"
            stroke="var(--gg-surface)"
            strokeWidth={STROKE}
            strokeLinecap="round"
          />
          {/* The fill. `pathLength` normalises the arc to 100 units so the
              dash offset is the percentage directly, rather than a number
              derived from the radius that would need recomputing if the shape
              ever changed. */}
          {/* **Not drawn at all at zero.** A dash of length zero with round
              caps still paints a cap at each end, so an empty dial showed
              two coloured dots and read as started — or finished (QA-18). */}
          {swept > 0 && (
            <path
              d={ARC}
              fill="none"
              stroke={hit ? 'var(--gg-success)' : 'var(--gg-brand)'}
              strokeWidth={STROKE}
              strokeLinecap="round"
              pathLength={100}
              strokeDasharray={`${swept} 100`}
              className="transition-[stroke-dasharray] duration-700"
            />
          )}
        </svg>

        {/* Inside the dial, where the eye already is. */}
        <div className="absolute inset-x-0 bottom-0 flex flex-col items-center">
          <p
            className={`text-wall-7xl font-bold tabular-nums ${
              hit ? 'text-success' : 'text-content'
            }`}
          >
            {Math.round(percent)}%
          </p>
        </div>
      </div>

      <p className="mt-6 text-wall-4xl tabular-nums text-content">
        <MetricValue
          bare
          value={slide.current_value ?? '0'}
          format={{
            unit: slide.unit ?? 'count',
            decimal_places: slide.decimal_places,
            unit_label: slide.unit_label,
          }}
        />
        <span className="text-wall-3xl text-content-muted">
          {' of '}
          <MetricValue
            value={slide.target_value ?? '0'}
            format={{
              unit: slide.unit ?? 'count',
              decimal_places: slide.decimal_places,
              unit_label: slide.unit_label,
            }}
          />
        </span>
      </p>
    </div>
  );
}

/**
 * One number, very large, and nothing else.
 *
 * For a target nobody has set — a gauge with no denominator is a dial with no
 * end, so the honest drawing is just the figure. Also the right screen for a
 * number that is its own point: calls taken today, days without an incident.
 */
export function BigNumber({ slide }: { slide: Slide }) {
  return (
    <div className="flex flex-col items-center justify-center py-10">
      <p className="text-[10rem] font-bold leading-none tabular-nums text-content">
        <MetricValue
          bare={Boolean(slide.target_value)}
          value={slide.current_value ?? '0'}
          format={{
            unit: slide.unit ?? 'count',
            decimal_places: slide.decimal_places,
            unit_label: slide.unit_label,
          }}
        />
      </p>
      {slide.target_value && (
        <p className="mt-6 text-wall-3xl text-content-muted">
          of{' '}
          <MetricValue
            value={slide.target_value}
            format={{
              unit: slide.unit ?? 'count',
              decimal_places: slide.decimal_places,
              unit_label: slide.unit_label,
            }}
          />
        </p>
      )}
    </div>
  );
}

/**
 * The levels past a goal's target, under whichever layout draws the goal.
 *
 * **Below the number, not on the gauge.** The gauge ends at the target; a
 * level is a further line past it, so marking it on the arc would put it off
 * the end. A reached one is lit, the next one is the thing the room is chasing.
 */
export function StretchStrip({ slide }: { slide: Slide }) {
  const format = { unit: slide.unit ?? 'count', decimal_places: slide.decimal_places, unit_label: slide.unit_label };
  return (
    <ul className="mt-6 flex flex-wrap items-center justify-center gap-4" aria-label="Stretch levels">
      {(slide.stretch ?? []).map((level) => (
        <li
          key={level.label}
          className={`rounded-full px-5 py-2 text-wall-xl ${
            level.reached ? 'bg-success/20 text-success' : 'bg-surface-raised text-content-muted'
          }`}
        >
          {level.reached && <span aria-hidden>✓ </span>}
          {level.label} · <MetricValue value={level.value} format={format} />
        </li>
      ))}
    </ul>
  );
}

/**
 * A semicircle, left to right, in a 200×112 box.
 *
 * Written out rather than computed: it never changes, and an arc built from
 * variables is a thing to re-derive every time somebody reads this file.
 */
const ARC = 'M 16 100 A 84 84 0 0 1 184 100';
const STROKE = 18;
