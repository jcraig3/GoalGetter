import type { ReactElement } from 'react';

import MetricValue from '../MetricValue';
import { hasRing } from '../ring';
import { FacePicture, MarkLabel, markColour } from './entryLook';
import { RACE_PIECES } from './Race';
import { useWallShape } from './WallStage';
import { sessionImageUrl, type Entry, type ImageUrl, type Slide } from './types';
import NobodyYet, { nobodyYet } from './NobodyYet';

/**
 * Three more game boards (6.8): a regatta, a mountain climb and a space race.
 *
 * **Layouts, like the race track** (`Race.tsx`): each reads the same ranked
 * slide, with every entrant's share of the finish line worked out by the
 * server (`app/game_boards.py`), and keeps the wall's background, type and
 * panels. Only the scene and the pieces differ. Every piece takes the
 * entrant's colour — the ring they bought, their team's colour, or their own
 * — and anybody can move their own face instead.
 *
 * **Drawn here, in code**, as simple silhouettes: read at three metres, where
 * a shape is everything and detail is noise.
 */

export type Family = 'regatta' | 'climb' | 'space';

export const GAME_FAMILIES: Family[] = ['regatta', 'climb', 'space'];

/** Names for the families and pieces, for the layout pickers and the piece picker. */
export const FAMILY_LABELS: Record<string, string> = {
  race: 'Race track',
  regatta: 'Regatta',
  climb: 'Summit',
  space: 'Space race',
};

export const PIECE_LABELS: Record<string, string> = {
  face: 'My face',
  car: 'Car',
  truck: 'Truck',
  bike: 'Bike',
  sailboat: 'Sailboat',
  speedboat: 'Speedboat',
  duck: 'Duck',
  climber: 'Climber',
  goat: 'Mountain goat',
  balloon: 'Hot-air balloon',
  rocket: 'Rocket',
  ufo: 'UFO',
  comet: 'Comet',
};

/** Each family's own pieces — the same lists the server accepts (`app/game_boards.py`). */
const FAMILY_PIECES: Record<Family, string[]> = {
  regatta: ['sailboat', 'speedboat', 'duck'],
  climb: ['climber', 'goat', 'balloon'],
  space: ['rocket', 'ufo', 'comet'],
};

/** Eight at most, for the same reason as the race: past that, nothing reads from across a room. */
const MAX = 8;

export default function GameBoard({
  slide,
  family,
  imageUrl = sessionImageUrl,
  rows = 10,
  showValues = true,
}: {
  slide: Slide;
  family: Family;
  imageUrl?: ImageUrl;
  rows?: number;
  showValues?: boolean;
}) {
  const entrants = slide.entries.slice(0, Math.min(rows, MAX));
  if (nobodyYet(slide) || entrants.length === 0) {
    return <NobodyYet slide={slide} />;
  }
  const format = {
    unit: slide.unit ?? 'count',
    decimal_places: slide.decimal_places,
    unit_label: slide.unit_label,
  };
  const hasLine = slide.finish_line !== null && slide.finish_line !== undefined;
  const props = { entrants, imageUrl, showValues, format, hasLine };

  return (
    <div data-family={family}>
      <div className="mb-3 flex justify-end text-wall-xl text-content-muted">
        {hasLine ? (
          <span>
            {family === 'climb' ? 'Summit' : family === 'space' ? 'The Moon' : 'Finish'} ·{' '}
            <MetricValue value={slide.finish_line as string} format={format} />
          </span>
        ) : (
          <span>Measured against the leader</span>
        )}
      </div>
      {family === 'regatta' ? <Regatta {...props} /> : <Vertical family={family} {...props} />}
    </div>
  );
}

interface BoardProps {
  entrants: Entry[];
  imageUrl: ImageUrl;
  showValues: boolean;
  format: { unit: string; decimal_places: number; unit_label?: string | null };
  hasLine: boolean;
}

const fraction = (entry: Entry) => Math.max(0, Math.min(entry.progress ?? 0, 1));

// ── Regatta: lanes of water, left to right ──────────────────────────────────

