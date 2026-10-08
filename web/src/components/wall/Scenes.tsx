import { useMemo, type CSSProperties, type ReactNode } from 'react';

/**
 * Drawn backgrounds (6.9): illustrated and abstract scenes, rendered in code
 * on the wall itself.
 *
 * **No licence, and the organization's colours.** Each scene is drawn from
 * three colours — the background's `color`, `color_mid` and `color_to` — so
 * the same scene can be the product's own or the brand's. They are percent-
 * based throughout, so a scene fills a 4K wall, a phone preview or a library
 * swatch the same way.
 *
 * **Movement is a layer moving, never a repaint.** Waves slide, lights rise,
 * confetti falls: every animation is a `transform` on a layer the
 * television's graphics chip moves on its own, so a cheap stick does not
 * stutter. All of it stops for anybody who asked their device for less
 * motion (`motion-safe`), and the scene stands still rather than vanishing.
 *
 * The names here must match `SCENES` in `api/app/appearance.py`.
 */

export const SCENE_NAMES: Record<string, string> = {
  waves: 'Ocean waves',
  mesh: 'Aurora mesh',
  bokeh: 'Bokeh lights',
  grid: 'Synthwave grid',
  lowpoly: 'Low-poly',
  skyline: 'Skyline at dusk',
  confetti: 'Confetti',
  contours: 'Contour lines',
};

interface Colours {
  base: string;
  mid: string;
  top: string;
}

