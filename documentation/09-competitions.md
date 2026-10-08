# Competitions

**Phase 2.** Time-boxed contests with a defined start, end, participants, and winner.

## Competition vs leaderboard vs goal

Easy to conflate, genuinely different:

| | Leaderboard | Goal | Competition |
|---|---|---|---|
| Time | Ongoing, rolling | A period | Fixed start and end |
| Measure | Relative rank | Absolute target | Relative rank |
| Ends | Never | Period ends | Explicitly, with a winner |
| Result | Live, always current | Achieved / missed | **Frozen permanently** |
| Purpose | Ongoing visibility | Accountability | A short burst of focus |

**A goal is you against a number; a competition is you against someone else.**
That is the sentence to use when explaining the difference — the table above is
the precise version, but this is the one people remember. It also explains why
a competition cannot simply be a goal: two teams both hitting 50 have both hit
the goal, and neither has won anything.

The defining property: **a competition's result is frozen when it closes.** A leaderboard for July recomputes if July's data is later corrected. July's competition winner does not change — the prize was already given out.

**What plays on a wall screen is usually a goal, not a competition.** Worth
saying here because the two get conflated in planning: goals are the things
tracked from metrics with a target and a pace marker, they run continuously,
and they are what a room can act on before the month closes. A competition is
the occasional time-boxed event layered on top. Both are valid channel screens
— see Phase 2 in [18-roadmap.md](18-roadmap.md) — but goals are the common
case and competitions are the special one.

**Settled for Phase 2:** a competition is its own entity with its own tables,
not a mode on `goal`. A goal must keep recomputing when a fact is corrected;
a competition must not. One row cannot do both without a flag that changes the
meaning of every query that reads it. See Phase 2 in
[18-roadmap.md](18-roadmap.md).

## Formats

There is no `format` column. There are two entity types and a participant
count, and every "format" falls out of those.

### `entity_type = "user"`
Individuals compete. Simplest and most common.

### `entity_type = "team"`
Teams compete; individual contributions roll up. Uses the same total-vs-average
choice as team leaderboards ([08-leaderboards.md](08-leaderboards.md)) — it is
the metric's own aggregation, not a competition setting.

### Head-to-head
Two entrants, of either type. **Not a stored format** — it is what two entrants
*look like*, so the UI renders two large numbers side by side instead of a
ranked list when `len(participants) == 2`. Storing it as a third option would
create a value that could disagree with the participant count, and a stored
fact contradicting a derived one is the exact shape of bug this codebase keeps
finding.

**Deliberately deferred:** brackets/tournaments, relay formats, and handicapping. Each is a meaningful chunk of scheduling and progression logic, and none is needed to prove the feature.

## Lifecycle

```
draft ──▶ scheduled ──▶ active ──▶ ended ──▶ closed
  │                        │
  └────── cancelled ◀──────┘
```

| State | Meaning |
|---|---|
| `draft` | Being configured, not visible to participants |
| `scheduled` | Published, `starts_at` in the future — visible, builds anticipation |
| `active` | Running, standings live |
| `ended` | Past `ends_at`, results computing |
| `closed` | Final ranks written and frozen |
| `cancelled` | Stopped early, no winner |

**Every state has a way back to `draft` except `closed`.** `POST /{id}/unpublish`
hides it from entrants again and unlocks the rules, which is what somebody who has
just spotted the wrong metric actually wants. Publishing was previously one-way:
the only exit was cancelling, and the contest then sat under Finished for good.

`closed` is the single refusal. Its result has been announced, so reopening it
would make a winner provisional after the fact.

**Deleting is separate from cancelling, and narrower.** Draft and cancelled only —
both mean "nothing came of this". A running contest must be cancelled first so its
entrants see a decision rather than a disappearance, and a settled one is refused
outright: it is the record of a prize somebody received, which is the whole reason
its numbers are stored instead of derived.

The gap between `ended` and `closed` is deliberate. When a competition's window ends, late data may still arrive — a deal closed at 4:55pm that syncs at 5:10pm. A configurable **settlement window** (default 24 hours) lets facts land before results are frozen.

During settlement the UI shows "Provisional results — finalizing." Announcing a winner and then changing it is far worse than a day's delay.

A scheduled job transitions states; it doesn't depend on someone loading the page. `competitions.advance()` runs in the existing job loop alongside notification detection and pruning.

**`draft` never leaves on its own.** A draft is being configured, and nobody should discover it went live. Only `scheduled` responds to the clock — publishing is a person's decision.

**Re-running `advance()` cannot re-settle a closed competition.** `closed` matches no transition, so the job is safe to run as often as the loop wants.

## Freezing results

On close, `competition_participant.final_rank` and `final_value` are written once.

