# Goals & Targets

**Phase 1.** A goal is a target value for a metric, over a period, assigned to someone.

## Anatomy

```
┌─────────────────────────────────────────────────────┐
│  "Close $50,000 this month"                          │
├─────────────────────────────────────────────────────┤
│  metric      revenue_closed                          │
│  target      50000                                   │
│  comparator  >=                                      │
│  period      monthly, 2026-08-01 → 2026-08-31        │
│  assigned to Enterprise West (team) + 6 agents (user)  │
│  recurrence  monthly                                 │
└─────────────────────────────────────────────────────┘
```

Assignment is a separate table from the goal itself. **Why:** "Close $50k this month" applied to fifteen agents is one goal with fifteen assignments, not fifteen goals. Editing the target once updates everyone, and reporting can ask "how is this goal doing overall?" rather than reconciling fifteen near-identical records.

## Scope types — built

| Scope | Meaning | Progress is measured by |
|---|---|---|
| `user` | One person's target | That user's facts |
| `team` | A collective team target | Every member's facts, via the `subject_team_id` snapshot |

**Exactly one subject per goal**, enforced by a CHECK constraint rather than by
every write path remembering. A goal for both a person and a team, or for
neither, has no defined meaning — so it must not be storable.

**No `organization` scope yet, and no multi-assignment goal.** The original
design had one goal carrying several assignments — a team target of $300k
alongside individual targets of $50k each — plus a `target_override` per
assignment. That is a `goal_assignment` join table, a second progress path, and
a rule for what the parent's percentage means when its children disagree.

One goal, one subject is a row. Two goals expressing the same intent are two
rows, and the relationship between them can be added later as a grouping if
anyone actually asks for it. Building the join table first would have meant
designing the harder version against a guess.

Team progress uses the **snapshot**, not the live team: moving someone between
teams must not retroactively hand their past work to a different team's goal.
Measured — see the leaderboard note in 1d-ii.

## Comparators and direction

`comparator` is `gte` (reach or exceed) or `lte` (stay at or below).

Most goals are `gte`. `lte` covers "keep average response time under 2 hours" or "no more than 5 escalations." It's usually paired with a metric whose `direction` is `lower_is_better`, but the two are independent fields — the comparator governs goal attainment, direction governs leaderboard sort order.

## Periods

| `period_type` | Boundaries |
|---|---|
| `daily` | Org timezone midnight to midnight |
| `weekly` | Starts on `organization.week_starts_on` |
| `monthly` | Calendar month |
| `quarterly` | Fiscal quarter, from `organization.fiscal_year_start_month` |
| `yearly` | Fiscal year |
| `custom` | Explicit `period_start` / `period_end` |

Period boundaries are computed from **organization settings**, never from the server or the viewer's browser. A weekly goal must start on the same day for everyone, or two people looking at the same screen see different progress. See [06-metrics-engine.md](06-metrics-engine.md#timezone-handling).

`period_start` and `period_end` are stored as concrete dates even for recurring goals, so a historical goal's window can never shift because someone later changed the org's week-start setting.

## Stretch levels — built

"Close $50,000 this month", with a stretch at $65,000 and another at $80,000
called "Crushed it". Up to three levels past the target, each harder than the
one before — higher for a count, lower for something where lower is better.

**The target is still the target.** Progress, pace and "hit" are measured
against it exactly as before; a level is a further line past it. Each level
crossed is announced once per period (`goal.stretch.1` … `.3` — one key per
level, so none latches another through the notification index), celebrated on
the wall, offered to Teams channels as "Stretch targets hit", and paid 50 points
on top of the target's own (adjustable on the Points page).

**On one goal, not as more goals.** The earlier answer — several goals on the
same metric — announced "Calls achieved" at $65k in words nobody could tell
from the first. One goal with levels is one bar with its levels listed under
it, each announced as what it is. A recurring goal carries its levels into the
next period with the target. Raising the target past a level is refused rather
than leaving a "stretch" easier than the target.

## Recurrence — built

A goal repeats by setting `recurring`. The cadence is its `period_type` — a
monthly goal repeats monthly — so there is no separate frequency field for the
two to disagree about.

```
goal 19  2026-08-01  recurring=true   from=—      ← the original
goal 20  2026-09-01  recurring=false  from=19     ← spawned
goal 22  2026-10-01  recurring=false  from=19     ← spawned
```

