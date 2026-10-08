# GoalGetter — UI / UX review, pass 2

**Date:** 2 Oct 2026
**Build:** `6828d9e` (dev), after Phases 5 and 6
**Viewports:** 1440×900 admin, 375×812 phone, light and dark; walls at 1920×1080, 1280×720 and 1080×1920
**Companion doc:** [qa-bug-report-2.md](qa-bug-report-2.md) (defects, Q2-n)
**First pass:** [ui-ux-review.md](ui-ux-review.md)

**Goal (unchanged):** a professional app that is responsive, intuitive and easy to understand, with a low learning curve.

---

## 1. Where things stand

The first pass's big themes are fixed:

- **Pickers scale.** The people picker is excellent: type-ahead, faces, team and email, "add everyone on Metropolis (90)".
- **Bots are out of the counts.**
- **The wall fits every TV**, and portrait is genuinely good.
- **The nav makes sense.**
- **Saves confirm with toasts.**
- **Pairing, re-pairing and revoke** feel like a real product.
- **Phase 6 added real delight:** the drawn badges, the trophy and confetti takeovers, the scenes, night mode, the Inbox and the command palette.

The app has moved from "powerful but rough" to "professional, with seams". What is left falls into four themes:

1. **The previews tell small lies.** The editors' wall previews show sample people, the wrong units, "March" and "Steak dinner" whatever the form says. The rule check and the template contradict each other. Celebrations print "500.00" without a "$" (Q2-2, Q2-3, Q2-4). Preview-first was the right bet, but a preview that's wrong is worse than none, because people trust it.
2. **Stale data is the real state of this deployment, and the app doesn't say so plainly.** Nothing has arrived for 9 days.
   - Home blames "400 people".
   - The manager card guesses right.
   - Integrations says "Working".
   - The Inbox says nothing.
   - The rule check advises lowering a bar.
   - Every goal reads "On track" at $0.

   One clear "No new numbers since 23 Sep" story would fix five screens (Q2-5, Q2-10).
3. **Time is measured too coarsely.** Pace counts whole days, so a 9-to-5 sprint, the template the app now offers, is "100% gone" at 10 am, and a "Today" goal never has a pace (Q2-1).
4. **The last 10% of polish:**
   - leftover dev vocabulary ("sum", "currency (2dp)", `asset.uploaded`)
   - old words ("screen", "achievement")
   - four date formats
   - a few phone clips

### Scorecard (pass 1 → pass 2)

| Area | Pass 1 | Pass 2 | Note |
|---|---|---|---|
| Copywriting & microcopy | A | **A** | Still the best thing about the product; a handful of leaks listed in §9 |
| Information architecture / nav | C+ | **A−** | Grouped, consistent names; the sidebar now scrolls at 900 px |
| Forms & pickers | C | **A−** | The people picker is excellent; metric form still raw enums |
| Feedback & state | C | **B+** | Toasts and skeletons everywhere; gaps after team and badge create |
| Wall / TV display | B− | **A−** | Scales, pages, portrait, night mode, re-pairing; celebration hierarchy (§6) |
| Previews & trust | n/a | **C+** | New area; previews ignore the form (§3) |
| Data health & honesty | C | **C+** | Diagnosed correctly in one card, contradicted in four places (§4) |
| Responsive admin (phone) | B | **A−** | No overflow anywhere; three clips |
| Accessibility | B− | **A−** | Clean scan; three small leftovers |
| Onboarding / time-to-first-wall | C | **B+** | Checklist, templates, Inbox; templates need a confirm step |

---

## 2. Top 10 recommendations

