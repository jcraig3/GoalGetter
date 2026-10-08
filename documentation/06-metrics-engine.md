# Metrics Engine

**Phase 1.** The machinery that turns raw events into the numbers everything else displays.

## The idea

A **metric definition** is what a company decided to measure. A **metric fact** is one measurable event. A **score** is facts aggregated over a scope and a time window.

```
metric_definition          metric_fact                    score
"Calls Made"       +       10,000 individual calls    =   "Jayden: 214 this month"
(config)                   (raw events)                   (computed on demand)
```

Nothing stores an agent's current total. Totals are always derived. See [Why nothing is precomputed](#why-scores-are-computed-not-stored).

## Metric definitions — built

Implemented in [`api/app/models/metric_definition.py`](../api/app/models/metric_definition.py) and [`api/app/routers/metrics.py`](../api/app/routers/metrics.py).

| Field | Purpose |
|---|---|
| `key` | Stable machine identifier (`calls_made`). Never changes; connectors map to it. |
| `name` | Human label (`Calls Made`). Freely editable. |
| `unit` | `count` · `currency` · `percent` · `duration` — drives formatting |
| `aggregation` | `sum` · `count` · `avg` · `max` · `min` · `last` |
| `direction` | `higher_is_better` or `lower_is_better` |
| `decimal_places` | Display precision |

**`direction` is not cosmetic.** "Calls Made" ranks descending; "Average Response Time" ranks ascending. Every ranking and goal-progress calculation reads it. Assuming "bigger is better" anywhere in the engine produces a leaderboard that celebrates the worst performer.

**`aggregation` semantics:**

- `sum` — add the values. Revenue, calls, deals.
- `count` — count the rows, ignore values. Useful when facts are events with no meaningful magnitude.
- `avg` — mean of values. Deal size, satisfaction score.
- `max` / `min` — largest/smallest single value. "Biggest deal closed."
- `last` — most recent value by `occurred_at`. For state-like metrics — pipeline size, current quota attainment — where facts are snapshots rather than events.

`last` exists because some source data is a running total rather than an increment. Summing snapshots produces nonsense; this is a common and painful integration bug, so the engine handles it explicitly rather than expecting connectors to diff.

**`key` is immutable after creation.** Connectors, saved import mappings, and goals all address a metric by key; renaming it would break every one of them silently. `PATCH` rejects a `key` field with 422 rather than ignoring it, so a client is never told it renamed something it did not. `name` is the freely editable label.

**Archive rather than delete.** Facts reference the definition, and a leaderboard for last quarter must still be able to name the metric it ranked. Delete exists for one case: a metric created by mistake.

### Seeded defaults

A fresh install ships with common metrics, active but editable, so a new deployment has something to do immediately instead of facing an empty configuration screen:

`calls_made` · `emails_sent` · `meetings_booked` · `meetings_held` · `deals_created` · `deals_won` · `revenue_closed` · `demos_completed`

`revenue_closed` is the only one with decimals (2). Money is the number people check most closely, and a revenue board rounding to whole units invites "that's not my figure".

**Seeded when an organization is created — not by a migration.** Migrations are structural and must behave identically forever; business defaults change as the product learns what teams actually track. `POST /api/metrics/seed-defaults` is the recovery path for an organization that cleared them out, and how an existing deployment picks up defaults added in a later release.

The seeder matches on **key**, so a metric renamed to "Dials" keeps its name when re-seeded. A key that is absent is added back — which is what "restore defaults" should do. To opt out of a default permanently, archive it: the key still exists, so the seeder skips it.

## Metric facts — built

Implemented in [`api/app/models/metric_fact.py`](../api/app/models/metric_fact.py).

One row per event. Written by a connector, or by an audited admin correction.

> **CSV/Excel import was dropped**, and this line described it until the end of
> Phase 3. The reasoning: numbers a person uploads by hand are wrong by lunchtime,
> and a spreadsheet somebody maintains alongside the real system is a second source
> of truth that quietly disagrees with the first. A spreadsheet that is *genuinely*
> the system of record is still supported — as a **live** Google Sheets or Excel
> connector, which re-reads it rather than snapshotting it.

