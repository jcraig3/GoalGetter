# GoalGetter — UI / UX review

**Date:** 30 Sept 2026
**Build tested:** `c0ed769` + working tree
**Where:** http://localhost:8080 (dev), signed in as an admin
**Viewports:** 1440×900 desktop, 375×812 phone, and wall displays at 1280×720, 1440×900, 1920×1080 and 1080×1920 (portrait)
**Companion doc:** [qa-bug-report.md](qa-bug-report.md) for defects with repro steps

**Goal of this review:** a professional app that is responsive, intuitive and easy to understand, with a low learning curve to get set up and using the tools.

**Known issues skipped:** appearance-editor spacing nits were already known and deferred (see memory), so they are left out.

---

## 1. Summary

GoalGetter has a lot of capability and very good writing. The copy is honest and specific, and it explains *why* ("White text over anything bright is unreadable at ten feet"; "A rule that fires ten times a day is wallpaper"). The Appearance page, TV pairing, the points economy, recognition variants and the competition "Check" preview are all better than Spinify's equivalents.

What holds it back is not features but **friction and trust**, grouped into three themes:

1. **Setup has no guard-rails for real-world data.** Directory sync imported service accounts, printers and shared mailboxes ("Jarvis Bot", "MFP 3100", "Lobby TV", "dummy account 2"). They now appear in every picker, inflate every health banner ("300 people have recorded nothing") and sit on leaderboards. Hiding them exists, but nothing suggests it.
2. **Pickers do not scale past ~30 people.**
   - Goal, recognition, badge and correction pickers are native `<select>` lists of 461 names.
   - Competition entrants are 461 checkboxes with no search.
   - This is the single biggest usability problem for a 100+ seat floor.
3. **The wall does not adapt to the TV.**
   - Fixed-pixel layout: rows fall off the bottom at 720p, and everything is small on a 4K set.
   - Photo backgrounds overpower the text.
   - Message slides truncate the message.

The rest is polish: consistency (dialog vs inline forms, button placement, naming), feedback (no success toasts, stale errors), and exposed internals (raw keys, GUIDs, "not built yet").

### Scorecard

| Area | Grade | One-line |
|---|---|---|
| Copywriting & microcopy | **A** | Best-in-class explanations; a few dev-speak leaks |
| Information architecture / nav | **C+** | Two flat lists, 21 items, confusing names (Achievements vs Announcements) |
| Forms & pickers | **C** | Great validation text, but pickers don't scale; silent coercion; stale errors |
| Feedback & state | **C** | Plain "Loading…", no success toasts, errors persist after success |
| Wall / TV display | **B−** | Great slide variety & pairing; fixed-size layout, contrast, truncation |
| Responsive admin (phone) | **B** | No horizontal page overflow; long modals, wide tables |
| Accessibility | **B−** | Skip link, labels, Esc closes dialogs; icon-button names, focus return, tooltips |
| Onboarding / time-to-first-wall | **C** | Many concepts before value; no guided path |

---

## 2. Top 10 recommendations (do these first)