**No template row.** The original is a real goal for its own period. A template
would be a row with no progress that every query has to remember to exclude.

**Copies point at the original**, never at the previous copy, so "has this
period been spawned?" is one indexed lookup. A copy never recurs further, so
the chain is one level deep and cannot fork.

**The target is copied, not referenced** — raising next month's target must not
rewrite what last month was judged against.

**Archive the original to stop it.** `recurrence_ends_on` sets a stop date in
advance; deleting cascades to every copy.

**A custom date range cannot recur** — there is no rule for what the next one
would be. Refused with that sentence rather than a constraint name.

### Guided creation — built

`POST /api/goals/preview` returns the last six **complete** periods for a
subject and metric, plus an average, the best, and a suggested target. The goal
form shows it between the period picker and the target field.

**The current period is excluded.** It is partway through, so counting it drags
the average down and suggests a target below what the person actually achieves.

**Empty periods are excluded from the average, not counted as zero.** Someone
who joined three months ago has empty periods before that; averaging them in
halves their target for a reason unrelated to performance.

**Suggestions round by magnitude, not by unit** — 196k average suggests
$220,000, not $216,026.54. A target is a thing people say out loud.

The typed target is assessed against that history as an **observation, never a
refusal**: a stretch above anything previously achieved is a legitimate choice,
and so is an easy target for someone returning from leave.

### Archived goals

Their own view, dimmed and dashed so they do not read as live. Actions are
Restore and Delete — editing a goal that no longer counts would be confusing.
Archiving is also how a recurring goal is switched off without losing what it
asked for.

### Editing an existing goal

`PATCH /api/goals/{id}` changes the target, the name, the period, and whether
it repeats. **The metric and the subject cannot change** — either would make it
a different goal, and its history of "you were at 60%" would then refer to
something else. Those are a delete and a new goal, which is honest about what
happened.

The form shows them as read-only rows with that reason written out, rather than
hiding them: a goal edit form with no metric on it does not read as a goal edit
form, and a disabled control with no explanation reads as a bug.

**Changing the *kind* of period without naming one means the current one.**
Otherwise the old anchor gets reinterpreted under the new type — August's
1 August is also Q3's start, so month → quarter → month landed on July rather
than August. An explicit `period_anchor` still wins; the re-anchoring is a
fallback for "you did not say".

**A spawned copy cannot be made to repeat.** It exists *because* something else
repeats, so the form does not offer the control — one that could only ever
produce a 400 is worse than none.

### Idempotency

A partial unique index on `(spawned_from_goal_id, period_anchor)` makes a
duplicate spawn impossible. The job does *not* check first: a check-then-insert
is a race, and two replicas — or one restarted between the check and the
insert — would both write. Confirmed by mutation: remove the index and running
the job twice produces two copies.

**Anchors are stored canonically**, normalised to the period's start date. Any
date inside a period names that period, so storing whichever the client sent
meant two rows for the same August held different dates — which is how a goal
created on the 13th spawned a duplicate of itself for the month it was already
covering.

### Scheduling

```bash
docker compose exec api python -m app.jobs             # run once
docker compose exec api python -m app.jobs --dry-run   # report only
```

Also runs hourly inside the API process. A plain loop rather than APScheduler:
the only schedule needed is "every so often", and idempotency handles missed
and duplicate runs. Hourly rather than daily-at-a-time removes the "container
was down at 02:00" problem entirely — a new period's goal appears within an
hour of that period starting.

## Recurrence (original design notes)

**Decision: recurring goals spawn a new `goal` row each period.** A scheduled job creates the next period's goal shortly before the current one ends, linked by `recurrence_parent_id`.

Why spawn rather than evaluate a rule:

- A single month can be edited (raise August's target without touching September's).
- Historical goals are immutable records of what was actually asked for.
- Progress queries stay simple — every goal has a real start and end date.
- "Did we hit our monthly goal for the last 12 months?" is a plain query over rows.

The cost is more rows, which is irrelevant at this volume.

Editing a recurring goal asks: **this period only**, or **this and all future periods**. Past periods are never modified.

## Progress — built