The important fields and why they exist are documented in [02-data-model.md](02-data-model.md). The three that shape the engine:

- **`occurred_at`** — when the event happened in the real world, *not* when it was imported. All time bucketing uses this. Getting it from the import timestamp instead would put a backfilled month of history into today.
- **`subject_team_id`** — the team snapshot at event time, so historical leaderboards don't change when people transfer.
- **`external_id`** — the source system's ID, making re-syncs idempotent.

### Timezone handling

This is the single most common source of "the numbers are wrong" complaints.

`occurred_at` is stored as `TIMESTAMPTZ` in UTC. Every query that buckets by day/week/month converts to the **organization's** timezone first:

```sql
date_trunc('day', occurred_at AT TIME ZONE :org_timezone)
```

Not the server's timezone and not the viewer's. A daily leaderboard has to mean the same thing to an agent in Phoenix and their manager in New York, or two people looking at the same screen see different numbers.

## Aggregation — built

Implemented in [`api/app/aggregate.py`](../api/app/aggregate.py) and [`api/app/periods.py`](../api/app/periods.py).

The central query. Everything — leaderboards, goal progress, dashboard tiles, competition standings — is a variation on it.

```sql
SELECT
    f.subject_user_id,
    SUM(f.value) AS score          -- swapped per metric aggregation
FROM metric_fact f
WHERE f.organization_id = :org_id
  AND f.metric_definition_id = :metric_id
  AND f.occurred_at >= :period_start
  AND f.occurred_at <  :period_end
  AND f.subject_user_id = ANY(:visible_user_ids)   -- permission scope
GROUP BY f.subject_user_id;
```

Note the permission scope is **in the query**, not applied to the results. See [05-roles-and-permissions.md](05-roles-and-permissions.md).

### Ranking

Ranking happens in the database with a window function:

```sql
WITH scores AS (
    SELECT subject_user_id, SUM(value) AS score
    FROM metric_fact
    WHERE ...
    GROUP BY subject_user_id
)
SELECT
    subject_user_id,
    score,
    RANK() OVER (ORDER BY score DESC) AS rank
FROM scores
ORDER BY rank;
```

**Why in SQL rather than sorting in Python:** the database is already holding the aggregated rows, so ranking is free there. Pulling every agent's score into the app to sort means transferring the whole set and re-implementing tie handling. It also composes — `RANK() OVER (PARTITION BY team_id ORDER BY score DESC)` gives per-team ranks in the same pass.

`ORDER BY score DESC` flips to `ASC` when the metric's `direction` is `lower_is_better`.

**Tie handling:** `RANK()` gives `1, 2, 2, 4` — two people tied for 2nd, nobody is 3rd. That matches how sales contests actually work, and it's the honest default. `DENSE_RANK()` (`1, 2, 2, 3`) is available per leaderboard config.

### Team aggregation

Two genuinely different questions, and the UI must be explicit about which:

- **Team total** — `SUM` of everything the team's members produced. Rewards headcount.
- **Team average per member** — total ÷ active member count. Lets a 4-person team compete fairly with a 12-person team.

Teams are flat, so a team total is one `GROUP BY subject_team_id` — no recursion, no `include_subteams` flag.

Facts belonging to people on no team are **excluded** from a team grouping rather than collected under a NULL row: "unassigned" is not a team and must not appear as one. Those people still rank on the per-person board, and `total` applies the same exclusion so the parts add up to the whole.

*Team average per member is not built yet* — it arrives with leaderboard configuration in 1f, where the UI can make the choice between total and per-member explicit.

### Over time — built

`aggregate.series()` is the same query with one more `GROUP BY`: a value per
day or per month rather than per person. It is in the same module and built
from the same filters deliberately — a sparkline that ended somewhere other
than the total printed beside it would be worse than no sparkline.

**Buckets are whole days or whole months in the organization's timezone**, via
`date_trunc(unit, occurred_at, tz)`. There is no week bucket: Postgres always
starts a `date_trunc('week')` on Monday, an organization can start its week on
Sunday, and a bucket that disagreed with every weekly period in the product
would do so invisibly.

