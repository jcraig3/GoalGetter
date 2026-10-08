# Design System & UI Language

**Phase 1.** Decide this before building screens, so components accumulate into a system instead of a pile.

## Design principles

1. **Data first, decoration second.** This is a tool people open daily. Numbers must be legible instantly; the visual style supports that rather than competing with it.
2. **Motivating, not childish.** Gamification earns celebration moments — a goal hit, a rank change. Everything else stays calm. Confetti on every page view is noise, and noise stops being rewarding within a week.
3. **Readable at distance.** TV display mode is a first-class surface, not an afterthought. Type scale and contrast must survive being viewed from across a room.
4. **Boring where it counts.** Settings, forms, and admin screens should be conventional and predictable. Save the personality for the leaderboards and celebrations.

## Color — dark-first

**GoalGetter is a dark interface by default.** Light mode is a supported alternative, not the baseline.

The reason is the TV display. A wall-mounted leaderboard is the product's most visible surface, and a large bright-white panel in an office is glaring and washed out, while a dark panel with luminous data reads cleanly across a room. Designing dark-first means the primary surface is native rather than an afterthought — and the data-dense screens people stare at all day get the same benefit.

The cost, stated honestly: dark UI is harder to get right for dense forms and tables, and printing/exporting needs a light path. Both are handled below.

### Tokens

All color goes through CSS custom properties. Components never contain a hex value.

```css
/* Dark is the default — defined on bare :root so it needs no media query */
:root {
  /* Surfaces — layered, not flat. Elevation is communicated by lightness. */
  --gg-bg:              #0B0E14;   /* app background, deepest layer */
  --gg-surface:         #141821;   /* cards, panels */
  --gg-surface-raised:  #1C212D;   /* modals, popovers, hover */
  --gg-border:          #262C3A;
  --gg-border-strong:   #39414F;

  /* Text */
  --gg-text:            #E8EBF0;   /* not pure white — reduces halation */
  --gg-text-muted:      #98A2B3;
  --gg-text-subtle:     #6B7484;
  --gg-text-inverse:    #0B0E14;

  /* Brand — overridable per organization */
  --gg-brand:           #6366F1;
  --gg-brand-hover:     #818CF8;
  --gg-brand-subtle:    #1E2140;   /* tinted surface, not a pale wash */
  --gg-on-brand:        #FFFFFF;

  /* Status — brightened for dark surfaces */
  --gg-success:         #34D399;   /* on track, achieved */
  --gg-warning:         #FBBF24;   /* at risk */
  --gg-danger:          #F87171;   /* missed, destructive */
  --gg-info:            #38BDF8;

  /* Rank accents */
  --gg-gold:            #F5C542;
  --gg-silver:          #C3CBD8;
  --gg-bronze:          #D08B4A;

  /* Data visualization — see the dataviz guidance before adding to this */
  --gg-chart-1:         #6366F1;
  --gg-chart-2:         #34D399;
  --gg-chart-3:         #FBBF24;
  --gg-chart-4:         #F87171;
  --gg-chart-5:         #38BDF8;
}

/* Light mode: explicit opt-in only */
:root[data-theme="light"] {
  --gg-bg:              #FAFAFA;
  --gg-surface:         #FFFFFF;
  --gg-surface-raised:  #FFFFFF;
  --gg-border:          #E4E4E7;
  --gg-border-strong:   #D4D4D8;

  --gg-text:            #18181B;
  --gg-text-muted:      #52525B;
  --gg-text-subtle:     #71717A;
  --gg-text-inverse:    #FAFAFA;

  --gg-brand:           #4F46E5;
  --gg-brand-hover:     #4338CA;
  --gg-brand-subtle:    #EEF2FF;
  --gg-on-brand:        #FFFFFF;

  --gg-success:         #15803D;
  --gg-warning:         #B45309;
  --gg-danger:          #B91C1C;
  --gg-info:            #0369A1;

  --gg-gold:            #B8860B;
  --gg-silver:          #71809A;
  --gg-bronze:          #9A5B25;
  /* chart tokens redefined to match */
}
```

Three things worth understanding:

**Status colors are not the same hex in both themes.** `#16A34A` green is readable on white and muddy on near-black; `#34D399` is the reverse. Reusing one value across both themes guarantees one of them fails contrast. Each theme gets values tuned for its background.

**Text is `#E8EBF0`, not `#FFFFFF`.** Pure white on near-black produces halation — the text appears to glow and bleed at the edges, which is fatiguing over a full workday. Pulling back slightly is materially more comfortable and costs nothing.

**Elevation is lightness, not shadow.** On a dark background a drop shadow is nearly invisible, so raising a surface means making it lighter. This inverts the usual instinct and needs to be applied consistently or the interface reads as flat.

### Rules

