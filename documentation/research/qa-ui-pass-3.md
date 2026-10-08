# GoalGetter — QA / UI pass 3: verification of Phases 7–9

**Date:** 5 Oct 2026
**Build:** working tree on `cacc8ef` (dev)
**Where:** http://localhost:8080, signed in as the org admin
**Viewports:** 1440×900 and 375×812 in the app; the wall in headless Chrome at 1920×1080

**Scope:** confirm that Phase 7 (the Q2 bug fixes and the review's top ten), Phase 8 (the review's page notes) and Phase 9 (profiles) landed, and find anything else worth doing.

**Earlier reports:**

- [qa-bug-report-2.md](qa-bug-report-2.md) (Q2-n)
- [ui-ux-review-2.md](ui-ux-review-2.md) (§n)

New findings here are **P3-1 onwards**.

**Method.** Real use, with throwaway records named "QA3":

- a board
- a channel made from the template
- a TV paired by code
- a celebration rule
- a $500 correction for Test User
- a live two-person contest (Test User vs Jayden Craig)

Each was watched on the paired TV, then deleted through the app's own delete actions, which also exercised the delete confirms. Integrations were not synced.

**Not covered:** the agent and manager views. There are no test logins, and I did not impersonate real accounts. The profile privacy rules were checked through the API as an admin only.

---

## 1. Verdict

**Nearly everything claimed is in and works.**

- Of about 60 items checked across Phases 7–9, **55 are confirmed** in the running app or on the TV.
- **2 are only partly done** (P3-3, P3-6).
- **No first-pass or second-pass fix has regressed.**

The app now reads as a finished, coherent product:

- The previews are honest.
- Money is formatted.
- Pace is right for short windows.
- The stale-data story is told by source.
- Deletes clean up after themselves.
- Profiles exist.

What's left is a short list of edges. Most are small, two are worth doing soon (P3-1, P3-2), and one is a real foot-gun (P3-4).

---

## 2. Confirmed working

### Phase 7: the Q2 bugs

| Item | Seen |
|---|---|
| Q2-1 hour-based pace | A same-day contest reads **"9.8% of the window gone"** about 50 min into the working day, rising to 11.3% later. It no longer says 100% |
| Q2-2 money in announcements | The TV showed **"QA3 BIG DEAL · $500 · Test User · Test just closed $500!"** about 4 s after the correction. The rules table shows "at least **$350**" |
| Q2-3 honest previews | The board sample shows teams ("Northern Lights"), a count as "48", "Last 30 days" and a SAMPLE chip. The contest sample says "Test User vs Jayden Craig", "13 hours left" and no prize |
| Q2-4 rule check | "Check the last 4 weeks" says "28 times… about 7 a week, for 28 people" |
| Q2-5 stale data | Source card: "No new numbers… newest row is from Thu 3 Sep". Inbox: "No new numbers from Excel since Thu 3 Sep". Home banner: "No new numbers since Thu 3 Sep · Excel · Check it" |
| Q2-6 deletes clean up | After deleting the contest and the rule, the notification count went back to the baseline exactly |
| Q2-7 track record | One row per series. "0 of 3" counts only the periods that count |
| Q2-8 bell on a phone | A full-width sheet at 375 px, with nothing off-screen |
| Q2-9 Send button | Choosing a TV sends nothing; Send does. Toast: "…plays for 10 seconds" |
| Q2-10/13 statuses | "Finished at $0.00 · missed by $250,000.00"; Home's Needs attention says "missed by…" |
| Q2-12 Data as of | The contest page says "Data as of just now" after a correction |
| Q2-14 bulk goals | Opens on "Choose a team…" |
| Q2-15 detector | Jarvis Bot, Northwind Vegas and the Test Users are handled (the Test Users are now suspended and hidden) |
| Q2-22/23 toasts and words | "QA3 throwaway TV connected — playing QA3 floor"; "Pair with a code"; "Board created · **View**" |
| Q2-24 titles | "Home · GoalGetter"; "Tony Stark — Closed Deals" as both H1 and tab title |
| Q2-28 | "Cancel contest" in red (but see P3-4) |
| Q2-29 dates | "Mon 5 Oct, 9:52 am", "Image from 28 Sep", "Since 3 Sep" |

### Phase 7.9 and Phase 8: the review's items