**Why store these when nothing else in the system stores computed values:** every other number is derived because derived numbers stay correct. A competition result is the opposite — it must stay *fixed*. It's a historical record of an event that had consequences (a prize, an announcement). If a metric fact is corrected in September, August's leaderboard should update and August's competition winner should not.

After close, standings are read from the frozen columns, never recomputed.
`standings()` decides which for you — one function for both, so no caller has
to remember, and no page can quietly disagree with the trophy.

**The test this needs**, and it is the sharpest one in Phase 2: correcting an
August metric fact must change August's *leaderboard* and must not change
August's *competition winner*. Everything else in this system is derived
because derived numbers stay correct. This one is stored because a prize was
handed over on the strength of it.

Both halves are asserted in a single test —
`test_a_correction_moves_the_leaderboard_and_not_the_winner` — because either
alone can pass for the wrong reason. It is also the one behaviour verified by
hand against real dev data: a 999,999 correction dated inside a closed
contest's window moved that window's leaderboard to a new first place and left
the winner alone.

**Absolute instants, not a period type.** A competition is an event somebody
scheduled — "the first two weeks of August" — not a recurring window. Storing a
period type would mean re-resolving it later and getting a different answer if
the organization's timezone changed, which for a settled result is rewriting
history.

## Scoring

Standings use the same aggregation and ranking engine as leaderboards ([06-metrics-engine.md](06-metrics-engine.md)) — one `RANK()` window function over facts within `starts_at` → `ends_at`.

**Ranking happens inside the entrant set.** `aggregate` takes `visible=` for
user competitions and `team_ids=` for team ones, so the `RANK()` runs over the
entrants alone. Ranking against the whole organization and hiding the rest
would give a different, wrong number — second of two is not second of forty.

**No viewer is passed.** The entrant set *is* the scope, and every entrant sees
the same table. `aggregate` reads its actor only to work out `visible` when the
caller stays silent, and this one never does, so `NO_ACTOR = None` is passed
deliberately — see the roadmap's 2e-i notes for why a fake admin was worse.

Competition-specific options:

- **`min_participation`** — a floor below which an entity is **unranked, not last**. They were in the contest and did not qualify; those mean different things. NULL means no floor, which is right for a sum or a count.
- **`tie_break`** — `earliest_to_reach` (whoever got there first wins) or `shared_rank` (1, 2, 2, 4). Sales contests usually want a decisive winner, so `earliest_to_reach` is the default.

`earliest_to_reach` needs the timestamp at which each participant reached their final value — one extra query at close, worth it to avoid a disputed tie. It looks only *inside* the window: somebody who hit the number early and kept selling must not have their "reached" time dragged past a slower rival's.

**Baseline is not a setting.** The window is `[starts_at, ends_at)`, so scoring
is zero-based by construction — facts before the start are simply not in it.
An earlier draft of this document offered a choice here; there was nothing for
the other option to mean.

### Gap to the place above

Each standing carries `gap_to_next`: the distance to the entrant immediately
above, `None` for the leader. Not the gap to first. "$4,100 behind 6th" is
something somebody can do today; "$45,300 behind 1st" is a reason to stop
trying, and a board that only motivates the top three is a board most of the
floor learns to ignore.

## UI

### Competition card / detail

```
┌──────────────────────────────────────────────────────────┐
│  🏆  August Revenue Sprint              ● Active         │
│      Revenue Closed · Individual                          │
│      🥇 $500 gift card + trophy                           │
├──────────────────────────────────────────────────────────┤
│      ⏱  3 days, 4 hours remaining                        │
│      ████████████████████████░░░░░░░░  73% elapsed        │
├──────────────────────────────────────────────────────────┤
│  🥇  1  Marcus Chen        $84,200                       │
│  🥈  2  Priya Raman        $71,900     $12,300 behind    │
│  🥉  3  Dan Whitfield      $68,400     $15,800 behind    │
│  ─────────────────────────────────────────────────────── │
│  ▸   7  You                $38,900     $45,300 behind    │
│                            ▲ 2 places since yesterday     │
└──────────────────────────────────────────────────────────┘
```

Design decisions:

- **The countdown is the most important element.** Urgency is the mechanism a competition adds over a leaderboard. It should be prominent and update live.
- **Show the gap to the position ahead**, not just to first. "$4,100 behind 6th place" is achievable and motivating; "$45,300 behind 1st" is not.
- **The prize is displayed everywhere the competition appears.** It's the reason anyone cares.
- **The viewer's row is always pinned**, as with leaderboards.

### Creation flow

```
1. Name, description, prize
2. Metric
3. Format: individual / team / head-to-head
4. Participants: individuals, teams, or whole org
5. Start and end (with quick presets: this week, this month, next 7 days)
6. Options: baseline, tie-break, min participation
7. Review — plain-English summary + preview against historical data
```