| # | Recommendation | Why | Effort |
|---|---|---|---|
| 1 | **Make the previews honest.** Feed the form's unit, ranking (people/teams), period label, prize, end time, entrant count and person into `sampleSlide`. Drop the fake "Main floor" strip on editors. | Q2-3. The preview is the product's best idea; it has to match the wall. | S |
| 2 | **Fix money in announcements.** "$500", not "500.00", on walls, the feed and the rules table. | Q2-2. The single most-seen sentence the product writes. | S |
| 3 | **Hour-based pace for short windows**, and for every competition. | Q2-1. A sprint template that's wrong all day undermines the contest feature. | S–M |
| 4 | **One stale-data story.** "Newest row" per source, an Inbox item, a single Home line ("No new numbers since 23 Sep — the Closed Deals sheet hasn't changed"), and the rule check and goal status saying "no data" instead of "lower the bar" or "on track". | Q2-4, Q2-5, Q2-10. The most common real-world failure, currently told five different ways. | M |
| 5 | **Make the celebration about the person and the number.** Their photo inside the trophy glow, the figure as the hero ("$500" huge), the name second, the rule name as the eyebrow. | §6. The takeover is the moment the room looks up. | S |
| 6 | **"Show on a TV" should finish the job.** From a board, goal or contest, open "Add to a channel" with the item chosen, list channels already showing it, and offer "Preview on a TV". | §5. Today it drops you on the channel list. | S |
| 7 | **Human words for internals.** Metrics: "Total", "Average", "Money · 2 decimals", "Higher is better". Activity log: sentences, not `competition.changed_while_running (fields: ends_at,prize…)`. Timezone: a searchable list ("Pacific Time — Los Angeles"). | §9. The last dev-tool seams. | S–M |
| 8 | **Person page as a profile, not just a form.** Points this season, badges with art, goals, recent wins, rank on their boards, then the editable fields. Same on Account for "me". | §7. "A badge stays on their profile" — there is no profile to see it on. | M |
| 9 | **Clean up after deletes**, and say what happens to points. | Q2-6. Ghost "QA2 sprint has started" notifications for a deleted contest. | S |
| 10 | **Command palette covers everything with a name:** teams, offices, rules, badges, metrics, settings tabs, and "actions" ("New goal", "Connect a TV"). | §8. "metropolis" finds nothing today. | S–M |

---

## 3. Previews and trust

Preview-before-it-reaches-a-TV (5j) is the strongest idea in the product. Three things stop it earning full trust.

### 3a. The sample doesn't follow the form

The table is in Q2-3. The fix is mechanical: `sampleSlide` should take the form state, not just `kind` and `title`.

Two extra touches:

- **Label the sample as such, inside the picture** (a small "Sample" chip in a corner, as the TV preview uses "PREVIEW").
- **When real data exists, offer "Show real numbers"** for boards and goals, the way the slide editor already does through `/channels/{id}/screens/preview`. A board's real standings can be computed from the unsaved form exactly as that endpoint does.

### 3b. Checks that agree with templates

The **Big deal** template says "fired 28 times in 4 weeks", then **Check last week** says "would not have fired… lower the bar" (Q2-4). Use one window, and when the window holds no data, say that instead of advising.

### 3c. "Preview on a TV" as a dropdown that fires

Selecting a TV sends immediately (Q2-9). A select plus a **Send** button is safer for keyboard users and allows re-sending.

---

## 4. Data health: one story, told once

**Today's state:** the Excel sheet hasn't changed since 23 Sep, and it syncs cleanly every time. What each screen says:

| Screen | Says | Should say |
|---|---|---|
| Home banner | "400 people have recorded nothing in 7 days" | "No new numbers since Wed 23 Sep · Closed Deals sheet · Check it" |
| Home health | "Data last recorded 8 days ago" (orange) and "324 on no team" again | Keep the first; drop the duplicate team line (the banner has it) |
| Manager card | "Nothing recorded for 92 of the team in 8 days — the data may have stopped arriving" | ✓ already right |
| Integrations | "Working — the last sync completed cleanly" | "Syncing cleanly · newest row 23 Sep (9 days)" in warning colour |
| Inbox | (nothing) | "No new numbers from Closed Deals in 9 days" |
| Rule check | "Would not have fired… lower the bar" | "No Sales Feed numbers in the last 7 days" |
| Goals | "On track" at $0 | "No numbers yet this period" |

**Rule of thumb:** whenever "nothing happened" could mean "the data stopped", say the data part first.

---