**Every bucket in the period is returned, not just the ones with facts.** The
query alone returns only the days something happened, and a chart built from
that closes the quiet days up — turning stop-start work into a steady line.

**What an empty bucket means is decided by the aggregation:**

| aggregation      | empty bucket       | reasoning                              |
| ---------------- | ------------------ | -------------------------------------- |
| `sum`, `count`   | zero               | nobody made a call                     |
| `avg, max, min`  | unknown, a gap     | the average of no responses is not 0   |
| `last`           | the previous value | a snapshot persists until it changes   |

Zero-filling an average draws a daily collapse that never happened; zero-filling
a `last` metric shows the pipeline emptying every night.

**`running_total()` turns per-bucket values into the cumulative line**, and is
only meaningful for `sum` and `count` — the same distinction `pace` draws.
Callers check the aggregation themselves rather than it being applied
automatically, because a running total of daily averages is not a number.

## Why scores are computed, not stored

There is no `current_total` column anywhere. Tempting, and wrong:

- **Late-arriving data.** A connector syncs yesterday's deals today. A stored total would already be wrong and would need invalidation logic everywhere.
- **Corrections.** Deleting a mistaken manual entry has to reduce the total. Every mutation path would need to remember to decrement.
- **Arbitrary windows.** Users ask for "this week," "last quarter," "since the competition started." A stored total answers exactly one of those.

The rule: **`metric_fact` is the only truth. Everything else is a query over it.**

Caching is real, but it happens at a layer where it can be invalidated wholesale rather than incrementally.

## Performance

Expected worst case at MVP scale: 500 users × ~50 facts/day ≈ 9M rows/year. Postgres handles the aggregation query comfortably at that size with the right indexes, so the plan is deliberately simple.

**1. Indexes** — the covering index carries the common query:

```sql
CREATE INDEX ix_metric_fact_leaderboard
    ON metric_fact (organization_id, metric_definition_id, occurred_at, subject_user_id)
    INCLUDE (value);
```

**`INCLUDE (value)` is what makes it covering**, and it is not optional.
Nobody filters or sorts by `value`, but the aggregation reads it — and without
it every matching row costs a random heap fetch. Measured at 4M facts:

| | Time |
|---|---|
| Without `INCLUDE (value)` | 7,423 ms |
| With it, before VACUUM | 2,116 ms |
| With it, after VACUUM | **12 ms** |

The Index Only Scan also needs a current visibility map, which autovacuum
maintains. A freshly bulk-loaded table does not have one — worth knowing after
an import or a restore, when the first queries will be slow for reasons that
have nothing to do with the query.

**1b. The other access pattern: one subject, over time.** A leaderboard asks
"everyone, in this window" and wants the index led by time. A sparkline asks
"one subject, across this window" and wants it led by the subject. One index
cannot be good at both, so there are three narrow ones beside the covering
board index:

```sql
CREATE INDEX ix_metric_fact_subject_time ON metric_fact (subject_user_id, occurred_at);
CREATE INDEX ix_metric_fact_office_time  ON metric_fact (subject_office_id, occurred_at);
CREATE INDEX ix_metric_fact_team_time    ON metric_fact (subject_team_id, occurred_at);
```

The team one arrived last, with sparklines, because nothing had ever asked for
a single team's line. Measured at 4M facts: a year-long team chart went from
**1,677 ms to 31 ms**, and a monthly one from 148 ms to 3.9 ms.

They are deliberately *not* covering. A covering team index measured 18 ms
against this one's 31 ms for nearly double the size — not a trade worth making
on the busiest table here, for the rarest chart in the product.

**A benchmark is a claim about a schema.** The first version of that change
also added a covering index for the *person* case, on a measurement showing
1,393 ms to 3.5 ms. That benchmark ran against a table carrying only the board
index, which is not the table this product has — `ix_metric_fact_subject_time`
was already doing the job at 8.6 ms. The speedup was real and entirely
redundant. Measure the schema you have.

