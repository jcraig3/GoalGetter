import LogoField from './LogoField';
import type { Appearance } from '../appearance';

/**
 * Who the company is: the mark and the colours.
 *
 * **Company identity, so it sits with the company's other settings** — its
 * name, its timezone, its currency. The Appearance tab is about how a
 * television draws a leaderboard; this is about whose tool this is, and the
 * answer applies to the app somebody uses at their desk just as much as to a
 * screen on the wall.
 *
 * Stored in the same object the wall reads, which is what makes "the brand is
 * the default for every screen" true by construction rather than by a copy
 * somebody has to keep in step.
 */
export default function BrandFields({
  chosen,
  resolved,
  onChange,
}: {
  /** What this organization set. Sparse — absent means the built-in. */
  chosen: Record<string, unknown>;
  /** The same thing with every field filled, for the colour inputs. */
  resolved: Appearance;
  onChange: (part: Record<string, unknown>) => void;
}) {
  const colour = (key: 'primary' | 'secondary' | 'accent') =>
    String(chosen[key] ?? resolved[key]);

  return (
    <div className="space-y-6">
      {/* One logo, for the app and the walls alike. */}
      <div className="max-w-sm">
        <LogoField
          label="Logo"
          digest={(chosen.logo ?? resolved.logo) as string | null}
          onChange={(d) => onChange({ logo: d })}
          hint="Shown beside GoalGetter in the top corner, and on the TVs. A mark on a transparent background suits both light and dark."
        />
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <Colour
          label="Primary"
          value={colour('primary')}
          onChange={(v) => onChange({ primary: v })}
        />
        <Colour
          label="Secondary"
          value={colour('secondary')}
          onChange={(v) => onChange({ secondary: v })}
        />
        <Colour
          label="Accent"
          value={colour('accent')}
          onChange={(v) => onChange({ accent: v })}
        />
      </div>

      {/* Said plainly because the scope is wider than the page it is on: one
          colour picker here changes buttons, links and highlights for
          everybody, in whichever theme they use, and seeds every wall. */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-content-subtle">
          These tint the app for everyone — buttons, links and highlights, in
          light mode and dark — and become the starting point for the TVs
          on the Appearance page. Greys and body text are deliberately left
          alone: an organization choosing purple has not asked for purple
          paragraphs.
        </p>
        {/* **Removing the keys, not writing the defaults back.** Writing
            #6366f1 in would pin this deployment to today's built-in, so a
            later change to it would stop reaching anybody who had ever
            pressed reset. `undefined` is dropped by `JSON.stringify`, which
            is exactly the sparse row the server wants. */}
        {(chosen.primary ?? chosen.secondary ?? chosen.accent) !==
          undefined && (
          <button
            type="button"
            onClick={() =>
              onChange({
                primary: undefined,
                secondary: undefined,
                accent: undefined,
              })
            }
            className="shrink-0 text-xs text-content-muted underline transition-colors hover:text-content"
          >
            Use the default colours
          </button>
        )}
      </div>

      <Slogan
        value={String(chosen.slogan ?? resolved.slogan ?? '')}
        onChange={(v) => onChange({ slogan: v || null })}
      />
    </div>
  );
}

function Colour({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div>
      <span className="block text-sm text-content-muted">{label}</span>
      <div className="mt-1 flex items-center gap-2">
        <input
          type="color"
          aria-label={label}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="h-9 w-12 shrink-0 cursor-pointer rounded-md border border-edge bg-bg"
        />
        {/* The hex beside the swatch, because a brand colour arrives as a hex
            code in an email from a designer and typing it is the fastest path
            from that email to this field. */}
        <input
          type="text"
          aria-label={`${label} hex`}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          spellCheck={false}
          className="w-full rounded-md border border-edge bg-bg px-2 py-1.5 font-mono text-sm text-content outline-none focus:border-brand"
        />
      </div>
    </div>
  );
}

function Slogan({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div>
      <label htmlFor="slogan" className="block text-sm text-content-muted">
        Slogan
      </label>
      <input
        id="slogan"
        type="text"
        value={value}
        maxLength={120}
        onChange={(e) => onChange(e.target.value)}
        className="mt-1 w-full rounded-md border border-edge bg-bg px-3 py-2 text-sm text-content outline-none focus:border-brand"
      />
      <p className="mt-1 text-xs text-content-subtle">
        Optional. Shown on the TVs beside the channel name.
      </p>
    </div>
  );
}
