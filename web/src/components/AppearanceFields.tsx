import { useState } from 'react';

import BackgroundFields from './BackgroundFields';
import Select from './Select';
import WallPreview from './wall/WallPreview';
import type { Appearance, Background } from '../appearance';

/**
 * "How should this look on a wall?", asked of one thing.
 *
 * **Collapsed until somebody wants it.** A board, a goal and a contest each
 * already have a form of their own asking real questions — who is in it, what
 * the target is, when it ends. Bolting eight appearance controls onto every one
 * of those would bury the questions that matter behind the ones that are
 * optional by definition.
 *
 * **Every field says where its value comes from.** An empty control here means
 * "whatever the organization says", and the placeholder shows what that
 * currently is — so choosing is a deliberate act and "back to default" is
 * removing a value rather than guessing at one to write.
 *
 * The preview is the real wall screen, so what is chosen here is what a room
 * sees. See `WallPreview`.
 */
export default function AppearanceFields({
  kind,
  chosen,
  inherited,
  onChange,
  previewBeside = false,
  withBackground = true,
}: {
  /** Which screen this thing becomes: `leaderboard`, `goal`, `competition`. */
  kind: string;
  /** What this item itself has set. Sparse — absent means inherit. */
  chosen: Record<string, unknown>;
  /** What it would look like with nothing set, for the placeholders. */
  inherited: Appearance | null;
  onChange: (next: Record<string, unknown>) => void;
  /** An `EditorPreview` is beside the form on a wide screen, so this one
   *  steps aside there rather than showing the same wall twice. */
  previewBeside?: boolean;
  /** False where the background has its own place in the form — a screen,
   *  whose background is shown up front with where it comes from (Phase 26). */
  withBackground?: boolean;
}) {
  const [open, setOpen] = useState(() => Object.keys(chosen).length > 0);

  const set = (key: string, value: unknown) =>
    onChange({ ...chosen, [key]: value });

  const clear = (key: string) => {
    const next = { ...chosen };
    delete next[key];
    onChange(next);
  };

  const count = Object.keys(chosen).length;

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="text-sm text-content-muted underline transition-colors hover:text-content"
      >
        {count > 0
          ? `Appearance — ${count} ${count === 1 ? 'setting' : 'settings'} of its own`
          : 'Give this its own appearance…'}
      </button>
    );
  }

  const ranked = kind === 'leaderboard' || kind === 'competition';

  return (
    // **Columns by its own width, not the window's** (review §5): it lives in
    // a 28rem modal, where a viewport breakpoint left the fields a sliver
    // beside the preview on any wide screen.
    <div className="@container rounded-lg border border-edge bg-surface-raised p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <p className="text-sm font-medium text-content">On a wall</p>
        {count > 0 && (
          <button
            type="button"
            onClick={() => onChange({})}
            className="text-xs text-content-muted underline transition-colors hover:text-content"
          >
            Use the defaults for everything
          </button>
        )}
      </div>
      <p className="mt-1 text-xs text-content-subtle">
        Anything left alone follows the Appearance settings. A channel or a
        single screen can still override this.
      </p>

      <div className="mt-4 grid gap-4 @2xl:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="space-y-4">
          {ranked && (
            <Inheritable
              label="Layout"
              chosen={chosen.ranked_layout as string | undefined}
              inherited={labelOf(RANKED_LAYOUTS, inherited?.ranked_layout)}
              onClear={() => clear('ranked_layout')}
            >
              <Select
                label="Layout"
                value={String(
                  chosen.ranked_layout ?? inherited?.ranked_layout ?? 'list',
                )}
                onChange={(v) => set('ranked_layout', v)}
                options={RANKED_LAYOUTS}
              />
            </Inheritable>
          )}

          {kind === 'goal' && (
            <Inheritable
              label="Layout"
              chosen={chosen.goal_layout as string | undefined}
              inherited={labelOf(GOAL_LAYOUTS, inherited?.goal_layout)}
              onClear={() => clear('goal_layout')}
            >
              <Select
                label="Layout"
                value={String(
                  chosen.goal_layout ?? inherited?.goal_layout ?? 'gauge',
                )}
                onChange={(v) => set('goal_layout', v)}
                options={GOAL_LAYOUTS}
              />
            </Inheritable>
          )}

          <Inheritable
            label="Highlight colour"
            chosen={chosen.primary as string | undefined}
            inherited={inherited?.primary}
            onClear={() => clear('primary')}
          >
            <div>
              <span className="block text-sm text-content-muted">
                Highlight colour
              </span>
              <input
                type="color"
                aria-label="Highlight colour"
                value={String(
                  chosen.primary ?? inherited?.primary ?? '#6366f1',
                )}
                onChange={(e) => set('primary', e.target.value)}
                className="mt-1 h-9 w-full cursor-pointer rounded-md border border-edge bg-bg"
              />
            </div>
          </Inheritable>

          {(ranked || kind === 'competition') && (
            <Inheritable
              label="Rows"
              chosen={
                chosen.row_count === undefined
                  ? undefined
                  : String(chosen.row_count)
              }
              inherited={
                inherited ? String(inherited.row_count) : undefined
              }
              onClear={() => clear('row_count')}
            >
              <div>
                <span className="block text-sm text-content-muted">
                  Rows
                  <span className="ml-2 tabular-nums text-content-subtle">
                    {String(chosen.row_count ?? inherited?.row_count ?? 10)}
                  </span>
                </span>
                <input
                  type="range"
                  aria-label="Rows"
                  min={3}
                  max={20}
                  step={1}
                  value={Number(chosen.row_count ?? inherited?.row_count ?? 10)}
                  onChange={(e) => set('row_count', Number(e.target.value))}
                  className="mt-2 w-full accent-brand"
                />
              </div>
            </Inheritable>
          )}

          <Inheritable
            label="Names"
            chosen={chosen.name_display as string | undefined}
            inherited={labelOf(NAME_DISPLAYS, inherited?.name_display)}
            onClear={() => clear('name_display')}
          >
            <Select
              label="Show names as"
              value={String(
                chosen.name_display ?? inherited?.name_display ?? 'full',
              )}
              onChange={(v) => set('name_display', v)}
              options={NAME_DISPLAYS}
            />
          </Inheritable>
        </div>

        <div>
          {withBackground && (
          <details className="mb-4">
            <summary className="cursor-pointer text-sm text-content-muted">
              Background
            </summary>
            <div className="mt-3">
              {/* **Its own disclosure, not another field.** A background is
                  four or five questions depending on the kind, and a board
                  form that opened with them would bury the two settings most
                  people want. */}
              <BackgroundFields
                value={
                  (chosen.background as Background | undefined) ??
                  inherited?.background
                }
                onChange={(next) => set('background', next)}
              />
            </div>
          </details>
          )}

          <div className={previewBeside ? 'lg:hidden' : ''}>
            <WallPreview
              kind={kind}
              appearance={
                inherited ? ({ ...inherited, ...chosen } as Appearance) : null
              }
            />
            <p className="mt-2 text-xs text-content-subtle">
              Sample data. The real numbers appear on the wall.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

const RANKED_LAYOUTS = [
  { value: 'list', label: 'Ranked list' },
  { value: 'podium', label: 'Podium' },
  { value: 'race', label: 'Race track' },
  { value: 'regatta', label: 'Regatta' },
  { value: 'climb', label: 'Summit' },
  { value: 'space', label: 'Space race' },
];
const GOAL_LAYOUTS = [
  { value: 'gauge', label: 'Dial' },
  { value: 'big_number', label: 'One big number' },
];
const NAME_DISPLAYS = [
  { value: 'full', label: 'Peter Parker' },
  { value: 'first', label: 'Peter' },
  { value: 'first_initial', label: 'Peter P.' },
  { value: 'last', label: 'Parker' },
  { value: 'nickname', label: 'Their nickname' },
];

/**
 * What a stored choice is called on screen. "Following the default — full"
 * showed the value the API stores rather than the option somebody would have
 * picked (review §11).
 */
function labelOf(options: { value: string; label: string }[], value: unknown): string | undefined {
  if (value === undefined || value === null) return undefined;
  return options.find((o) => o.value === value)?.label ?? String(value);
}

/**
 * One control, and whether this thing has an opinion about it.
 *
 * **"Reset" appears only once something is set.** A reset on a value nobody
 * chose is a button that does nothing and invites the question of what it would
 * have done.
 */
function Inheritable({
  label,
  chosen,
  inherited,
  onClear,
  children,
}: {
  label: string;
  chosen: string | undefined;
  inherited: string | undefined;
  onClear: () => void;
  children: React.ReactNode;
}) {
  return (
    <div>
      {children}
      {chosen === undefined ? (
        <p className="mt-1 text-xs text-content-subtle">
          Following the default{inherited ? ` — ${inherited}` : ''}.
        </p>
      ) : (
        <button
          type="button"
          onClick={onClear}
          className="mt-1 text-xs text-content-muted underline transition-colors hover:text-content"
          aria-label={`Reset ${label} to the default`}
        >
          Reset to the default
        </button>
      )}
    </div>
  );
}
