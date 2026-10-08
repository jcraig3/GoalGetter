import { useId, type ReactNode } from 'react';

/**
 * The art a badge wears (6.5).
 *
 * **Drawn here, in code, as the product's own baseline set** — the line icons
 * that stood in since 4j were placeholders waiting on artwork. Each badge is
 * an emblem (a medallion on a ribbon, a shield, a hexagon, a rosette or a
 * coin) in a metal or a jewel, with a symbol on its face. Original, so
 * nothing needs a licence, and vector, so it is as sharp on a 4K wall as in a
 * list.
 *
 * **A badge still stores a key, never a picture** — `medal`, `rocket` — so
 * changing the art is a change to this file and touches no data. Or it stores
 * `asset:<digest>`: an organization's own picture from Organization → Assets,
 * drawn as it was uploaded.
 *
 * The six keys from before (medal, trophy, target, flag, spark, team) keep
 * their meaning, so every badge already given keeps its look's intent.
 */

type Shape = 'medal' | 'shield' | 'hexagon' | 'rosette' | 'coin';

interface Finish {
  /** Rim: light, mid, dark. */
  rim: [string, string, string];
  /** Face: light, dark. */
  face: [string, string];
  /** The symbol. */
  ink: string;
  /** A medal's ribbon. */
  ribbon: string;
}

const FINISHES = {
  gold: { rim: ['#fef3c7', '#f59e0b', '#92400e'], face: ['#fcd34d', '#b45309'], ink: '#fffbeb', ribbon: '#2563eb' },
  silver: { rim: ['#f8fafc', '#94a3b8', '#334155'], face: ['#e2e8f0', '#64748b'], ink: '#ffffff', ribbon: '#dc2626' },
  bronze: { rim: ['#ffedd5', '#c2410c', '#7c2d12'], face: ['#fdba74', '#9a3412'], ink: '#fff7ed', ribbon: '#047857' },
  ruby: { rim: ['#ffe4e6', '#e11d48', '#881337'], face: ['#fb7185', '#9f1239'], ink: '#fff1f2', ribbon: '#f59e0b' },
  sapphire: { rim: ['#dbeafe', '#2563eb', '#1e3a8a'], face: ['#60a5fa', '#1e40af'], ink: '#eff6ff', ribbon: '#f59e0b' },
  emerald: { rim: ['#d1fae5', '#059669', '#064e3b'], face: ['#34d399', '#065f46'], ink: '#ecfdf5', ribbon: '#7c3aed' },
  amethyst: { rim: ['#f3e8ff', '#9333ea', '#4c1d95'], face: ['#c084fc', '#6b21a8'], ink: '#faf5ff', ribbon: '#0ea5e9' },
  ember: { rim: ['#ffedd5', '#ea580c', '#7c2d12'], face: ['#fb923c', '#c2410c'], ink: '#fff7ed', ribbon: '#1d4ed8' },
  slate: { rim: ['#f1f5f9', '#475569', '#0f172a'], face: ['#94a3b8', '#1e293b'], ink: '#f8fafc', ribbon: '#f59e0b' },
} satisfies Record<string, Finish>;

// ── Symbols, on a 64 × 64 face centred at 32,32 ────────────────────────────

const S = { stroke: 'currentColor', fill: 'none', strokeLinecap: 'round', strokeLinejoin: 'round' } as const;

