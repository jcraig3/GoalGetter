# Organization Structure & Teams

**Phase 1.** How people are arranged, and how that arrangement drives everything else.

## Why this matters more than it looks

The org tree is not an org chart feature. It's the axis that **permissions**, **leaderboard scoping**, **goal rollups**, and **dashboard filtering** all read from. Getting it wrong means rebuilding four other features.

## The model: flat teams

A team is a flat group. Teams do not nest.

```
Acme Sales (organization)
├── Enterprise      6 agents
├── SMB             8 agents
├── Inside Sales    5 agents
└── Renewals        3 agents
```

An earlier design made this a self-referencing tree, so a company could run
divisions → regions → teams → pods. **It was simplified before anything
depended on it**, and the saving was larger than one column:

| Removed with the hierarchy | Existed to |
|---|---|
| Recursive CTE traversal | walk arbitrary depth |
| Depth tracking and a 20-level cap | stop a cycle looping forever |
| Cycle prevention on reparent | keep a team from becoming its own ancestor |
| Archive-with-children guard | avoid orphaning or hiding a branch |

A sales floor has teams, and leaderboards compare them directly. If divisional
rollups are ever wanted, a separate grouping concept is a smaller change than
reinstating the tree.

## Membership: one team per agent

Stored as `user_account.team_id`, not a join table.

Several teams per person would force every leaderboard to answer *"does this
person count twice?"*. Adding a join table later is contained; unpicking one
that aggregations already depend on is not.

**`team_id` is nullable on purpose.** Someone invited but not yet placed is a
real state, and the most common setup failure — they are silently missing from
every team leaderboard until assigned. The Users table marks them in amber
rather than leaving the cell blank, because a blank reads as "nothing to see".

### Historical accuracy

Moving someone between teams must not rewrite the past. That is handled by
`metric_fact.subject_team_id`, which records the team an agent was on **when
each event happened** — not by keeping membership history.

So if an agent moves from SMB to Enterprise in June, May's numbers stay with
SMB. Reading their current `team_id` when rendering a historical leaderboard
would silently rewrite it.

## Rules and constraints

1. **No cycles.** A team cannot be its own ancestor. Enforced in the service layer on create and reparent by walking the ancestor chain before committing.
2. **Archiving is not deleting.** Archiving hides a team from pickers while its history stays queryable — a leaderboard for last quarter must still be able to name the team that won it. Archiving is reversible.
3. **Deleting is permitted only while nothing references the team.** A team with people assigned returns 409 naming the count, and points at archive instead. Delete therefore exists for one case: a team created by mistake.
4. **A user with no team is valid.** Newly invited users, admins, and executives may have no team membership. They simply don't appear on team-scoped leaderboards. Never force a placeholder team.
5. **Depth is not artificially limited.** Practically it stays under 5 levels; the code shouldn't care.

## UI

### Org structure page (admin/manager)

A tree view with inline actions. Not a drag-and-drop org chart canvas — that looks impressive in a demo and is painful to use with 40 teams.

```
┌──────────────────────────────────────────────────────┐
│  Organization Structure          [+ New Team]        │
├──────────────────────────────────────────────────────┤
│                                                       │
│  ▼ West Division                    24 people   ⋮    │
│      ▼ Enterprise West              11 people   ⋮    │
│          • Pod A                     5 people   ⋮    │
│          • Pod B                     6 people   ⋮    │
│      ▶ SMB West                     13 people   ⋮    │
│                                                       │
│  ▶ East Division                    31 people   ⋮    │
│                                                       │
│  ⚠ Unassigned                        3 people        │
└──────────────────────────────────────────────────────┘
```

- Expand/collapse, with state persisted per user.
- Each team shows its member count, so an empty team is obvious at a glance.
- `⋮` menu: Edit, Add Sub-team, Move, Manage Members, Archive.
- **"Unassigned" is a computed bucket, not a real team.** Surfacing it prevents the most common setup failure: people invited but never placed, silently missing from every leaderboard.

### Team detail page

Members list, active goals, and the team's leaderboard position. Assignment happens from the Users page, where the whole roster is visible at once — moving five people between teams there is one screen rather than five.

### Drag-and-drop

Deferred. Nice, but click-to-move with an explicit confirmation is safer for an operation that relocates dozens of people, and it's accessible by default.

## API surface

```
GET    /api/teams                     flat list, supports ?include_archived
GET    /api/teams/tree                nested tree with rolled-up counts
POST   /api/teams
GET    /api/teams/{id}
PATCH  /api/teams/{id}                rename, recolor, reparent
POST   /api/teams/{id}/archive
GET    /api/teams/{id}/members        ?include_subteams=true
POST   /api/teams/{id}/members        add users (bulk)
DELETE /api/teams/{id}/members/{uid}  sets left_at
PATCH  /api/teams/{id}/members/{uid}  change team_role

GET    /api/organization              settings
PATCH  /api/organization              name, timezone, week start, fiscal year, branding
```

`GET /api/teams/tree` returns the whole structure in one call. Companies have tens of teams, not thousands, so pagination would add complexity for no benefit, and the client needs the full tree to render pickers anyway.

## Organization settings

Configured once, but they change how every number is calculated:

| Setting | Why it's load-bearing |
|---|---|
| **Timezone** | Determines when "today" starts. Wrong timezone puts events in the wrong day and quietly corrupts daily leaderboards. |
| **Week starts on** | Monday vs Sunday shifts every weekly goal boundary. |
| **Fiscal year start month** | "This quarter" is meaningless without it. |
| **Currency** | Display and formatting of currency-unit metrics. |
| **Branding** | Logo and accent color, mainly for TV display mode. |

These need to be set during first-run setup, not discovered later — changing `week_starts_on` after three months of data shifts historical weekly boundaries. The UI should warn about that explicitly.

## Open questions

1. **Multiple leads per team** — allowed by the model. Should the UI encourage or discourage it?
2. **Should a lead automatically get the `manager` org role?** Currently org role and team role are independent, which is flexible but means a lead without the `manager` role can't actually manage. Auto-granting is convenient; it also makes permissions less predictable. *Leaning: keep independent, but warn in the UI when a lead lacks manager rights.*
3. **Import** — is CSV import of the org structure needed for Phase 1, or is manual setup acceptable for the first deployments?

## Related docs

- [02-data-model.md](02-data-model.md) — `team`, `team_membership`
- [05-roles-and-permissions.md](05-roles-and-permissions.md) — how the tree drives access
- [08-leaderboards.md](08-leaderboards.md) — team scoping
