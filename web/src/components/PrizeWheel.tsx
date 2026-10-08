import { dayMonth } from '../time';
import { useCallback, useEffect, useRef, useState } from 'react';

import { api } from '../api';
import { formatPoints } from '../pages/pointsCopy';
import {
  type Slice,
  type Spin,
  type Wheel,
  chanceLabel,
  landOn,
  shortBy,
  slices,
  wonLabel,
} from '../pages/spendCopy';
import Loading from './Loading';

/** How long the wheel turns before it stops. */
const SPIN_MS = 4200;

/**
 * The prize wheel.
 *
 * **Everything a spinner needs to judge it is on the screen before they
 * spin**: the price, every segment, and each one's true chance. The slices are
 * drawn from those same chances, so a rare prize is a thin slice — a wheel of
 * equal slices over a hidden weighting is a slot machine, and a workplace
 * should not be running one.
 *
 * **The server draws; this only animates.** The result is known before the
 * wheel starts turning, and the animation is aimed at it. A draw made in the
 * browser is one anybody with the developer tools open can make come out
 * their way.
 */
export default function PrizeWheel({ onChange }: { onChange?: () => void }) {
  const [wheel, setWheel] = useState<Wheel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rotation, setRotation] = useState(0);
  const [spinning, setSpinning] = useState(false);
  const [result, setResult] = useState<Spin | null>(null);
  const timer = useRef<number | undefined>(undefined);

  const load = useCallback(() => {
    api<Wheel>('/api/points/wheel')
      .then(setWheel)
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load.'));
  }, []);

  useEffect(load, [load]);
  useEffect(() => () => window.clearTimeout(timer.current), []);

  async function spin() {
    if (!wheel) return;
    setError(null);
    setResult(null);
    setSpinning(true);
    try {
      const won = await api<Spin>('/api/points/wheel/spin', { method: 'POST' });
      const drawn = slices(wheel.segments);
      setRotation((from) => landOn(drawn, won.prize_id, from));

      // Somebody who has asked for less motion gets the answer straight away:
      // a four-second spin is decoration, and decoration they have opted out
      // of should not stand between them and what they won.
      const still = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
      timer.current = window.setTimeout(
        () => {
          setResult(won);
          setSpinning(false);
          load();
          onChange?.();
        },
        still ? 0 : SPIN_MS,
      );
    } catch (e) {
      setSpinning(false);
      setError(e instanceof Error ? e.message : 'Could not spin.');
    }
  }

  if (error && !wheel) {
    return (
      <p role="alert" className="rounded-md border border-danger px-3 py-2 text-sm text-danger">
        {error}
      </p>
    );
  }
  if (!wheel) return <Loading />;

  if (!wheel.enabled || wheel.segments.length === 0) {
    return (
      <section className="rounded-lg border border-dashed border-edge p-6 text-center">
        <p className="text-content">The prize wheel is not running</p>
        <p className="mt-1 text-sm text-content-muted">
          It appears here once an admin has put prizes on it.
        </p>
      </section>
    );
  }

  const drawn = slices(wheel.segments);
  const short = shortBy(wheel.wallet, wheel.spin_cost);

  return (
    <section className="rounded-lg border border-edge bg-surface p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-4">
        <h2 className="text-h3 text-content">Prize wheel</h2>
        <p className="text-sm text-content-muted">
          <span className="tabular-nums text-content">{formatPoints(wheel.wallet)}</span>{' '}
          to spend
        </p>
      </div>

      <div className="mt-6 grid items-center gap-8 md:grid-cols-[auto_1fr]">
        <div className="relative mx-auto size-64">
          {/* The pointer, fixed at the top; the wheel turns under it. */}
          <span
            aria-hidden="true"
            className="absolute left-1/2 top-0 z-10 -translate-x-1/2 -translate-y-1 border-x-[10px] border-t-[16px] border-x-transparent border-t-content"
          />
          <WheelFace slices={drawn} rotation={rotation} />
        </div>

        <div>
          <ul className="space-y-1.5 text-sm">
            {wheel.segments.map((segment) => (
              <li key={segment.id} className="flex justify-between gap-4">
                <span className="text-content">
                  {segment.label}
                  {segment.stock !== null && (
                    <span className="ml-2 text-xs text-content-muted">
                      {segment.stock} left
                    </span>
                  )}
                </span>
                <span className="tabular-nums text-content-muted">
                  {chanceLabel(segment.chance)}
                </span>
              </li>
            ))}
          </ul>

          <button
            type="button"
            onClick={spin}
            disabled={spinning || short > 0}
            className="mt-5 w-full rounded-md bg-brand px-4 py-2.5 text-white disabled:opacity-50"
          >
            {spinning
              ? 'Spinning…'
              : short > 0
                ? `${formatPoints(short)} short of a spin`
                : `Spin for ${formatPoints(wheel.spin_cost)} points`}
          </button>

          {/* Announced, so a screen reader hears the result the wheel shows. */}
          <p aria-live="polite" className="mt-3 min-h-6 text-content">
            {result && wonLabel(result)}
          </p>
          {error && (
            <p role="alert" className="mt-2 rounded-md border border-danger px-3 py-2 text-sm text-danger">
              {error}
            </p>
          )}
        </div>
      </div>

      {wheel.recent.length > 0 && (
        <div className="mt-6">
          <h3 className="text-sm text-content-muted">Your recent spins</h3>
          <ul className="mt-2 space-y-1 text-sm">
            {wheel.recent.map((spin) => (
              <li key={spin.id} className="flex justify-between gap-4">
                <span className="text-content">{spin.label}</span>
                <span className="text-content-muted">
                  {spin.kind === 'prize'
                    ? spin.given_at
                      ? 'handed over'
                      : 'waiting to be handed over'
                    : dayMonth(spin.created_at)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

/** Characters that fit between the hub and the rim at the label's size. */
const LABEL_CHARS = 13;

/** A label that fits along the radius, cut with an ellipsis (Q2-26). */
export function wheelLabel(label: string): string {
  return label.length <= LABEL_CHARS ? label : `${label.slice(0, LABEL_CHARS - 1).trimEnd()}…`;
}

/**
 * How far to turn a slice's label so it runs along the radius (Q2-26).
 *
 * Turned along the rim, a slice at three o'clock read top to bottom. Along the
 * radius it reads outward on the right half, and inward on the left so it is
 * never upside down.
 */
export function labelTurn(middle: number): number {
  return middle <= 180 ? middle - 90 : middle + 90;
}

/** Tones for the slices, alternated, from the organization's own brand. */
const TONES = [
  'var(--gg-brand)',
  'color-mix(in srgb, var(--gg-brand) 55%, var(--gg-surface))',
  'color-mix(in srgb, var(--gg-accent) 70%, var(--gg-surface))',
  'color-mix(in srgb, var(--gg-brand) 30%, var(--gg-surface))',
];

function WheelFace({ slices: drawn, rotation }: { slices: Slice[]; rotation: number }) {
  const point = (degrees: number, radius = 100) => {
    const radians = ((degrees - 90) * Math.PI) / 180;
    return [100 + radius * Math.cos(radians), 100 + radius * Math.sin(radians)];
  };

  return (
    <svg
      viewBox="0 0 200 200"
      role="img"
      aria-label="Prize wheel"
      className="size-full motion-safe:transition-transform motion-safe:ease-[cubic-bezier(0.15,0.85,0.25,1)]"
      style={{
        transform: `rotate(${rotation}deg)`,
        transitionDuration: `${SPIN_MS}ms`,
      }}
    >
      {drawn.map((slice, index) => {
        const [x1, y1] = point(slice.start);
        const [x2, y2] = point(slice.end);
        const large = slice.end - slice.start > 180 ? 1 : 0;
        const whole = slice.end - slice.start >= 359.999;
        const middle = (slice.start + slice.end) / 2;
        const [lx, ly] = point(middle, 57);
        return (
          <g key={slice.segment.id}>
            {whole ? (
              <circle cx="100" cy="100" r="100" fill={TONES[index % TONES.length]} />
            ) : (
              <path
                d={`M100,100 L${x1},${y1} A100,100 0 ${large} 1 ${x2},${y2} Z`}
                fill={TONES[index % TONES.length]}
                stroke="var(--gg-surface)"
                strokeWidth="1.5"
              />
            )}
            {/* Labels only on slices wide enough to hold a line of text; the
                list beside the wheel names every segment regardless. */}
            {slice.end - slice.start >= 14 && (
              <text
                x={lx}
                y={ly}
                textAnchor="middle"
                dominantBaseline="middle"
                transform={`rotate(${labelTurn(middle)}, ${lx}, ${ly})`}
                className="fill-white text-[9px] font-medium"
              >
                <title>{slice.segment.label}</title>
                {wheelLabel(slice.segment.label)}
              </text>
            )}
          </g>
        );
      })}
      <circle cx="100" cy="100" r="10" fill="var(--gg-surface)" />
    </svg>
  );
}
