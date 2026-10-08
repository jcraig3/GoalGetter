import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { api } from '../api';
import { forgetOrgAppearance } from '../orgAppearance';
import BackgroundFields from '../components/BackgroundFields';
import {
  FONT_LABELS,
  NAME_DISPLAY_LABELS,
  applyAppearance,
  applyTheme,
  storedTheme,
  type Appearance as Resolved,
  type ThemeChoice,
} from '../appearance';
import PageHeader from '../components/PageHeader';
import Select from '../components/Select';
import { Tab } from '../components/Tabs';
import WallPreview from '../components/wall/WallPreview';
import Loading from '../components/Loading';

/** What the preview can be pointed at. */
const PREVIEW_KINDS: [string, string][] = [
  ['leaderboard', 'Leaderboard'],
  ['goal', 'Goal'],
  ['competition', 'Competition'],
  ['champion', 'Winner'],
  ['spotlight', 'Player spotlight'],
  ['comparison', 'Side by side'],
  ['achievements', 'Celebrations'],
  ['message', 'Message'],
];

interface OrgRead {
  id: number;
  name: string;
  appearance: Record<string, unknown>;
  appearance_resolved: Resolved;
}

/**
 * One page for how everything looks.
 *
 * **Deliberately one page.** The product this borrows from keeps its logo in
 * two places, fonts under Company Settings, colours under Branding and
 * per-screen colours in a wizard step — so "why is this green?" has five
 * possible answers. Here there is one, and everything below it inherits.
 *
 * **Every control has its effect beside it.** The same product asks you to
 * design a full-screen celebration through forty fields and a static
 * thumbnail. A sample panel that uses the real tokens costs almost nothing and
 * removes the guessing.
 */
