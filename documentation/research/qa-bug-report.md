# GoalGetter — QA bug report

**Date:** 30 Sept 2026
**Build:** `c0ed769` (dev) running on docker compose at http://localhost:8080
**Tester:** Claude (acting as QA), signed in as an org admin (user 1)
**Companion doc:** [ui-ux-review.md](ui-ux-review.md), which covers design and UX recommendations. This file covers defects: things that are wrong, not just could be better.

**Severity**

- **High:** a feature doesn't work, or the product tells the user something false.
- **Med:** wrong result or confusing behaviour with a workaround.
- **Low:** cosmetic, edge case or polish.

**Method.** I treated the app as a sandbox:

- Created, edited and deleted boards, goals, competitions, rules, badges, teams, offices, metrics, corrections, channels and slides.
- Paired and revoked a TV.
- Uploaded a walk-up clip.
- Viewed the wall at four resolutions.
- Checked phone width (375 px).
- Watched the console and network throughout. There were no uncaught JS exceptions.

Integrations were **not** synced or modified.

---

## Summary table

| ID | Sev | Area | Title |
|---|---|---|---|
| QA-1 | High | Teams / Boards / Goals | Team grouping, team goals and "Who is contributing" are always empty |
| QA-2 | High | Announcement rules | Rules say "fires the moment…" but detection runs hourly |
| QA-3 | High | Wall display | Fixed-pixel layout clips rows at 720p and overflows at 1080p |
| QA-4 | Med | Forms (several) | Error message stays on screen after a successful submit |
| QA-5 | Med | Leaderboards | Whitespace-only name accepted; empty name gives no error |
| QA-6 | Med | Numeric inputs | Invalid numbers (`-5`, `abc`) silently dropped |
| QA-7 | Low | Offices | Duplicate office names allowed |
| QA-8 | Med | Teams | Adding a member silently moves them off their current team |
| QA-9 | Med | Metrics | Duplicate metric display names allowed, making pickers ambiguous |
| QA-10 | Med | Points / Badges | Badge holders list doesn't refresh after giving a badge |
| QA-11 | Low | Channels | Competition slide labelled with raw kind "competition" |
| QA-12 | Med | Integrations / Health | Read-once source reported as "Late — check the scheduler" and overdue |
| QA-13 | Med | Competitions | "Value error," prefix leaks; publish lands on the wrong tab |
| QA-14 | Med | Competitions | Announcement date formatted in UTC ("Runs until 3 October"); inputs use browser tz |
| QA-15 | Med | Channels / TVs | Revoke says "stops immediately"; TV keeps playing ~60–90 s |
| QA-16 | Low | Wall – Message slide | Long headline truncated with ellipsis; no limit in the editor |
| QA-17 | Low | Channels / TVs | Revoked TVs can't be deleted from the list |
| QA-18 | Low | Wall – Goal slide | Gauge at 0% shows green caps at both ends |
| QA-19 | Low | Points / Seasons | First award auto-opened a season on the quarter's last day |
| QA-20 | Low | Goals | "Behind" status chip rendered twice per card |
| QA-21 | Low | Competitions | "Leading · X" shown when everyone is at 0 |
| QA-22 | Low | Points (a11y) | Screen readers read "10" + "1st" as "101st" |
| QA-23 | Low | Global (a11y) | Avatar link has no accessible name; drag handles named "⠿" |
| QA-24 | Low | Dialogs | Focus not returned to trigger; Esc discards a filled form silently |
| QA-25 | Low | Global | Row-action tooltips clipped/overlapping ("Renar Archiv Delete") |
| QA-26 | Low | Routing | Unknown routes silently redirect to Home (no 404) |
| QA-27 | Low | Global | `document.title` is always "GoalGetter" |
| QA-28 | Low | Performance | `/api/organization` fetched twice on every load |
| QA-29 | Low | Auth | Reset-password shows the form before validating the token |
| QA-30 | Low | Reporting | Email tab refers to a "Send me a test" button that doesn't exist |
| QA-31 | Low | Users – walk-up | YouTube `t=` not parsed; stored clip can't be played or removed |
| QA-32 | Low | Settings / MFA | "Require two-step sign-in" is on, but an unenrolled admin is never prompted |
| QA-33 | Low | Account | "Change password" offered to SSO-only user |
| QA-34 | Low | Recognition | Self-recognition allowed with no hint that it earns 0 points |
| QA-35 | Low | Notifications | Bell badge count updates late |
| QA-36 | Low | Leaderboards / Home | "6 days ago" vs "7 days ago" for the same timestamp |
| QA-37 | Low | Leaderboards | Detail page ignores the board's chosen layout |
| QA-38 | Low | Account | Notification preferences have no competition events |
| QA-39 | Info | Data | "Closed Deals" (count) sums to ~57K, likely the wrong column or unit |
| QA-40 | Low | Home | Standings debug card shipped on the Home page |