| # | Recommendation | Why | Effort |
|---|---|---|---|
| 1 | **One searchable People Picker component** (type-ahead, avatar, team, email on second line, multi-select chips, "Add whole team / office", "Select all matching"). Replace every native person `<select>` and the entrants checkbox list. | Fixes goals, recognition, badges, corrections, spotlight, and competitions (entrants) in one component. 461-option dropdowns are unusable. | M |
| 2 | **"Who takes part" cleanup for directory data.** A review card: "43 accounts look like devices or shared mailboxes (no job title, no department, names like MFP 3100)". Actions: Hide all · Review. Make hidden or non-participants disappear from pickers, banners, boards and "recorded nothing" counts. | Every other number in the app is polluted until this is done. It is the first thing a new admin needs. | S–M |
| 3 | **Scale-to-fit wall stage.** Render every slide on a fixed 1920×1080 canvas and `transform: scale()` it to the screen, with letterboxing. Auto-page rows that don't fit, rather than clipping. | 720p TVs lose rows 7–10 entirely, and 4K TVs get tiny text. A wall product must look identical on every TV. | M |
| 4 | **Setup checklist on Home for admins:** connect data → hide non-people → make teams → first board → first channel → pair a TV. Each step links to the page, and they tick off automatically. | Today an admin lands on "300 people have recorded nothing" with no path forward. A checklist turns alarms into steps. | S |
| 5 | **Global feedback system:** toast on every create, save or delete ("Goal created · View"); clear form errors on change and on success; skeletons instead of "Loading…". | There are currently no success confirmations anywhere, and stale errors linger after a successful save. | S |
| 6 | **Rename and regroup navigation** (see §4): *Home · Boards · Goals · Competitions · Recognition · Points* for everyone; *TV & Channels · People · Data · Settings* for admins. Drop "Achievements vs Announcements vs achievement-rules". | 21 flat items with overlapping names means admins can't predict where things live. | S |
| 7 | **Live-preview-first editors.** Every editor that affects a wall (board, goal, competition, rule, channel slide) gets a large 16:9 preview pane, "Play celebration" buttons, and "Preview on a TV" (push to one paired display). | The Appearance page proves the pattern. The editors still show a thumbnail or nothing. | M |
| 8 | **Wall readability defaults:** auto-scrim photo backgrounds (darken ≥ 0.55, or a gradient behind text blocks), text-shadow on the header, and shrink-to-fit message headlines. | Podium over a photo is hard to read. Message slides cut the text off. | S |
| 9 | **Consistent CRUD pattern:** one "create" affordance per page (top-right primary button → side sheet or modal), identical row actions (⋯ menu with Edit / Duplicate / Archive / Delete), and one styled confirm dialog. | Today there's a mix of modals, inline forms, icon buttons, left and right buttons, and native `confirm()`. | M |
| 10 | **Hide internals:** raw keys (`microsoft_excel`, `closed_deals`), GUIDs, `Value error,` prefixes, "not built yet", enum values ("Following the default — full"). | These make a polished product feel like a dev build. | S |

---

## 3. First-run & setup experience

**What an admin sees on day one** (Home):

- Two alarming orange banners: "300 people have recorded nothing in 7 days" and "350 agents are on no team".
- A "Where you stand" card ranking the admin **39th of 137 with $0.00**.
- System health: "1 overdue — usually the background job rather than the source". That source is actually a read-once source, not a broken one (QA-12).

**Problems**

- The banners count bots and non-sales staff, so they are alarming and not actionable. They link to lists, but there's no "these aren't salespeople → hide" path.
- Admins and managers are ranked on boards as if they were agents.
- The Standings card at the bottom is a debug component. Its code comment says it exists "so the numbers can be checked against the database by eye". It isn't a user feature.

**Recommendations**