function Regatta({ entrants, imageUrl, showValues, format }: BoardProps) {
  return (
    <ol className="space-y-3">
      {entrants.map((entry) => {
        const percent = fraction(entry) * 100;
        return (
          <li
            key={entry.entity_id}
            className={`wall-panel flex items-center gap-6 px-6 py-3 ${entry.finished ? 'ring-2 ring-gold' : ''}`}
          >
            <span className="w-12 shrink-0 text-right text-wall-3xl tabular-nums text-content-subtle">
              {entry.rank}
            </span>
            <span className="w-[22%] shrink-0 truncate text-wall-3xl text-content">{entry.entity_name}</span>
            <div className="relative h-[3.4em] min-w-0 flex-1 overflow-hidden rounded-full text-wall-base">
              {/* Water, with its waves. */}
              <div className="absolute inset-0 bg-gradient-to-b from-sky-500/25 to-blue-700/35" />
              <svg className="absolute inset-0 h-full w-full opacity-40" preserveAspectRatio="none" viewBox="0 0 200 20" aria-hidden="true">
                <path d="M0 7 Q5 4 10 7 T20 7 T30 7 T40 7 T50 7 T60 7 T70 7 T80 7 T90 7 T100 7 T110 7 T120 7 T130 7 T140 7 T150 7 T160 7 T170 7 T180 7 T190 7 T200 7" fill="none" stroke="#e0f2fe" strokeWidth="0.8" />
                <path d="M0 14 Q5 11 10 14 T20 14 T30 14 T40 14 T50 14 T60 14 T70 14 T80 14 T90 14 T100 14 T110 14 T120 14 T130 14 T140 14 T150 14 T160 14 T170 14 T180 14 T190 14 T200 14" fill="none" stroke="#e0f2fe" strokeWidth="0.6" />
              </svg>
              {/* The wake behind the piece. */}
              <div
                className="absolute left-0 top-1/2 h-[0.35em] -translate-y-1/2 rounded-full bg-white/50 motion-safe:transition-[width] motion-safe:duration-1000"
                style={{ width: `calc(${percent}% - ${(fraction(entry) * 3.6).toFixed(3)}em + 1.6em)` }}
              />
              <div className="absolute inset-y-0 left-0 right-[3.6em]">
                <div
                  className="absolute top-1/2 -translate-y-1/2 motion-safe:transition-[left] motion-safe:duration-1000 motion-safe:ease-out"
                  style={{ left: `${percent}%` }}
                >
                  <Piece entry={entry} imageUrl={imageUrl} family="regatta" />
                </div>
              </div>
            </div>
            {/* The finishing buoy. */}
            <svg viewBox="0 0 24 40" className="h-[3em] w-[1.8em] shrink-0 text-wall-base" aria-hidden="true">
              <path d="M12 4v8" stroke="#e5e7eb" strokeWidth="2" />
              <path d="M12 4l7 3-7 3z" fill="#facc15" />
              <path d="M5 20a7 7 0 0 1 14 0v8H5z" fill="#ef4444" />
              <path d="M5 23h14v3H5z" fill="#fff" />
              <path d="M2 30q5-3 10 0t10 0" fill="none" stroke="#bae6fd" strokeWidth="2" />
            </svg>
            {showValues && (
              <MetricValue value={entry.value} format={format} className="w-[7em] shrink-0 text-right text-wall-3xl text-content" />
            )}
          </li>
        );
      })}
    </ol>
  );
}

// ── Summit and Space race: columns, bottom to top ──────────────────────────

