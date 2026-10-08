import { useId, useMemo, type CSSProperties, type ReactNode } from 'react';

/**
 * The trophy on a celebration, and the way it arrives (6.6).
 *
 * A win used to take over the wall with an emoji. Now each kind of win has its
 * own drawn piece — a cup for a goal hit, a laurelled cup for a competition,
 * a medal for recognition, a rocket for a rule's big deal, a cake for a
 * birthday, a rosette for an anniversary — that rises in, glows, catches the
 * light, and throws confetti.
 *
 * **Original SVG and CSS**, so nothing needs a licence and it is sharp on any
 * television. **In step across screens**: the entrance is timed from when the
 * celebration began (`joinedAt`), so a screen that joins part-way shows the
 * same moment as the rest rather than replaying the entrance late. And it
 * honours reduced motion: everything appears, nothing flies.
 */

type Piece = 'cup' | 'laurel' | 'medal' | 'rocket' | 'cake' | 'rosette';

/** Which piece a win gets, by what it is for. */
export function pieceFor(eventKey: string | undefined): Piece {
  const key = eventKey ?? '';
  if (key === 'competition.won') return 'laurel';
  if (key === 'recognition') return 'medal';
  if (key.startsWith('achievement:')) return 'rocket';
  if (key === 'birthday') return 'cake';
  if (key === 'work_anniversary') return 'rosette';
  return 'cup';
}