Step 7 previewing against history is what stops the most common failure: a contest whose outcome was effectively decided before it started because one agent always leads that metric. Showing "over the last 3 comparable periods, Marcus won all 3" prompts the creator to reconsider the format or handicap.

### Results / archive

Closed competitions get a permanent results page: final standings, winner highlighted, full participant list, and a link to the period's data. A visible history of past contests is itself motivating.

## Notifications

Competitions generate the highest-value notifications in the product (see [11-notifications-and-celebrations.md](11-notifications-and-celebrations.md)):

| Event | Key | Recipients | Public |
|---|---|---|---|
| Competition starts | `competition.started` | Entrants | No — the wall gets the standings screen instead |
| Won | `competition.won` | The winner(s) | **Yes**, and celebrated |
| Where everyone else finished | `competition.finished` | Every other ranked entrant | No |
| Lead change | — | *Deferred: needs a rank snapshot table* | |
| 24 hours remaining | — | *Deferred with the above* | |

**A win is public and a placing is not.** "You came 4th of 9" belongs in the bell,
not on a display read by whoever walks past — the same reasoning that keeps
`goal.period_ending` off the wall.

**Recipients are people, never entities.** A team contest notifies everybody *on*
the entrant teams: "Enterprise won" is news to the twelve people who made it
happen, not to a row in a table. Archived and non-active accounts are excluded, so
somebody on an unaccepted invitation is not told they finished third in a contest
nothing ever told them had started.

**The winner's walk-up media rides along**, resolved at emit and frozen on the
row, so changing your music later does not re-score a win you have already had.
Nothing for a team win — there is no one person whose song it would be.

**Announced from `close()`, not from the job**, so settling early through the API
produces exactly what the clock would have.

**Lead-change notifications need hard rate limiting.** Two agents trading first place every ten minutes on the last day would generate dozens of pushes. Cap at one per participant per hour, and suppress entirely in the final hour except for the actual lead change.

## API surface

```
GET    /api/competitions                   ?state= &mine= (scope-filtered)
POST   /api/competitions                   creates a draft
POST   /api/competitions/preview           historical rehearsal
GET    /api/competitions/{id}              competition + standings + your row
PATCH  /api/competitions/{id}              rules locked once active
POST   /api/competitions/{id}/publish      draft → scheduled
POST   /api/competitions/{id}/cancel       stops it, no result
POST   /api/competitions/{id}/close        settle early (admin only)

GET    /api/competitions/{id}/participants
POST   /api/competitions/{id}/participants
DELETE /api/competitions/{id}/participants/{pid}
```

**No separate `/standings` endpoint.** `GET /{id}` returns the competition, its
standings, and the caller's own row together, because a page assembling those
from three requests has to make their answers agree about whether the contest
closed in between. The response says whether the table is `final`, so a caller
cannot mistake a settled result for a live one.

**`/preview` is declared above `/{id}`.** FastAPI matches in definition order.
`competition_id: int` would reject "preview" with a 422 rather than mis-routing
it, but relying on a type-coercion failure to keep two endpoints apart stops
being true the day somebody widens the parameter — so there is a test that fails
here rather than in the browser.

**Editing an active competition is heavily restricted.** Name and prize can change. Metric, dates, scoring rules, and participants cannot — changing the rules mid-contest destroys trust in the result. Enforced server-side, and the refusal names the fields rather than saying "not allowed", because the person is mid-edit and needs to know which part to undo. `rules_editable` on the read model lets the UI lock the fields up front instead of accepting a save the server then rejects.

`scheduled` counts as editable alongside `draft`: it is published and visible, but nobody has competed under the old rules yet.

**Entrants cannot be added or removed once it starts.** Joining halfway through means less time to win; being removed rewrites what everyone else already saw. Cancel it instead.

## Who can see a competition

**You are in it, or you could see every entrant anyway.**

This is the only place in the product where one person's numbers are deliberately
shown to another. Everywhere else `visible_user_ids` hides them; a competition
whose entrants cannot see each other's positions is not a competition, so
**entering one is consent to be ranked in it**. The scope rule therefore governs
whether the contest appears *at all*, and once you are in it you see the whole
table.

One sentence covers all three roles without a special case:

| Role | Sees |
|---|---|
| admin | every competition in the organization |
| manager | contests confined to their own people, and their own drafts |
| agent | the contests they are entered in |

"Every entrant", not "any". A contest between one colleague an agent can see and
forty they cannot would otherwise hand over forty names.

