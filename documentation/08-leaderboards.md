# Leaderboards

**Phase 1.** The most visible feature in the product, and the one people judge it by.

## What a leaderboard is

A saved configuration that answers: *for this metric, over this period, among these people, who's ahead?*

Results are never stored — they're computed from `metric_fact` on request. What's saved is the question, not the answer.

## Configuration

| Field | Options | Notes |
|---|---|---|
| `metric_definition_id` | any active metric | What's being ranked |
| `entity_type` | `user` · `team` | Rank individuals or teams |
| `scope_type` | `organization` · `team` · `custom` | Who's included |
| `scope_team_id` | a team | With `include_subteams` |
| `period_type` | day/week/month/quarter/year/custom/rolling | Time window |
| `display_limit` | number or all | Top N |
| `visibility` | `org` · `team` · `private` | Who can view |
| `is_tv_enabled` | bool | Eligible for display mode |
| `config.rank_method` | `rank` · `dense_rank` | Tie behavior |
| `config.show_goal_attainment` | bool | Extra column: % of personal goal |
| `config.min_facts` | number | Exclude entities below a floor |

**Rolling periods** (`last_7_days`, `last_30_days`) matter more than they look. Calendar-month boards reset to near-empty on the 1st, which is demotivating and useless for several days. A rolling window is always populated.

`config.min_facts` prevents the common embarrassment where someone with one lucky data point tops an average-based board.

## The query

One `RANK()` window function does the work:

```sql
WITH scores AS (
    SELECT
        f.subject_user_id AS entity_id,
        SUM(f.value)      AS score        -- per metric aggregation
    FROM metric_fact f
    WHERE f.organization_id = :org
      AND f.metric_definition_id = :metric
      AND f.occurred_at >= :start AND f.occurred_at < :end
      AND f.subject_user_id = ANY(:scoped_user_ids)
    GROUP BY f.subject_user_id
    HAVING COUNT(*) >= :min_facts
)
SELECT
    entity_id,
    score,
    RANK() OVER (ORDER BY score DESC) AS rank        -- ASC if lower_is_better
FROM scores
ORDER BY rank
LIMIT :display_limit;
```

Ranking in SQL rather than in Python: the database already holds the aggregated rows, so ranking there costs nothing extra and avoids shipping the full set to the app to re-sort. It also composes — adding `PARTITION BY team_id` produces per-team ranks in the same pass.

### Movement

"Up 2 since yesterday" is a large part of what makes a leaderboard engaging. It's computed by running the same ranking against the previous comparable window and joining:

```sql
SELECT c.entity_id, c.rank AS current_rank, p.rank AS previous_rank,
       p.rank - c.rank AS movement
FROM current_ranks c
LEFT JOIN previous_ranks p USING (entity_id);
```

The comparison window depends on period type — a monthly board compares to the same day-of-month last period, not to the completed previous month, so it's like-for-like rather than comparing 8 days of data against 31.

### Team leaderboards

Two modes, and the UI must label which is in use:

- **Total** — sum of all members' facts. Rewards larger teams.
- **Average per member** — total ÷ active members in the period. Lets a 4-person team compete with a 12-person team.

Member count is measured over the period using `team_membership.joined_at` / `left_at`, so a team that grew mid-month isn't unfairly divided by its end-of-month headcount.

## UI

### Standard view

```
┌───────────────────────────────────────────────────────────┐
│  Revenue Closed — Enterprise West          This Month  ▾  │
│  Updated 30 seconds ago                          ⋮        │
├───────────────────────────────────────────────────────────┤
│                                                            │
│  🥇  1   ┌──┐  Marcus Chen          $84,200      ▲2       │
│          └──┘  Pod A                ██████████            │
│                                                            │
│  🥈  2   ┌──┐  Priya Raman          $71,900      ▼1       │
│          └──┘  Pod B                ████████░░            │
│                                                            │
│  🥉  3   ┌──┐  Dan Whitfield        $68,400      —        │
│          └──┘  Pod A                ███████░░░            │
│                                                            │
│      4   ┌──┐  Sarah Boyd           $52,100      ▲3       │
│          └──┘  Pod B                █████░░░░░            │
│  ─────────────────────────────────────────────────────── │
│  ▸  7   ┌──┐  You                   $38,900      ▲1       │
│          └──┘  Pod A                ████░░░░░░            │
└───────────────────────────────────────────────────────────┘
```

Design decisions:

- **Bars are relative to the leader**, giving instant proportional context. Absolute values alone don't communicate the gap.
- **The viewer's own row is always pinned** at the bottom if they're outside the display limit, with a separator. Being 14th on a top-10 board and seeing nothing about yourself is the fastest way to make someone stop opening the page.
- **Movement indicators** (▲▼—) do more for engagement than the ranking itself, because they give people who aren't in the top 3 something to react to.
- **Medals for top 3 only.** Beyond that, plain numbers — over-decorating flattens the hierarchy.
- **Refresh timestamp is always visible.** People immediately ask "is this current?" and the answer must be on screen.

### TV / display mode

A distinct route (`/display/:id`) designed for a screen 15 feet away with nobody interacting with it.

