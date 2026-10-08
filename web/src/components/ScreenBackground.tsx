import type { Background } from '../appearance';
import BackgroundFields from './BackgroundFields';

const KIND_WORDS: Record<string, string> = {
  solid: 'a colour',
  gradient: 'a gradient',
  image: 'a photograph',
  video: 'a video loop',
  youtube: 'a YouTube video',
  scene: 'a drawn scene',
};

/**
 * A screen's background: **what it has unless told otherwise, and where that
 * comes from**, then the choice to give it its own (Phase 26).
 *
 * "From the leaderboard “Sales floor” — a photograph", with a swatch of it.
 * **Use a different background** starts from that one, already filled in, so
 * changing a colour isn't starting again; **Back to …** drops the screen's own.
 */
export default function ScreenBackground({
  value,
  onChange,
  inherited,
  source,
}: {
  /** The screen's own, or undefined while it follows what's above it. */
  value: Background | undefined;
  onChange: (next: Background | undefined) => void;
  /** What it would have with nothing of its own. */
  inherited: Background | null | undefined;
  /** Where that comes from, in words ("the leaderboard “Sales floor”"), or "". */
  source: string | undefined;
}) {
  const from = source || 'the default';
  const inheritedKind = inherited?.kind && inherited.kind !== 'none' ? inherited.kind : null;

  if (value) {
    return (
      <div className="space-y-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <p className="text-sm text-content">This screen’s own background</p>
          <button
            type="button"
            onClick={() => onChange(undefined)}
            className="text-xs text-brand hover:underline"
          >
            Back to {source ? `${from}’s` : 'the default'}
          </button>
        </div>
        <BackgroundFields value={value} onChange={(next) => onChange(next)} />
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-md border border-edge bg-surface-raised p-3">
      <Swatch background={inherited} />
      <div className="min-w-0 flex-1 text-sm">
        <p className="text-content">
          {source === undefined
            ? 'Working out what it inherits…'
            : inheritedKind
              ? `From ${from}: ${KIND_WORDS[inheritedKind] ?? 'a background'}`
              : 'No background set — the plain wall'}
        </p>
        <p className="text-xs text-content-subtle">Left like this, it follows whatever that is set to.</p>
      </div>
      <button
        type="button"
        onClick={() => onChange({ ...(inherited ?? {}), kind: inherited?.kind && inherited.kind !== 'none' ? inherited.kind : 'solid' } as Background)}
        className="rounded-md border border-edge px-3 py-1.5 text-sm text-content transition-colors hover:bg-surface-hover"
      >
        Use a different background
      </button>
    </div>
  );
}

function Swatch({ background }: { background: Background | null | undefined }) {
  const style =
    background?.kind === 'solid' && background.color
      ? { background: background.color }
      : background?.kind === 'gradient' && background.color
        ? { background: `linear-gradient(135deg, ${background.color}, ${background.color_to ?? background.color})` }
        : undefined;
  const picture = background?.kind === 'image' && background.asset ? `/api/images/${background.asset}` : null;
  return (
    <span
      aria-hidden="true"
      style={style}
      className="relative flex h-12 w-20 shrink-0 items-center justify-center overflow-hidden rounded border border-edge bg-bg text-content-subtle"
    >
      {picture && <img src={picture} alt="" className="absolute inset-0 size-full object-cover" />}
      {(background?.kind === 'video' || background?.kind === 'youtube') && '▶'}
    </span>
  );
}