---

## High

### QA-1 — Team grouping, team goals and "Who is contributing" are always empty
- **Where:**
  - Leaderboards → group by Team
  - team goals
  - Goal detail → "Who is contributing"
  - Home → Standings (team)
- **Repro:**
  1. Create a board grouped by **Team** for Closed Deals, this month.
  2. It shows no rows (or only "unassigned"), even though Metropolis Sales Team has 89 members with data.
- **Cause:**
  - `api/app/aggregate.py` groups on `MetricFact.subject_team_id`, a snapshot taken when the fact was recorded.
  - Teams were created after the data arrived, so only **3 of 613** facts have a team id.
  - Rows with a null team are excluded.
- **Fix, either:**
  - **(a)** Group on the person's *current* team via a join to `user.team_id` for open periods, and keep the snapshot only for closed periods.
  - **(b)** When team membership changes, backfill `subject_team_id` for that user's facts in all open periods. Add a one-off migration or admin action "Re-attribute this period's data to current teams".
- Add a test: create facts, then the team, then add the member. The team board should show the total.

### QA-2 — Announcement rules say "fires the moment…" but only run hourly
- **Where:** Announcements (`/achievement-rules`) form copy, `api/app/notifications.py` `detect_rules`, called from `jobs.py` (hourly, `JOB_INTERVAL_SECONDS = 3600` in `main.py`).
- **Repro:**
  1. Create a rule "Closed Deals ≥ 1 in a day".
  2. Record a correction that crosses the threshold.
  3. Nothing appears on the wall. The celebration only comes after the next job tick, up to 60 min later.
- **Impact:** the core "celebrate the win on the floor" moment is delayed long enough to be meaningless, and the user thinks the rule is broken.
- **Fix:**
  - Run `detect_rules` for the affected metric and user right after ingest (connector sync, webhook, correction) in the same request or a background task. Keep the hourly sweep as a safety net.
  - Until then, change the copy to "within the hour".

### QA-3 — Wall layout doesn't fit the screen
- **Where:** `/display/{token}` board slides.
- **Repro:**
  1. Open a board slide with 10 rows at 1280×720. Rows 7–10 are entirely off-screen.
  2. At 1920×1080 the page overflows by 5 px (scrollbar flicker on some TVs).
  3. At 4K everything renders at 1080p pixel size, so it's tiny.
- **Cause:** fixed pixel heights (~1085 px total, 24 px rows) rather than viewport-relative sizing.
- **Fix:**
  - Render slides inside a fixed 1920×1080 "stage" and `transform: scale(min(vw/1920, vh/1080))`, letterboxed.
  - Alternatively, compute visible rows from available height and auto-page.
  - Add a visual regression check at 720p, 1080p, 4K and portrait.

---

## Medium

### QA-4 — Stale error after a successful submit
- **Where:** Recognise dialog (Achievements), Metrics create, Corrections record.
- **Repro:**
  1. Submit with a missing field. An error appears.
  2. Fix the field and submit successfully. The old error text stays visible.
- **Fix:** clear the error state on field change and on success, and show a success toast. A shared `useFormStatus` hook would fix all three.