- No navigation, no chrome, no scrollbars
- Much larger type; readable at distance
- Auto-refresh on a fixed interval (default 30s)
- Auto-rotation through multiple boards if several are TV-enabled (configurable dwell time)
- Organization logo and accent color
- Optional: full-screen celebration overlay when someone hits a goal (Phase 2)
- Survives network interruption — keeps showing last known data with a stale indicator rather than an error page

Accessed by a `viewer` account, or via a signed display URL so an office TV doesn't need someone to log in after every reboot. That URL grants access to nothing but the flagged boards.

### Empty and degenerate states

Genuinely important, because early deployments hit them constantly:

- **No data yet** — explain how to get data in, with a link to manual entry or import. Never a blank table.
- **Fewer than 3 entities** — render as a simple list without medals; a "leaderboard" of two people looks broken.
- **Everyone at zero** — say so plainly rather than showing an arbitrary alphabetical order that looks like a ranking.

## Permissions

Visibility is checked before the scope filter is applied — see [05-roles-and-permissions.md](05-roles-and-permissions.md).

The deliberate exception: an `org`-visible leaderboard is viewable by an `agent` even though it exposes colleagues' numbers. That's the entire point of a leaderboard. The control is that a manager or admin chose to publish it. What an agent still can't do is open another agent's detail page or raw metric history.

## Performance

- The aggregation query is covered by `idx_fact_leaderboard`.
- The API caches computed results briefly (default 30s), keyed by config + period + resolved scope. A TV polling every 15s and 20 people watching the same board all hit one computation.
- Materialized views come later, only for boards that measurably need them. Don't build them preemptively.

## API surface

```
GET    /api/leaderboards                  saved boards visible to the requester
POST   /api/leaderboards
GET    /api/leaderboards/{id}             config
GET    /api/leaderboards/{id}/results     ?period_anchor= — the actual rankings
PATCH  /api/leaderboards/{id}
DELETE /api/leaderboards/{id}
POST   /api/leaderboards/{id}/archive

POST   /api/leaderboards/preview          run an unsaved config (live builder preview)

GET    /api/display/{token}               signed TV access, no session required
```

`POST /api/leaderboards/preview` lets the builder show real results as options change, which makes configuration self-explanatory instead of guesswork.

Results response shape:

```json
{
  "leaderboard_id": 12,
  "period": { "start": "2026-08-01", "end": "2026-08-31", "label": "August 2026" },
  "metric": { "name": "Revenue Closed", "unit": "currency", "decimal_places": 0 },
  "computed_at": "2026-08-12T14:32:00Z",
  "entries": [
    { "rank": 1, "entity_id": 8, "name": "Marcus Chen", "team_name": "Pod A",
      "avatar_url": "...", "score": "84200.0000", "movement": 2,
      "goal_attainment_percent": 168.4 }
  ],
  "viewer_entry": { "rank": 7, "entity_id": 42, "score": "38900.0000", "movement": 1 }
}
```

`viewer_entry` is returned separately so the client can pin it without searching the list or requesting more rows than it displays.

## Open questions

1. **Anonymous / bottom-half hiding** — some orgs want to show only the top N and hide the rest to avoid publicly shaming low performers. Worth an org setting? *Leaning: yes — `hide_below_rank`, still showing the viewer their own position privately.*
2. **Should agents create their own private leaderboards?** Useful for self-tracking. *Leaning: yes, `private` visibility, low cost.*
3. **Historical snapshots** — should end-of-period standings be frozen into a table so "who won July" is permanent even if data is later corrected? *Leaning: yes for competitions (already planned), optional for leaderboards.*
4. **Refresh interval** — 30s default for TV. Too aggressive for a large deployment?

## Related docs

- [06-metrics-engine.md](06-metrics-engine.md)
- [09-competitions.md](09-competitions.md)
- [12-design-system.md](12-design-system.md)


## Wall displays — built

A `display` row is a screen authenticated by its URL. `GET /api/display/{token}`
returns one channel — every board marked for display that applies to it —
without a session.

**The URL is the entire credential.** Anyone who photographs the address bar
has the board. What makes that acceptable is how little it reaches: one
channel, read-only, and nothing else. Presenting it as a session cookie returns
401 everywhere.

**Only org-visible boards are eligible**, enforced by a CHECK constraint as
well as the API. A wall screen has no audience control — anyone walking past
reads it — so it must never show something its audience could not see by
signing in.

**Stored readably, and listed beside the screen it belongs to.** The one
credential here that is not hashed, because a TV is set up days later by
whoever is standing next to it — an unrecoverable link just moves the URL into
a note somewhere less protected. Affordable because the token grants one
channel, read-only, of boards already published to everyone, and only an admin
can list them.

**Revocation is immediate** and the row survives, because the question after a
screen goes missing is "what did it have access to".

**`last_seen_at`, throttled to five minutes**, tells a live screen from one
unplugged months ago without a database write every few seconds per screen.

### The page

Runs unattended for months on a TV nobody can reach, so it never shows an error
to a room: a failed poll keeps the last good board with a quiet "Reconnecting…"
rather than replacing a leaderboard with a stack trace. Only a revoked token
replaces the screen, because frozen-forever is worse than saying so. Rotation
is automatic, type is large, and the slide indicator is dots rather than "3 of
7" — a counter is unreadable from across a room.