- **Status color is never the only signal.** "At risk" gets an icon and a label, not just amber. Roughly 1 in 12 men has some form of color vision deficiency, and a leaderboard is exactly the kind of dense display where color-only encoding fails.
- **Brand color is org-configurable and must not carry meaning.** A company whose brand is red must not have every button read as destructive. Semantic status colors stay fixed, independent of branding. The configured brand color must also be validated for contrast against the dark surface — a dark navy brand is invisible on `#0B0E14`, so the app auto-lightens it and warns the admin.
- **Contrast minimums:** 4.5:1 for body text, 3:1 for large text and UI boundaries. TV mode targets 7:1 — viewing distance and screen glare are real.
- **CSV and PDF exports always render light.** Nobody wants a dark-background print.

### Theme switching

Dark is the default with no configuration. A user toggle writes `data-theme` to the root element and persists per user.

**Phase 1 builds the token architecture and ships dark only.** The light palette is defined and correct from the start, so the Phase 2 toggle is a switch rather than a retrofit. Auditing every component against a second theme is the expensive part, and that work belongs where it doesn't block the foundation.

## Typography

```
Display   32 / 40   600    Page titles, TV headings
H1        24 / 32   600    Section headings
H2        20 / 28   600    Card titles
H3        16 / 24   600    Sub-sections
Body      14 / 20   400    Default
Small     13 / 18   400    Secondary
Caption   12 / 16   500    Labels, table headers
Metric    variable  700    Big numbers — tabular figures
```

**Font:** system stack (`-apple-system, Segoe UI, Roboto, …`). Zero network requests, correct rendering on every platform, and no font file to serve from a self-hosted container that may have no internet access.

**All numbers use `font-variant-numeric: tabular-nums`.** Without it, digits have different widths and every leaderboard column visibly jitters as values change on refresh. This is the single highest-impact typography detail in the product.

## Spacing & layout

4px base scale: `4 · 8 · 12 · 16 · 24 · 32 · 48 · 64`. Nothing off-scale.

- Card padding: 24px desktop, 16px mobile
- Section gap: 32px
- Related element gap: 8–12px
- Border radius: 8px cards, 6px inputs/buttons, 4px badges, full for avatars and pills

### App shell

```
┌────────────────────────────────────────────────────────┐
│  ☰  GoalGetter                    🔔    Jayden C.  ▾   │  56px
├──────────┬─────────────────────────────────────────────┤
│          │                                              │
│  Home    │                                              │
│  Leader- │              Page content                    │
│   boards │              max-width 1440px                │
│  Goals   │              centered                        │
│  Teams   │                                              │
│  Compet- │                                              │
│   itions │                                              │
│  ────    │                                              │
│  Data    │                                              │
│  Admin   │                                              │
│          │                                              │
│  240px   │                                              │
└──────────┴─────────────────────────────────────────────┘
```

- Sidebar collapses to icons at `< 1280px`, becomes a drawer at `< 768px`.
- Nav items are filtered by capability — an agent never sees Admin. (Cosmetic only; the server enforces access.)
- Content max-width 1440px. Wider makes long tables genuinely hard to scan.

## Core components

**No component library.** Components are hand-written against the tokens below. A library can be adopted later if one earns its place, but starting with one means inheriting its opinions before we know our own.

### Product-specific components

| Component | Purpose | Notes |
|---|---|---|
| `<MetricValue>` | Renders a value per its metric definition | Handles currency/percent/duration/count, decimal places, tabular figures. **Every number in the app goes through this.** |
| `<GoalCard>` | Goal with progress bar + pace marker | See [07-goals-and-targets.md](07-goals-and-targets.md) |
| `<ProgressBar>` | Progress with optional pace marker | Status-colored, icon + label |
| `<LeaderboardTable>` | Ranked list | Medals, movement, relative bars, pinned viewer row |
| `<RankBadge>` | Position indicator | Medal for 1–3, number beyond |
| `<MovementIndicator>` | ▲2 / ▼1 / — | Color + arrow + number |
| `<UserChip>` | Avatar + name + team | Consistent person representation everywhere |
| `<TeamPicker>` | Tree-aware team selector | Used in goals, leaderboards, filters |
| `<PeriodPicker>` | Period type + navigation | Respects org week start / fiscal year |
| `<MetricPicker>` | Metric selector with unit hints | |
| `<EmptyState>` | Icon + explanation + action | Never show a bare empty table |
| `<StatTile>` | Single KPI with delta | Dashboard building block |

**`<MetricValue>` is the most important one.** Centralizing formatting means `$84,200`, `84,200`, `84.2%`, and `2h 14m` all derive from the metric definition rather than from ad-hoc formatting scattered across twenty components that will inevitably disagree.

## Charts

Recharts. Sufficient for what's needed, reasonable bundle size, composable with React.

Chart types actually used:
- **Line** — metric trend over time
- **Bar** — comparison across people or teams
- **Area** — cumulative progress toward a goal, with a target line
- **Sparkline** — inline trend inside cards and table rows