/** A small seeded random, so every screen draws the same scene. */
function seeded(seed: number) {
  let h = seed >>> 0;
  return () => {
    h += 0x6d2b79f5;
    let t = h;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export default function Scene({
  scene,
  colours,
  moving,
}: {
  scene: string;
  colours: Colours;
  moving: boolean;
}) {
  const Draw = SCENES[scene] ?? SCENES.mesh!;
  return (
    <div className="absolute inset-0 overflow-hidden" data-scene={scene} style={{ backgroundColor: colours.base }}>
      <Draw c={colours} moving={moving} />
    </div>
  );
}

type Drawing = (props: { c: Colours; moving: boolean }) => ReactNode;

const SCENES: Record<string, Drawing> = {
  waves: ({ c, moving }) => (
    <>
      <div className="absolute inset-0" style={{ background: `linear-gradient(180deg, ${c.base} 0%, ${c.mid} 100%)` }} />
      {[
        { h: '46%', colour: c.mid, o: 0.55, d: '34s' },
        { h: '36%', colour: c.top, o: 0.45, d: '24s' },
        { h: '26%', colour: c.base, o: 0.65, d: '16s' },
      ].map((w, i) => (
        <div key={i} className="absolute inset-x-0 bottom-0" style={{ height: w.h }}>
          <div
            className={`absolute inset-y-0 left-0 w-[200%] ${moving ? 'motion-safe:animate-[gg-slide-x_var(--d)_linear_infinite]' : ''}`}
            style={{ '--d': w.d } as CSSProperties}
          >
            <svg viewBox="0 0 400 100" preserveAspectRatio="none" className="h-full w-full">
              <path
                d={`M0 ${30 + i * 8} ${Array.from({ length: 8 }, (_, k) => `Q${k * 50 + 25} ${10 + i * 8} ${k * 50 + 50} ${30 + i * 8}`).join(' ')} V100 H0 Z`}
                fill={w.colour}
                opacity={w.o}
              />
            </svg>
          </div>
        </div>
      ))}
    </>
  ),

  mesh: ({ c, moving }) => (
    <>
      {[
        { x: '10%', y: '15%', s: '55%', colour: c.mid, d: '26s' },
        { x: '55%', y: '5%', s: '60%', colour: c.top, d: '32s' },
        { x: '35%', y: '55%', s: '65%', colour: c.mid, d: '38s' },
        { x: '75%', y: '60%', s: '45%', colour: c.top, d: '29s' },
      ].map((b, i) => (
        <div
          key={i}
          className={`absolute aspect-square -translate-x-1/4 -translate-y-1/4 rounded-full ${moving ? 'motion-safe:animate-[gg-blob_var(--d)_ease-in-out_infinite_alternate]' : ''}`}
          style={
            {
              left: b.x,
              top: b.y,
              width: b.s,
              background: `radial-gradient(circle, ${b.colour} 0%, ${b.colour}aa 22%, transparent 70%)`,
              opacity: 0.85,
              '--d': b.d,
              animationDelay: `${-i * 7}s`,
            } as CSSProperties
          }
        />
      ))}
    </>
  ),

  bokeh: ({ c, moving }) => <Bokeh c={c} moving={moving} />,

  grid: ({ c, moving }) => (
    <>
      <div className="absolute inset-x-0 top-0 h-[58%]" style={{ background: `linear-gradient(180deg, ${c.base} 0%, ${c.mid} 100%)` }} />
      {/* The sun on the horizon, banded. */}
      <div
        className="absolute left-1/2 top-[22%] aspect-square w-[26%] -translate-x-1/2 rounded-full"
        style={{
          background: `linear-gradient(180deg, ${c.top} 0%, ${c.mid} 100%)`,
          maskImage: 'linear-gradient(180deg, #000 0 55%, transparent 55% 60%, #000 60% 68%, transparent 68% 72%, #000 72% 78%, transparent 78% 82%, #000 82% 86%, transparent 86%)',
          WebkitMaskImage: 'linear-gradient(180deg, #000 0 55%, transparent 55% 60%, #000 60% 68%, transparent 68% 72%, #000 72% 78%, transparent 78% 82%, #000 82% 86%, transparent 86%)',
          boxShadow: `0 0 8vmin ${c.mid}`,
        }}
      />
      {/* The perspective is in the floor's own height (`cqh`), so the grid
          recedes the same way in a library swatch and on a 4K wall. */}
      <div
        className="absolute inset-x-0 bottom-0 h-[42%] overflow-hidden"
        style={{ background: c.base, perspective: '420cqh', containerType: 'size' }}
      >
        <div className="absolute -inset-x-1/2 bottom-0 top-0 origin-top" style={{ transform: 'rotateX(68deg)' }}>
          <div
            className={`absolute inset-x-0 -top-full h-[300%] ${moving ? 'motion-safe:animate-[gg-slide-y_6s_linear_infinite]' : ''}`}
            style={{
              backgroundImage: `linear-gradient(${c.top} 2px, transparent 2px), linear-gradient(90deg, ${c.top} 2px, transparent 2px)`,
              backgroundSize: '6% 6%',
              opacity: 0.55,
            }}
          />
        </div>
        <div className="absolute inset-x-0 top-0 h-1/3" style={{ background: `linear-gradient(180deg, ${c.mid}66, transparent)` }} />
      </div>
    </>
  ),

  lowpoly: ({ c }) => <LowPoly c={c} />,

  skyline: ({ c, moving }) => <Skyline c={c} moving={moving} />,

  confetti: ({ c, moving }) => <Confetti c={c} moving={moving} />,

  contours: ({ c }) => <Contours c={c} />,
};

function Bokeh({ c, moving }: { c: Colours; moving: boolean }) {
  const lights = useMemo(() => {
    const r = seeded(7);
    return Array.from({ length: 26 }, (_, i) => ({
      x: r() * 100,
      size: 4 + r() * 12,
      colour: i % 3 === 0 ? c.top : c.mid,
      duration: 26 + r() * 30,
      delay: -r() * 50,
      opacity: 0.25 + r() * 0.45,
    }));
  }, [c.mid, c.top]);
  return (
    <>
      <div className="absolute inset-0" style={{ background: `radial-gradient(ellipse at 50% 120%, ${c.mid}55, transparent 60%)` }} />
      {lights.map((l, i) => (
        // A column the scene's full height carries each light, so it rises
        // through the scene's own height — a library swatch or a 4K wall.
        <div
          key={i}
          className={`absolute inset-y-0 ${moving ? 'motion-safe:animate-[gg-rise_var(--d)_linear_infinite]' : ''}`}
          style={
            {
              left: `${l.x}%`,
              width: `${l.size}%`,
              transform: moving ? undefined : `translateY(${(i * 37) % 85}%)`,
              '--d': `${l.duration}s`,
              animationDelay: `${l.delay}s`,
            } as CSSProperties
          }
        >
          <span
            className="absolute inset-x-0 top-0 block aspect-square rounded-full"
            style={{
              background: `radial-gradient(circle, ${l.colour} 0%, ${l.colour}88 45%, transparent 70%)`,
              opacity: l.opacity,
            }}
          />
        </div>
      ))}
    </>
  );
}

/** `#rrggbb` blended towards another by t, 0–1. Anything else passes through. */
function mix(a: string, b: string, t: number): string {
  const hex = (h: string) => /^#[0-9a-f]{6}$/i.test(h);
  if (!hex(a) || !hex(b)) return t < 0.5 ? a : b;
  const ch = (h: string, i: number) => parseInt(h.slice(1 + i * 2, 3 + i * 2), 16);
  const out = [0, 1, 2].map((i) => Math.round(ch(a, i) + (ch(b, i) - ch(a, i)) * t));
  return `#${out.map((v) => v.toString(16).padStart(2, '0')).join('')}`;
}

function LowPoly({ c }: { c: Colours }) {
  const triangles = useMemo(() => {
    const r = seeded(11);
    const cols = 12;
    const rows = 7;
    const points: [number, number][][] = [];
    for (let y = 0; y <= rows; y += 1) {
      const row: [number, number][] = [];
      for (let x = 0; x <= cols; x += 1) {
        const jitter = (edge: boolean) => (edge ? 0 : (r() - 0.5) * 9);
        row.push([
          (x / cols) * 160 + jitter(x === 0 || x === cols),
          (y / rows) * 90 + jitter(y === 0 || y === rows),
        ]);
      }
      points.push(row);
    }
    const out: { d: string; t: number; shade: number }[] = [];
    for (let y = 0; y < rows; y += 1) {
      for (let x = 0; x < cols; x += 1) {
        const a = points[y]![x]!;
        const b = points[y]![x + 1]!;
        const d = points[y + 1]![x]!;
        const e = points[y + 1]![x + 1]!;
        const t = (x + y) / (cols + rows);
        out.push({ d: `M${a} L${b} L${e} Z`, t, shade: r() });
        out.push({ d: `M${a} L${e} L${d} Z`, t, shade: r() });
      }
    }
    return out;
  }, []);
  const colourAt = (t: number, shade: number) => {
    const ramp = t < 0.5 ? mix(c.base, c.mid, t * 2) : mix(c.mid, c.top, (t - 0.5) * 2);
    // Light from the top left: each facet a touch lighter or darker.
    return mix(ramp, shade > 0.5 ? '#ffffff' : '#000000', Math.abs(shade - 0.5) * 0.22);
  };
  return (
    <svg viewBox="0 0 160 90" preserveAspectRatio="xMidYMid slice" className="absolute inset-0 h-full w-full">
      {triangles.map((tri, i) => {
        const fill = colourAt(Math.min(1, tri.t * 1.1), tri.shade);
        return <path key={i} d={tri.d} fill={fill} stroke={fill} strokeWidth="0.2" strokeLinejoin="round" />;
      })}
    </svg>
  );
}

function Skyline({ c, moving }: { c: Colours; moving: boolean }) {
  const city = useMemo(() => {
    const r = seeded(23);
    const far: { x: number; w: number; h: number }[] = [];
    const near: { x: number; w: number; h: number; windows: { x: number; y: number; lit: boolean; slow: boolean }[] }[] = [];
    for (let x = 0; x < 200; x += 6 + r() * 6) far.push({ x, w: 5 + r() * 6, h: 18 + r() * 22 });
    for (let x = -2; x < 200; x += 9 + r() * 7) {
      const w = 8 + r() * 8;
      const h = 14 + r() * 26;
      const windows = [];
      for (let wy = 100 - h + 3; wy < 96; wy += 3.2) {
        for (let wx = x + 1.5; wx < x + w - 1.5; wx += 2.6) {
          windows.push({ x: wx, y: wy, lit: r() > 0.62, slow: r() > 0.8 });
        }
      }
      near.push({ x, w, h, windows });
    }
    return { far, near };
  }, []);
  return (
    <>
      <div className="absolute inset-0" style={{ background: `linear-gradient(180deg, ${c.base} 0%, ${c.mid} 62%, ${c.top} 100%)` }} />
      <div className="absolute left-[62%] top-[48%] aspect-square w-[16%] rounded-full" style={{ background: `radial-gradient(circle, ${c.top} 0%, ${c.top}55 45%, transparent 70%)` }} />
      <svg viewBox="0 0 200 100" preserveAspectRatio="xMidYMax slice" className="absolute inset-0 h-full w-full">
        {city.far.map((b, i) => (
          <rect key={`f${i}`} x={b.x} y={100 - b.h - 6} width={b.w} height={b.h + 6} fill={c.base} opacity="0.55" />
        ))}
        {city.near.map((b, i) => (
          <g key={`n${i}`}>
            <rect x={b.x} y={100 - b.h} width={b.w} height={b.h} fill="#05070c" />
            {b.windows.map((w, k) =>
              w.lit ? (
                <rect
                  key={k}
                  x={w.x}
                  y={w.y}
                  width="1.2"
                  height="1.5"
                  fill="#fde68a"
                  opacity="0.85"
                  className={w.slow && moving ? 'motion-safe:animate-[gg-twinkle_7s_ease-in-out_infinite]' : ''}
                  style={{ animationDelay: `${-(k % 7)}s` }}
                />
              ) : null,
            )}
          </g>
        ))}
      </svg>
    </>
  );
}

function Confetti({ c, moving }: { c: Colours; moving: boolean }) {
  const pieces = useMemo(() => {
    const r = seeded(31);
    const palette = [c.mid, c.top, '#ffffff', '#f472b6', '#38bdf8'];
    return Array.from({ length: 46 }, (_, i) => ({
      x: r() * 100,
      y: r() * 100,
      colour: palette[i % palette.length]!,
      wide: r() > 0.5,
      duration: 14 + r() * 16,
      delay: -r() * 30,
      spin: (r() - 0.5) * 720,
      tilt: r() * 360,
    }));
  }, [c.mid, c.top]);
  return (
    <>
      <div className="absolute inset-0" style={{ background: `radial-gradient(ellipse at 50% 0%, ${c.mid}33, transparent 60%)` }} />
      {pieces.map((p, i) => (
        // Falling through the scene's own height, like the bokeh.
        <div
          key={i}
          className={`absolute inset-y-0 ${moving ? 'motion-safe:animate-[gg-fall_var(--d)_linear_infinite]' : ''}`}
          style={
            {
              left: `${p.x}%`,
              width: p.wide ? '1.5%' : '0.8%',
              transform: moving ? undefined : `translateY(${p.y}%)`,
              '--d': `${p.duration}s`,
              animationDelay: `${p.delay}s`,
            } as CSSProperties
          }
        >
          <span
            className="absolute inset-x-0 top-0 block"
            style={{
              aspectRatio: p.wide ? '2.2 / 1' : '1 / 2',
              background: p.colour,
              borderRadius: p.wide ? '15%' : '40%',
              opacity: 0.8,
              transform: `rotate(${p.tilt}deg)`,
            }}
          />
        </div>
      ))}
    </>
  );
}

function Contours({ c }: { c: Colours }) {
  const rings = useMemo(() => {
    const out: { d: string; colour: string; o: number }[] = [];
    const peaks = [
      { cx: 48, cy: 34, n: 11, seed: 3 },
      { cx: 128, cy: 62, n: 9, seed: 5 },
    ];
    for (const p of peaks) {
      for (let k = 1; k <= p.n; k += 1) {
        const radius = k * 5.2;
        const pts: string[] = [];
        for (let a = 0; a <= 64; a += 1) {
          const t = (a / 64) * Math.PI * 2;
          const wobble = 1 + 0.12 * Math.sin(t * 3 + p.seed + k * 0.4) + 0.06 * Math.sin(t * 5 + k);
          pts.push(`${(p.cx + Math.cos(t) * radius * wobble * 1.3).toFixed(2)},${(p.cy + Math.sin(t) * radius * wobble).toFixed(2)}`);
        }
        out.push({ d: `M${pts.join(' L')} Z`, colour: k % 4 === 0 ? c.top : c.mid, o: k % 4 === 0 ? 0.7 : 0.45 });
      }
    }
    return out;
  }, [c.mid, c.top]);
  return (
    <svg viewBox="0 0 160 90" preserveAspectRatio="xMidYMid slice" className="absolute inset-0 h-full w-full">
      <rect width="160" height="90" fill={c.base} />
      {rings.map((r, i) => (
        <path key={i} d={r.d} fill="none" stroke={r.colour} strokeWidth="0.35" opacity={r.o} />
      ))}
    </svg>
  );
}