const SYMBOLS: Record<string, ReactNode> = {
  star: <path d="M32 19.5l3.7 7.6 8.3 1.2-6 5.9 1.4 8.3L32 38.6l-7.4 3.9 1.4-8.3-6-5.9 8.3-1.2z" fill="currentColor" />,
  trophy: (
    <>
      <path d="M24.5 20.5h15v6.5a7.5 7.5 0 0 1-15 0z" fill="currentColor" />
      <path d="M24.5 23h-3.2a3.6 3.6 0 0 0 4.4 5.6M39.5 23h3.2a3.6 3.6 0 0 1-4.4 5.6" {...S} strokeWidth={2.2} />
      <path d="M30.2 34h3.6v5h-3.6z" fill="currentColor" />
      <path d="M25.5 39.5h13v3.5h-13z" fill="currentColor" />
    </>
  ),
  target: (
    <>
      <circle cx="32" cy="32" r="11" {...S} strokeWidth={2.6} />
      <circle cx="32" cy="32" r="6" {...S} strokeWidth={2.6} />
      <circle cx="32" cy="32" r="2.2" fill="currentColor" />
    </>
  ),
  flag: (
    <>
      <path d="M23.5 19v26" {...S} strokeWidth={2.6} />
      <path d="M24.5 20h17v12h-17z" fill="currentColor" />
      {[0, 1, 2, 3].map((col) =>
        [0, 1, 2].map((row) =>
          (col + row) % 2 === 0 ? (
            <rect key={`${col}${row}`} x={24.5 + col * 4.25} y={20 + row * 4} width={4.25} height={4} fill="#0f172a" opacity={0.55} />
          ) : null,
        ),
      )}
    </>
  ),
  spark: (
    <>
      <path d="M31 18c1.4 7.6 4.4 10.6 12 12-7.6 1.4-10.6 4.4-12 12-1.4-7.6-4.4-10.6-12-12 7.6-1.4 10.6-4.4 12-12z" fill="currentColor" />
      <path d="M42 18.5c.5 2.6 1.4 3.5 4 4-2.6.5-3.5 1.4-4 4-.5-2.6-1.4-3.5-4-4 2.6-.5 3.5-1.4 4-4z" fill="currentColor" />
    </>
  ),
  team: (
    <>
      <circle cx="32" cy="24.5" r="4.4" fill="currentColor" />
      <circle cx="22.5" cy="27.5" r="3.4" fill="currentColor" opacity={0.85} />
      <circle cx="41.5" cy="27.5" r="3.4" fill="currentColor" opacity={0.85} />
      <path d="M24 42a8 8 0 0 1 16 0z" fill="currentColor" />
      <path d="M16.5 42a6 6 0 0 1 10.5-4 9.5 9.5 0 0 0-1.6 4zM47.5 42a6 6 0 0 0-10.5-4 9.5 9.5 0 0 1 1.6 4z" fill="currentColor" opacity={0.85} />
    </>
  ),
  rocket: (
    <>
      <path d="M32 17c5.2 4 7.2 10 7.2 16.2L36.4 39h-8.8l-2.8-5.8C24.8 27 26.8 21 32 17z" fill="currentColor" />
      <circle cx="32" cy="28" r="2.8" fill="#0f172a" opacity={0.45} />
      <path d="M25.6 32.5l-4.4 7.3 5.6-1.2zM38.4 32.5l4.4 7.3-5.6-1.2z" fill="currentColor" />
      <path d="M29 40.5h6l-3 6z" fill="#fbbf24" />
    </>
  ),
  flame: (
    <>
      <path d="M32.5 16c2.2 6.2 9.5 9 9.5 18.5a10 10 0 0 1-20 0c0-5.5 3.2-7.7 4.4-12 1 3.1 2.2 4.4 4.3 5.4-.2-5.3-.6-8.3 1.8-11.9z" fill="currentColor" />
      <path d="M32 33c1 2.8 4.5 4 4.5 7.5a4.5 4.5 0 0 1-9 0c0-2.4 1.6-3.6 2.4-5.6.5 1.2 1 1.6 2.1 2.2-.2-1.6 0-2.6 0-4.1z" fill="#0f172a" opacity={0.3} />
    </>
  ),
  crown: (
    <>
      <path d="M20 40l2-16 6.5 7.5L32 20.5l3.5 11L42 24l2 16z" fill="currentColor" />
      <path d="M20.5 41.5h23v3.5h-23z" fill="currentColor" />
      <circle cx="32" cy="35" r="1.8" fill="#0f172a" opacity={0.4} />
      <circle cx="25.5" cy="36" r="1.4" fill="#0f172a" opacity={0.4} />
      <circle cx="38.5" cy="36" r="1.4" fill="#0f172a" opacity={0.4} />
    </>
  ),
  bolt: <path d="M35.5 16L23 34.5h8.2L28.5 48 41 29h-8.2z" fill="currentColor" />,
  gem: (
    <>
      <path d="M21.5 27l5.5-6.5h10l5.5 6.5L32 44.5z" fill="currentColor" />
      <path d="M21.5 27h21M27 20.5l2.5 6.5L32 44.5l2.5-17.5L37 20.5M29.5 27h5" stroke="#0f172a" strokeOpacity={0.35} strokeWidth={1.1} fill="none" strokeLinejoin="round" />
    </>
  ),
  phone: (
    <path
      d="M25.2 19.6c1.6-1 3.6-.5 4.4 1.1l2 4.1c.6 1.3.2 2.8-.9 3.7l-1.6 1.2a12.6 12.6 0 0 0 6.2 6.2l1.2-1.6c.9-1.1 2.4-1.5 3.7-.9l4.1 2c1.6.8 2.1 2.8 1.1 4.4l-1.2 1.8c-1.2 1.8-3.4 2.6-5.5 2-8.1-2.4-14.4-8.7-16.8-16.8-.6-2.1.2-4.3 2-5.5z"
      fill="currentColor"
    />
  ),
  dollar: (
    <>
      <path d="M37.5 24.5c-1-2-3.1-3.2-5.6-3.2-3.2 0-5.4 1.7-5.4 4.2 0 5.9 11.5 3.2 11.5 9.3 0 2.7-2.5 4.5-5.9 4.5-2.8 0-5.1-1.3-6.1-3.5" {...S} strokeWidth={3.2} />
      <path d="M32 17v30" {...S} strokeWidth={2.6} />
    </>
  ),
  heart: <path d="M32 44.5C21 37 18.5 31.2 18.5 27.3a6.8 6.8 0 0 1 13.5-1.2 6.8 6.8 0 0 1 13.5 1.2c0 3.9-2.5 9.7-13.5 17.2z" fill="currentColor" />,
  mountain: (
    <>
      <path d="M16.5 43.5L27 26.5l5 7.5 4.5-6.5 11 16z" fill="currentColor" />
      <path d="M27 26.5l2.8 4.2-1.6-.6-1.2 1.5-1.2-1.5-1.6.6z" fill="#0f172a" opacity={0.3} />
      <path d="M36.5 27.5v-9" {...S} strokeWidth={1.8} />
      <path d="M36.5 18.5l5.5 2.6-5.5 2.6z" fill="currentColor" />
    </>
  ),
  clock: (
    <>
      <circle cx="32" cy="32" r="11.5" {...S} strokeWidth={2.8} />
      <path d="M32 25v7.5l5 3" {...S} strokeWidth={2.8} />
    </>
  ),
  calendar: (
    <>
      <rect x="20" y="21.5" width="24" height="22" rx="3" {...S} strokeWidth={2.4} />
      <path d="M20 21.5h24v6H20z" fill="currentColor" />
      <path d="M26 19v4.5M38 19v4.5" {...S} strokeWidth={2.4} />
      <path d="M26 35l4 3.8 8-8" {...S} strokeWidth={2.8} />
    </>
  ),
  chart: (
    <>
      <path d="M21 36h5v7h-5zM29.5 31h5v12h-5zM38 25h5v18h-5z" fill="currentColor" />
      <path d="M20 29.5l8-6 5 3 9.5-7.5" {...S} strokeWidth={2.2} />
      <path d="M38.5 18.5h4.5V23" {...S} strokeWidth={2.2} />
    </>
  ),
};