### QA-5 — Leaderboard names: whitespace accepted, empty gives no error
- **Repro:**
  - Name `"   "` → Save. This creates a board with a blank title card.
  - Name empty → Save. Nothing happens, and no message is shown.
- **Fix:**
  - `name: constr(strip_whitespace=True, min_length=1)` on the API.
  - Trim on the client, with an inline "Give the board a name" error.
- Audit other name fields (goals, competitions, channels, badges) for the same issue.

### QA-6 — Invalid numbers silently dropped
- **Where:** Board row count and goal target / stretch inputs.
- **Repro:** type `-5` or `abc`. The value is stripped or ignored, and the form saves the previous or default value with no message.
- **Fix:** validate and show an inline error with the allowed range. Don't coerce silently.

### QA-8 — Adding someone to a team silently moves them
- **Where:** Teams → type-ahead add member.
- **Repro:**
  1. Add a person who is on Metropolis Sales Team to a new team.
  2. They are removed from Metropolis without any warning (member count 90 → 89).
- **Fix:** show "Test user is on Metropolis Sales Team. Move them?", or show the current team in the type-ahead result.

### QA-9 — Duplicate metric display names allowed
- **Repro:** create a metric with the same name as an existing one. It saves.
- **Impact:** metric, goal and rule pickers show two identical options, and rule labels become ambiguous.
- **Fix:** add a unique constraint on `(org_id, lower(name))` for active metrics, and show the source and unit in pickers.

### QA-10 — Badge holders don't refresh after "Give"
- **Where:** Points → Badges.
- **Repro:** give a badge to a person. The holder count and list stay unchanged until you reload the page.
- **Fix:** invalidate or refetch the badge query after the award mutation.

### QA-12 — Read-once data source reported as late
- **Where:** Integrations source list, Home → System health ("1 overdue"), and the stale-feed banner on boards (also shown on mobile, i.e. to agents).
- **Repro:** a Snowflake source with `interval_minutes = 0` (READ_ONCE, `models/data_source.py:31`) shows "Every 0 minutes · Late — check the scheduler".
- **Fix:**
  - Treat READ_ONCE as "Manual — last read {date}" in freshness, and exclude it from the overdue counts.
  - The API currently allows `0`. Make READ_ONCE an explicit mode rather than a magic number.

### QA-13 — Competitions: raw validation prefix, and the wrong tab after publish
- **Repro, validation prefix:** set an end before the start. The message reads "**Value error,** A competition has to end after it starts."
  - **Fix:** raise `PydanticCustomError`, or strip the prefix in the global 422 handler.
- **Repro, wrong tab:**
  1. Publish a contest whose start is in the past.
  2. The page switches to **Upcoming**, but the contest is under **Live**.
  - **Fix:** navigate to the tab that matches the item's computed status, or to its detail page.

### QA-14 — Competition announcement dates are in UTC; inputs use browser time
- **Where:** `api/app/competitions.py` `_start_body`: `ends = f"{competition.ends_at.day} {competition.ends_at:%B}"`.
- **Repro:**
  1. Create a contest that ends on the evening of 2 October, local time.
  2. The `competition.started` announcement says "Runs until **3 October**", because `ends_at` is stored in UTC and formatted without converting.
  3. Separately, the Starts and Ends inputs use the browser zone (Pacific here), while the org timezone is America/New_York.
- **Fix:**
  - Convert to the org's `ZoneInfo` before formatting.
  - Label the inputs with the org zone and convert on submit.
  - Apply the same check to every server-rendered date in notifications and emails.

### QA-15 — Revoked TV keeps playing
- **Where:** Channels → TV → Revoke ("stops immediately").
- **Repro:**
  1. Revoke a playing TV.
  2. `/api/display/{token}/celebrations` returns 404 every 3 s, but the slide rotation continues for about 60–90 s, until the next channel refresh.
- **Fix:** in the display client, treat a 404 or 403 from *any* feed request as revoked, and switch to the disconnected / re-pair screen at once.

---