Team contests collapse to **"your team is in it"** — a non-admin can only ever see
all the members of their own team, so a member-by-member check computes the same
answer, except for two *empty* teams where it is vacuously true and leaks. Drafts
are hidden from agents entirely, and an entrant-less draft is visible only to
whoever created it, so the creation flow has somewhere to stand.

## The historical preview

`POST /api/competitions/preview` — the same metric and entrants over an
equally-long window that has actually happened.

The question somebody setting up a contest really has is not "what is the
target" — a competition has no target — it is **"will this be worth watching?"**
A field where one entrant does four times the volume of the rest is a coronation,
and the honest moment to find that out is while the entrant list is still
editable. `spread` is that answer as one number: how many times the leader's
total the bottom of the field managed.

The window is anchored at `min(starts_at, now)`. Measuring back from `starts_at`
alone is history only when the contest begins today — a contest planned for next
month otherwise gets a "history" reaching into the future, where every number is
necessarily zero.

The preview scores through `standings_for()`, the same function the real contest
uses. A separate code path would be a second place for the numbers to be right in
isolation and disagree in practice.

## On the wall

A `competition` screen shows the prize, a countdown, and the top eight of the
table with "of 14" beside it. The standings come from the same `standings()` call
the app makes, so a settled contest shows its frozen result here too and the wall
cannot disagree with the trophy.

**Only `scheduled`, `active`, `ended` and `closed` reach a wall.** A draft is a
plan nobody published and a cancelled contest has no result and no future — both
would be a slide saying nothing. Refused when the screen is authored, and skipped
again at render for rows that predate the check.

**A competition belongs to a *set* of offices**, which is why it cannot use the
single-slot `Where` that goals and boards do. A goal names one subject and sits in
one place; a contest between Phoenix and Dallas sits in two, and "two" is not a
value `Where` can hold.

| Wall | Shows the contest when |
|---|---|
| organization-wide | always — it is the company's own wall |
| an office | that office is involved |
| a team | that team is entered, or its office is involved |

So a Phoenix-versus-Dallas contest reaches Phoenix's wall and Dallas's wall, **and
not Austin's**. An earlier version collapsed any multi-office contest to
`EVERYWHERE`, which got the two-office case right by accident and every other
office wrong — `EVERYWHERE` fits every wall, so uninvolved offices showed it too.

An entrant with no team contributes "no office" to the set rather than making the
contest everybody's. See `eligibility.competition_offices` and
`competition_fits`.

## Repeating

"Weekly sprint every Monday" — a contest set to repeat every day, week or month,
optionally until a date.

**Rounds, not a longer contest.** The first round is an ordinary competition
that repeats; every later round is another ordinary competition pointing back at
it with a round number. Each has its own absolute window, its own entrants and
its own frozen result, so last week's winner stays last week's winner and the
settlement window works per round exactly as it does for a one-off. That is why
"absolute instants, not a period type" above still holds.

**Dates follow the series; everything else follows the last round.** A round's
window is the first round's, moved on by whole days, weeks or months on the
organization's wall clock — 9am Monday stays 9am across a daylight saving
change, and a monthly contest on the 31st runs on the 30th in April. Its name,
prize, rules and entrants are copied from the most recent round, so **editing
the upcoming round is how the series changes** from then on.

**One round ahead.** The next round is made (published, `scheduled`) as soon as
the current one starts, so it is on the list building anticipation. Nothing is
made before the first round starts, nothing for an unpublished series, and a
series left alone for a month is not back-filled with four contests nobody saw —
only the round running now, if one is, and the next. A unique index on
(series, round) makes a second copy of a round impossible.

**A round cannot overlap the next**, so a fortnight's contest cannot repeat
weekly — refused in words when it is set. Repeating can be switched on, changed
or stopped from any round, in any state, because it decides future rounds and
not this one's rules; stopping keeps every round already made. Each contest's
page lists the series' rounds and who won each.

## Open questions

1. **Points and badges** — Phase 4 in the roadmap. Competitions are the natural place to award them. Should the schema carry a `points_awarded` field now to avoid a migration later? *Leaning: yes, nullable, unused until Phase 4.*
2. **Recurring competitions** — **built.** See "Repeating" below.
3. **Self-enrollment** — can agents opt into an open competition, or are participants always assigned? *Leaning: assigned for v1.*
4. **Settlement window default** — 24 hours, configurable per competition from 0 to 168 (a week). Still open whether it should *scale* with duration rather than being set by hand; 24h is clearly too long for a one-day sprint. Left as a per-competition field for now because a wrong automatic answer is harder to notice than a wrong manual one.

## Related docs

- [08-leaderboards.md](08-leaderboards.md)
- [06-metrics-engine.md](06-metrics-engine.md)
- [11-notifications-and-celebrations.md](11-notifications-and-celebrations.md)