Computed by `app/goals.py`, never stored. It is the same `aggregate` query the
leaderboards run, narrowed to one subject — so a goal and a leaderboard showing
the same month cannot disagree about someone's number. A `current_value` column
would be wrong the moment a connector backfilled yesterday's data, and would
need invalidating from every write path that touches `metric_fact`.

**The percentage is not capped at 100.** Beating a target is the point of
having one, and a bar that stops at 100% cannot tell "just made it" from
"doubled it". It *is* capped at 1000%, because one stray fact would otherwise
render a bar 40,000% wide and take the layout with it. The bar element clamps
its own width to 100%; the number beside it does not.

**`lower_is_better` inverts what attainment means.** Response time, cost per
deal: being *under* the target is success. Treating those like a count would
show someone at 40% for beating their target by 60%. A current value of zero is
a perfect score there, not a division by zero.

## Progress (original design notes)

Progress is computed, never stored.

```
current  = aggregate(metric, scope, period_start → period_end)
percent  = current / target × 100          (gte)
percent  = target / current × 100          (lte, guarding divide-by-zero)
status   = not_started | on_track | at_risk | achieved | missed
```

### Pace

Raw percentage is misleading mid-period. Being at 40% of a monthly goal is excellent on the 8th and alarming on the 25th. Every goal display carries a pace comparison:

```
expected_percent = elapsed_period_time / total_period_time × 100
pace_delta       = percent_complete − expected_percent
```

| Status | Condition |
|---|---|
| `achieved` | Target met, regardless of time remaining |
| `on_track` | `pace_delta >= -5` |
| `at_risk` | `pace_delta < -5` and period still open |
| `missed` | Period ended, target not met |
| `not_started` | No facts recorded yet |

The −5 threshold is a starting point and should become an org setting once real usage shows what's useful.

**Pace uses business days by default**, not calendar days — a monthly goal shouldn't look like it's falling behind over a weekend when nobody is working. Configurable per organization, since some teams do work weekends.

### Achievement is sticky

Once a goal hits `achieved`, it stays achieved for that period even if a later correction drops the value below target. The status flag is recorded with a timestamp when first reached.

**Why:** the celebration already fired and the team already saw it. Silently un-achieving a goal because a synced record was amended is worse than a slightly stale status. Admins can manually reset it, and the change is audited.

## Pace — built

Implemented in [`api/app/pace.py`](../api/app/pace.py).

| Field | Meaning |
|---|---|
| `elapsed_percent` | How much of the period's **working time** has passed |
| `expected_percent` | Where progress should be by now. `null` for non-cumulative metrics |
| `projected_value` | Where this lands if the current rate holds. `null` likewise |
| `status` | `not_started` · `behind` · `on_track` · `ahead` · `hit` · `missed` |
| `needs_attention` | `behind` or `missed` |

**Working days, not calendar days.** A month goal checked on Monday morning has
had two calendar days pass and zero selling days. Calendar pacing tells every
agent they slipped over the weekend, every weekend, and a warning that fires on
a predictable schedule stops being read.

Mon–Fri with no holiday calendar, which is an assumption rather than a fact
about any given company — configurable once someone has a real calendar to
configure it against.

**The current day counts only once it is over.** Nobody is told they are behind
at 9am for work the day still has time to produce.

**Only `sum` and `count` are paced.** An average has no honest "should be here
by now", so those goals show elapsed time and nothing else. The alternative —
projecting a running average linearly — produces numbers that look authoritative
and are meaningless.

**A five-point tolerance band** stops a goal flickering between ahead and behind
on every recorded fact.

**Nothing recorded is not attainment.** For `lower_is_better`, an empty period
reads as zero and zero is under every cap — so attainment requires that facts
exist. Without it, "average response time under 60s" reports HIT for someone
who answered no calls.

## UI

### Goal card

The core reusable component. Appears on personal dashboards, team pages, and manager views.

```
┌────────────────────────────────────────────────────┐
│  Revenue Closed                        ● On track  │
│  $32,400 of $50,000                                │
│  ████████████████░░░░░░░░░░░░░░  64.8%             │
│  ┆                              ┆                   │
│  └─ pace marker (58%)           └─ target          │
│                                                     │
│  12 days left · $17,600 to go · $1,467/day needed  │
└────────────────────────────────────────────────────┘
```

The pace marker on the bar is the most valuable element — it turns an abstract percentage into "am I ahead or behind right now" at a glance.

