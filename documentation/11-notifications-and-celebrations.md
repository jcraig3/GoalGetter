# Notifications & Celebrations

**Phase 2.** The recognition half of the core loop.

## Why this is a real feature, not polish

Tracking without recognition is surveillance. The reason Spinify-style tools work is that hitting a number produces a visible, public moment. Remove that and you've built a reporting dashboard people are required to look at.

The design tension is equally real: **notifications that fire too often stop being rewarding and start being noise.** Every decision here optimizes for keeping the moments meaningful.

## Channels

| Channel | Phase | Notes |
|---|---|---|
| In-app notification center | 2 | Always available, no configuration required |
| In-app celebration overlay | 2 | Triggered when the recipient is looking at the app |
| TV display celebration | 2 | Full-screen takeover on office displays |
| ~~Email~~ | — | **Cut.** See "Email is not a notification channel" below |
| Slack | 4 | **Built.** An incoming webhook link per channel (only `hooks.slack.com/services/` accepted), posted as a Slack message with typed text escaped so it cannot ping a channel. Its own card under "Messaging and notifications"; not paused by the Microsoft Teams switch |
| Microsoft Teams | 4 | **Built.** A channel picked from a list, posted through Graph as one signed-in account — or a Workflows link made in the channel. Switched on in the Microsoft 365 box, set up in the Microsoft Teams card. See [18-roadmap.md](18-roadmap.md#microsoft-teams-integration--done) |
| Browser push | — | Not planned; permission prompts are hostile and adoption is poor |

**In-app works with zero configuration.** Every other channel is an enhancement. A deployment with no SMTP server must still deliver the full recognition experience.

### Email is not a notification channel

Decided while planning Phase 2, and it removed an abstraction rather than
adding one.

Email's real job in this product is **invitations and password resets** — the
two flows that today work by copying a link out of the UI. SMTP arrives with
the integrations phase and turns those into "it just arrives", which is the
actual win and has nothing to do with recognition.

Recognition reaches people through the app they already have open and the
screen on the wall. An internal sales floor does not need an email saying
somebody hit their number; it needs the TV to light up.

With in-app, celebration and TV all reading the same notification rows, there
is nothing left to dispatch: **no queue, no retry policy, no adapter
registry.** The "delivery architecture" diagram below describes a fan-out that
Phase 2 does not build. If email ever becomes a notification channel, that is
when a dispatch layer earns its place — designed against a working SMTP
connection instead of imagined without one.

## What is, and is not, a notification

A notification is a **stored record, addressed to one person, that something
happened at a moment in time**, which persists until they have seen it. Four
properties: one recipient, a timestamp, a discrete event, read/unread state.

Deliberately narrow, because the dashboard already carries something that looks
similar and is not. The attention banner — "3 goals behind pace", "2 people
recorded nothing this week" — is **state**: recomputed on every load, addressed
to nobody, no unread flag, and it disappears on its own when the condition
clears. So is the health card.

The test: **if it stops being true, should it vanish?** Yes, it is state and
belongs on the dashboard. No, it happened, it is a notification.

## Where notifications appear

| Surface | Audience | Shows |
|---|---|---|
| Notification centre (bell) | you | everything addressed to you |
| Celebration overlay | you | your celebratory ones, once |
| Recognition page | everyone in scope | the public feed |
| TV channel screen | the room | the public feed, scoped to the office |
| Dashboard | you | state, not events — unchanged |

**A notification is addressed to one person; a wall screen has no person.** It
has no session and no viewer identity, and is read by whoever walks past. So a
screen never renders "notifications" — it renders the public subset.

That subset is fixed **in code**, as a property of the event type:

```python
PUBLIC_EVENTS = ("goal.achieved", "competition.results_final", "recognition")
```

`goal.at_risk` is a conversation between an agent and their manager. On a
permanent display in front of the whole floor it is public shaming. Making the
distinction a constant rather than a per-notification flag or an admin setting
is the point: a checkbox somebody could tick is a checkbox somebody will tick.
Same pattern as `pace.CUMULATIVE` — make the wrong thing unrepresentable.

The Recognition page (formerly Achievements) and the TV screen read the **same** public feed, so what
somebody sees at their desk is what the room sees.

## Measured against Spinify

Researched against Spinify's own documentation while building 2c, because
matching it is the goal. Spinify runs **two separate systems**, and the split
is the thing worth copying.

### Achievements — automatic

A rule, not a goal. Set up a **record type** (Deals Won), **filters** on it
("Amount > $5000") and an **owner field**; when a matching record arrives, it
fires. Recipients are a chosen list or everybody.

Each achievement carries its own **background** (image or video, 16:9),
**sound** (a default, a custom upload, the user's own, or none), theme text and
colours, and **points**. Three separate durations: total lifecycle on the
channel, display time per appearance (default 45 s), and an initial display
duration when first created. On a TV it **interrupts the current leaderboard**.

Two constraints they state explicitly: an achievement **cannot be applied
retroactively** — the action has to happen after the rule exists — and an
achievement can be **enabled or disabled** org-wide.

### Announcements → Messages — manual

A manager writes one: title, description, message body, **sender**,
**recipient (specific teams or members)**, background video or image, optional
sound file, duration, and channel assignment. One documented type is **Web** —
any HTML page by HTTPS URL, with the caveat that `X-Frame-Options` stops many
sites embedding.

### The Gong — manual, self-service

*Anyone* with a login, including from the mobile app, taps Celebrate and either
rings instantly or configures a message and title. **Rate-limited to once every
five minutes** so an accidental double-tap does not fire twice.

### What that told us

We matched on shape — detection that cannot fire retroactively, authored
shout-outs sharing one delivery path, media on celebrations, a public feed —
and were missing one real capability plus several details.

| | Spinify | Ours after 2c | Decision |
|---|---|---|---|
| Automatic trigger | any fact matching a filter | only a **goal** being hit | **build it** (2c-iii) |
| Not retroactive | stated constraint | unique index + goal must exist | already true |
| Recipient | person, team, or everyone | one person | **add teams** |
| Media | on the achievement *and* the person | per-person only | **add per-rule** |
| Enable/disable | per achievement, org-wide | per-person mute only | **add** |
| TV durations | three, 45 s default | none yet | **copy in 2f** |
| Self-service gong | anyone, 5-minute cooldown | admin and manager only | **declined** |
| Points | awarded per achievement | none | not planned |
| Sidekick (AI text) | writes the message for you | none | not planned |

**The gap that mattered:** our celebrations could only fire off a *goal*, which
is a target over a period. "Marcus closed a deal over $5,000" has no goal and
never will, so it was not expressible — and that is most of what a sales floor
actually celebrates. 2c-iii adds fact-triggered rules.

**The gong was declined deliberately.** Spinify answers the abuse question with
a cooldown rather than a permission; we are keeping recognition with admins and
managers. Recorded because it is a reasonable thing to change our mind about
later, and the reasoning should not have to be reconstructed.

**`X-Frame-Options` is a real gotcha for web screens** and belongs in 2d's
notes: many sites refuse to be embedded, and without saying so up front every
install will report it as our bug.

## Event catalogue

| Event | Default recipients | Default channel |
|---|---|---|
| `goal.achieved` | The achiever + their manager | In-app + celebration + TV |
| ~~`goal.threshold` (50%, 75%)~~ | — | **Cut**, see below |
| ~~`goal.at_risk`~~ | — | **Merged** into `goal.period_ending` |
| `goal.assigned` | The assignee | In-app + email |
| `goal.period_ending` | Owners not yet achieved, + their manager | In-app |
| `rank.changed` | The mover | In-app, rate-limited |
| `rank.overtaken` | The person passed | In-app, rate-limited |
| `competition.scheduled` | Participants | In-app + email |
| `competition.started` | Participants | In-app |
| `competition.lead_change` | Participants | In-app, heavily rate-limited |
| `competition.ending_soon` | Participants not leading | In-app |
| `competition.results_final` | Participants + creator | In-app + email + celebration |
| `user.invited` | The invitee | Email (or copyable link) |
| `import.completed` / `import.failed` | The importer | In-app |
| `data_source.sync_failed` | Admins | In-app + email |

## Recognition — authored, not detected

Every event in the catalogue above is something the system *notices*. A
shout-out is something a person *writes*: a manager recognising an agent for a
sale, a save, or an effort no metric captures.

It is the same object with an author. `notification.created_by_user_id` is NULL
for a detected event and set for an authored one, which means a shout-out
reaches the notification centre, the celebration overlay, and the wall screens
through the machinery that already exists.

The one behavioural difference is repeatability. Detected events latch — once
per subject per period, enforced by a unique index. Authored ones must repeat,
because two good weeks are two shout-outs. So the index is partial:
`WHERE created_by_user_id IS NULL`.

**Both kinds share one Achievements feed.** "Marcus hit his call target" and
"Priya turned around the Henderson account" belong in the same list; splitting
them by origin would leak an implementation detail into the UI, and the
authored ones are usually the better story.

Scoped and audited: a manager may only recognise somebody already within their
scope, and the action is recorded, because it broadcasts to every screen in an
office.

### Two events cut before building

**`goal.at_risk` merged into `goal.period_ending`.** They say the same thing —
the period is running out and you are not there — days apart, which is exactly
the noise this document spends a page warning about.

`at_risk` also had a trap. It is a latching event describing an oscillating
condition, so firing it the first time somebody dips behind spends the single
shot. They recover, fall behind again on the 25th when it actually matters,
and hear nothing. One event, fired once the period is **75% elapsed and the
target not met**, spends the shot at a moment somebody can still act on.

**`goal.threshold` (50%, 75%) cut entirely.** Being halfway to a monthly target
on the 15th is precisely what is supposed to happen. It is not news, and the
pace marker already says it on screen, more precisely, without interrupting
anybody. It would only be interesting when somebody is *ahead* of pace — at
which point it is a different event with different logic, and one nobody has
asked for.

It is also the event most likely to train people to ignore the bell, and a bell
only works if it is rare. **Five events that always mean something beat eight
where three are wallpaper.**

## Rate limiting

The most important part of the design.

| Rule | Limit |
|---|---|
| Rank change, per user | 1 / hour |
| Competition lead change, per user | 1 / hour; suppressed in the final hour except the actual lead change |
| Any single event type, per user | 10 / day |
| Total notifications, per user | 30 / day |
| Goal thresholds | Once per threshold per goal per period — never re-fire |

**Deduplication window:** identical events for the same user within 5 minutes collapse into one. This matters because a bulk import can write 400 facts at once and would otherwise fire a notification per fact.

**Digest instead of drip:** low-urgency events (`goal.threshold`, `rank.changed`) can be batched into a single daily summary. Org setting, defaulting to immediate for goal achievement and digest for everything else.

## Celebrations

The high-value moment: someone hits a goal or wins a competition.

### In-app overlay

```
┌────────────────────────────────────────────┐
│                                             │
│              🎉  ✨  🎉                     │
│                                             │
│           GOAL ACHIEVED                     │
│                                             │
│        ┌──────┐                             │
│        │      │   Jayden Craig              │
│        └──────┘                             │
│                                             │
│      Revenue Closed — August                │
│         $51,200 of $50,000                  │
│              102%                           │
│                                             │
│         [ Nice! ]                           │
└────────────────────────────────────────────┘
```

- Auto-dismisses after 6 seconds, or on click.
- Fires **once**, tracked server-side, never on subsequent page loads.
- Queues rather than stacks if multiple fire at once.
- Honors `prefers-reduced-motion` — degrades to a static banner with no confetti. Non-negotiable; confetti animation is a genuine vestibular trigger.

### TV display celebration

Full-screen takeover, then back to the rotation. This is the feature that produces
the actual office moment — the screen changes and people look up.

**Built in 2f-ii.** `GET /api/display/{token}/celebrations`, polled every ten
seconds, separately from the channel feed: the rotation is heavy — every board,
goal and competition on the channel — and a wall has to notice a win within seconds
of it landing, not within a refresh cycle.

**Three durations, all server-side** so pacing a display stays an operational
setting rather than something baked into a browser nobody can reach:

| Constant | Question it answers | Value |
|---|---|---|
| `CELEBRATION_LIFETIME_SECONDS` | how long a win stays worth interrupting for | 300 |
| `CELEBRATION_HOLD_SECONDS` | how long one *without* media holds the screen | 10 |
| `CELEBRATION_COOLDOWN_SECONDS` | the quiet gap between two | 5 |

A win **with** media holds for the length of its clip instead, capped by
`media.MAX_CLIP_SECONDS` — which is why a walk-up is fifteen seconds and not a
whole song, and why cutting one off halfway is not a thing that happens.

**The lifetime is the handoff to the achievements slide.** Past five minutes a win
stops interrupting and carries on appearing in the rotation, where old news
belongs. It also bounds what a television replays after a reload: a screen switched
on in the morning must not fire a night's worth of celebrations back to back.

**The screen remembers what it has played, not the server.**
`notification.celebrated_at` is per-person, for the in-app overlay. A wall has no
person, and two televisions on the same channel should *both* celebrate a win
rather than race to claim it — so the server offers a window and each screen keeps
its own set. That set is trimmed to what is still on offer, which is safe because a
win that has aged out can never be offered again.

**What qualifies is `public` **and** `celebrate`.** `public` is permission — a
screen is read by whoever walks past, so falling behind on a goal must never reach
one. `celebrate` is significance — the achievements slide happily lists everything
public, while stopping the rotation is reserved for things that happen once. Today
every public event is also a celebration so the two sets coincide, but the
conjunction is what stays right when that changes.

**The cooldown is what makes four wins read as four people being congratulated**
rather than as flashing.

**Sound plays here and nowhere else** — see the note on the in-app overlay above.
Autoplay with sound requires the page to have been interacted with, which a wall
satisfies because a person opens the link once and leaves it running.

Configurable per organization: enabled/disabled, duration, and which events trigger it (goal achievement only, by default — everything else makes the display noisy).

### Walk-up media — decided in, reversing the note below

**Decision:** a celebration can carry a **walk-up song, GIF, or YouTube clip**,
the way a batter has walk-up music. Somebody closing a deal gets their own
fifteen seconds on the wall. This is the gamification, not decoration around it.

The original note (kept below) argued sound and custom media out of v1. One of
those objections has an answer and the other was overweighted:

- **Sound in an open-plan office.** Answered operationally rather than in
  software: a company that does not want it mutes the TVs. That is a decision
  the room can make for itself, and it does not need to be prevented here.
- **Custom media as "a CMS in disguise".** True *if it means uploads* — storage,
  quotas, moderation, cleanup. It does not have to. See below.

**Built in 2c-ii:** the per-person default, the per-shout-out override, and the
validation. Nothing plays anywhere until 2f gives the wall a screen to play it
on.

**URLs first, uploads later.** A YouTube link with a start and end offset covers
walk-up songs completely, and a hosted GIF URL covers the rest. That is a text
column, and it skips file storage, upload limits, virus scanning, orphan
cleanup, and a moderation queue — none of which this product has ever needed.
Uploads can follow if people actually want local files.

**Where it lives:**

| | |
|---|---|
| Per person | Your walk-up media, set once, plays whenever you are celebrated |
| Per shout-out | An override a manager picks for one particular occasion |

The per-person default is the stronger idea and the one that makes it a
*walk-up*; the override is what lets a specific save get a specific joke.

**Kept short by design.** Ten to fifteen seconds, enforced by the end offset
rather than trusted to whoever pasted the link. A wall screen owes the room its
leaderboard back.

**Two things to work out when this is built (2f):**

1. **Autoplay with sound is blocked by browsers** without a user gesture. A wall
   display has nobody to click anything, so the TV needs launching with
   `--autoplay-policy=no-user-gesture-required` (or its equivalent) — a
   deployment note, not a code change, and one that has to be written down or
   every install will report "the sound does not work".
2. **The display page loads remote media**, which is a change to what a
   token-authenticated screen is allowed to fetch. The URL is chosen by an
   admin or the person themselves, not by an outsider, but the content security
   policy has to permit YouTube and image hosts deliberately rather than by
   accident.

**Still not built:** virtual gongs, and any of this in the in-app overlay. A
song playing at somebody's desk when they open a laptop is a different
proposition from one playing in a room that just watched them earn it.

### What was deliberately not built in v1 (superseded, kept for the reasoning)

- **Sound.** An office TV playing an air horn is either delightful or a fireable offense depending on the workplace, and there's no way to know which. If added later, default off and clearly labeled.
- **Custom memes, GIFs, videos.** Spinify has these. They're a content management system in disguise — upload, storage, moderation, per-event assignment. Not v1.
- **Virtual gongs.** Same reasoning as sound.

Keep the trigger infrastructure generic enough that these are content plugged into an existing pipeline later, not a rebuild.

## Notification center

Bell icon in the top bar with an unread count, backed by the partial index from [02-data-model.md](02-data-model.md):

```sql
CREATE INDEX idx_notification_unread
    ON notification (user_id, created_at DESC) WHERE read_at IS NULL;
```

A partial index only indexes unread rows, so the badge query stays fast permanently — the index never grows past the number of genuinely unread notifications, no matter how much history accumulates.

Panel behavior: grouped by day, unread visually distinct, click navigates to the relevant object via `link_url`, "mark all read," and 90-day retention (a scheduled job prunes older rows).

## Delivery architecture

```
Domain event occurs (goal service detects achievement)
   │
   ▼
NotificationService.emit(event_type, context)
   │
   ├─▶ resolve recipients (per event rules + permission scope)
   ├─▶ apply dedupe + rate limits          ← drops here are normal
   ├─▶ write notification rows
   └─▶ dispatch to enabled channels
          ├─ in-app: already written
          ├─ celebration: flag on the row, client polls and displays
          ├─ email: queued, retried on failure
          └─ webhook (Phase 4): queued, retried
```

Two rules:

**Emission is fire-and-forget.** A failing SMTP server must never break goal achievement. Notification dispatch runs outside the transaction that recorded the achievement — if email fails, the goal is still achieved and the in-app notification still exists.

**Detection needs no stored status.** The line above says the job "compares
current progress against the last known status". Taken literally that is a
`last_status` column — stored derived state, which this system deliberately has
nowhere, because it would be wrong the moment a connector backfilled.

It is not needed: **the notification row is itself the record that we announced
it.** A partial unique index on
`(organization_id, user_id, subject_type, subject_id, period_anchor, event_key)`
makes firing twice impossible rather than merely unlikely, and the job emits
with `INSERT ... ON CONFLICT DO NOTHING` — the same pattern that already keeps
recurring goals from spawning duplicates.

This also removes the five-minute dedupe window described above. That window
existed because a bulk import writing 400 facts would otherwise fire 400 times;
for the events Phase 2 ships, the index guarantees one, permanently. What
remains is a per-user daily cap as a backstop.

**Detection is a scheduled job, not a write-time check.** Goal achievement is evaluated by a job every few minutes rather than on every metric fact write. Checking on write would mean re-evaluating every affected goal on every one of thousands of rows during a bulk import. The job compares current progress against the last known status and emits on transition.

The tradeoff is up to a few minutes of latency between hitting a number and seeing the celebration. Acceptable — and it also naturally handles achievements caused by connector syncs, which have no user request to hang the check on.

## Preferences — built

Stored as **deviations only**: a row in `notification_preference` means muted,
and somebody who has never opened the settings has no rows. A new event in the
catalogue is therefore on for everybody without a backfill.

They live on the **account page**, because they are about one person.

**They filter at read, never at creation.** The same notification rows feed the
bell, the Recognition page, and the wall screens — so suppressing a row for
somebody who muted the event would remove them from what the organization
celebrates. A preference governs your bell, not whether the thing happened.
Unmuting therefore reveals what you missed, which is what switching a setting
back on should do.

### Quiet hours — deferred

They suppress an interruption, and Phase 2 has none. With email cut, an in-app
notification is **pulled, not pushed**: it sits in a table until somebody opens
the bell. Nothing arrives at 9pm to be quiet about.

The only real interruption is the celebration overlay, and that reaches
somebody who already has the app open and is looking at it.

A control with no observable effect is worse than a missing one — it teaches
people the settings page is decorative. Revisit when a channel exists that
actually reaches out.

## Preferences (original design notes)

Per-user, with org-level defaults:

```
Goal achievements        [in-app ✓] [email ✓] [celebration ✓]
Goal reminders           [in-app ✓] [email ✗]
Rank changes             [in-app ✓] [email ✗]
Competitions             [in-app ✓] [email ✓]
System / imports         [in-app ✓] [email ✓]     admins only

Digest    ( ) Immediate   (•) Daily summary   ( ) Off
Quiet hours   [18:00] to [08:00]   org timezone
```

Quiet hours hold non-urgent notifications rather than dropping them. Recognition arriving at 2am is worthless; recognition arriving at 8:05am still lands.

**Goal achievement notifications cannot be fully disabled for managers** about their own team — that's the mechanism that prompts a manager to acknowledge a win, and it's a small deliberate paternalism.

## API surface

```
GET    /api/notifications                 ?unread_only=true, cursor paginated
GET    /api/notifications/unread-count
POST   /api/notifications/{id}/read
POST   /api/notifications/read-all
GET    /api/notifications/pending-celebrations    polled by the client
POST   /api/notifications/celebrations/{id}/seen  marks as shown

GET    /api/notification-preferences
PATCH  /api/notification-preferences

GET    /api/admin/notification-settings           org defaults
PATCH  /api/admin/notification-settings
POST   /api/admin/test-email                      verify SMTP config
```

`GET /api/notifications/pending-celebrations` is polled alongside the existing dashboard refresh — no separate mechanism, and it works without WebSockets. `POST .../seen` is what guarantees a celebration fires exactly once.

## Open questions

1. **Is email needed in Phase 2, or can it wait?** In-app covers the core loop; email requires SMTP configuration that many internal deployments won't have initially. *Leaning: build the channel abstraction in Phase 2, implement email in it, but never require it.*
2. **Should managers be notified of every team goal achievement?** In a 15-person team that's a lot. *Leaning: digest by default for managers, immediate for the achiever.*
3. **Peer recognition** — should colleagues be able to send kudos or react to an achievement? Genuinely valuable for engagement, and a meaningful scope addition. *Leaning: Phase 4, but reserve the schema shape.*
4. **TV celebration and privacy** — should a celebration name someone on a screen visible to the whole office? Almost always yes, but some organizations will want it off. Needs to be an org setting.

## Related docs

- [07-goals-and-targets.md](07-goals-and-targets.md)
- [09-competitions.md](09-competitions.md)
- [12-design-system.md](12-design-system.md)