- A **setup checklist** (Top-10 #4) replaces the banners until setup is complete. After that, turn the banners into a dismissible "Health" card that shows only actionable counts.
- An **"Exclude from boards" flag per role**: default admins out, managers optional. Or show "You're not ranked — admins aren't on boards".
- Move Standings to Reporting (or remove it), and give managers their team's live board instead.
- **Empty states should teach.** The copy is already good; add the primary action button inside each one (e.g. "No rules yet" → [Start from a template ▾]).
- **Templates everywhere a blank form appears:** rules ("Big deal over $X", "First sale of the day", "Every 10th call"), competitions ("Friday sprint", "Month-end push", "Team vs team"), channels ("Sales floor", "Lobby — top 3 only").

---

## 4. Navigation & information architecture

**Current:** Home, Leaderboards, Goals, Achievements, Offices, Reporting, Points, Teams, Competitions, Channels | MANAGE: Users, Metrics, Corrections, Announcements, Integrations, Appearance, Settings.

**Issues**

- "**Achievements**" (a feed), "**Announcements**" (rules, at URL `/achievement-rules`) and in-app copy that says "**Achievement rules**" are three names for two things.
- "**Screens**" means slides ("2 screens · 1 television") *and* TVs ("Add a screen" = pair a TV), and the pairing page says "Channels → Pair a screen".
- Offices and Teams are separate top-level items for everyone, but they're admin structure.
- Points mixes the player view (This season, Spend) with admin configuration (Seasons, Tiers, Values, Wheel, Cosmetics) across 8 tabs.
- Corrections is reachable both from the nav and from Metrics.
- Every page's `<title>` is just "GoalGetter", so browser tabs and history are indistinguishable.

**Proposed IA**

```
EVERYONE                     ADMIN / MANAGER
Home                         TV & Channels   (channels, connected TVs, pairing)
Boards        (leaderboards) People          (users, teams, offices, directory sync, hidden)
Goals                        Data            (sources/integrations, metrics, corrections)
Competitions                 Celebrations    (auto-announcement rules, wall takeover settings)
Recognition   (feed + give)  Points setup    (seasons, tiers, badges, cosmetics, wheel, values)
Points        (my season, spend)             Appearance
Reporting (managers)         Settings        (org, security, audit)
```

- Rename consistently: **Slide** (one item in a channel), **TV** (a paired display), **Channel** (a playlist), **Celebration** (a takeover), **Rule** (automatic celebration).
- Per-page titles: "Goals · GoalGetter".
- Breadcrumbs on detail pages ("Goals › QA Goal"), not just "← Goals".

---

## 5. Consistency & component system

| Pattern | Today | Standardise on |
|---|---|---|
| Create | Modal (boards, goals, competitions, rules); inline form (offices, teams, metrics, corrections, badges); button left (Competitions) or right (everywhere else) | Primary button **top-right**; a **side sheet** for long forms, a modal for short ones |
| Row actions | Icon-only buttons (some with tooltips that render clipped over the sidebar); text links on others | A visible primary action plus a **⋯ menu** (Edit, Duplicate, Archive, Delete), consistent everywhere |
| Delete confirm | Native `window.confirm()` (good copy, unstyled) | App **Confirm dialog** with a consequence list ("2 slides and 1 goal use this board") and a typed-name confirm for destructive actions |
| Save | One "Save settings" for part of a 5,510px page while later sections auto-save; user page has 2+ Save buttons | Per-card forms with a **sticky save bar** that appears when dirty ("3 unsaved changes · Save · Discard") |
| Feedback | None on success; errors persist | Toasts plus inline field errors that clear on change |
| Loading | "Loading…" text, layout shift | Skeletons matching the card shape |
| Status chips | "Behind" shown twice per goal card | One status chip per card |
| Colour of "unassigned" | Warning orange on ~350 rows | Muted grey "No team"; reserve orange for things to act on |

**Design tokens:** the colour, radius and blur tokens are well done (Appearance and Settings prove it). Add a **component inventory page** (Storybook, or a hidden `/ui` route) so the patterns above are enforced.

---

## 6. Forms & pickers

- **People Picker** (Top-10 #1). Required everywhere a person or team is chosen. Show duplicate names with an email or team ("Peter Parker · Metropolis" vs "Peter Parker · Gotham").
- **Numbers:**
  - Use `inputmode="decimal"` inputs with visible validation.
  - Don't silently strip characters (`-5`, `abc` currently vanish or are ignored).
  - Say what's allowed ("Whole number, 1–50").
- **Disabled submit buttons must explain themselves.** "Create goal" is disabled with no hint; either enable it and show errors on click, or add helper text ("Enter a target to continue").
- **Metric picker:**
  - Show unit and source ("Closed Deals · count · Excel").
  - Prevent duplicate display names (QA-9).
  - Add a *display name* separate from the source-derived name ("Sales Feed Amount Today" is a feed name, not a label for a wall).
- **Dates and times:** label the timezone ("Times are Eastern — organization time") and convert from the browser's zone. A Pacific admin creating a 5 pm contest currently gets a UTC-dated announcement (QA-14).
- **Media links:** parse `t=`/`start=` from YouTube URLs into "Start at", and show a mini preview thumbnail on paste.
- **Long forms** (competition, rule, board) need section headers with anchors, a sticky action bar, and progress ("3 of 5 sections complete") on mobile.

---

## 7. Page-by-page notes

### Home
- The admin rank card ("39 of 137, $0.00") and the flat sparkline both look like a progress bar at zero. Hide admins, or show "No activity" instead of a line.
- "96 points behind" collides with the Points economy. Use "96% behind pace" or "needs $X/day".
- Give Needs attention a "Nudge" or "Open goal" action per row.
- System health: link each count ("1 overdue" → the source; "350 on no team" → People filtered to no team).

### Leaderboards
- The list card preview is good. The detail page should show the chosen wall layout (podium or race), with Edit and "Show on a TV" buttons.
- Replace "Results are computed on request — nothing is stored" with user language, e.g. "Updates live as new data arrives".
- Add silver/bronze styling for 2nd and 3rd, and period stepping (◀ last month ▶) on calendar periods.
- Units on count metrics: show "48,210 deals", not a bare number.

### Goals
- **Card title:** use "Steve Rogers — Closed Deals" (who first, then what), with one status chip.
- **Filters:** search, person or team, metric, status (Behind / On track / Hit), period.
- **Copy:** replace "95.5% of the period gone" with "1 working day left · needs 74,600".
- **Detail page:** add Edit/Archive actions; draw stretch levels as ticks on the same bar, not as a second full-width line.
- **Bulk goals:** "Give everyone on Metropolis Sales Team a 25,000 goal". This is currently one goal per person.

### Competitions
- Entrants picker (Top-10 #1), plus "Add Metropolis Sales Team (90)".
- Editable while running: prize, end time (extend), late entrants, with an audit note.
- **Zero-score state:** "No scores yet". Don't show "Leading · Jayden Craig" when everyone is at 0.
- After publishing, land on the tab that contains the item (a back-dated contest goes to Live, not Upcoming).
- The detail page repeats the title twice. Collapse the header and summary.

### Recognition (Achievements page)
- The dialog is good. Add a warning for self-recognition ("You won't earn points for recognising yourself").
- The feed needs filters (person, team, type) and reactions or comments later.
- "Play on wall" should let you pick which channel or TV.

### Points
- Split the player page (This season, Spend, Badges I have) from the admin setup pages.
- **Badges:** allow uploaded art or colour and a frame. The six nav icons as "marks" look like menu items.
- **Season auto-open:** when the first award lands in the last days of a quarter, ask "Start the season now (ends today) or from 1 Oct?".
- **Tiers:** "Suggest tiers from the distribution" is a great idea. Surface it once data exists.

### Offices & Teams
- Make cards and rows clickable, leading to a detail page (members, goals, boards, channels using it).
- **Moving someone** already on another team needs a confirm: "Moves Test user from Metropolis Sales Team".
- **Team identity:** logo, colour and short name, for team boards and head-to-head.
- The office select styled as plain text needs an explicit edit affordance, or move it into the team editor.
- Enforce unique names (QA-7).

### Channels & TVs
- Rename per §4. Use one "Connect a TV" button with "Pair with a code" / "Copy a link" tabs.
- **Channel editor:**
  - a rotation preview (auto-playing thumbnails)
  - per-slide schedule (days and hours) and weight
  - reorder handles with accessible names
  - the slide name for competition slides (QA-11)
- **Revoked TVs:** allow delete or clear. They currently can't be removed from the list (QA-17).
- **Disconnected TV screen:** show a new pairing code automatically, so the TV can be re-paired without anyone touching it.
- **Board visibility:** explain the relationship between "Show on wall displays" and adding a board slide, or merge them.

### Users
- **Scale:** paginate or virtualise (450 rows), and add Team / Role / Status filters and bulk actions (Hide, Set team, Set role).
- **User detail:**
  - two-column layout on desktop (profile | access & media)
  - one save bar
  - play and remove controls for an uploaded walk-up clip
- The YouTube-ads explanation is excellent. Keep it, and show "Uploaded clip · 0:15 · ▶ · Remove".

### Metrics & Corrections
- **Metrics:**
  - Friendly source labels ("Microsoft Excel · Closed Deals sheet").
  - Hide the KEY column behind a disclosure.
  - Add a *sanity hint* when a "count" metric sums values in the tens of thousands ("These look like amounts — should the unit be currency?").
- **Corrections:**
  - Date filter plus pagination.
  - Visually separate manual entries from connector facts, and warn when editing a connector fact ("the next sync may overwrite this").

### Announcements (rules)
- Starter templates, a large takeover preview, and "This would have fired N times last week" (reuse the competitions Check).
- Say honestly when it will appear: "Within a minute" once detection runs on ingest (QA-2). Today it's up to an hour.

### Integrations
- Name sources after the file or sheet by default, never `microsoft_excel`.
- Real logos for Close, Pipedrive, Freshdesk and Gong.
- Hide the client GUID behind "Details", and remove "not built yet" rows (or mark them "Coming soon" in a muted style).
- **Read-once sources:** show "Manual · last read 9/23 · [Sync now]", not "Late — check the scheduler" (QA-12).

### Appearance (keep as the model page)
- Enlarge the preview (a pop-out or full-screen button), and add "Preview on TV…".
- Defaults: darken 0.55 for photos, and **Rows = Fit to screen** (auto).

### Settings
- Split into sub-pages: General · Branding · Self-service · Sign-in & security · Roles · Audit & export.
- **Logo guidance:** warn when the logo looks like a portrait photo (the header now shows two faces).
- **Timezone sanity:** "Your offices are in Metropolis (Pacific) but the organization is Eastern".
- **Two-step "required":** show who isn't enrolled, and explain the SSO exemption.

---

## 8. Wall / TV display

**What's strong**

- Pairing by a 4-character code, which works end to end.
- Nine slide kinds, the podium, race track and spotlight layouts, and a stale-data "Reconnecting".
- The display link security copy.
- Revoke and Reload per TV.

**What to fix**

1. **Fixed-size layout.** It's ~1085 px tall with 24 px rows. At 1280×720, rows 7–10 are fully off-screen; at 1080p it overflows by 5 px. Use the scale-to-fit stage (Top-10 #3) plus auto-paging ("Page 1 of 2" dots).
2. **Contrast.**
   - Photo backgrounds need a scrim.
   - The channel label ("test") is grey on yellow and invisible.
   - The header subtitle is low-contrast.
   - Run automatic contrast checks against the sampled background colour.
3. **Message slide.** The headline is ellipsised ("QA message: this is a very long he…"). Use shrink-to-fit with a minimum size and wrapping, plus a character counter in the editor.
4. **Goal gauge.** At 0% it has green caps at both ends, which reads as complete. Colour only the progress cap. Headline with the goal name or person ("Clark — $0 of $250K") rather than the raw metric name.
5. **Units on the wall:** "48,210 deals", "$8,450".
6. **Revoke latency.** Revoke says "stops immediately" but takes about 60–90 s (QA-15).
7. **Idle and night mode:** dim or show a clock outside office hours, per channel (TV burn-in and energy).
8. **Portrait support** fits, but layouts aren't designed for it. Offer a portrait variant of the list and podium.

---

## 9. Responsive admin (phone, 375 px)

- No page-level horizontal overflow was found on the pages checked. The hamburger nav works.
- **Tables** (Users, Corrections, Metrics) scroll inside an 859 px container. Switch to a stacked card layout below 640 px.
- **Modals** become ~2,000 px tall (the competition form). Use a full-screen sheet with a sticky header and action bar on mobile.
- **Filters** take the whole first screen on Users. Collapse them behind a "Filters (2)" button.
- The stale-data warning ("A feed behind these numbers is overdue… Check the sources") shows on mobile boards. Agents can't act on it, so show it to admins only.

---

## 10. Accessibility

**Good:** a skip link, labelled form fields, Esc closes dialogs, reduced-motion awareness in celebrations (per docs), and good heading structure.

**Fix:**

- **Icon-only buttons.** The header avatar link has no accessible name, and drag handles are labelled "⠿". Add `aria-label`s ("Reorder DEALS BOARD", "Your account").
- **Focus return.** After closing a dialog, focus goes to the page body rather than the trigger button.
- **Unsaved-change guard.** Esc or × on a filled form discards without warning.
- **Tooltips** render clipped over the sidebar ("Renar · Archiv · Delete"). Use a portal-positioned tooltip with collision handling.
- **Combined text for screen readers.** "10" and "1st" in separate spans read as "101st". Add a visually hidden separator ("10 points, 1st place").
- **Colour-only meaning.** Rank colours and status chips need text or an icon as well. They mostly have text; keep it that way.
- **Page titles** (see §4) are an accessibility requirement as well as a UX one.

---

## 11. Content & microcopy

Keep the house voice; it's a differentiator. Fix these leaks:

| Where | Now | Suggested |
|---|---|---|
| Leaderboards subtitle | "Results are computed on request — nothing is stored." | "Always live — updates as data arrives." |
| Competition error | "Value error, A competition has to end after it starts." | "The end has to be after the start." |
| Board editor | "Following the default — full" | "Following the default — Peter Parker (full name)" |
| Reporting | "On 0 a day, needs 25,000 for 1 working day." | "Needs 25,000 in the last working day (0/day so far)." |
| Goal card | "95.5% of the period gone" | "1 day left" |
| Needs attention | "96 points behind" | "96% behind pace" |
| Pair page | "Channels → Pair a screen" | Match the button: "Channels → Connect a TV" |
| Rules form | "Fires the moment…" | "Appears on the wall within a minute" (after QA-2) |
| Badge empty state | "Add one under Achievement rules first" | "Create a celebration rule first → [Celebrations]" |
| Integrations | "Sync people from your directory · not built yet" | Hide, or "Coming soon" |

---

## 12. Suggested new features (UX-driven)

1. **Setup checklist and health centre** (§3).
2. **Participant flag / auto-detect service accounts** (§2 #2).
3. **Bulk goals:** one target for a team or office, with per-person overrides in a grid.
4. **Starter templates** for rules, competitions and channels.
5. **"Preview on a TV"**: push any unsaved slide or celebration to one paired TV for 30 s.
6. **Rotation scheduling:** per-slide time windows and weights, and a night/idle mode.
7. **Team identity:** logos and colours for team boards and head-to-head.
8. **Manager "My team" home:** a team board, who needs a nudge, and quick recognise buttons.
9. **Command palette (Ctrl+K):** jump to any person, board or goal, which matters with 400+ people.
10. **Activity inbox for admins:** failed syncs, new directory people awaiting placement, revoked TVs still polling, seasons ending soon.

---

## Appendix — coverage

**Pages exercised:**

- Home; Leaderboards (list, create, edit, appearance, detail); Goals (list, create, stretch, detail)
- Achievements (recognise); Offices (create, rename, delete); Reporting (4 tabs)
- Points (8 tabs, badge create and give); Teams (create, members, move)
- Competitions (create, validate, check, publish, detail)
- Channels (editor, all 9 slide kinds, pair a TV, revoke); wall display (rotation at 4 resolutions)
- Users (list, search, bulk select, detail, walk-up link and upload, preview)
- Metrics (create, duplicate checks); Corrections (validation, record)
- Announcement rules (create); Integrations (overview, source detail, read-only)
- Appearance (theme switch); Settings (read-only); Account
- `/pair`, `/reset-password`, `/accept-invite`, `/setup` and unknown routes

**Not exercised:**

- Agent and manager role views (no test logins)
- Email sending, SMTP digests, and connector syncs (deliberately not triggered)
- Slack and Teams posting, the directory sync run, SSO sign-in, 2FA enrolment
