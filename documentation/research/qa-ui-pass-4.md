# GoalGetter — QA / UI pass 4: Phases 10–12, sign-in, and setting people up

**Date:** 5 Oct 2026
**Build:** `aadb784` plus the uncommitted Phase 12 and 11.5 work

**Signed in as:**

- **Admin:** your Microsoft account, in the app's browser pane.
- **Agent:** a throwaway agent, "QA4 Agent" (`qa4.agent@example.com`, a reserved domain that can't receive mail). I invited it with a temporary password and drove it in its own headless Chrome profile, so the two sessions never mixed.

**Previous reports:**

- [qa-ui-pass-3.md](qa-ui-pass-3.md) (P3-n)

New findings here are **P4-1 onwards**.

**Not done, on purpose:**

- I didn't press **"Issue a reset link"** or invite with **"Send a link"**. Both send email from your Microsoft 365 mailbox.
- I didn't call the temporary-password endpoint against a real person who must use Microsoft. If its refusal ever failed, it would reset a real account. I read the code instead.

---

## 1. Verdict

**Phases 10–12 work, and so do both new ways of setting someone up.**

A person outside the tenant can be invited with a temporary password, sign in, be made to choose their own, and then use the app as an agent. Each step behaves as the roadmap describes.

**Checked on screen:**

- the login page with Microsoft sign-in required
- the "Choose your own password" screen
- the Password section on a person's page
- the invite form's "How they get in"
- Clear all and ✕ in the bell
- Not now in the Inbox
- the ✕ on Home's banners

**Bugs found:**

- **One real bug that matters (P4-1).** Activating someone late sends them stale notifications for a finished month. Your 11.5 change will make this happen more often.
- **Two smaller correctness issues:**
  - P4-2: the person page's status hides a suspension.
  - P4-3: a tie at zero reads "$0 behind".

The rest are wording and polish.

---

## 2. Your questions

### Is the bell's ✕ easy enough to find?

**On a phone, yes.** It's always shown, though at 28×28 px it's under the usual 44 px touch target.

**On desktop, not really.** The ✕ has opacity 0 until the row is hovered (`sm:opacity-0 sm:group-hover:opacity-100`). Nothing in the row hints that it exists, so most people will only ever find "Clear all". Keyboard users are fine: `focus-visible` shows it.

**Suggested fix:** show it faintly all the time (opacity around 0.35), at full strength on hover or focus. That costs no layout and makes it discoverable. Two related points:

- After ✕, focus drops to `<body>`. Move it to the next row, or to the panel.
- The Undo toast lasts about 5 seconds. One of my Undos missed it, and a row was gone for good. Give toasts that carry Undo 8–10 seconds.

### Required or optional "choose your own password"?

**Keep it required.** I agree with the reasoning in your note. The password an admin types is seen by two people and often pasted into a chat, so it shouldn't survive the first sign-in. The screen is one step, it says why, and it works at phone width.

If the extra step is a concern, the friendlier fix is on the admin side: the copy box could say "They'll be asked to choose their own the first time they sign in". It already says nearly that.

---

## 3. Verified

### Login with Microsoft sign-in required (signed out)

- The Microsoft button leads, followed by "or with a password" and the form, which is always shown.
- A wrong password gets only **"Incorrect email or password."**, so nothing reveals whether an address is in the tenant.
- The hint reads "Have a company account? Use the button above — passwords are for admins and people without one."

### Inviting someone outside the tenant

The invite form is under Users → Invite someone.

- **"How they get in":** "Send a link to set their password" (the default) or "Set a temporary password".
- **Temporary password:**
  - It validates as you type ("7 more characters needed").
  - "Suggest one" gives four words and a number (29 characters).
- **The result** is a copy box: "QA4 Agent is set up. Hand them this password — they choose their own when they sign in." No email is sent on this path (confirmed in `routers/users.py`).

### The agent's first sign-in

- **The temporary password opens "Choose your own password"**, and nothing else: every API call answers 403 "Choose your own password first.", and visiting `/goals` still shows the screen. It works at 375 px.
- **It refuses bad choices:**
  - the password that was given ("Choose a different password from the one you were given.")
  - a short one
- **After choosing:**
  - the temporary password is refused at login
  - the chosen one works
  - `must_change_password` is cleared
- **Repeating it from the person page works the same way.** "Set a temporary password" (with a confirm: "They are signed out everywhere…") → copy box → the agent's old password stops working → the next sign-in asks again.
- **Activity records it in plain words:** "Jayden Craig set a temporary password for QA4 Agent", "QA4 Agent chose their own password".

### The person page's Password section

| Person | What it shows |
|---|---|
| Directory-bound (Arthur Curry, Kara Danvers) | "They sign in with their company account. Single sign-on is required for people in your directory…", with **no buttons** |
| Set up by hand (QA4) | "Set by an admin — they choose their own the next time they sign in." Then, once chosen: the reset link / temporary password text |
| Yourself | No "Set a temporary password" (but see P4-5) |

### The agent's view

| Check | Result |
|---|---|
| Nav | Home, Leaderboards, Goals, Competitions, Recognition, Points, Teams |
| 15 admin pages | "Not part of your role · Go to Home", with that as the tab title |
| Admin endpoints | Users, temporary password, reset link, Inbox and Audit all **403** |
| Profiles | A colleague: the public half only (`private: null`, no buttons). Their own: the lock line and "No goals or numbers this period yet" |
| Palette | Finds colleagues by name with a PERSON label, but not by address; no "new" actions |
| Recognition | Can react and comment, and comments notify the shout-out's writer privately |
| Console | No errors captured |

### Phase 12

| Feature | Seen |
|---|---|
| Bell ✕ | The row goes, the badge drops to "2 unread", and the toast says "Cleared from your notifications · Undo"; Undo restores it as read |
| Clear all | "Cleared 2 notifications · Undo"; Undo brings back exactly those |
| Home banners | "Not now: No new numbers…" puts it away; the team card goes back to its own sentence; "A notice is put away… · Show it" restores it |
| Inbox | "Not now" removes the item and the sidebar badge; "N put away · Show" lists them with "Bring back" |

### Phase 10

| Fix | Seen |
|---|---|
| Empty-board preview | "Real numbers" on an empty month: "Nobody has scored yet." + "September 2026's top 3" + "Numbers as of Wed 23 Sep" + "this is what a TV shows right now" |
| Archive confirm | "It stops playing on test (1 slide). Restore it to bring it back." (cancelled) |
| Money | "$0 / $250,000", "missed by $250,000", "$4,049" beside "$4,215.37" |
| Goal history | Bars are drawn (July full height, August about half) |
| Profile | No $0 board; "Profile not available" in the tab title |
| Contests | "Too early to call" shortly after the start; the cancel confirm is **"Keep it" (focused) / "Yes, cancel it"**; a cancelled contest has no forecast |
| Home | System health by source ("Sales Feed — read once, newest row Wed 23 Sep", "Excel — no new rows since Thu 3 Sep"); the team card says "see 'No new numbers' above"; "TVs offline" |
| Palette | Rows labelled by kind: TEAM, OFFICE, PERSON, METRIC |
| Activity | Names, not addresses; plain kinds ("Walk-up media", "Data mappings") |
| Walk-up | "Or choose from Assets" with the hint while Assets has no sound or video |

---

## 4. Findings

| ID | Sev | Area | Finding |
|---|---|---|---|
| P4-1 | **Med–High** | Notifications | Activating someone late sends stale notifications: "New goal" and "running out of time — 100% of September gone" for a finished month |
| P4-2 | Med | Person page | Status says "Invited — has not signed in…" while the account is **suspended**, so an admin can't tell they're locked out |
| P4-3 | Med | Contests | A tie at zero reads "Test User is $0 behind" (the wall says "Level") |
| P4-4 | Med | Bell | The ✕ is invisible on desktop until hover; focus is lost after ✕; Undo lasts about 5 s |
| P4-5 | Low | Person page | Password copy offers options that aren't there, and assumes a password exists |
| P4-6 | Low | Settings | The "Require single sign-on" hint doesn't mention that anyone who has signed in with Microsoft is bound too |
| P4-7 | Low | Login | No hint for a forgotten password; the tab title is just "GoalGetter"; the old password stays in the field after a failure |
| P4-8 | Low | Choose password | The submit handler doesn't re-check the confirm field or the length; no show-password toggle; no page title |
| P4-9 | Low | Dismissals | Putting an item away in the Inbox doesn't put away the same notice on Home (and vice versa) |
| P4-10 | Low | Invite form | Role options in lower case ("agent / manager / admin"); no toast after "Let them back in" |
| P4-11 | Low | Palette | "password" finds nothing; "new" is capped at 8, so "Invite people" and "Connect a TV" drop off when something else matches |
| P4-12 | Low | Profiles | A colleague's public profile hides a rank the same viewer can read on the board ("0 points · Not ranked yet" for the board's #1) |
| P4-13 | Low | Activity | "QA4 Agent chose their own password QA4 Agent" repeats the name; "target: 1000" and "target: 1,000" in neighbouring rows |
| P4-14 | Low | Editors | Changing a dropdown and pressing Cancel closes without "Discard changes?" (only typing counts) |
| P4-15 | Low | Bell | After clearing everything, the empty state still says "Nothing yet. Goals you hit… turn up here." |
| P4-16 | Low | Person page | It loads the whole roster (`/api/users?roster=all`, about 480 rows) to show one person; `GET /api/users/{id}` is 405 |

### P4-1 — Late activation backfills stale notifications

**What happened:**

1. Tony Stark was "Invited" until he was reactivated at 22:51 today (`user.reactivated`, status → active; this is the 11.5 path).
2. At 23:42 the hourly job sent him three notifications:
   - `goal.assigned` "New goal: Closed Deals" for **goal 190, September 2026**, a goal created on 10 Sep for a month that's over
   - `goal.period_ending` "Closed Deals is running out of time — **100% of September 2026 gone**"
   - `goal.assigned` for October's goal 194, which is legitimate if late

**Cause:**

- Detection is stateless and skips people who aren't active.
- The moment someone becomes active, every event they never received looks new.
- "Running out of time" is gated on 75% elapsed, but not on the period still being open.

**Why it matters now:** 11.5 turns invited people active in bulk (directory sync matches, Microsoft sign-in, Reactivate). The first hourly run after a sync could send a batch of people stale "new goal" and "running out of time" messages for last month, possibly to Teams or Slack too.

**Fix:**

- Never emit `goal.period_ending` once `elapsed >= 1.0`.
- Never emit `goal.assigned` for a goal whose period has already ended.
- Optionally, treat an account's activation time like "rules never apply to work done before they were created": don't notify about anything created before the person became active, except current-period goals.

The three notifications are still in the database (ids 1001, 1002, 1003, all for Tony Stark) as evidence. Delete them once you've looked.

### P4-2 — Suspended but labelled "Invited"
In `UserDetail.tsx` the Status chain checks `awaiting_first_sign_in` and `invite_pending` before it looks at `status`. A temporarily-passworded person who is then suspended (which also happens after hide → unhide) shows "Invited — has not signed in with the password you set", while Access offers "Let them back in". **Put suspended first:** "Suspended — can't sign in. Let them back in".

### P4-3 — "$0 behind" at a tie
A running two-person contest with both at $0 says "**Test User is $0 behind**" on its page. The wall's head-to-head says "Level" for a tie (8.5). Use the same rule on the page: "Level", or "No scores yet" when both are zero.

### P4-4 — The bell's ✕
See §2. In short: a faint ✕ all the time, focus to the next row after clearing, and a longer toast when it carries Undo.

### P4-5 — Password copy on a person's page
- **On your own page:** "…their current password keeps working… Or set a temporary password to hand over." The temporary button is correctly hidden for yourself, so the sentence points at nothing, and it says "their". Say "Change it on your Account page" and link there; a reset link to yourself is an odd offer.
- **For someone who has never had a password** (Jean Grey, a company address with no directory link and no password): "their current password keeps working until they use it". Say "They have no password yet — they sign in with Microsoft. A temporary password gives them one."

### P4-6 — The Require single sign-on hint
11.1 binds anyone with a live directory row **or who has already signed in with Microsoft**. The hint (Integrations → Microsoft 365 → Settings) says only "People synced from your directory must use their company account". A contractor who once tried "Sign in with Microsoft" would lose password sign-in without the setting ever saying so. Add the second half to the hint, and show it on that person's page ("Bound because they signed in with Microsoft on 2 Oct").

### P4-7 — The login page
- **No hint for a forgotten password.** There's deliberately no self-service reset (`passwords.py`), but now that people outside the tenant use passwords, the page should say "Forgotten it? Ask an admin for a reset link."
- **The tab title is "GoalGetter".** Use "Sign in · GoalGetter".
- **After a failure** both fields keep their values, so pressing Sign in again repeats the wrong attempt. This is what made my deliberately wrong test sign-in look like the agent failing. Clear the password.

### P4-8 — Choose your own password
- **`submit()` posts without re-checking** `mismatch` or `problem`. It relies on the disabled button, and a forced submit with a different confirmation saved the first field. A normal user can't do this (implicit submission is blocked while the button is disabled), but add the guard.
- **Add a show-password toggle.**
- **Add a title** ("Choose your password · GoalGetter").

### P4-9 — One notice, two places
"No new numbers from Excel" put away in the Inbox still shows as Home's banner, and the other way round. If that's intentional (one is a list, one is a banner), say so on the toast ("Put away here — Home still shows it"). Otherwise, share the dismissal key.

### P4-10 to P4-16
These are as described in the table. P4-12 is a judgement call: board positions on boards everyone can see are already public, so showing them on the public half of a profile would make colleague profiles much less empty.

---

## Test data and cleanup

**Created:**

- QA4 Agent (user 490, via the invite form with a temporary password), signed in, given a second temporary password from its page, and signed in again
- three comments by the agent on the "Tony Stark — Sale" shout-out (to put notifications in your bell)
- two goals on your account (removed straight away: setting your own goal doesn't notify you)
- a contest, "QA4 contest", published, cancelled and deleted

**Removed:**

- the comments, goals and contest, through the app
- the account and my eight sign-in attempt rows, by one transaction matched on id and address
- the agent's browser profile

**Your account's state, as you left it:**

- **Inbox:** the Excel notice you'd put away is still put away. I briefly brought it back by mistake and then put it away again.
- **Home:** no notice put away.
- **Bell:** empty.
- **One of the agent's three comment notifications** was cleared without Undo during testing, and was then deleted with its comment.

**Verified:**

- Every table matches the pre-test row counts, except:
  - `audit_log`, which is expected
  - `session`, from your new admin sign-in
  - `sync_run`, from the scheduled hourly syncs
  - `notification`, from the three P4-1 notifications to Tony, left on purpose
- **Backup:** `scratchpad/goalgetter-before-qa4.dump`.