Rules: no 3D, no pie charts with more than 4 slices, no dual y-axes. Axes start at zero for bar charts. Every chart needs a text alternative or accessible summary.

## Motion

Restrained by default, expressive at the moment of achievement.

| Interaction | Duration | Easing |
|---|---|---|
| Hover / focus | 120ms | ease-out |
| Dropdown, popover | 150ms | ease-out |
| Modal, drawer | 200ms | ease-in-out |
| Page transition | 0 | none — instant |
| Progress bar fill | 400ms | ease-out |
| Rank change | 500ms | ease-in-out |
| Goal celebration | 2–3s | custom |

**Rank change animation matters.** When a leaderboard refreshes and someone moves, animating the row to its new position communicates *what changed*. A hard swap makes people think the page glitched.

**Everything respects `prefers-reduced-motion`.** Celebrations degrade to a static banner. Non-negotiable — vestibular disorders are real and confetti is a genuine trigger.

## Responsive

| Breakpoint | Layout |
|---|---|
| `< 640px` | Single column, drawer nav, cards stack, tables become card lists |
| `640–1024px` | Two columns, collapsed icon sidebar |
| `1024–1440px` | Full layout |
| `> 1440px` | Content capped and centered |
| TV mode | Own layout entirely — see [08-leaderboards.md](08-leaderboards.md) |

**Tables become card lists on mobile, never horizontally scrolling tables.** A leaderboard scrolled sideways on a phone is unusable, and agents check standings on their phone constantly.

## Accessibility

Non-negotiable baseline:

- Every interactive element reachable and operable by keyboard, with a visible focus ring
- Semantic HTML — real `<table>`, `<button>`, `<nav>`
- Form inputs have associated `<label>`s; errors are linked via `aria-describedby`
- Live-updating regions (leaderboards) use `aria-live="polite"`, never `assertive` — an announcement every 30 seconds would be unusable with a screen reader
- Color is never the sole carrier of meaning
- `prefers-reduced-motion` honored throughout

## Open questions

1. ~~**Dark mode in Phase 1 or Phase 2?**~~ — **Resolved: dark-first.** Dark is the default and the only theme shipped in Phase 1; the light palette is defined from the start so the Phase 2 toggle is a switch, not a retrofit.
2. **How much brand customization?** Logo + one accent color is proposed. Full theming is a support burden for a self-hosted tool. *Leaning: keep it to logo + accent, with automatic contrast correction against the dark surface.*
3. **Avatars** — uploaded images, initials-only, or Gravatar? *Leaning: initials with a deterministic color, plus optional upload. No Gravatar — it's an external network call from a tool that may run air-gapped.*

## Related docs

- [13-frontend-architecture.md](13-frontend-architecture.md)
- [08-leaderboards.md](08-leaderboards.md)
- [10-dashboards.md](10-dashboards.md)


## Input constraints

Rules are declared on `<Field>`, not checked in each form's submit handler, so
a field cannot hold a value its own rules reject and a new form inherits the
behaviour without remembering to write it.

```tsx
<Field label="Target" numeric={{ decimals: 4, min: 0 }} … />
<Field label="Port"   numeric={{ decimals: 0, min: 1, max: 65535 }} … />
<Field label="Key"    allow={/^[a-z][a-z0-9_]*$/} maxLength={64} … />
<Field label="Email"  type="email" … />
```

**Not `<input type="number">`.** It accepts `1e5` and `--`, reports an empty
string for anything it considers invalid — so a form cannot tell "blank" from
"nonsense" — and changes its value when a scroll wheel passes over it.
Filtering a text input with `inputMode="decimal"` keeps every keystroke
inspectable, still raises the numeric keyboard on a phone, and leaves the value
always exactly what is on screen.

**A rejected keystroke never lands.** Typing `a` into a numeric field leaves
the previous value, rather than being accepted and refused on submit. A pasted
`1,234.50` is rejected whole — silently turning it into `1` or `1234.50` would
be worse than refusing it.

**Mid-typing states are not errors.** `12.` and `-` pass the filter and raise
no message; flagging them the moment someone reaches for the decimal point
makes the field feel broken.

**Clearing is always allowed**, or a rule could trap a value the user has no
way to remove.

Every one of these is duplicated by an API check and usually a database CHECK
constraint. The field rule exists so the interface is pleasant, not so the data
is safe.


## Podium colours

`--gg-gold`, `--gg-silver`, `--gg-bronze`, exposed as `text-gold` and friends.

Added as their own tokens rather than reusing the palette. A gold that is
really `--gg-warning` amber reads as a warning, and a leaderboard's top three
is the one place in this product where a literal colour carries meaning rather
than a status.

Each theme has its own values — the dark-mode gold is invisible on white, so
light mode uses darkened equivalents.

**Rank colour is never the only signal.** The number is always present, and
movement pairs a glyph with a figure (▲2, ▼2) rather than relying on green and
red. Roughly one man in twelve cannot distinguish those reliably, and a
leaderboard is the screen people look at most.