**2. Partition pruning** — monthly partitions on `occurred_at` mean "this month" reads one partition regardless of total history. **Not built.** At current scale the index above answers a month's leaderboard by reading 52 rows; partitioning an empty table defends against a problem we cannot yet measure.

**3. Materialized views for hot boards** — **not built, and measured as unnecessary.** At 4M facts a board resolves end-to-end in ~35ms including the movement comparison. A cache would hide a fixable index problem behind an invalidation strategy and every stale-data bug that comes with one. Revisit if a real deployment shows a real number. The original plan follows, for when it does:

```sql
CREATE MATERIALIZED VIEW mv_leaderboard_current_month AS ...;
REFRESH MATERIALIZED VIEW CONCURRENTLY mv_leaderboard_current_month;
```

Refreshed on a schedule by APScheduler. `CONCURRENTLY` means readers aren't blocked during refresh — without it, the TV goes blank each cycle.

> **Build these in this order, and only as far as needed.** Indexes first. Add partitioning when the table gets large. Add materialized views only when a real query is measurably slow. Optimizing before there's data produces complexity that defends against a problem you don't have.

## Data entry

**Policy: production metric data comes from integrations, not from people typing.** Hand-keyed numbers are slow, error-prone, and gameable, and a leaderboard nobody believes is worthless. Connectors ([15-data-integrations.md](15-data-integrations.md)) are the intended path for real deployments.

Three ways data can enter, in descending order of preference:

| Path | Phase | Status |
|---|---|---|
| **Connectors** — sixteen of them | 3 | Built. The only production path |
| **Admin correction / backfill** | 1 | Narrow tool for fixing bad rows, not a workflow |
| ~~CSV / Excel import~~ | — | **Dropped.** A live spreadsheet connector replaced it |

**Agent self-reporting is not built.** Agents have no write path to `metric_fact` at all — it isn't a permission toggle, the endpoints simply reject them. See [05-roles-and-permissions.md](05-roles-and-permissions.md).

### CSV / Excel import — the Phase 1 workhorse

This is a genuine integration, not manual entry. An admin exports from whatever system they have and uploads it; mapping is saved and reused. It's how a business gets real value before any connector exists, and it's the fallback that keeps every deployment viable.

```
Upload → parse → preview + column mapping → validate → confirm → import
```

Mapping maps each spreadsheet column to a metric, the user identifier, and the date column. Mappings are saved per file shape so a recurring weekly upload doesn't get remapped every time.

Validation happens **before** anything is written, and reports all problems at once — unmatched users, unparseable dates, non-numeric values, duplicates against existing facts. A partial import that half-succeeds is worse than one that cleanly refuses.

User matching is by email first, then exact full-name match. Unmatched rows are listed for manual mapping rather than silently dropped. **Silently dropping rows is the worst possible failure here** — the import looks successful and the numbers are quietly incomplete.

Imports are recorded as a batch so a bad one can be rolled back in full.

### Admin correction — built

A narrow tool: pick a metric, person, value, and date, or edit/delete an existing entry. Lives at `/corrections`, linked from the Metrics page rather than sitting in the sidebar.

It exists because **synced data is sometimes wrong**, and a number pulled from Snowflake that nobody can fix is worse than no number at all. Without a correction path, the only remedy is fixing the source system and waiting for the next sync — which may be impossible if the source is a closed period.

Constraints that keep it from becoming a back door:

- **Admin and manager only**, scoped by `visible_user_ids()`. Agents have no write path at all — the endpoints reject them, rather than a permission being switched off.
- Every entry, edit, and deletion writes an `audit_log` row **in the same transaction**, so a change cannot be applied without being recorded.
- Facts written this way carry `source_type = 'manual'` and are **visibly marked in the UI** wherever they appear. `source_type` is not an accepted request field — the endpoint sets it, so a caller cannot label a hand-typed number as connector data.
- Corrections to a fact that came from a connector set `corrected_at` / `corrected_by_user_id`, so the next sync doesn't silently overwrite them. The row keeps its original `source_type`, so "edited by hand" stays distinguishable from "entered by hand".

