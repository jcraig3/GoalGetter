# Dashboards & Reporting

**Phase 1** for the personal and manager dashboards. Advanced reporting is Phase 2.

## Principle

Dashboards answer a specific question for a specific person. They are not configurable canvases.

> **Agent:** "Am I going to hit my number, and where do I stand?"
> **Manager:** "Is my team going to hit their number, and who needs help?"
> **Admin:** "Is the system healthy and is the data flowing?"

Building one generic drag-and-drop dashboard builder means nobody's question is answered well by default. Three purpose-built dashboards is less work and more useful.

## Personal dashboard (`/dashboard`)

The landing page for every `agent`. This is the screen that determines whether people open the tool daily.

```
┌────────────────────────────────────────────────────────────┐
│  Good morning, Jayden                     August 12, 2026  │
├────────────────────────────────────────────────────────────┤
│                                                             │
│  YOUR GOALS                                                 │
│  ┌───────────────────────┐  ┌───────────────────────┐     │
│  │ Revenue Closed        │  │ Meetings Booked       │     │
│  │ $32,400 / $50,000     │  │ 14 / 20               │     │
│  │ ████████████░░░░ 65%  │  │ █████████████░░░ 70%  │     │
│  │ ┆ pace          ● On  │  │ ┆ pace       ▲ Ahead  │     │
│  │ 12 days · $1,467/day  │  │ 12 days · 0.5/day     │     │
│  └───────────────────────┘  └───────────────────────┘     │
│                                                             │
│  THIS MONTH                    ┌─────────────────────────┐ │
│  ┌──────┐┌──────┐┌──────┐     │  YOUR RANK              │ │
│  │ 214  ││  38  ││ $32k │     │                          │ │
│  │Calls ││Mtgs  ││Rev   │     │      #7 of 24            │ │
│  │ ▲12% ││ ▲5%  ││ ▼3%  │     │      ▲ up 2 this week    │ │
│  └──────┘└──────┘└──────┘     │  Revenue · Enterprise W. │ │
│                                └─────────────────────────┘ │
│  TREND                                                      │
│  ┌────────────────────────────────────────────────────┐   │
│  │  Revenue Closed — last 30 days      [Metric ▾]     │   │
│  │        ╱╲      ╱                                    │   │
│  │    ╱╲╱  ╲    ╱                                      │   │
│  │  ╱       ╲╱╲╱                                       │   │
│  └────────────────────────────────────────────────────┘   │
│                                                             │
│  RECENT ACTIVITY                                            │
│  🎉 You hit "20 Meetings Booked" — 3 days ago              │
│  ▲  You moved to #7 on Revenue Closed — yesterday          │
└────────────────────────────────────────────────────────────┘
```

Decisions:

- **Goals come first.** The single most actionable thing. Pace and "per day needed" turn a percentage into something a person can act on.
- **Rank is prominent but not the top item.** Rank is motivating; your own target is what you control. Putting rank first makes the tool feel like surveillance.
- **Stat tiles compare to the previous equivalent period**, not to a target. "▲12% vs last month" is context that a raw number lacks.
- **Recent activity is personal**, not an org-wide feed. An org feed becomes noise at 40+ people and gets ignored.
- **Metric selector on the trend chart** — one chart the user chooses, rather than six charts they scroll past.

## Manager dashboard (`/dashboard` for `manager`)

Same route, different composition based on role. A manager's question is "who needs my attention today," so the design is built around exception-surfacing rather than showing everything equally.

```
┌────────────────────────────────────────────────────────────┐
│  Enterprise West                          August 12, 2026  │
│  [ Enterprise West ▾ ]  ← team scope switcher              │
├────────────────────────────────────────────────────────────┤
│  TEAM GOALS                                                 │
│  ┌────────────────────────────────────────────────────┐   │
│  │ Revenue Closed — Team    $284,300 / $400,000        │   │
│  │ ██████████████░░░░░░░░  71%      ┆ pace   ● On     │   │
│  └────────────────────────────────────────────────────┘   │
│                                                             │
│  ⚠ NEEDS ATTENTION                                          │
│  ┌────────────────────────────────────────────────────┐   │
│  │ ● Dan Whitfield    Revenue    38% · 22% behind pace│   │
│  │ ● Ana Torres       Meetings   12% · no activity 6d │   │
│  └────────────────────────────────────────────────────┘   │
│                                                             │
│  TEAM PERFORMANCE                                           │
│  ┌────────────────────────────────────────────────────┐   │
│  │ Name          Revenue    Goal %   Calls   Trend    │   │
│  │ Marcus Chen   $84,200    168% ██  312     ╱╲╱      │   │
│  │ Priya Raman   $71,900    143% ██  287     ╱─╲      │   │
│  │ Dan Whitfield $19,200     38% ░░  104     ╲──      │   │
│  └────────────────────────────────────────────────────┘   │
│                                          [Export CSV]      │
└────────────────────────────────────────────────────────────┘
```