## Low

### QA-7 — Duplicate office names
Two offices named "Gotham" can coexist. One office also shares its name with a team.
**Fix:** unique `(org_id, lower(name))`, with an inline error.

### QA-11 — Competition slide label
In the channel slide list, competition slides show the lowercase kind "competition" instead of the competition's name.
**Fix:** resolve the name, the way board and goal slides already do.

### QA-16 — Message slide truncation
A long headline is ellipsised on the wall.
**Fix:** shrink-to-fit with a minimum size, wrap to two lines, and add a character counter or limit in the editor.

### QA-17 — Revoked TVs can't be removed
Revoked displays stay in the list forever.
**Fix:** add a Delete action for revoked displays, or collapse them into "Revoked (3)".

### QA-18 — Goal gauge at 0%
Both ends of the arc have green round caps, so an empty gauge looks started or complete.
**Fix:** draw the progress stroke only when value > 0, and use a neutral track colour.

### QA-19 — Season auto-opened on the quarter's last day
The first point award (30 Sept) auto-created season "Q3 2026", which ends the same day.
**Fix:** if fewer than N days remain, open the *next* period, or ask the admin. Show a toast: "Season Q3 started".

### QA-20 — Duplicate "Behind" chip
Goal cards render the status chip twice (header and footer).
**Fix:** keep one.

### QA-21 — "Leading" with no scores
A running competition where every entrant is at 0 shows "Leading · Jayden Craig".
**Fix:** show "No scores yet" when the max score is 0 or tied at 0.

### QA-22 — "101st"
`web/src/pages/Points.tsx` renders points and ordinal in adjacent spans, so assistive tech reads "101st".
**Fix:** add a visually hidden separator, or an `aria-label` such as "10 points, 1st place".

### QA-23 — Unnamed controls
- The header avatar link has no accessible name.
- Slide drag handles announce as "⠿".

**Fix:** `aria-label="Your account"` and `aria-label="Reorder {slide name}"`, plus keyboard reordering.

### QA-24 — Dialog focus and discard
- After closing a dialog, focus goes to `<body>`.
- Esc or × on a filled form discards the input with no prompt.

**Fix:** return focus to the trigger, and confirm when the form is dirty.

### QA-25 — Tooltips clipped
Icon-button tooltips on list rows overlap each other and the sidebar ("Renar · Archiv · Delete").
**Fix:** a portal-rendered tooltip with collision detection, or a ⋯ menu.

### QA-26 — No 404 page
`/anything-unknown` redirects to `/` with no message.
**Fix:** a "Page not found" page with a link home. Keep the redirect only for the old `/achievement-rules` alias, if one is introduced.

### QA-27 — Page titles
The tab title is always "GoalGetter".
**Fix:** set `document.title = "{Page} · GoalGetter"` per route.

### QA-28 — Duplicate request
`/api/organization` is requested twice on load (two components fetching independently).
**Fix:** a shared query cache or context.

### QA-29 — Reset-password with a bad token
The form is shown and the error appears only after submit.
**Fix:** validate the token on load, and show "This link has expired — request a new one" straight away.