function Vertical({ family, entrants, imageUrl, showValues, format }: BoardProps & { family: Family }) {
  // **Twice as tall on a portrait wall** (6.11) — a climb is a vertical thing,
  // and a screen on its side is the one shape that suits it — with names
  // over two lines, because eight columns in 1080 pixels leave little width.
  const portrait = useWallShape() === 'portrait';
  return (
    <div className="wall-panel relative overflow-hidden px-6 pt-6 pb-4">
      {family === 'climb' ? <MountainScene /> : <SpaceScene />}
      <div className={`relative flex text-wall-base ${portrait ? 'h-[64em]' : 'h-[30em]'}`}>
        {entrants.map((entry) => {
          const up = fraction(entry);
          return (
            <div key={entry.entity_id} className="relative flex-1">
              {/* The way up: a rope on the mountain, a trajectory in space. */}
              <div
                className={`absolute inset-y-[1.5em] left-1/2 w-0 -translate-x-1/2 border-l-2 ${
                  family === 'climb' ? 'border-dashed border-white/35' : 'border-dotted border-sky-200/30'
                }`}
              />
              <div
                className={`absolute bottom-[1.5em] left-1/2 w-[0.4em] -translate-x-1/2 rounded-full motion-safe:transition-[height] motion-safe:duration-1000 ${
                  family === 'climb' ? 'bg-white/45' : 'bg-gradient-to-t from-amber-300/70 to-transparent'
                }`}
                style={{ height: `calc(${up * 100}% - ${(up * 3).toFixed(3)}em)` }}
              />
              {/* A box one piece shorter than the column, so at the top the
                  piece sits at the summit rather than past it. */}
              <div className="absolute inset-x-0 top-[3.6em] bottom-0">
                <div
                  className="absolute left-1/2 -translate-x-1/2 motion-safe:transition-[bottom] motion-safe:duration-1000 motion-safe:ease-out"
                  style={{ bottom: `${up * 100}%` }}
                >
                  <div className={entry.finished ? 'rounded-full ring-4 ring-gold' : ''}>
                    <Piece entry={entry} imageUrl={imageUrl} family={family} />
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
      {/* Who is in each column, and how far they are. */}
      <div className="relative mt-3 flex gap-2">
        {entrants.map((entry) => (
          <div key={entry.entity_id} className="min-w-0 flex-1 text-center">
            <p className={`text-wall-xl text-content ${portrait ? 'line-clamp-2 break-words' : 'truncate'}`}>
              <span className="text-content-subtle">{entry.rank}</span> {entry.entity_name}
            </p>
            {showValues && (
              <MetricValue value={entry.value} format={format} className="text-wall-xl text-content-muted" />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

/** Mountains behind the columns, with the summit flag at the top. */
function MountainScene() {
  return (
    <svg className="absolute inset-0 h-full w-full" preserveAspectRatio="none" viewBox="0 0 400 300" aria-hidden="true">
      <defs>
        <linearGradient id="gg-sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#0ea5e9" stopOpacity="0.18" />
          <stop offset="1" stopColor="#0ea5e9" stopOpacity="0" />
        </linearGradient>
      </defs>
      <rect width="400" height="300" fill="url(#gg-sky)" />
      <path d="M-20 300 L90 120 L150 190 L200 40 L260 170 L310 110 L420 300 Z" fill="#334155" opacity="0.75" />
      <path d="M200 40 L222 88 L208 80 L200 94 L190 80 L178 88 Z" fill="#f8fafc" opacity="0.85" />
      <path d="M90 120 L104 143 L94 138 L86 146 L80 140 Z" fill="#f8fafc" opacity="0.7" />
      <path d="M-20 300 L60 210 L130 260 L220 180 L330 250 L420 200 L420 300 Z" fill="#1e293b" opacity="0.85" />
      <path d="M200 40 V18" stroke="#e2e8f0" strokeWidth="1.5" />
      <path d="M200 18 L214 23 L200 28 Z" fill="var(--gg-accent)" />
    </svg>
  );
}

/** Stars, the Earth below and the Moon above. */
function SpaceScene() {
  // Scattered, not in a line: a hash of each index, so every screen draws the
  // same sky.
  const stars = Array.from({ length: 90 }, (_, i) => {
    const a = Math.sin(i * 12.9898) * 43758.5453;
    const b = Math.sin(i * 78.233) * 12543.1234;
    return { x: (a - Math.floor(a)) * 100, y: (b - Math.floor(b)) * 82, big: i % 9 === 0 };
  });
  return (
    <div className="absolute inset-0 overflow-hidden" aria-hidden="true">
      <div className="absolute inset-0 bg-gradient-to-b from-[#020617]/80 via-[#0b1030]/70 to-[#0b1030]/40" />
      {stars.map((star, i) => (
        <span
          key={i}
          className="absolute rounded-full bg-slate-100"
          style={{
            left: `${star.x}%`,
            top: `${star.y}%`,
            width: star.big ? '0.35em' : '0.18em',
            height: star.big ? '0.35em' : '0.18em',
            opacity: 0.35 + (i % 5) * 0.13,
          }}
        />
      ))}
      {/* The Moon, top right: where the leader is going. */}
      <div className="absolute right-[4%] top-[5%] size-[6em] rounded-full bg-gradient-to-br from-slate-100 to-slate-400 shadow-[0_0_2.5em_rgba(226,232,240,0.35)]">
        <span className="absolute left-[24%] top-[30%] size-[1.2em] rounded-full bg-slate-400/70" />
        <span className="absolute left-[58%] top-[56%] size-[0.9em] rounded-full bg-slate-400/70" />
        <span className="absolute left-[52%] top-[18%] size-[0.6em] rounded-full bg-slate-400/60" />
      </div>
      {/* The Earth, along the bottom: where everybody starts. */}
      <div className="absolute -bottom-[9em] -left-[10%] -right-[10%] h-[10em] rounded-[50%] bg-gradient-to-b from-sky-500 to-blue-900 shadow-[0_-0.6em_2em_rgba(56,189,248,0.45)]">
        <span className="absolute left-[22%] top-[10%] h-[2.2em] w-[16%] rounded-[50%] bg-emerald-600/80" />
        <span className="absolute left-[58%] top-[16%] h-[1.6em] w-[12%] rounded-[50%] bg-emerald-600/80" />
      </div>
    </div>
  );
}

// ── Pieces ─────────────────────────────────────────────────────────────────

function Piece({ entry, imageUrl, family }: { entry: Entry; imageUrl: ImageUrl; family: Family }) {
  const colour = hasRing(entry.ring) ? (entry.ring as string) : markColour(entry);
  // Only this family's pieces: anything else — a sample slide's car, a piece
  // from another board — is drawn as the entrant's face.
  const token = entry.token && FAMILY_PIECES[family].includes(entry.token) ? entry.token : 'face';

  if (token === 'face' || !DRAWINGS[token]) {
    const style = { outline: `0.15em solid ${colour}`, outlineOffset: '0.08em' };
    return entry.photo_digest ? (
      <FacePicture
        entry={entry}
        src={imageUrl(entry.photo_digest)}
        style={style}
        className="size-[3em] rounded-full"
      />
    ) : (
      <span
        aria-hidden="true"
        style={{ backgroundColor: colour, ...style }}
        className="grid size-[3em] place-items-center rounded-full text-[1.1em] font-semibold text-white"
      >
        <MarkLabel entry={entry} />
      </span>
    );
  }

  return <PieceArt token={token} colour={colour} className={family === 'regatta' ? 'h-[3em] w-[4.8em]' : 'h-[3.6em] w-[3.6em]'} />;
}

/** One piece's drawing, alone — for the boards, and for the piece picker. */
export function PieceArt({ token, colour, className }: { token: string; colour: string; className?: string }) {
  // The race's own pieces are drawn with the race (`Race.tsx`).
  const race = RACE_PIECES[token];
  if (race) {
    return (
      <svg viewBox="0 0 64 40" aria-hidden="true" className={`block ${className ?? 'h-10 w-10'}`} data-token={token}>
        {race(colour)}
      </svg>
    );
  }
  const draw = DRAWINGS[token];
  if (!draw) return null;
  return (
    <svg viewBox={draw.box} aria-hidden="true" className={`block ${className ?? 'h-10 w-10'}`} data-token={token}>
      {draw.art(colour)}
    </svg>
  );
}

const DRAWINGS: Record<string, { box: string; art: (colour: string) => ReactElement }> = {
  sailboat: {
    box: '0 0 64 40',
    art: (c) => (
      <>
        <path d="M30 4 V28" stroke="#e5e7eb" strokeWidth="2" />
        <path d="M31 5 L50 26 H31 Z" fill="#f8fafc" />
        <path d="M29 9 L16 26 H29 Z" fill="#e2e8f0" />
        <path d="M6 29 H58 L50 37 H14 Z" fill={c} />
        <path d="M2 38 Q10 35 18 38 T34 38 T50 38 T62 38" fill="none" stroke="#bae6fd" strokeWidth="1.5" />
      </>
    ),
  },
  speedboat: {
    box: '0 0 64 40',
    art: (c) => (
      <>
        <path d="M4 24 H44 L58 20 L54 32 H10 Z" fill={c} />
        <path d="M26 24 L32 15 H42 L44 24 Z" fill="rgba(255,255,255,0.6)" />
        <path d="M10 32 H54" stroke="#0b0e14" strokeOpacity="0.35" strokeWidth="2" />
        <path d="M0 30 Q-2 34 4 36 M4 26 Q-4 30 0 36" fill="none" stroke="#e0f2fe" strokeWidth="1.5" />
      </>
    ),
  },
  duck: {
    box: '0 0 64 40',
    art: (c) => (
      <>
        <path d="M10 22 Q10 34 30 34 Q48 34 52 24 Q44 26 40 22 Q36 18 26 20 Q14 18 10 22 Z" fill={c} />
        <circle cx="44" cy="15" r="7" fill={c} />
        <path d="M50 15 L59 17 L50 19 Z" fill="#f97316" />
        <circle cx="46" cy="13" r="1.3" fill="#0b0e14" />
        <path d="M22 24 Q28 28 34 24" fill="none" stroke="rgba(255,255,255,0.55)" strokeWidth="2" strokeLinecap="round" />
      </>
    ),
  },
  climber: {
    box: '0 0 48 48',
    art: (c) => (
      <>
        <circle cx="24" cy="9" r="5" fill="#f1f5f9" />
        <path d="M18 7 Q24 1 30 7 Z" fill={c} />
        <rect x="16" y="15" width="16" height="15" rx="4" fill={c} />
        <rect x="28" y="16" width="8" height="12" rx="2" fill="#475569" />
        <path d="M18 30 L14 42 M30 30 L34 42 M16 19 L8 12 M32 19 L40 14" stroke="#f1f5f9" strokeWidth="3.5" strokeLinecap="round" />
        <path d="M40 14 L44 6" stroke="#cbd5e1" strokeWidth="2" strokeLinecap="round" />
      </>
    ),
  },
  goat: {
    box: '0 0 48 48',
    art: (c) => (
      <>
        <path d="M8 22 Q8 34 22 34 L32 34 Q38 34 38 26 L38 20 Q30 18 22 20 Q10 18 8 22 Z" fill={c} />
        <path d="M14 33 V43 M20 34 V43 M30 34 V43 M35 32 V43" stroke="#e2e8f0" strokeWidth="3" strokeLinecap="round" />
        <path d="M34 20 Q34 10 42 10 Q46 14 42 20 Z" fill={c} />
        <path d="M38 11 Q34 3 40 2 M42 11 Q42 4 47 5" fill="none" stroke="#e2e8f0" strokeWidth="2" strokeLinecap="round" />
        <circle cx="42" cy="14" r="1.2" fill="#0b0e14" />
        <path d="M44 19 Q45 23 42 24" fill="none" stroke="#e2e8f0" strokeWidth="1.5" />
      </>
    ),
  },
  balloon: {
    box: '0 0 48 48',
    art: (c) => (
      <>
        <path d="M24 2 C10 2 6 14 10 22 Q14 30 20 34 H28 Q34 30 38 22 C42 14 38 2 24 2 Z" fill={c} />
        <path d="M24 2 C18 6 17 22 20 34 M24 2 C30 6 31 22 28 34" fill="none" stroke="rgba(255,255,255,0.5)" strokeWidth="2" />
        <path d="M20 34 L21 40 M28 34 L27 40" stroke="#94a3b8" strokeWidth="1.2" />
        <rect x="19" y="40" width="10" height="6" rx="1.5" fill="#92400e" />
      </>
    ),
  },
  rocket: {
    box: '0 0 48 48',
    art: (c) => (
      <>
        <path d="M24 2 C32 8 34 18 34 28 L30 36 H18 L14 28 C14 18 16 8 24 2 Z" fill="#f1f5f9" />
        <path d="M24 2 C28 5 30 8 31 12 H17 C18 8 20 5 24 2 Z" fill={c} />
        <circle cx="24" cy="20" r="4.5" fill="#bae6fd" stroke={c} strokeWidth="2" />
        <path d="M14 26 L7 38 L16 35 Z M34 26 L41 38 L32 35 Z" fill={c} />
        <path d="M19 37 Q24 48 29 37 Z" fill="#fbbf24" />
      </>
    ),
  },
  ufo: {
    box: '0 0 48 48',
    art: (c) => (
      <>
        <path d="M14 22 A10 10 0 0 1 34 22 Z" fill="#bae6fd" opacity="0.85" />
        <ellipse cx="24" cy="25" rx="20" ry="7" fill={c} />
        <ellipse cx="24" cy="23" rx="20" ry="3" fill="rgba(255,255,255,0.35)" />
        <circle cx="12" cy="26" r="1.6" fill="#fde047" />
        <circle cx="24" cy="28" r="1.6" fill="#fde047" />
        <circle cx="36" cy="26" r="1.6" fill="#fde047" />
        <path d="M16 32 L12 44 H36 L32 32 Z" fill="#fde68a" opacity="0.25" />
      </>
    ),
  },
  comet: {
    box: '0 0 48 48',
    art: (c) => (
      <>
        <path d="M24 30 L10 46 M20 28 L4 40 M28 30 L22 47" stroke={c} strokeOpacity="0.55" strokeWidth="4" strokeLinecap="round" />
        <circle cx="28" cy="22" r="11" fill={c} />
        <circle cx="25" cy="19" r="4" fill="rgba(255,255,255,0.55)" />
        <circle cx="31" cy="26" r="2" fill="rgba(0,0,0,0.2)" />
      </>
    ),
  },
};