| Item | Seen |
|---|---|
| Celebration hierarchy | Figure first ("$895", "$500"), then name, then sentence, with the person's photo |
| Show on a TV | Lists channels with "Already on", adds in one click ("QA3 sprint added to QA3 floor"), and offers Preview + Send |
| Channel template confirm | Asks for a name and shows a numbered list of slides before creating |
| Palette | Finds teams, offices, rules, boards and contests ("qa3" found all four kinds), lists "new" actions and settings tabs ("brand" → Branding). People show their address |
| Recent wins | "Test User — QA3 Big deal · **$500** · 2 minutes ago" |
| 8.1 people | "Their face"; "No team"; "Agent / Invited / Active"; team editor "Leave empty to use its initials, 'ST'" and "From its name"; "Empty — archive?"; five offices marked "Unused — archive it to tidy the pickers?"; "View profile" |
| 8.2 Home and goals | One-line personal state; "No numbers for October 2026 yet · Show last month" works; "Teams ranked"; "Whole organization"; "Made automatically" and "Repeats monthly" tags with a hover line; "\| expected by today"; "Leave out the 50 who recorded nothing in September 2026" |
| 8.3 | The entrant picker closes after a pick and keeps focus; Default sounds sit below the rules; the Email tab says "Email is set up — sending from goalgetter@…"; the metric duplicate error is on the field (`aria-invalid`); "New metric" rests disabled; plain words (Total, Number, Money · 2 decimals, Higher is better) |
| 8.4 | Assets has an "Unused 4" shelf with "Remove all 4". **The portrait warning does show** on Appearance for the 811×1080 background (the roadmap said it was not seen). Activity filters work (Kind = Contest). "You are the only one… Set it up now". Sidebar groups fold (`gg:nav-folded:1`). The timezone list reads "Pacific Time — Los Angeles (UTC−7)" |
| 8.5 | Channel editor thumbnails, the "Settings" label, "Connect a TV" (channel preselected), and Play rotation (Prev, Pause, Next, "2 of 3"). **The two-entrant contest is a head-to-head on the wall, with faces** |
| 8.6 | "It also comes off the TVs: removes 1 slide from QA3 floor." on board and contest delete |
| 8.7 | "Sample · Real numbers" in the board and goal editors; Real draws today's numbers |

### Phase 9: profiles

- `/people/:id`: a header with Recognise, Give a badge and Edit, This season, and a private Numbers section under "🔒 Only Arthur, their managers and admins see this".
- `/people/me` has "Edit your details".
- A hidden account returns **404**. An unknown ID shows "This profile isn't available".
- Names link to profiles on Home's team card (11 links).
- At 375 px the profile stacks cleanly.
- "Colleagues can see each other's profiles" is in Settings → What people can set, with its explanation.

### Phone and accessibility

- **No horizontal scrolling** on the 13 routes re-checked at 375 px. Home measures 2 px wide, but it can't scroll.
- **One `h1`** on the pages checked.

---

## 3. New and remaining findings

| ID | Sev | Area | Finding |
|---|---|---|---|
| P3-1 | Med | Wall | An empty **list** board draws a blank screen on a TV, and "Real numbers" previews it as blank |
| P3-2 | Med | Wall / Boards | Archiving a board that plays on a TV gives no warning; it silently drops off the wall, and the editor calls it "Nothing to show yet" |
| P3-3 | Med | Home | Stale data is still told three ways on one screen (Thu 3 Sep vs 11 days ago vs "Check the integrations") |
| P3-4 | Med | Contests | The "Cancel this competition?" confirm has **two buttons both labelled "Cancel"** |
| P3-5 | Low | Profiles | Tab title keeps the previous person's name on "This profile isn't available" |
| P3-6 | Low | Profiles / goals | "Nothing yet is not a place" isn't applied: my profile says "$0.00 · 39th of 137"; a goal with an all-zero history still draws an empty chart |
| P3-7 | Low | Money | Cents are inconsistent: "$500" in celebrations, "$500.00" on the wall's contest panels, "missed by $250,000.00" on goals |
| P3-8 | Low | Channel editor | Thumbnails are read aloud in full by screen readers, and look alike (mostly background photo) |
| P3-9 | Low | Wall | A template-made "Recent wins" slide never becomes "Latest wins", because the template typed its title |
| P3-10 | Low | Contests | A cancelled contest still shows "How it is going · Leading · On pace to finish at $3,900" |
| P3-11 | Low | Contests | Projection from the first minutes of a window ("On pace to finish at $5,106" from one $500 entry at 9:50) |
| P3-12 | Low | Home | "Showing September 2026" while the period select still says "This month", and "is leading" in the present tense |
| P3-13 | Low | Boards | Board detail's wall preview still has the invented "Main floor" line |
| P3-14 | Low | Copy | Several small wording mismatches (list below) |
| P3-15 | Low | Palette | A team and an office with the same name are two identical rows, with no kind label |
| P3-16 | Low | Channels | "Connect a TV" from a channel drops you on the channel list with `?channel=18` left in the URL |
| P3-17 | Low | Boards | Archiving a board shows no toast (deleting does) |
| P3-18 | Low | Walk-up | "Choose from Assets" is invisible until the library has a sound or video, with no hint that it exists |
| P3-19 | Low | Activity | A few kinds are still internal ("User identity", "Game token", "Warehouse", "Mapping", "Walkup"); rows show keys ("metric: sales_feed_amount_today · entity type: user") and email addresses rather than names |