### QA-30 — Reporting email tab
The copy refers to a "Send me a test" button that isn't rendered, and it doesn't say whether SMTP is configured.
**Fix:** add the button (disabled with an explanation when SMTP isn't set), or change the copy.

### QA-31 — Walk-up clip handling
- A YouTube link with `&t=43s` ignores the timestamp (the separate "Start at" field stays 0).
- An uploaded clip can't be previewed or removed after saving.
- The YouTube player chrome is visible in the preview.

**Fix:**
- Parse `t`/`start` from the URL into "Start at".
- Add ▶ and Remove controls for the stored asset.
- Use `controls=0`, `modestbranding` and `iv_load_policy=3` in the preview.

### QA-32 — Two-step "required" but not enforced
Settings has "Require two-step sign-in" on, yet the signed-in admin has 2FA off and was never prompted.
**Fix, either:**
- Enforce enrolment at next sign-in, with a grace period.
- Or state "SSO users are exempt — your identity provider handles MFA".

Also list the unenrolled users.

### QA-33 — Change password for SSO users
The Account page shows "Change password" to a user who signs in with Microsoft.
**Fix:** hide it for SSO-only accounts, or explain that it sets a fallback password.

### QA-34 — Self-recognition
You can recognise yourself. `_pay_the_recognised` correctly pays 0 points, but the UI doesn't say so.
**Fix, either:**
- Exclude self from the picker.
- Or show a hint: "You won't earn points for recognising yourself."

### QA-35 — Bell badge lag
After a recognition, the notification bell count updates only on the next poll or navigation.
**Fix:** invalidate the notifications query after mutations that create notifications for the current user.

### QA-36 — Inconsistent relative time
The same "last recorded" timestamp shows "6 days ago" on one page and "7 days ago" on another.
**Fix:** one shared `formatRelative` helper with consistent rounding.

### QA-37 — Board detail ignores its layout
A board set to podium or race still renders as a plain table on its detail page.
**Fix:** render the chosen layout, or show a wall preview, and add Edit and "Show on a TV" buttons.

### QA-38 — Notification preferences are incomplete
Competition events (started, ending soon, won) can't be toggled.
**Fix:** add them to the preferences list.

### QA-39 — Suspicious metric values (data, not code)
"Closed Deals" is typed as a count but sums to ~57K for the month, which suggests it's pointing at an amount column.
**Fix:**
- Verify the Excel mapping.
- Consider a sanity warning when a count metric's daily values are consistently > 1,000.

### QA-40 — Standings debug card on Home
`web/src/components/StandingsCard.tsx` is described in its own comment as existing so the numbers can be checked by eye.
**Fix:** remove it from Home, or move it behind an admin "Diagnostics" page.

---

## Verified working (no bugs found)

- **Sign-in session and role gating:** all admin pages loaded, and there were no console errors on any page.
- **TV pairing:** the 4-character code works end to end and accepts lowercase.
- **Display security:** invalid or revoked token → 404; IP allowlist → 403.
- **Validation:**
  - goal stretch levels, with clear messages
  - future-dated corrections are rejected
  - recognition link validation
  - walk-up audio file-type and size validation
- **Other:**
  - The competition "Check" preview (last-period simulation) is accurate.
  - The Appearance live preview is correct for all 8 slide types, and the theme toggle persists (`gg.theme`).
  - Phone width (375 px) has no page-level horizontal overflow; tables scroll inside their containers.
  - Delete flows use confirm prompts with clear consequence copy (native `confirm()`, see UI review §5).

---

## Test-data cleanup status

**Removed via the API** (all created by this QA pass):

- display 5
- rule 5
- badge 1
- board 8
- goal 193
- team 17 (the moved user 417 was put back on team 13)
- competition 10
- channel 8 slides 19 and 21. Channel 8 is back to its original two slides.

**Still in the database.** I have no delete endpoint for these. My SQL cleanup transaction failed and rolled back, and further direct DB access was blocked, so they need a manual decision:

| Table | Rows | Notes |
|---|---|---|
| `point_award` | id 1 | "QA Badge" award to user 1 |
| `season` | id 1 | Q3 2026, auto-opened by that award (QA-19) |
| `notification` | 96591–96594 | recognition / badge notifications |
| `walkup_media` | user 401 | uploaded test clip, plus its `stored_asset` row |
| `metric_fact` | metric 35, user 401 | manual −5 and +7 corrections |
| `metric_definition` | id 35 `qa_closed_deals` | duplicate-name test metric (QA-9) |

- **Audit-log entries** for all QA actions remain. This is expected, and they're useful as a record.
- **Display 4 ("test")** now shows as recently seen, because I opened its link.
- **Backup:** a pre-QA dump was taken at `%TEMP%\claude\…\scratchpad\goalgetter-before-qa.dump` (pg_dump `-Fc`, 3.9 MB). Restoring it removes everything above, but also anything else changed since it was taken.