/** A small seeded random, so every screen throws the same confetti. */
function seeded(text: string) {
  let h = 2166136261;
  for (let i = 0; i < text.length; i += 1) h = Math.imul(h ^ text.charCodeAt(i), 16777619);
  return () => {
    h += 0x6d2b79f5;
    let t = h;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const CONFETTI_COLOURS = [
  'var(--gg-brand)',
  'var(--gg-accent)',
  '#fbbf24',
  '#f472b6',
  '#38bdf8',
  '#ffffff',
];

/** How long the entrance takes, in seconds. A screen joining later starts settled. */
const ENTRANCE = 1.1;

export default function CelebrationArt({
  celebration,
  joinedAt = 0,
  photo = null,
}: {
  celebration: { id: string; event_key?: string };
  /** Seconds into the celebration this screen arrived. */
  joinedAt?: number;
  /**
   * Their photograph's URL. **The face goes inside the glow** and the piece
   * becomes its badge (7.9): a face on the wall is the most motivating thing
   * the product shows, and they had one.
   */
  photo?: string | null;
}) {
  const piece = pieceFor(celebration.event_key);
  // Negative delays put an animation part-way through, so a screen joining
  // two seconds in shows the two-second moment.
  const at = (delay: number): CSSProperties => ({ animationDelay: `${delay - joinedAt}s` });

  const confetti = useMemo(() => {
    const random = seeded(celebration.id);
    return Array.from({ length: 44 }, (_, i) => {
      const angle = random() * Math.PI * 2;
      const distance = 260 + random() * 420;
      return {
        key: i,
        colour: CONFETTI_COLOURS[i % CONFETTI_COLOURS.length]!,
        dx: Math.cos(angle) * distance,
        // Up and out, then gravity: more down than up.
        dy: Math.sin(angle) * distance * 0.6 + 260 + random() * 200,
        rot: (random() - 0.5) * 1080,
        delay: 0.35 + random() * 0.35,
        wide: random() > 0.5,
      };
    });
  }, [celebration.id]);

  return (
    <div className="relative flex h-[340px] w-[340px] items-center justify-center" aria-hidden="true">
      {/* The glow behind it. */}
      <div
        className="absolute inset-6 rounded-full bg-[radial-gradient(circle,color-mix(in_srgb,var(--gg-accent)_45%,transparent)_0%,transparent_70%)] motion-safe:animate-[gg-glow_2.4s_ease-in-out_infinite]"
        style={at(0)}
      />

      {/* Confetti, thrown once as the piece lands. */}
      <div className="pointer-events-none absolute left-1/2 top-1/2 motion-reduce:hidden">
        {confetti.map((c) => (
          <span
            key={c.key}
            className="absolute block opacity-0 motion-safe:animate-[gg-confetti_2.6s_cubic-bezier(.15,.6,.35,1)_both]"
            style={
              {
                width: c.wide ? 14 : 9,
                height: c.wide ? 7 : 14,
                background: c.colour,
                borderRadius: c.wide ? 2 : 999,
                '--dx': `${c.dx}px`,
                '--dy': `${c.dy}px`,
                '--rot': `${c.rot}deg`,
                ...at(c.delay),
              } as CSSProperties
            }
          />
        ))}
      </div>

      {/* The piece: in with a bounce, then a slow float. */}
      <div className="relative motion-safe:animate-[gg-trophy-in_1.1s_cubic-bezier(.2,.9,.3,1.2)_both]" style={at(0)}>
        <div className="motion-safe:animate-[gg-float_4s_ease-in-out_infinite]" style={at(ENTRANCE)}>
          {photo ? (
            <div className="relative">
              <img
                src={photo}
                alt=""
                data-testid="celebration-photo"
                className="size-[280px] rounded-full object-cover shadow-[0_18px_40px_rgba(0,0,0,0.5)] ring-8 ring-[color-mix(in_srgb,var(--gg-accent)_70%,white)]"
              />
              <div className="absolute -bottom-6 -right-10">
                <Piece piece={piece} small />
              </div>
            </div>
          ) : (
            <div className="relative overflow-hidden">
              <Piece piece={piece} />
              {/* Light catching the metal, once, after it lands. */}
              <div
                className="absolute inset-y-0 left-0 w-1/3 bg-gradient-to-r from-transparent via-white/45 to-transparent opacity-0 motion-safe:animate-[gg-shine_1.2s_ease-in-out_both] [mix-blend-mode:overlay]"
                style={at(ENTRANCE - 0.1)}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── The pieces, on a 200 × 220 canvas ───────────────────────────────────────

function Piece({ piece, small = false }: { piece: Piece; small?: boolean }) {
  const id = useId().replace(/:/g, '');
  const gold = `url(#${id}gold)`;
  const defs = (
    <defs>
      <linearGradient id={`${id}gold`} x1="0" y1="0" x2="1" y2="0">
        <stop offset="0" stopColor="#92400e" />
        <stop offset="0.28" stopColor="#fcd34d" />
        <stop offset="0.45" stopColor="#fffbeb" />
        <stop offset="0.68" stopColor="#f59e0b" />
        <stop offset="1" stopColor="#78350f" />
      </linearGradient>
      <linearGradient id={`${id}plinth`} x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stopColor="#374151" />
        <stop offset="1" stopColor="#111827" />
      </linearGradient>
      <linearGradient id={`${id}leaf`} x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stopColor="#fde68a" />
        <stop offset="1" stopColor="#b45309" />
      </linearGradient>
      <linearGradient id={`${id}blue`} x1="0" y1="0" x2="1" y2="0">
        <stop offset="0" stopColor="#1e3a8a" />
        <stop offset="0.4" stopColor="#60a5fa" />
        <stop offset="0.6" stopColor="#dbeafe" />
        <stop offset="1" stopColor="#1e40af" />
      </linearGradient>
      <linearGradient id={`${id}pink`} x1="0" y1="0" x2="1" y2="0">
        <stop offset="0" stopColor="#be185d" />
        <stop offset="0.45" stopColor="#f9a8d4" />
        <stop offset="1" stopColor="#9d174d" />
      </linearGradient>
    </defs>
  );

  const pieces: Record<Piece, ReactNode> = {
    cup: <Cup gold={gold} plinth={`url(#${id}plinth)`} emblem={<Star cx={100} cy={64} r={17} />} />,
    laurel: (
      <>
        <Laurel fill={`url(#${id}leaf)`} />
        <Cup gold={gold} plinth={`url(#${id}plinth)`} emblem={<text x="100" y="76" textAnchor="middle" fontSize="34" fontWeight="800" fill="#78350f" opacity="0.75" fontFamily="system-ui, sans-serif">1</text>} />
      </>
    ),
    medal: <Medal gold={gold} />,
    rocket: <Rocket hull={`url(#${id}blue)`} />,
    cake: <Cake icing={`url(#${id}pink)`} />,
    rosette: <Rosette gold={gold} />,
  };

  return (
    <svg
      viewBox="0 0 200 220"
      className={`${small ? 'h-[140px] w-[127px]' : 'h-[300px] w-[273px]'} drop-shadow-[0_18px_30px_rgba(0,0,0,0.45)]`}
    >
      {defs}
      {pieces[piece]}
    </svg>
  );
}

function Star({ cx, cy, r, fill = '#fffbeb' }: { cx: number; cy: number; r: number; fill?: string }) {
  const points: string[] = [];
  for (let i = 0; i < 10; i += 1) {
    const radius = i % 2 === 0 ? r : r * 0.42;
    const a = (Math.PI / 5) * i - Math.PI / 2;
    points.push(`${(cx + radius * Math.cos(a)).toFixed(1)},${(cy + radius * Math.sin(a)).toFixed(1)}`);
  }
  return <polygon points={points.join(' ')} fill={fill} opacity={0.92} />;
}

function Cup({ gold, plinth, emblem }: { gold: string; plinth: string; emblem: ReactNode }) {
  return (
    <g>
      {/* Handles behind the bowl. */}
      <path d="M52 44H34a20 20 0 0 0 26 34" fill="none" stroke={gold} strokeWidth="10" strokeLinecap="round" />
      <path d="M148 44h18a20 20 0 0 1-26 34" fill="none" stroke={gold} strokeWidth="10" strokeLinecap="round" />
      {/* The bowl. */}
      <path d="M48 32h104v36a52 52 0 0 1-104 0z" fill={gold} />
      <ellipse cx="100" cy="32" rx="52" ry="9" fill="#fef3c7" />
      <ellipse cx="100" cy="33" rx="45" ry="5.5" fill="#b45309" opacity="0.55" />
      {emblem}
      {/* Stem, knot and foot. */}
      <path d="M92 118h16l5 26H87z" fill={gold} />
      <ellipse cx="100" cy="120" rx="15" ry="6" fill={gold} />
      <path d="M70 144h60l7 22H63z" fill={gold} />
      {/* The plinth, with its plate. */}
      <path d="M54 166h92v26H54z" fill={plinth} />
      <rect x="76" y="172" width="48" height="13" rx="2" fill={gold} />
    </g>
  );
}

function Laurel({ fill }: { fill: string }) {
  const leaves = [];
  for (let i = 0; i < 7; i += 1) {
    const t = i / 6;
    const y = 150 - t * 120;
    const x = 30 - Math.sin(t * Math.PI) * 18;
    const angle = -60 + t * 70;
    leaves.push(
      <ellipse key={`l${i}`} cx={x} cy={y} rx="7" ry="15" fill={fill} transform={`rotate(${angle} ${x} ${y})`} />,
      <ellipse key={`r${i}`} cx={200 - x} cy={y} rx="7" ry="15" fill={fill} transform={`rotate(${-angle} ${200 - x} ${y})`} />,
    );
  }
  return <g opacity="0.95">{leaves}</g>;
}

function Medal({ gold }: { gold: string }) {
  return (
    <g>
      <path d="M62 8h30l14 70H76z" fill="#2563eb" />
      <path d="M138 8h-30L94 78h30z" fill="#1d4ed8" />
      <path d="M62 8h30l2 10H64z" fill="#000" opacity="0.15" />
      <circle cx="100" cy="134" r="62" fill={gold} />
      <circle cx="100" cy="134" r="49" fill="#b45309" opacity="0.35" />
      <circle cx="100" cy="134" r="46" fill={gold} />
      <Star cx={100} cy={134} r={30} />
    </g>
  );
}

function Rocket({ hull }: { hull: string }) {
  return (
    <g>
      {/* Flame. */}
      <path d="M84 160c4 22 10 34 16 50 6-16 12-28 16-50z" fill="#fbbf24" />
      <path d="M91 160c3 14 6 22 9 32 3-10 6-18 9-32z" fill="#fef3c7" />
      {/* Fins. */}
      <path d="M66 112L44 160l30-8z" fill="#dc2626" />
      <path d="M134 112l22 48-30-8z" fill="#dc2626" />
      {/* Body. */}
      <path d="M100 10c26 22 36 56 36 92l-10 58H74l-10-58c0-36 10-70 36-92z" fill={hull} />
      <path d="M100 10c10 9 17 19 22 30H78c5-11 12-21 22-30z" fill="#dc2626" />
      <circle cx="100" cy="86" r="17" fill="#e0f2fe" stroke="#1e3a8a" strokeWidth="6" />
      <circle cx="94" cy="80" r="5" fill="#fff" opacity="0.8" />
      <path d="M78 160h44v8H78z" fill="#1e3a8a" />
    </g>
  );
}

function Cake({ icing }: { icing: string }) {
  return (
    <g>
      {/* Candles and flames. */}
      {[70, 100, 130].map((x) => (
        <g key={x}>
          <rect x={x - 4} y="52" width="8" height="34" rx="2" fill="#a5b4fc" />
          <path d={`M${x} 30c6 8 7 14 0 20-7-6-6-12 0-20z`} fill="#fbbf24" />
        </g>
      ))}
      {/* Tiers. */}
      <rect x="48" y="86" width="104" height="44" rx="8" fill={icing} />
      <path d="M48 98c9 9 17 9 26 0s17-9 26 0 17 9 26 0 17-9 26 0V94c0-4 0-8-8-8H56c-8 0-8 4-8 8z" fill="#fdf2f8" />
      <rect x="30" y="130" width="140" height="54" rx="9" fill={icing} />
      <path d="M30 144c12 11 23 11 35 0s23-11 35 0 23 11 35 0 23-11 35 0v-5c0-5-2-9-9-9H39c-7 0-9 4-9 9z" fill="#fdf2f8" />
      <rect x="18" y="184" width="164" height="12" rx="6" fill="#e5e7eb" />
    </g>
  );
}

function Rosette({ gold }: { gold: string }) {
  const petals: string[] = [];
  for (let i = 0; i < 24; i += 1) {
    const r = i % 2 === 0 ? 70 : 58;
    const a = (Math.PI * 2 * i) / 24 - Math.PI / 2;
    petals.push(`${(100 + r * Math.cos(a)).toFixed(1)},${(84 + r * Math.sin(a)).toFixed(1)}`);
  }
  return (
    <g>
      <path d="M72 130l-16 82 22-12 16 16 8-80z" fill="#7c3aed" />
      <path d="M128 130l16 82-22-12-16 16-8-80z" fill="#6d28d9" />
      <polygon points={petals.join(' ')} fill="#8b5cf6" />
      <circle cx="100" cy="84" r="50" fill={gold} />
      <circle cx="100" cy="84" r="40" fill="#b45309" opacity="0.3" />
      <circle cx="100" cy="84" r="37" fill={gold} />
      <Star cx={100} cy={84} r={24} />
    </g>
  );
}