Decisions:

- **"Needs attention" is the most valuable element.** Computed as: significantly behind pace, or no activity in N days. A manager scanning 12 people for problems is doing work the tool should do.
- **"No recent activity" is flagged separately from "behind pace."** They mean different things — one is a performance conversation, the other is often a data problem or someone on leave.
- **The team table is sortable and includes goal attainment %**, which is fairer than raw volume when agents carry different targets.
- **Scope switcher** lets a manager over multiple teams move between them and view rolled-up totals.
- **CSV export** on every table. Managers will want the data in a spreadsheet, and refusing that just means they screenshot it.

## Admin dashboard (`/admin`)

Operational health, not performance.

- User counts by status; anyone invited but never activated
- **People with no team membership** — the most common setup failure, and it silently excludes them from every leaderboard
- Metrics with no data in the last 7 days (usually a broken import or connector)
- Recent imports and their outcomes
- Data source sync status and last-error — **built.** Sources failing, sources
  overdue, and the most recent failure's own words. Counted separately because the
  fixes differ: a failing source has an error to read, while an overdue one usually
  means the background job is not running at all
- Recent audit log entries

## Reporting (Phase 2)

Deliberately constrained. This is not a BI tool ([00-overview.md](00-overview.md)).

| Report | Question |
|---|---|
| Period comparison | This month vs last, per person or team |
| Goal attainment history | Hit rate over the last N periods |
| Team comparison | Teams side by side on one metric |
| Individual detail | One person, all metrics, full history |
| Activity vs outcome | Correlate a leading metric with a lagging one |

All exportable to CSV.

### Scheduled delivery — built

The coaching digest — the Reporting overview as plain text: how many goals are
on pace, behind and hit, and the worst gaps with what closing each would take —
emailed every weekday, once a week, or on the 1st, at an hour in the
organization's clock. Set up on Reporting → Email.

- **Each recipient gets their own**, worked out in their own scope, so a
  manager on an admin's schedule is sent their team. Recipients are accounts,
  not typed addresses, for exactly that reason.
- **Admins and managers only**, and a manager can schedule it only for
  themselves. Somebody demoted or hidden stops receiving it.
- **Email only.** Everything in it is "who is behind", which is kept off the
  wall and out of Teams channels for the same reason.
- **Once per slot, never a backlog**: a schedule remembers the slot it last
  sent for, and a new or changed schedule starts from its next slot. "Send me a
  test" sends to whoever pressed it. A failure is shown on the schedule.

**Deliberately excluded:** ad-hoc query builders, custom SQL, pivot tables. Each request for those should be evaluated as "should this be a named report" rather than "should we build a query engine."

## Shared components

Every dashboard composes the same pieces — see [12-design-system.md](12-design-system.md):

`<StatTile>` · `<GoalCard>` · `<TrendChart>` · `<LeaderboardTable>` · `<AttentionList>` · `<ActivityFeed>`

One `<GoalCard>` used on personal, manager, and goal-detail views means a fix or improvement lands everywhere at once.

## Performance

A dashboard is many queries at once. Two rules:

1. **One batched endpoint per dashboard**, not 8 parallel requests. `GET /api/dashboard` returns everything the personal dashboard needs in a single round trip, computed server-side where the data already is.
2. **Cache aggressively but visibly.** Dashboard data is cached ~60s server-side with the computation timestamp in the response, and the UI shows it. Users tolerate slightly stale data; they don't tolerate not knowing whether it's stale.

## API surface

```
GET /api/dashboard                    role-aware payload for the current user
GET /api/dashboard/team/{team_id}     manager view for a specific team
GET /api/dashboard/admin              operational health

GET /api/reports/period-comparison
GET /api/reports/goal-attainment
GET /api/reports/team-comparison
GET /api/reports/user/{id}
GET /api/reports/{report}/export      CSV
```

`GET /api/dashboard` returning a role-shaped payload keeps role logic on the server. The client renders what it receives rather than deciding what a manager should see — which would duplicate permission logic in the UI.

## Open questions

1. **Should the dashboard be configurable at all?** Even reordering sections. *Leaning: no for v1 — a well-chosen fixed layout beats a configurable one people never configure.*
2. **"Needs attention" thresholds** — hardcoded (behind pace by >15%, no activity 5 days) or org settings? *Leaning: sensible defaults now, settings in Phase 2.*
3. **Should agents see their team's full performance table**, or only their own numbers plus leaderboard rank? *Leaning: rank yes, full table no — that's a manager view. Worth confirming, since some cultures are fully transparent.*

## Related docs

- [07-goals-and-targets.md](07-goals-and-targets.md)
- [08-leaderboards.md](08-leaderboards.md)
- [12-design-system.md](12-design-system.md)