export default function Appearance() {
  const [org, setOrg] = useState<OrgRead | null>(null);
  const [chosen, setChosen] = useState<Record<string, unknown>>({});
  const [theme, setTheme] = useState<ThemeChoice>(storedTheme);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [previewKind, setPreviewKind] = useState('leaderboard');

  const load = useCallback(async () => {
    try {
      const next = await api<OrgRead>('/api/organization');
      setOrg(next);
      setChosen(next.appearance ?? {});
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load that.');
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const next = await api<OrgRead>('/api/organization', {
        method: 'PATCH',
        body: JSON.stringify({ appearance: chosen }),
      });
      setOrg(next);
      setChosen(next.appearance ?? {});
      // Applied to the whole document as well, so the change is visible
      // immediately rather than after a reload.
      applyAppearance(next.appearance_resolved);
      // Every per-item form shows these as its "leave it alone" placeholders,
      // cached for the page load. Without this, a board opened after saving
      // here would describe the brand that was just replaced.
      forgetOrgAppearance();
      setSaved(true);
      window.setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save that.');
    } finally {
      setBusy(false);
    }
  }

  if (!org) {
    return (
      <>
        <PageHeader title="Appearance" />
        <Loading />
      </>
    );
  }

  const live = org.appearance_resolved;

  // **Merged here so a slider moves the preview as it is dragged.** The server
  // owns the real merge; this is the same operation over one layer, which is
  // all an unsaved edit is. A round trip per keystroke would make every control
  // feel broken.
  const previewing = { ...live, ...(chosen as Partial<typeof live>) };
  const set = (key: string, value: unknown) =>
    setChosen((current) => ({ ...current, [key]: value }));

  const value = <T,>(key: string, fallback: T): T =>
    (chosen[key] as T) ?? fallback;

  return (
    <>
      <PageHeader
        title="Appearance"
        description="How GoalGetter looks here, and on every TV. A channel or a single slide can override any of it."
      />

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="space-y-6">
          {/* ── Your own screen ─────────────────────────────────────────── */}
          <section className="rounded-lg border border-edge bg-surface p-6">
            <h2 className="text-h3 text-content">Your screen</h2>
            <p className="mt-1 text-sm text-content-muted">
              Yours alone — it does not change what anybody else or a wall sees.
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              {(['light', 'dark', 'system'] as ThemeChoice[]).map((option) => (
                <Tab
                  key={option}
                  active={theme === option}
                  onClick={() => {
                    setTheme(option);
                    applyTheme(option);
                  }}
                >
                  {option === 'system'
                    ? 'Follow my system'
                    : option === 'light'
                      ? 'Light'
                      : 'Dark'}
                </Tab>
              ))}
            </div>
          </section>

          {/* ── Brand, which lives elsewhere ───────────────────────── */}
          <Panel
            title="Brand"
            hint="Your mark and colours, set with the rest of your company's details."
          >
            {/* **Shown, not editable.** This page is the on-screen experience;
                the brand is who the company is, and it applies to the app as
                much as to a wall. Repeating the controls here would be two
                places to change one thing — and the version of that nobody
                notices is the one where they disagree. */}
            <div className="flex flex-wrap items-center gap-4">
              {live.logo && (
                <img
                  src={`/api/images/${live.logo}`}
                  alt=""
                  className="h-8 w-auto max-w-32 object-contain"
                />
              )}
              <div className="flex items-center gap-2">
                {(['primary', 'secondary', 'accent'] as const).map((key) => (
                  <span
                    key={key}
                    title={live[key]}
                    className="size-7 rounded-full border border-edge"
                    style={{ backgroundColor: live[key] }}
                  />
                ))}
              </div>
              <Link
                to="/settings"
                className="text-sm text-brand hover:underline"
              >
                Change in Settings →
              </Link>
            </div>
            <p className="mt-3 text-xs text-content-subtle">
              Every screen starts from these. A channel, a single screen or one
              board can still differ — that is what the rest of this page is
              for.
            </p>
          </Panel>

          {/* ── Background ──────────────────────────────────────────────── */}
          <Panel
            title="Background"
            hint="What sits behind every wall screen. A channel or a single screen can override it."
          >
            <BackgroundFields
              value={previewing.background}
              onChange={(next) => set('background', next)}
            />
          </Panel>

          {/* ── Type ────────────────────────────────────────────────────── */}
          <Panel
            title="Type"
            hint="Bundled with the build, so a wall with no internet still renders."
          >
            <div className="grid gap-4 sm:grid-cols-2">
              <Select
                label="Wall font"
                value={String(value('font', live.font))}
                onChange={(v) => set('font', v)}
                options={Object.entries(FONT_LABELS).map(([k, label]) => ({
                  value: k,
                  label,
                }))}
              />
              <Slider
                label="Font size"
                value={Number(value('font_scale', live.font_scale))}
                min={0.5}
                max={2.5}
                step={0.05}
                format={(n) => `${Math.round(n * 100)}%`}
                onChange={(n) => set('font_scale', n)}
                hint="A deeper room needs larger type."
              />
            </div>
          </Panel>

          {/* ── Panels ──────────────────────────────────────────────────── */}
          <Panel
            title="Panels"
            hint="The cards that sit over a background on a wall screen."
          >
            <div className="grid gap-4 sm:grid-cols-3">
              <Slider
                label="Opacity"
                value={Number(value('panel_opacity', live.panel_opacity))}
                min={0}
                max={1}
                step={0.02}
                format={(n) => `${Math.round(n * 100)}%`}
                onChange={(n) => set('panel_opacity', n)}
              />
              <Slider
                label="Blur"
                value={Number(value('panel_blur', live.panel_blur))}
                min={0}
                max={40}
                step={1}
                format={(n) => `${n}px`}
                onChange={(n) => set('panel_blur', n)}
              />
              <Slider
                label="Corners"
                value={Number(value('panel_radius', live.panel_radius))}
                min={0}
                max={48}
                step={1}
                format={(n) => `${n}px`}
                onChange={(n) => set('panel_radius', n)}
              />
            </div>
          </Panel>

          {/* ── Layout ──────────────────────────────────────────────────── */}
          <Panel
            title="Layout"
            hint="How ranked screens are drawn. A channel or a single screen can differ."
          >
            <Select
              label="Leaderboards and competitions"
              value={String(value('ranked_layout', live.ranked_layout))}
              onChange={(v) => set('ranked_layout', v)}
              options={[
                { value: 'list', label: 'Ranked list' },
                { value: 'podium', label: 'Podium — top three on steps' },
                { value: 'race', label: 'Race track — everyone racing to the finish' },
                { value: 'regatta', label: 'Regatta — boats sailing for the buoy' },
                { value: 'climb', label: 'Summit — climbers racing up a mountain' },
                { value: 'space', label: 'Space race — rockets from the Earth to the Moon' },
              ]}
              hint="A list answers “where am I?”. A podium answers “who won?” — a room glancing up for two seconds gets that without reading anything. A race answers “how close is everyone?”, against the finish line set on the board."
            />

            <div className="mt-4">
              <Select
                label="Goals"
                value={String(value('goal_layout', live.goal_layout))}
                onChange={(v) => set('goal_layout', v)}
                options={[
                  { value: 'gauge', label: 'Dial — how far toward the target' },
                  { value: 'big_number', label: 'One big number' },
                ]}
                hint="A dial needs a target to be a proportion of. Without one, the honest drawing is just the figure."
              />
            </div>

            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              <Slider
                label="Rows on a ranked screen"
                value={Number(value('row_count', live.row_count))}
                min={3}
                max={20}
                step={1}
                format={(n) => String(n)}
                onChange={(n) => set('row_count', n)}
                hint="The board still decides who is on it. This is how many of those fit on one television."
              />
              <div>
                <span className="block text-sm text-content-muted">
                  Scores
                </span>
                <label className="mt-2 flex items-start gap-2 text-sm text-content-muted">
                  <input
                    type="checkbox"
                    checked={Boolean(value('show_values', live.show_values))}
                    onChange={(e) => set('show_values', e.target.checked)}
                    className="mt-0.5 accent-brand"
                  />
                  <span>
                    Show the numbers beside the names
                    <span className="block text-xs text-content-subtle">
                      Off leaves positions only — for a room where the figures
                      are commercially sensitive and the ranking is the
                      motivating part.
                    </span>
                  </span>
                </label>
              </div>
            </div>
          </Panel>

          {/* ── Names ───────────────────────────────────────────────────── */}
          <Panel
            title="Names"
            hint="How people are written on leaderboards and celebrations."
          >
            <Select
              label="Show names as"
              value={String(value('name_display', live.name_display))}
              onChange={(v) => set('name_display', v)}
              options={Object.entries(NAME_DISPLAY_LABELS).map(
                ([k, label]) => ({
                  value: k,
                  label,
                }),
              )}
              hint="A wall the public walks past should probably not publish surnames."
            />
          </Panel>

          {/* ── Deadlines ───────────────────────────────────────────────── */}
          <Panel
            title="Deadlines"
            hint="How a competition's remaining time is written on a wall."
          >
            <Select
              label="Time left"
              value={String(value('end_time_format', live.end_time_format))}
              onChange={(v) => set('end_time_format', v)}
              options={[
                { value: 'default', label: '2d 4h left' },
                { value: 'simple', label: '2 days left' },
                { value: 'full', label: 'Ends Friday 3 October, 5:00 pm' },
                { value: 'off', label: 'Do not show it' },
              ]}
              hint="A floor watching a sprint end today wants minutes. A lobby showing a month-long contest should not tick."
            />
          </Panel>

          {/* ── Celebrations ────────────────────────────────────────────── */}
          <Panel
            title="Celebrations"
            hint="Which wins stop the rotation and take over the screen."
          >
            <Select
              label="Interrupt for"
              value={String(value('milestones', live.milestones))}
              onChange={(v) => set('milestones', v)}
              options={[
                { value: 'all', label: 'Every win' },
                {
                  value: 'important',
                  label: 'Contest wins and goals hit only',
                },
                { value: 'none', label: 'Nothing — never interrupt' },
              ]}
              hint="A sales floor wants every shout-out. A reception area wants the big ones. A screen above a support desk wants to be left alone."
            />
          </Panel>

          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => void save()}
              disabled={busy}
              className="rounded-md bg-brand px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-hover disabled:opacity-50"
            >
              {busy ? 'Saving…' : 'Save appearance'}
            </button>
            {Object.keys(chosen).length > 0 && (
              <button
                type="button"
                onClick={() => setChosen({})}
                className="text-sm text-content-muted underline transition-colors hover:text-content"
              >
                Reset everything to the defaults
              </button>
            )}
            {saved && <span className="text-sm text-success">Saved.</span>}
          </div>

          {error && (
            <p
              role="alert"
              className="rounded-md border border-danger px-3 py-2 text-sm text-danger"
            >
              {error}
            </p>
          )}
        </div>

        {/* ── The sample ──────────────────────────────────────────────── */}
        <aside className="lg:sticky lg:top-6 lg:self-start">
          <p className="mb-2 text-sm font-medium text-content">Wall preview</p>
          {/* **The real screen, at desk size.** This was a hand-drawn stand-in
              until the wall renderer was extracted — which is the whole point
              of having extracted it. A preview built to imitate the wall is a
              second renderer to keep in step, and stops being a preview the
              week after anybody relies on it. */}
          <WallPreview
            kind={previewKind}
            channelName="Main floor"
            appearance={previewing}
            turnable
          />

          <div className="mt-3 flex flex-wrap gap-2">
            {PREVIEW_KINDS.map(([kind, label]) => (
              <Tab
                key={kind}
                active={previewKind === kind}
                onClick={() => setPreviewKind(kind)}
              >
                {label}
              </Tab>
            ))}
          </div>
          <p className="mt-2 text-xs text-content-subtle">
            Unsaved changes show here first. Nothing on a real wall changes
            until you save.
          </p>
        </aside>
      </div>
    </>
  );
}

function Panel({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border border-edge bg-surface p-6">
      <h2 className="text-h3 text-content">{title}</h2>
      {hint && <p className="mt-1 text-sm text-content-muted">{hint}</p>}
      <div className="mt-4">{children}</div>
    </section>
  );
}

/**
 * A colour, and whether it is this organization's own choice.
 *
 * **"Reset" only appears once something has been chosen**, because a reset on a
 * value that was never set is a button that does nothing and invites the
 * question of what it would have done.
 */
function Slider({
  label,
  value,
  min,
  max,
  step,
  format,
  onChange,
  hint,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  format: (value: number) => string;
  onChange: (value: number) => void;
  hint?: string;
}) {
  const id = `slider-${label.toLowerCase().replace(/\s+/g, '-')}`;
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <label htmlFor={id} className="text-sm text-content-muted">
          {label}
        </label>
        <span className="text-xs tabular-nums text-content-subtle">
          {format(value)}
        </span>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mt-2 w-full accent-[var(--gg-brand)]"
      />
      {hint && <p className="mt-1 text-xs text-content-subtle">{hint}</p>}
    </div>
  );
}