### P3-1 — An empty list board is a blank TV screen

**Repro:**

1. Make a board for Closed Deals by team, "This month".
2. Choose **Real numbers**. The preview is the header over an empty background, with no rows and no words.

**Cause:**

- The podium, race and game-board layouts each say "Nobody has scored yet". The default **list** layout (`components/wall/Board.tsx`) says nothing.
- `EditorPreview` falls back to the sample only when the server returns `null`, not when it returns a board with no entries.

**Why it matters:** on the 1st of every month, every calendar-period list board on every TV is a blank screen until the first number arrives.

**Fix:**

- Give the list the same empty state as the other layouts: "Nobody has scored yet this month", plus last period's winner if there was one.
- In the editor, treat zero entries like `null` and say so ("Nothing in October yet — showing a sample").

### P3-2 — Archiving a board on a TV is silent

**What happens:**

- Archiving QA3 board (which played on QA3 floor) happened instantly, with no confirm and no toast.
- The board **left the TV's rotation** (the display feed no longer listed it).
- The channel editor still lists it, with a thumbnail saying "Nothing to show yet", which reads as missing data.

**Fix:**

- Give archive the same wall-aware confirm as delete: "It stops playing on QA3 floor (1 slide). Restore it to bring it back."
- In the channel editor, mark the slide "Archived — not playing", with a Restore link.
- The same applies to archiving a goal.

### P3-3 — Home still tells the stale-data story three ways

Home currently shows:

- **Banner:** "No new numbers since **Thu 3 Sep** · Excel · Check it". This is right for Excel.
- **System health:** "Data last recorded **11 days ago**". That is 23 Sep, from the read-once Snowflake source.
- **Your team:** "Nothing recorded for 88 of the team in 11 days — the data may have stopped arriving. **Check the integrations**".

Each line is true on its own, but together they're three dates and two calls to action.

**Fix:**

- The team card should reuse the banner's sentence (source, date and link), or just say "No numbers for 11 days — see the note above".
- System health should label its date by source ("Snowflake read once on 23 Sep · Excel: no new rows since 3 Sep").

### P3-4 — "Cancel" vs "Cancel" in the contest confirm

**What happens:**

- **Cancel contest** opens "Cancel this competition? … **[Cancel] [Cancel]**".
- The first button closes the dialog; the second (unbordered) cancels the contest.
- My first attempt pressed the wrong one.

**Fix:**

- Name the action button "Cancel contest" and the dismiss button "Keep it running".
- Check the other `ask()` calls for a verb that collides with "Cancel" (for example "Cancel invite", "Cancel schedule").

### P3-5 — Stale tab title on an unavailable profile
After viewing /people/me, opening /people/999999 shows "This profile isn't available", but the tab still says "Jayden Craig · GoalGetter". Set the title to "Profile not available".

### P3-6 — "Nothing yet is not a place", not applied everywhere
- **Profile → Numbers:** my profile shows "DEALS BOARD · $0.00 · 39th of 137". Home stopped doing this in 5c. Leave out boards where the person is at zero on a higher-is-better metric, or show "No numbers yet".
- **Goal detail:** "Before this" is still an empty axis for Tony Stark, whose earlier months are all zero rows. 8.2's "No earlier months" covers months with *no* rows, but not months whose rows are all zero. Treat all-zero as none, or draw visible zero bars with "Nothing recorded".

### P3-7 — Cents
| Where | Shows |
|---|---|
| Celebrations and Recent wins | "$500" |
| The wall's head-to-head and lists | "$500.00" / "$4,215.37" |
| Goals and Home | "missed by $250,000.00" / "$0.00 of $250,000.00" |

**Fix:** one rule — drop `.00` on whole amounts everywhere a person reads money, keep cents where they're non-zero, and keep exports exact.

### P3-8 — Thumbnails and screen readers
The channel editor's thumbnails are full slides in the DOM. A screen reader reads every name and score in each one, and their titles become extra `h2`s. Add `aria-hidden="true"` (or `inert`) to the thumbnail. Visually, all three look like the same background photo; drawing them without the background (or dimmed heavily) would make each slide's content readable at that size.

### P3-9 — "Recent wins" on template channels
7.9 retitles the slide to "Latest wins" when the newest win is over a day old, unless a title was typed. The channel template types "Recent wins", so template channels never switch. On QA3 floor the slide showed "Recent wins" over a 3-day-old win. Leave the template's title empty so the automatic title applies.

