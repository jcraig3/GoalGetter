# GoalGetter — QA bug report, pass 2

**Date:** 2 Oct 2026
**Build:** `6828d9e` (dev), after Phase 5 (the first pass's fixes) and Phase 6 (17 new features)
**Where:** docker compose at http://localhost:8080, signed in as the org admin
**Companion doc:** [ui-ux-review-2.md](ui-ux-review-2.md), which covers design and UX. This file covers defects: things that are wrong, not just could be better.
**First pass:** [qa-bug-report.md](qa-bug-report.md) (QA-1 to QA-40). New IDs here are **Q2-1 onwards**, so the two sets never collide.

**Severity**

- **High:** the product says or shows something false, or a feature doesn't do its job.
- **Med:** a wrong result or a confusing outcome, with a workaround.
- **Low:** cosmetic, an edge case, or polish.

**Method.** Everything was done as a real user, in the app:

- Boards, goals, a live contest, rules, a badge, a team, a channel from a template, a correction, comments and reactions, and an asset upload.
- A throwaway TV, paired by code and watched through a full rotation. Then revoked, re-paired from the Inbox, and put into night mode.
- Wall screenshots taken in headless Chrome at 1920×1080, 1280×720 and 1080×1920.
- Every route checked at 375 px for overflow.
- An accessibility scan of 22 routes.
- Light and dark themes.
- Code read wherever a symptom needed a cause.

**What was not touched:**

- No integration was synced.
- Only the existing data was used.
- Test records used the test accounts (Test User, Test User 69), so no real person was notified.

---

## First-pass fixes re-checked

These were verified in the running app, not just read in the roadmap.

| First-pass item | Result |
|---|---|
| QA-1 team boards empty | **Fixed.** A team board shows Metropolis Sales Team at 15,400 |
| QA-2 rules hourly | **Fixed.** A correction fired the rule on the TV in about 2 s |
| QA-3 wall doesn't fit | **Fixed.** Scale-to-fit and paging are correct at 720p, 1080p and portrait |
| QA-4 stale errors | **Fixed** on the forms tried |
| QA-5/6/7/9 names and numbers | **Fixed.** A duplicate metric name is refused with a clear sentence |
| QA-8 silent team move | **Fixed** (the confirm exists) |
| QA-12 read-once source | **Fixed.** It shows "Read once" |
| QA-13 Value error / wrong tab | **Fixed.** Publish lands on Live |
| QA-15 revoke latency | **Fixed.** The TV showed a pairing code about 2 s after Revoke |
| QA-17 revoked TVs removable | **Fixed** |
| QA-21 "Leading" at zero | **Fixed** |
| QA-26/27 404 and titles | **Fixed** (one title exception, Q2-24) |
| QA-28 double fetch | Not re-measured |
| QA-31 walk-up | Not re-tested; the controls are present |
| 6.1/6.2 re-pair and Inbox Reconnect | **Works end to end.** The TV loaded its new link by itself in about 6 s |
| 6.10 night mode | **Works.** A drifting clock with "back at 12:00 PM"; a preview still shows over it |
| 6.11 portrait | **Works.** The portrait podium is very good |
| 6.14 change while running | **Works.** An earlier end is refused with a clear reason |
| 6.15 reactions and comments | **Work** (see Q2-17) |
| Phone layout | **No page-level horizontal overflow** on any of 26 routes |
| Accessibility | **No unnamed buttons or links**, and one `h1` per page, on 22 routes (two small exceptions in Q2-27) |

---

## Summary table

| ID | Sev | Area | Title |
|---|---|---|---|
| Q2-1 | High | Competitions / Goals | Pace counts whole days: same-day contests show "100% gone" from the start; daily goals never have a pace |
| Q2-2 | High | Celebrations | `{value}` drops the currency symbol: walls say "closed 500.00!" |
| Q2-3 | Med | Editors | Board, goal and competition previews ignore the form (unit, ranking, period, prize, entrants) |
| Q2-4 | Med | Celebrations | "Check last week" contradicts the template ("28 times" vs "would not have fired… lower the bar") |
| Q2-5 | Med | Data health | "Check the integrations" leads to a page that says all is well; stale data is flagged nowhere useful |
| Q2-6 | Med | Notifications | Deleting a contest, rule or comment leaves notifications pointing at things that no longer exist |
| Q2-7 | Med | Reporting | Track record lists every repeating goal twice and counts months before the goal existed as misses |
| Q2-8 | Med | Phone | Bell popover hangs 17 px off the left edge of a 375 px screen |
| Q2-9 | Med | Preview on a TV | Choosing a TV in the dropdown sends at once; arrowing through the list sends to every TV |
| Q2-10 | Med | Goals / Reporting | 0% with a working day gone reads "On track", and Reporting headlines "On pace 100%" |
| Q2-11 | Low | Goals | A goal created already met doesn't celebrate until the hourly pass |
| Q2-12 | Low | Goals | "Data as of Sep 23" on a goal whose figure includes a 2 Oct correction |
| Q2-13 | Low | Goals | Ended periods still say "on pace for $0.00" |
| Q2-14 | Low | Bulk goals | Team defaults to the first alphabetically ("Avengers") |
| Q2-15 | Low | Users | Detector misses non-people that have a team or a two-word name (Jarvis Bot, Northwind Vegas, FastSourcing NTax, Test User NN) |
| Q2-16 | Low | Leaderboards | A team row shows its own name twice and a "you" chip |
| Q2-17 | Low | Recognition | Comment "Remove" is instant, with no undo, beside an identical "Remove" for the shout-out |
| Q2-18 | Low | Phone | Teams list cuts team names to "$…", "C…" |
| Q2-19 | Low | Phone | Home "Your team" Recognise button pokes 5 px out of its card |
| Q2-20 | Low | Assets | Toast says "Added to the library" when 1 of 2 files was refused |
| Q2-21 | Low | Appearance | Photo help says "nothing is cropped away" — cover crops |
| Q2-22 | Low | Toasts | Missing after creating a team or a badge; "for 10." / "Reconnect: done" wording |
| Q2-23 | Low | Naming | "screen" for a TV survives in six places; "achievement" in two |
| Q2-24 | Low | Titles | Home's tab title is the greeting; goal detail's H1 and title are the metric only |
| Q2-25 | Low | Points | "Give a badge" with no badges is a dead end |
| Q2-26 | Low | Points | Prize wheel labels are cut and run vertically |
| Q2-27 | Low | a11y | Unlabelled file inputs (Account, Appearance); Appearance has two `h1`s |
| Q2-28 | Low | Competitions | Detail's contest "Cancel" looks like a form cancel |
| Q2-29 | Low | Dates | Four date formats in use ("10/1/2026", "Fri 2 Oct", "Fri, Oct 2", "Sep 23") |
| Q2-30 | Low | Leaderboards | Empty board name gives the browser's native bubble, not the app's error |

---

## High

### Q2-1 — Pace counts whole days, so short windows are wrong all the way through

**Where:**

- `api/app/pace.py:95` `elapsed_fraction`
- used by `api/app/reporting.py:371` (the competition report card) and by every goal's status

**Repro:**

1. Make a contest that runs from today 00:00 to today 23:30. The new **Friday sprint** template does the same thing: 9 am to 5 pm on one day.
2. Publish it and open its page at 10:25 am. It says **"13h 4m left"** directly above **"100% of the window gone"** and **"On pace to finish at $500.00"** (the current score, repeated).

**Cause:**

- `start`, `end` and `today` are all reduced to **dates**.
- For a same-day window, `today >= end` is already true, so the function returns `1.0` the moment the contest starts.
- The mirror case is a **"Today" goal**: `today <= start` is true all day, so it returns `0.0`. A daily goal is "Not started" until the day is over, then "Missed". It is never Behind or Ahead while the day is running.
- A contest that ends at 5 pm on its last day never counts that day either.

**Impact:**

- Short sprints are the most exciting contest a sales floor runs, and the app now ships a template for one.
- The report card and the projection are wrong for its whole life.

**Fix:**

- Measure elapsed time in **hours** for windows shorter than about two days, and for every competition: `(now - start) / (end - start)`.
- Optionally clip to working hours (09:00–18:00 org time).
- Keep the working-day logic for months and quarters.
- Add tests for:
  - a 9–5 contest at noon (≈ 37.5%)
  - a "Today" goal at noon (> 0)
  - a contest ending 17:00 on its last day

### Q2-2 — Announcements show money without its currency symbol

**Where:**

- `api/app/notifications.py:798` `format_value`
- used for the `{value}` merge tag in rule celebrations, the feed, and the rule preview

**Repro:**

1. Create a rule from the **Big deal** template.
2. Record a correction of 500 for a test person. The TV shows **"Test just closed 500.00!"**
3. "Preview on a TV" shows "Jayden just closed 350.00!"
4. The Recognition feed shows the same text.

The rule form's own sample, drawn by the client, says **"$6,200"**, so the editor and the wall disagree.

**Cause:**

- For `unit == "currency"` the function returns `f"{quantised:,.2f}"` with no symbol. Count units get their noun from `units.with_noun`, but currency gets nothing.
- `api/tests/test_achievement_rules.py:666` asserts `"Admin just closed 5,000.00!"`, so the test locks the bug in.

**Also:** the rules table shows the bar as "at least 350", again with no "$".

**Fix:**

- Prefix the organization's currency symbol, the same one the web formatter uses.
- Drop `.00` on whole amounts in announcements: "$500", not "$500.00".
- Update the test, and add one that the client sample and the server agree on.

---

## Medium

### Q2-3 — Editor previews ignore most of the form

**Where:** `web/src/components/wall/sample.ts` (`sampleSlide(kind, title)`), used through `WallPreview` by the board, goal and competition editors.

**Repro, and what each preview shows:**

| Editor | What the form says | What the preview shows |
|---|---|---|
| Board | Rank = Teams | Peter Parker, Clark Kent… |
| Board | Metric = Closed Deals (a count) | "$48,200" |
| Board | Period = Last 30 days | Subtitle "Everyone · **March**" |
| Board | Show top, finish line, lower-is-better | Not reflected |
| Goal | For = A person (Test User) | Subtitle "Everyone", and "$184,300 of $250,000" for a count metric |
| Competition | Prize "Lunch on us" | "Steak dinner" |
| Competition | Ends today | "2 days left" |
| Competition | 2 entrants | "Top 6 of 14", "Enterprise vs SMB" |

**Cause:** the sample takes only `kind` and `title`. Unit, entity type, period label, prize, end time and entrant count are hard-coded. Phase 5j describes the preview as "in its own layout and look", which holds for the look, but the content is wrong.

**Fix:**

- Pass the form's `unit`, `decimal_places`, `entity_type`, `direction`, period label, prize, `ends_at`, entrant count, top-N and finish line into `sampleSlide`.
- For teams, use sample team names.
- For a person goal, use the chosen person's name ("Test User — Sales Feed Amount Today").
- Drop the fictional channel strip ("Main floor · Make today a great day!") from previews of things that aren't on a channel yet.

### Q2-4 — The rule's "Check last week" contradicts the template that just filled it

**Repro:**

1. Celebrations → **Big deal**. The form says "Set from your own Sales Feed Amount Today: it would have fired **28 times in the last 4 weeks**."
2. Press **Check last week**. It says "**Would not have fired in the last 7 days.** Fine for a rare win; **lower the bar** if it should be heard more often."

**Cause:**

- The suggestion looks back 4 weeks (`SUGGEST_WEEKS`); the check looks back 7 days (`RULE_CHECK_DAYS`).
- No data has arrived for 9 days, so the check sees nothing and blames the threshold.

**Fix:**

- Check over the same 4 weeks, reporting "per week".
- When the window holds **no data at all for the metric**, say so ("No Sales Feed numbers arrived in the last 7 days — the check has nothing to try"), rather than advising a lower bar.

### Q2-5 — Stale data sends you to a page that says everything is fine

**What each place says:**

| Place | What it says |
|---|---|
| Home banner | "400 people have recorded nothing in 7 days" |
| Manager card | "Nothing recorded for 92 of the team in 8 days — the data may have stopped arriving. **Check the integrations**" |
| Integrations (the Excel source) | **"Working — The last sync completed cleanly."** |
| Inbox | Nothing about it |

**Cause:** health is judged by sync success, not by whether new rows arrived. The spreadsheet syncs cleanly but hasn't been updated since 23 Sep.

**Fix:**

- Track the newest `occurred_at` per source.
- Show "Newest row: 23 Sep (9 days ago)" on the source card, with a "No new rows in 9 days" warning past a threshold.
- Add an Inbox item for the same condition.
- Make Home's banner use the manager card's diagnosis: one "No new numbers since 23 Sep — check the Closed Deals sheet" line, rather than blaming 400 people.

### Q2-6 — Deleting things leaves notifications behind

**Seen during cleanup:**

- After deleting the contest, the rule and the correction, these notifications remained:
  - "QA2 sprint has started" for both entrants, linking to a contest that no longer exists
  - the rule's win notification
  - "Jayden Craig commented: …" for a comment already removed in the UI
- Points paid by the deleted rule and the deleted badge (10 and 5) stayed on the season table.

**Fix:**

- When a contest, rule, badge, fact or comment is deleted, delete or tombstone the notifications whose `subject` is that item, as 6.15 already does for a removed shout-out.
- Decide explicitly whether deleting a rule or badge reverses its points:
  - If yes, add reversing ledger rows.
  - If no, say so in the delete confirmation: "Points already paid stay."

### Q2-7 — Track record duplicates goals and counts months that never had one

**Where:** Reporting → Track record.

**What it shows:**

- Each repeating goal appears **twice**, for example "Tony Stark · Closed Deals 0% · 0 of 6" covering Mar–Aug, and again covering Apr–Sep. That's because the September and October instances are listed separately.
- A goal created today, for a person with no history, shows **"0% · 0 of 6"**: six misses for months before the goal or the data existed.

**Fix:**

- Group by person + metric (the repeat series), not by goal row.
- Count only periods in which a goal was running, or in which the person had data. Otherwise show "No history yet".

### Q2-8 — Bell popover is cut off on phones

**Where:** the header bell, at 375 px.

**What happens:** the panel is `w-80` (320 px), anchored `right-0` to the bell at x ≈ 303, so its left edge sits at **x = −17 px**. The "Notifications" title and the left side of every item are clipped.

**Fix:** below 640 px, make it `fixed inset-x-2 top-14`, or a full-width sheet like the other phone modals.

### Q2-9 — "Preview on a TV" fires as soon as a TV is selected

**Where:** the rule editor and the slide editor.

**What happens:**

- It is a `<select>` whose change handler sends the preview straight away.
- A keyboard user arrowing down the list sends a celebration to **every TV they pass**.
- A mouse user who picks the wrong TV can't take it back.
- Selecting the same TV again doesn't fire, so repeating a preview needs a detour.

**Fix:** keep the select, and add a **Send** button next to it.

### Q2-10 — Zero progress reads as "On track"

**Repro:** on 2 Oct (one working day gone), the goal "Clark — $0 of $250,000" shows **On track**, and Reporting's Overview headlines **"On pace 100%"**.

**Cause:**

- Expected progress is 1/22 ≈ 4.5%.
- The ±5-point tolerance in `pace.py` treats 0% as within band.
- This is correct for "don't flap", but a $0 board reads as reassuring.

**Fix:**

- Either show "Too early to tell" until about 3 working days or 10% of the period have gone,
- or never call **zero with time elapsed** "On track"; use "Not started yet".

---

## Low

### Q2-11 — A goal created already met waits for the hourly pass
I created a goal of $400 for someone already at $500. It shows **Hit** at once, but the "goal hit" celebration waits for the hourly job, because announcing runs only after ingest. Either announce on goal save too, or decide that a goal created already met should not celebrate, and suppress it.

### Q2-12 — "Data as of" ignores corrections
Goal detail says "Data as of Sep 23", but its $500 comes from a correction entered 2 Oct. Base the label on the newest fact behind the figure, including manual entries.

### Q2-13 — Ended periods still talk about pace
September goals say "Period over · on pace for $0.00" (Goals) and "100% behind pace · Missed" (Home, Needs attention). After the end, show "Finished at $0 · missed by $250,000".

### Q2-14 — Bulk goals default to an arbitrary team
"Set for a group" opens with team **Avengers**, the first alphabetically. Start with "Choose a team…". If the viewer manages exactly one team, start with that.

### Q2-15 — Non-people still visible
After the 26 suggestions were hidden, these are still listed as people:

- **"Jarvis Bot"**: on Metropolis Sales Team, so it's in bulk goals, nudges and team counts
- **"Northwind Vegas"** and **"FastSourcing NTax"**: shared or vendor mailboxes with no title
- about ten **"Test User NN" / "test user25"** accounts

The detector needs both "nothing marks it as a person" and "name shaped like a thing". Add `test`, `dummy` and `bot` as service words, and treat the organization's own name ("Northwind", "NTax") as a thing-word. Don't let "has a team" by itself disqualify a suggestion.

### Q2-16 — Team rows on board detail
The detail table shows "Metropolis Sales Team" with "Metropolis Sales Team" again underneath (the team subtitle is the team), plus a **"you"** chip. Drop the subtitle on team rows, and say "your team".

### Q2-17 — Removing a comment
"Remove" deletes the comment instantly with no confirm or undo. It sits beside the shout-out's own "Remove", which deletes the whole entry. Label them "Remove comment" and "Remove shout-out", and give the comment an Undo toast.

### Q2-18 — Teams list on a phone
At 375 px, three team names are cut to "$…", "C…", "C…", because the "from Microsoft Teams" chip and the member count share the line. Wrap the chip under the name, or shorten it to an icon with a tooltip.

### Q2-19 — Home "Your team" row on a phone
The Recognise button ends at x = 364, past the card edge at 359, and is clipped. Let the row wrap, or use an icon button below 400 px.

### Q2-20 — Mixed upload result
I added two files, one valid and one fake PNG. The toast said "Added to the library", while the refusal appeared at the top of the page. Make it "Added 1 · 1 refused", with the refusal next to the drop zone.

### Q2-21 — Photo background copy is wrong
Appearance says a photograph "is kept whole — the screen covers with it, so nothing is cropped away". `cover` does crop, and the organization's current background is an 811×1080 **portrait** photo on 16:9 walls. Say "Fills the screen; edges may be cropped", and warn when a photo's shape is far from the wall's.

### Q2-22 — Toast gaps and wording
- **Missing toasts:** none after creating a team (inline form) or a badge.
- **"Sent to QA2 throwaway TV. It starts in about 4 seconds, for 10."** is missing "seconds".
- **"Reconnect: done"** should be "QA2 throwaway TV is back on Sales floor".
- **Pairing by code** says "TV link created". It should say "TV connected — playing Sales floor".

### Q2-23 — Old words survive
- **"screen" for a TV:**
  - Connect a TV's tab "Pair a screen"
  - Play on wall's "Everyone · **1 screen**"
  - Appearance's "Channels and **screens** can override"
  - the channel delete refusal "**1 screen** still plays this channel"
  - the channel picker's "active (no office)"
- **"achievement":**
  - Account → Notifications says "the **achievements feed**"
  - the badge form says "When an **achievement** fires enough times"

### Q2-24 — Titles
- **Home's tab title** is "Welcome back, Jayden · GoalGetter". Use "Home · GoalGetter".
- **Goal detail's H1** and tab title are the metric ("Sales Feed Amount Today"), while its breadcrumb says "Test User — Sales Feed Amount Today". Use the breadcrumb's form for both.

### Q2-25 — Give a badge with no badges
The dialog says "No badges have been set up yet." and stops. Link to Points setup → Badges.

### Q2-26 — Prize wheel labels
On Points → Spend, segment labels run vertically and are cut ("Maybe another"). Rotate the text along the radius, shorten it with a tooltip, or show the legend only.

### Q2-27 — Accessibility leftovers
- The walk-up file input (Account) and the photo input (Appearance) have no label.
- Appearance has two `h1`s, because the wall preview's slide title is an `h1`. Render preview titles as `div role="heading" aria-level="2"`, or `aria-hidden` the preview.
- The reaction "☺ +" toggle has no `aria-expanded`.

### Q2-28 — Contest "Cancel"
On a running contest's page, **Cancel** (which cancels the contest) sits next to "Back to draft" in the same neutral style as a form's Cancel. Label it "Cancel contest" and style it as a danger action. It does confirm first.

### Q2-29 — Date formats
Four formats are in use:

| Format | Where |
|---|---|
| "10/1/2026 – 10/2/2026" | Competition Check |
| "Image from 9/28/2026" | Assets |
| "10/2/2026, 10:35:42 AM" | Activity |
| "Fri 2 Oct, 11:00 PM" and "Fri, Oct 2, 10:26 AM" | One card on the competition page |

Use one helper with a short form ("2 Oct", "Fri 2 Oct, 11 pm") everywhere.

### Q2-30 — Native validation bubble
An empty board name gets the browser's "Please fill out this field". Other forms use the app's inline errors. Add `noValidate` and use the app's message.

---

## Test data and cleanup

**Created during the pass, all with "QA2" in the name:**

- board 11
- channel 12 "Sales floor" (from the template), with four slides
- display 11 "QA2 throwaway TV" (paired, revoked, reconnected, deleted)
- rule 6
- goal 575
- competition 12 (published, changed while running)
- badge 2 (given to Test User)
- team 18
- asset "qa2-logo"
- one correction (Test User, $500, 2 Oct)
- one reaction and one comment

**Removed** through the app's own delete actions, which cascaded the pairing, preview, replay and badge award rows. The six rows the app had no delete for were removed in one transaction, each matched on its id *and* content:

- point awards 3 and 4
- notifications 97602–97605

**Verified:** the row count of every table touched equals the count taken before testing.

**What remains:**

- Audit-log entries for the actions above, by design.
- A pre-test backup: `scratchpad/goalgetter-before-qa2.dump` (pg_dump `-Fc`).