"$X/day needed" is the actionable number an agent can do something about, and it's what makes the card worth looking at daily rather than a static progress bar.

### Goal creation

A short guided flow rather than one dense form, because six interdependent fields presented at once is where admins make mistakes:

```
1. What are we measuring?     → metric picker
2. What's the target?         → value + comparator (unit-aware input)
3. Over what period?          → period type + recurrence
4. Who's it for?              → user / team / org picker, with per-assignee overrides
5. Review                     → plain-English summary + preview against historical data
```

Step 5 is the one that prevents bad goals. Showing "your team averaged $38k/month over the last 3 months" next to a proposed $50k target immediately surfaces targets that are impossible or trivially easy.

### Goals list

Filterable by scope, metric, period, and status. Managers default to their team's goals; agents default to their own.

### Goal detail — built

`/goals/:id`, reached from the list or the dashboard card. The list answers
"how far along"; the detail page answers the two questions a card cannot fit.

**Who is contributing.** For a team goal, the per-person breakdown, ranked. A
manager looking at a team goal that is behind does not need the gap repeated —
the bar says that — they need to know which people make it up. The list is
scoped, so an agent opening a team goal sees only their own line while the
total above stays the team's. That reads as inconsistent and is not: the total
is what the goal *is*, and the breakdown is what the viewer may read.

**Whether the target was ever realistic.** Six earlier periods of the same
metric and subject, as bars against the current target.

This is the same insight as step 5 of the creation flow above — *"your team
averaged $38k/month over the last 3 months"* next to a proposed $50k target —
arriving after the fact instead of before it. The creation preview stops a bad
goal being set; this one surfaces a bad goal already running, which is the more
common situation, because most targets are set once and inherited thereafter.

**Measured against today's target, and labelled as such.** It is not a record
of the goals that existed then: most of those periods had no goal at all, and a
recurring goal's copies could each have carried a different target. One line
across the row is the only comparison that stays consistent from bar to bar.

A custom period has no history — there is no rule for what precedes an
arbitrary range.

## API surface

```
GET    /api/goals                    ?scope&metric&status&period (permission-scoped)
                                     ?trend=true adds a sparkline per goal
GET    /api/goals/{id}               goal + contributors + history, composed
POST   /api/goals                    with assignments
GET    /api/goals/{id}               includes computed progress
PATCH  /api/goals/{id}               ?apply=this_period|all_future
DELETE /api/goals/{id}
POST   /api/goals/{id}/archive

GET    /api/goals/{id}/progress      progress per assignment
GET    /api/goals/{id}/history       progress over time, for the trend chart

POST   /api/goals/{id}/assignments
DELETE /api/goals/{id}/assignments/{aid}

GET    /api/users/{id}/goals         a person's active goals
GET    /api/teams/{id}/goals

POST   /api/goals/preview            historical context for a proposed target
```

`GET /api/goals` returns progress inline for list rendering. It's one aggregation query grouped by assignment, not N queries — important, because a manager's goal list can easily contain 50 goals.

## Interaction with other features

- **Leaderboards** rank on a metric; **goals** measure against a target. A leaderboard can optionally display each person's goal attainment percentage as a column, which is often more meaningful than raw volume when agents have different targets.
- **Competitions** are time-boxed and comparative; goals are absolute. A competition can be created from a goal ("who gets to their number first").
- **Notifications** fire on goal achievement, and on crossing 25/50/75% thresholds. Phase 2 — see [11-notifications-and-celebrations.md](11-notifications-and-celebrations.md).

## Open questions

1. **Stretch goals / tiers** — **built.** See "Stretch levels" below.
2. **Goal approval workflow** — should agent-proposed goals require manager approval? *Leaning: no for v1; managers set goals.*
3. **Prorating for partial periods** — if someone joins mid-month, is their monthly target prorated? *Leaning: manual `target_override` for v1; automatic proration is a surprising behavior to introduce silently.*
4. **Pace threshold** — is ±5% the right at-risk boundary, or should it vary by period length? A daily goal at −5% means something very different from a yearly one.

## Related docs

- [06-metrics-engine.md](06-metrics-engine.md)
- [08-leaderboards.md](08-leaderboards.md)
- [10-dashboards.md](10-dashboards.md)