**Dates are bounded**: two days into the future (a fact recorded in Sydney is already "tomorrow" on a UTC server) and five years back (backfilling before a connector exists is legitimate). A typo'd year would otherwise sit somewhere nobody looks and inflate a yearly total.

**Deletion is a hard delete.** A `deleted_at` column would mean every aggregation query needs a filter somebody eventually forgets, silently resurrecting deleted numbers. The audit row carries the metric, person, value, and date, so the deletion is fully reconstructable — which is the only reason a hard delete is acceptable here. without warning

### Development seed data — built

    docker compose exec api python -m app.seed_demo --days 120
    docker compose exec api python -m app.seed_demo --clear

Generates several months of realistic facts for the agents that already exist.

This exists because Phase 1 builds goals, leaderboards, and dashboards *before* any connector exists. Without generated data there's nothing to build those features against, and nothing to demo the tool with. It's also how the aggregation and ranking queries get tested at realistic row counts. Development and evaluation only; never enabled in a production deployment.

## API surface

```
GET    /api/metrics                          definitions
POST   /api/metrics                          admin only
PATCH  /api/metrics/{id}
POST   /api/metrics/{id}/archive

POST   /api/metric-facts                     admin correction (single)
GET    /api/metric-facts                     ?metric&user&team&from&to (scoped)
PATCH  /api/metric-facts/{id}
DELETE /api/metric-facts/{id}

POST   /api/imports/upload                   returns parsed preview + inferred mapping
POST   /api/imports/{id}/validate            dry run, returns all issues
POST   /api/imports/{id}/commit
GET    /api/imports                          history
POST   /api/imports/{id}/rollback

POST   /api/metrics/query                    the general aggregation endpoint
```

`POST /api/metrics/query` (POST because the filter body is structured) is the single endpoint behind leaderboards, dashboards, and goal progress:

```json
{
  "metric_id": 4,
  "group_by": "user",
  "period": { "type": "month", "anchor": "2026-08-01" },
  "scope": { "type": "team", "team_id": 7, "include_subteams": true },
  "rank": true
}
```

One well-tested aggregation path instead of three that drift apart.

## Derived metrics — built

A metric with aggregation `ratio` divides one metric by another — close rate is
deals won ÷ deals created. It has **no facts of its own**: every figure is
worked out from its two parts inside `aggregate.py`, the one query behind every
board, goal and competition, so a close-rate leaderboard is scoped, snapshotted
and ranked exactly like a calls one, with nothing stored to go stale.

- **A ratio of totals, never an average of ratios.** Each part is aggregated
  its own way over the same rows and scope, then divided. A team's rate is the
  team's wins over its deals; the company figure is everybody's over everybody's.
- **No denominator, no rate.** Somebody with no deals is off the board rather
  than bottom of it at 0%; somebody with deals and no wins is 0%.
- **A percent reads as a percent**: unit `percent` multiplies by 100.
- **Per bucket on a chart**, so the line ends at the printed figure; a bucket
  with nothing to divide by is a gap. Not paced — like an average, a rate has no
  honest "should be here by now".
- **One level only**: a ratio's parts must be recorded metrics, not other
  ratios. A part cannot be deleted while a ratio uses it, and a metric that
  already has data cannot become a ratio.
- **Nothing is recorded against one.** Manual entry, source mappings and
  achievement rules refuse a derived metric, and their pickers leave it out.
  Competitions count the denominator's facts for a participation floor and
  either part's latest fact for "earliest to reach".

## Open questions

1. **Derived metrics** (`close_rate = deals_won / deals_created`) — **built.** See "Derived metrics" below.
2. **Metric weighting / composite scores** — a "points" metric combining several weighted metrics. Related to Phase 4 gamification. *Leaning: defer.*
3. **Backdating limits** — should there be a cutoff beyond which facts can't be entered or edited, to stop last quarter's closed numbers from moving? *Leaning: yes, an org setting defaulting to open, with an audit trail regardless.*

## Related docs

- [02-data-model.md](02-data-model.md)
- [07-goals-and-targets.md](07-goals-and-targets.md)
- [08-leaderboards.md](08-leaderboards.md)
- [15-data-integrations.md](15-data-integrations.md)