// ── Shapes ──────────────────────────────────────────────────────────────────

const HEXAGON = 'M32 6.5l22 12.7v25.6L32 57.5 10 44.8V19.2z';
const SHIELD = 'M32 6l21 7.5v16.2c0 13.4-9 22.6-21 27.8-12-5.2-21-14.4-21-27.8V13.5z';
const ROSETTE = (() => {
  const points: string[] = [];
  for (let i = 0; i < 32; i += 1) {
    const r = i % 2 === 0 ? 29 : 25;
    const a = (Math.PI * 2 * i) / 32 - Math.PI / 2;
    points.push(`${(32 + r * Math.cos(a)).toFixed(2)},${(32 + r * Math.sin(a)).toFixed(2)}`);
  }
  return points.join(' ');
})();

function Outline({ shape, ...rest }: { shape: Shape } & React.SVGProps<SVGPathElement>) {
  switch (shape) {
    case 'shield':
      return <path d={SHIELD} {...rest} />;
    case 'hexagon':
      return <path d={HEXAGON} {...rest} />;
    case 'rosette':
      return <polygon points={ROSETTE} {...(rest as React.SVGProps<SVGPolygonElement>)} />;
    case 'medal':
      return <circle cx="32" cy="29" r="21" {...(rest as React.SVGProps<SVGCircleElement>)} />;
    default:
      return <circle cx="32" cy="32" r="27" {...(rest as React.SVGProps<SVGCircleElement>)} />;
  }
}

/** The face: the shape again, smaller, about its own centre. */
function inset(shape: Shape): string {
  const cy = shape === 'medal' ? 29 : 32;
  const k = shape === 'rosette' ? 0.74 : shape === 'medal' ? 0.82 : 0.84;
  return `translate(32 ${cy}) scale(${k}) translate(-32 ${-cy})`;
}

interface Art {
  label: string;
  shape: Shape;
  finish: keyof typeof FINISHES;
  symbol: keyof typeof SYMBOLS;
}