### P3-10 — A cancelled contest still forecasts
After cancelling, the page says "Cancelled — no result" but keeps "How it is going · 11.3% of the window gone · Leading · Test User · On pace to finish at $3,900" and "Jayden Craig is $500.00 behind". Hide the report card and the "behind" line once a contest is cancelled.

### P3-11 — Early projections
"On pace to finish at $5,106" came from one $500 entry about 50 working minutes into the day. Don't project until about 25% of the window has gone, or until a few entries exist; show "Too early to call" instead.

### P3-12 — Home's "Show last month"
While "Showing September 2026 · Back to now" is on, the period select still reads "This month", and Worth a word says "Arthur Curry **is** leading the team…". Show the select as "September 2026" (or disable it), and use the past tense ("led September with…").

### P3-13 — "Main floor" on board detail
7.4 removed the invented channel line from editor previews, but the board detail's "As a wall shows it" still draws "Main floor".

### P3-14 — Wording
| Where | Now | Suggest |
|---|---|---|
| Delete an archived board | "Archive it instead to keep it out of the way" | Drop the line when it's already archived |
| Rule delete | "…pause it instead" (the button is **Disable**) | Use the same verb in both: "Pause" |
| Metrics hint | "should the unit be **currency**" (the option is now **Money**) | "should the unit be Money" |
| Inbox vs source card | "It **reads** cleanly" vs "It **syncs** cleanly" | Pick one |
| Contest-started notification | "Runs until 5 October." | "Runs until 11:30 pm today" (or "Mon 5 Oct, 11:30 pm", the app's date style) |
| Channels footer | "Revoking it stops that television immediately." | "…and the TV shows a pairing code instead." |

### P3-15 — Palette results without a kind
"metropolis" returns "Metropolis Sales Team / Metropolis Sales Team" and "Metropolis Sales Team": a team and an office, indistinguishable. Add a small kind label (Team, Office, Board, Rule, Contest, Channel) to every result.

### P3-16 — Connect a TV from a channel
The button links to `/channels?connect=1&channel=18`, so after pairing you're on the channel list (URL still `?channel=18`) rather than back on the channel. Open the dialog in place, or return to the channel afterwards.

### P3-17 — Archive toast
Deleting a board says "Board deleted". Archiving said nothing. Add "QA3 board archived · Undo".

### P3-18 — Walk-up from Assets
The option only appears once Assets holds a sound or video (the dev library has none), so nobody will find it. Show it disabled, with "Add sounds or video in Assets to choose one here".

### P3-19 — Activity, the last internals
- **Kind filter:** "User identity", "Game token", "Warehouse", "Mapping", "Walkup" (lowercase u) and "Announcements" (the Teams posting tab) need plainer names, or grouping under "Integrations".
- **Rows:**
  - show metric keys ("metric: sales_feed_amount_today")
  - show raw enums ("entity type: user")
  - name the actor by email ("peter@…") rather than by name

---

## 4. Suggestions beyond fixes

1. **The first of the month on the wall.** Together with P3-1, consider a "Last month's winners" fallback on calendar boards for their first working day. A wall that celebrates September on 1 October beats a blank one.
2. **An agent and manager pass after Phase 9.** Profiles changed what agents can open (names are now links, and the palette finds colleagues). Phase 7.1 did this before profiles existed, so it is worth one more short pass with two real logins, or test accounts made for it.
3. **A data-freshness chip on every wall slide.** Admins now get the stale story, but a TV still shows September's numbers under "Last 30 days" with no hint. A small "as of 23 Sep" in the corner, shown only when the data is over a day old, keeps the wall honest.

---

## Test data and cleanup

**Created:**

- board 16 "QA3 board"
- channel 18 "QA3 floor" (template), with 3 slides and later the contest
- display 12 "QA3 throwaway TV" (paired by code)
- rule "QA3 Big deal"
- one correction (Test User, $500, 5 Oct)
- competition 14 "QA3 sprint" (published, then cancelled)

**Removed:**

- The board, the contest and the rule were deleted through the UI, which also tested the wall-aware confirms.
- The TV, the channel and the correction were removed with the app's own delete endpoints.
- The rule's 10 points (kept by design on rule delete) were removed directly, matched on id and content.

**Verified:**

- Every table matches the pre-test row counts, except:
  - `audit_log`, which is expected
  - `display_preview`, where two rows from your earlier session were swept by the app's own expiry when I sent a preview
- **Notifications are back to baseline with no manual cleanup**, which confirms 7.5.

**Backup:** `scratchpad/goalgetter-before-qa3.dump`.