## 5. Getting things onto a wall

The pieces are all there: templates, slide editor, previews, pairing and scheduling. The paths between them are a little long.

- **"Show on a TV"** on a board just links to TVs & Channels. Open the add-slide dialog with the board chosen, show "Already on: Sales floor", and offer "Preview on a TV".
- **Channel templates** create the channel instantly, with no name and no preview of what goes in it. Show a one-step confirm: name, the slides it will add (with thumbnails), and Create. Clicking twice makes two "Sales floor"s.
- **Channel editor:**
  - slide thumbnails
  - a "Play rotation" preview
  - a **Connect a TV** button beside "No televisions are playing this yet"
  - the gear icon labelled "Settings"
- **Connect a TV:**
  - the tab says "Pair a screen"
  - success says "TV link created" even when paired by code
  - say "Connected — QA2 throwaway TV is playing Sales floor"
- **Competition slides:** a two-entrant contest is a VS layout on its detail page but a two-row list on the wall. Use the head-to-head panels there too.
- **Recent wins slide:**
  - rows are "Name — rule name", with no figure and no time
  - add the value ("$500") and "2 min ago"
  - when the newest win is days old, title it "Last wins" or fall back to a board, so a wall never presents week-old news as recent

---

## 6. Celebrations on the wall

The takeover (screenshot taken at 1920×1080) has lovely drawn art, a glow and confetti. The hierarchy needs one change.

```
Now:                                 Suggested:
      [ rocket ]                           [ photo inside the glow, rocket badge ]
     QA2 BIG DEAL      (eyebrow)              QA2 BIG DEAL          (eyebrow)
    Jayden Craig       (huge)                    $500               (huge)
 Jayden just closed 350.00!  (small)          Jayden Craig          (large)
                                        "Jayden just closed $500!"  (medium)
```

- **The person's photo is missing**, though they have one. A face on the wall is the most motivating thing the product shows.
- **The figure is the news**, and it's currently the smallest text, with no "$" (Q2-2).
- **The takeover background** is plain near-black. Use the channel's background, dimmed, so it feels like the same wall.
- The sound and walk-up logic is good; the "Default sounds" card is well thought through (but see §8 about where it sits).

---

## 7. People, and seeing what they've earned

The economy (points, seasons, badges, tiers and the wheel) is rich, but **there is nowhere to see one person's story**:

- **User detail is a form:**
  - name and email three times
  - Nickname, Birthday, Title, Team, Role
  - Walk-up, Game pieces
- **Account is the same form**, for "me".

**Proposed: a profile header on both pages, above the form:**

```
[photo]  Test User · Software Engineer · No team        [Recognise] [Give badge]
         Q4 2026: 15 points · 2nd       Badges: 🚀 QA2 Badge (2 Oct)
         Goals: Sales Feed Amount — Hit ($500 / $400)
         Recent: QA2 Big deal · $500 · today
```

**Smaller fixes:**

- An admin editing someone else sees "**Your** face" in game pieces. Use "Their face".
- Use "No team" rather than "— unassigned —".
- Capitalise roles and statuses ("Agent", "Invited").
- **Walk-up upload** is a bare native file input. Reuse the Assets drop zone, or "choose from Assets".

**Teams:**

- The short-name placeholder "ENT" looks like a value.
- The preview draws green while Colour = None.
- The logo picker offers only staff photos. Offer generated monogram badges (initials on the team colour) as the default "logo".
- Flag empty teams ("Sales Team · 0 members — archive?").

**Offices:** five offices have 0 teams and 0 agents ("HQ", "Annex B"…). An "Unused" filter, or a hint, would help tidy.

---

## 8. Page notes

### Home
- **Collapse the three empty personal cards** for someone with no personal data (Where you stand, Your goals, Your competitions) into one line, "Nothing personal to show yet — you're not on a board, goal or contest". It takes half the first screen for an admin.
- **Your team at $0 for everyone:** show "No numbers for this period yet", and offer "Last month" if it had data, rather than ten "– $0.00" rows.
- **Needs attention** lists last month's missed goals as "100% behind pace". Group under "Last month" with "missed by…" (Q2-13), or show only the current period.
- **Tab title:** "Home", not the greeting (Q2-24).