export const BADGE_MARKS = {
  medal: { label: 'Medal', shape: 'medal', finish: 'gold', symbol: 'star' },
  trophy: { label: 'Trophy', shape: 'coin', finish: 'gold', symbol: 'trophy' },
  target: { label: 'Bullseye', shape: 'coin', finish: 'ruby', symbol: 'target' },
  flag: { label: 'Finish line', shape: 'shield', finish: 'slate', symbol: 'flag' },
  spark: { label: 'Spark', shape: 'rosette', finish: 'amethyst', symbol: 'spark' },
  team: { label: 'Team player', shape: 'hexagon', finish: 'emerald', symbol: 'team' },
  rocket: { label: 'Rocket', shape: 'shield', finish: 'sapphire', symbol: 'rocket' },
  flame: { label: 'On fire', shape: 'coin', finish: 'ember', symbol: 'flame' },
  crown: { label: 'Crown', shape: 'medal', finish: 'gold', symbol: 'crown' },
  bolt: { label: 'Lightning', shape: 'hexagon', finish: 'gold', symbol: 'bolt' },
  gem: { label: 'Diamond', shape: 'rosette', finish: 'sapphire', symbol: 'gem' },
  phone: { label: 'Dialer', shape: 'coin', finish: 'emerald', symbol: 'phone' },
  dollar: { label: 'Big ticket', shape: 'medal', finish: 'emerald', symbol: 'dollar' },
  heart: { label: 'Team spirit', shape: 'coin', finish: 'ruby', symbol: 'heart' },
  mountain: { label: 'Summit', shape: 'shield', finish: 'silver', symbol: 'mountain' },
  clock: { label: 'Early bird', shape: 'hexagon', finish: 'sapphire', symbol: 'clock' },
  calendar: { label: 'Consistent', shape: 'shield', finish: 'emerald', symbol: 'calendar' },
  chart: { label: 'Climber', shape: 'rosette', finish: 'bronze', symbol: 'chart' },
} satisfies Record<string, Art>;

export type BadgeMarkKey = keyof typeof BADGE_MARKS;

/** An organization's own picture, by digest: `asset:<sha256>`. */
export const ASSET_PREFIX = 'asset:';

export function isUploaded(icon: string): boolean {
  return icon.startsWith(ASSET_PREFIX);
}

/** The drawn emblem for one key. */
function Emblem({ art, className }: { art: Art; className: string }) {
  const id = useId().replace(/:/g, '');
  const finish = FINISHES[art.finish];
  const shape = art.shape;
  return (
    <svg viewBox="0 0 64 64" className={className} aria-hidden="true">
      <defs>
        <linearGradient id={`${id}rim`} x1="0.15" y1="0" x2="0.85" y2="1">
          <stop offset="0" stopColor={finish.rim[0]} />
          <stop offset="0.45" stopColor={finish.rim[1]} />
          <stop offset="1" stopColor={finish.rim[2]} />
        </linearGradient>
        <radialGradient id={`${id}face`} cx="0.35" cy="0.3" r="0.85">
          <stop offset="0" stopColor={finish.face[0]} />
          <stop offset="1" stopColor={finish.face[1]} />
        </radialGradient>
      </defs>

      {shape === 'medal' && (
        // The ribbon, behind the medallion.
        <g>
          <path d="M22 40l-5 21 7-4 5 5 4-17z" fill={finish.ribbon} />
          <path d="M42 40l5 21-7-4-5 5-4-17z" fill={finish.ribbon} />
          <path d="M22 40l-5 21 7-4 5 5 4-17z" fill="#000" opacity={0.18} />
        </g>
      )}

      {/* A soft shadow under the whole emblem. */}
      <g transform="translate(0 1.6)" opacity={0.28}>
        <Outline shape={shape} fill="#000" />
      </g>
      <Outline shape={shape} fill={`url(#${id}rim)`} />
      <g transform={inset(shape)}>
        <Outline shape={shape} fill={`url(#${id}face)`} stroke={finish.rim[0]} strokeOpacity={0.55} strokeWidth={1.4} />
      </g>

      {/* The symbol, with a faint drop so it sits on the face. */}
      <g transform={`translate(0 ${shape === 'medal' ? -2.4 : 0.6})`}>
        <g transform="translate(0.6 1)" color="#000" opacity={0.3}>
          {SYMBOLS[art.symbol]}
        </g>
        <g color={finish.ink}>{SYMBOLS[art.symbol]}</g>
      </g>

      {/* A highlight across the top, the way light catches metal. */}
      <ellipse cx="27" cy={shape === 'medal' ? 15 : 15.5} rx="13" ry="5" fill="#fff" opacity={0.2} />
    </svg>
  );
}

/**
 * One badge's mark: the drawn emblem for its key, or the organization's own
 * picture. Falls back to the medal for a key this build does not know — a
 * badge made on a newer version — rather than drawing nothing, which would
 * read as a badge somebody does not have.
 */
export function BadgeMark({
  icon,
  className = 'h-10 w-10',
}: {
  icon: string;
  className?: string;
}) {
  if (isUploaded(icon)) {
    return (
      <img
        src={`/api/images/${icon.slice(ASSET_PREFIX.length)}`}
        alt=""
        aria-hidden="true"
        className={`${className} object-contain`}
      />
    );
  }
  const art: Art = BADGE_MARKS[icon as BadgeMarkKey] ?? BADGE_MARKS.medal;
  return <Emblem art={art} className={`${className} shrink-0`} />;
}