### Leaderboards
- **Dev-speak:** the editor subtitle "A saved question. The answer is computed each time it is opened." and the detail footer "Nothing here is stored…". Use the list page's "Always live — updates as the numbers arrive".
- **Select text is cut** in the 2-column editor ("Everyone in the organi…", "1, 2, 2, 4 — nobody is t…"). Widen those two, or put them on their own row.
- **Lowercase "teams"** in subtitles ("· teams ·"). Use "Teams ranked" or "By team".
- **Board create toast:** add a **View** link.

### Goals
- **Explain or drop the "auto" and "repeats" tags**, and show "Repeats monthly" consistently (a new repeating goal shows no tag).
- **Goal detail:**
  - The **"Before this"** chart is an empty axis when there's no history. Say "No earlier months".
  - The **progress strip's purple pace line** has no label or legend. Add "Expected by today" on hover, or a tick.
- **Bulk goals:**
  - default to "Choose a team"
  - offer "Only people who recorded something last period" (the grid ticks all 93, including people at $0 and Jarvis Bot)

### Competitions
- **Entrant picker** stays open listing every person after each pick. Close it, or clear and refocus.
- **Head-to-head** says "$500.00 behind" under the second card. Say "Test User 69 is $500 behind", and add faces.
- **Contest "Cancel"** should be a danger action (Q2-28).

### Recognition
- **"Recognise someone":** say where it will be seen ("…and it plays on the walls of channels that show recognition").
- **"Play on wall"** says "within a minute or so", but it arrived in about 7 s. Say "in a few seconds".
- **Comment and shout-out Remove** need distinct labels and an undo (Q2-17).

### Celebrations (page)
- **Order:** "Default sounds" sits above the rules list. The rules are the page's purpose, so move the defaults below the list, or into a side card.
- **The "Plays" column** says "their own" for a rule with no sound. Use "Walk-up only — others hear nothing".

### Points
- **Give a badge** with no badges is a dead end (Q2-25).
- **Prize wheel labels** are vertical and cut (Q2-26).
- **Badge art names** truncate ("Team pla…"). Allow two lines.

### Reporting
- **Track record:** group by person and metric, and count only periods with a goal (Q2-7).
- **Email tab:** say "Email is set up — sending from goalgetter@…" when it is.

### Metrics
- **Plain words** for aggregation, unit and direction. "count" is both an aggregation and a unit today, which is confusing.
- **Put the duplicate-name error on the Name field**, not as a page banner.
- **The header's "New metric"** turns into a purple primary **Cancel** while the form is open. Keep the header button as "New metric" (disabled), and put Cancel in the form.

### Integrations
- **Source cards:** add "newest row" (§4).
- **Close, Pipedrive, Freshdesk and Gong** still have letter placeholders instead of logos.

### Assets
- **Mixed upload result toast** (Q2-20).
- **Names "Image from 9/28/2026"**: use "Image · 28 Sep".
- **An "Unused" filter** with bulk remove (4 of 7 are unused).
- **Warn on wrong-shaped backgrounds** (portrait photo on landscape walls).

### Settings
- **Timezone:** a searchable, friendly list.
- **Activity:**
  - The page says "changes to people's access" but lists everything.
  - Write each row as a sentence: "Jayden Craig changed QA2 sprint: end moved to 11:30 PM, prize changed — 'QA2 test earlier end'".
  - Add filters for person, type and date.
- **Sign-in:** when the only person without two-step is *you*, add "Set it up now".

### Command palette
- **Searchable things:** add teams, offices, rules, badges, metrics, settings tabs and actions.
- **People results:** show team or email, so "Test User" and "Test user" can be told apart, as the people picker does.

### Navigation
- **At 900 px tall the sidebar scrolls** (5 groups, about 22 items). Let groups collapse, remembered per user, or collapse Organization by default for non-admins.

---

## 9. Words

Keep the voice. These are the leaks left:

| Where | Now | Suggested |
|---|---|---|
| Board editor | "A saved question. The answer is computed each time it is opened." | "Always live — updates as the numbers arrive." |
| Board detail | "Computed from recorded data when this page loaded. Nothing here is stored…" | "Live. A correction or a late sync shows up immediately." |
| Metrics | sum · count · avg · currency (2dp) · higher | Total · Number of entries · Average · Money (2 decimals) · Higher is better |
| Activity | `competition.changed_while_running (fields: ends_at,prize, competition_id: 12)` | "Changed QA2 sprint while running: end, prize" |
| Connect a TV | "Pair a screen" | "Pair with a code" |
| Play on wall | "Everyone · 1 screen" | "Everyone · 1 TV" |
| Channel delete | "1 screen still plays this channel" | "1 TV still plays this channel" |
| Account | "…the achievements feed…" | "…the Recognition feed…" |
| Badge form | "When an achievement fires enough times" | "When a celebration rule fires enough times" |
| Toast | "It starts in about 4 seconds, for 10." | "…for 10 seconds." |
| Toast | "Reconnect: done" | "QA2 throwaway TV is back on Sales floor" |
| Slide picker | "QA2 sprint — active (no office)" | "QA2 sprint · running · everyone" |
| Appearance | "nothing is cropped away" | "Fills the screen; edges may be cropped" |
| Goals | "Period over · on pace for $0.00" | "Finished at $0 · missed by $250,000" |
| Head-to-head | "$500.00 behind" | "Test User 69 is $500 behind" |

**Dates:** settle on one style ("Fri 2 Oct", "2 Oct, 11:30 pm") and use it everywhere (Q2-29).

---

## 10. Phone (375 px)

**Good:**

- no horizontal overflow on any of 26 routes
- modals as sheets
- tables as stacked cards
- filters folded

**Fix:**

- **The bell popover** is cut off on the left (Q2-8).
- **Teams list** names are cut to "$…" and "C…" (Q2-18).
- **Home "Your team"** Recognise button is clipped (Q2-19).
- **The head-to-head cards** stack nicely; add faces.

---

## 11. What to build next (beyond fixes)

1. **Profiles** (§7): the economy has no shop window without them.
2. **Live numbers in editors** for boards and goals (§3a), since the slide editor already proves it.
3. **"Last data" awareness everywhere** (§4): a deployment's most common failure is quiet data.
4. **Celebration hierarchy, and photo in takeovers** (§6).
5. **Wall-aware deletes:** when deleting a board, goal or contest, list the channels and slides that use it ("Removes 1 slide from Sales floor") before the confirm.
6. **Agent and manager walkthrough.** This pass and the last were admin-only. A short session with an agent and a manager login would test what most people actually see. I recommend doing that before release.

---

## Appendix: coverage

**Exercised:**

- Home, all at 1440 px and 375 px
- Leaderboards: create, detail, team ranking
- Goals: create, detail, bulk grid, filters
- Competitions: template, entrants, Check, publish, change while running, wall slide
- Recognition: reactions, comments, Play on wall
- Points (both tabs) and Points setup (all 6 tabs, badge create and give)
- Reporting (4 tabs)
- TVs & Channels: template, slide editor, settings, night mode, pair by code, revoke, re-pair from the Inbox
- Celebrations: template, Check, Play, Preview on a TV, real firing from a correction
- Appearance
- Users (list and detail), Teams (create and edit), Offices
- Integrations (read only), Metrics (duplicate check), Corrections (create)
- Inbox, Assets (upload, invalid upload, in-use protection)
- Settings (all 6 tabs), Account
- Command palette, bell, the 404 page and the old-address redirect
- Light theme

**Wall:**

- full rotation at 1920×1080, 1280×720 and 1080×1920
- celebration takeover frames
- night-mode clock

**Not exercised:**

- agent and manager logins
- integration syncs (as instructed)
- email sending
- Slack/Teams posting
- directory sync runs
- sounds (headless)
- a contest settling
- the prize wheel spin (no points to spend)
