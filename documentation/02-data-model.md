# Data Model

The schema is the spine of the product. Everything else is a view onto it.

## Entity map

```
organization
    │
    ├── team ◀──── user_account.team_id
    │                     │
    ├── metric_definition                │
    │      │                             │
    │      └── metric_fact ──────────────┘   (who gets credit)
    │
    ├── goal ──── goal_assignment (user | team | org)
    │
    ├── leaderboard (saved config)
    │
    ├── competition ──── competition_participant
    │
    ├── notification
    ├── audit_log
    │
    └── data_source ──── sync_run          (Phase 3)
```

## Conventions

- Primary keys are `BIGINT GENERATED ALWAYS AS IDENTITY`, except `metric_fact` (see below).
- Every table carries `organization_id`. One deployment is one company, but keeping the column means the tenancy boundary already exists if it's ever needed, and it makes every query explicitly scoped.
- Timestamps are `TIMESTAMPTZ`, always stored UTC. Display timezone is a per-organization setting.
- Money and metric values are `NUMERIC`, never `FLOAT`. Ranking people by revenue in floating point produces off-by-a-cent numbers, and someone always notices.
- Soft delete via `archived_at TIMESTAMPTZ NULL` on user-facing entities. Historical leaderboards must not break because a team was deleted.
- `created_at` / `updated_at` on everything.

---

## Core tables

### `organization`

The root record. Exactly one row in a normal deployment.

```sql
CREATE TABLE organization (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name            TEXT NOT NULL,
    slug            TEXT NOT NULL UNIQUE,
    timezone        TEXT NOT NULL DEFAULT 'UTC',
    week_starts_on  SMALLINT NOT NULL DEFAULT 1,   -- 1 = Monday
    fiscal_year_start_month SMALLINT NOT NULL DEFAULT 1,
    currency        TEXT NOT NULL DEFAULT 'USD',
    logo_url        TEXT,
    brand_color     TEXT,
    settings        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

`week_starts_on` and `fiscal_year_start_month` are load-bearing. "This week" and "this quarter" are the most common goal periods, and getting the boundary wrong silently corrupts every number in the product.

### `team`

Flat — teams do not nest.

```sql
CREATE TABLE team (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organization(id),
    name            TEXT NOT NULL,
    description     TEXT,
    color           TEXT,
    archived_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

An earlier design made this a self-referencing tree so a company could run
divisions → regions → teams → pods. It was simplified before anything depended
on it. The hierarchy carried four separate mechanisms — a recursive CTE, depth
tracking, cycle prevention, and an archive-with-children guard — in exchange for
structure a sales floor does not use: it has teams, and leaderboards compare
them directly.

If divisional rollups are ever wanted, a separate grouping is a smaller change
than reinstating a tree.

### `user_account`

```sql
CREATE TABLE user_account (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id     BIGINT NOT NULL REFERENCES organization(id),
    email               TEXT NOT NULL,
    full_name           TEXT NOT NULL,
    team_id             BIGINT REFERENCES team(id),      -- one team per agent
    org_role            TEXT NOT NULL DEFAULT 'agent',   -- admin|manager|agent
    password_hash       TEXT,                 -- NULL for SSO-only users
    external_subject_id TEXT,                 -- OIDC 'sub' claim
    status              TEXT NOT NULL DEFAULT 'invited', -- invited|active|suspended
    last_login_at       TIMESTAMPTZ,
    archived_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- UNIQUE index on (organization_id, lower(email))
);
```

Email uniqueness is case-insensitive, enforced by a functional unique index on
`(organization_id, lower(email))` rather than a `CITEXT` column — no extension
required, and the database still refuses to let `Jayden@x.com` and
`jayden@x.com` become two accounts.

`password_hash` is nullable and `external_subject_id` exists alongside it because a user may sign in either way. See [03-auth-and-users.md](03-auth-and-users.md).

### Team membership — a column, not a table

An agent belongs to **one team**, stored as `user_account.team_id`.

A join table would allow several teams per person, but then every leaderboard
has to answer *"does this person count twice?"* — and a sales floor puts someone
on one team. Adding a join table later is a contained change; unpicking one that
aggregations already depend on is not.

`team_id` is nullable, because *invited but not yet placed* is a real state — and
one worth surfacing, since an unassigned agent is silently missing from every
team leaderboard.

> **Historical accuracy comes from `metric_fact.subject_team_id`**, not from
> membership history. Each fact records the team the agent was on when the event
> happened, so moving someone between teams in June does not rewrite May's
> leaderboard.

---

## The metric layer

This is the part that makes the product work. Read [06-metrics-engine.md](06-metrics-engine.md) alongside it.

### `metric_definition`

What a company decides to measure. Configuration, not data.

```sql
CREATE TABLE metric_definition (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organization(id),
    key             TEXT NOT NULL,          -- 'calls_made', 'revenue_closed'
    name            TEXT NOT NULL,          -- 'Calls Made'
    description     TEXT,
    unit            TEXT NOT NULL DEFAULT 'count',  -- count|currency|percent|duration
    aggregation     TEXT NOT NULL DEFAULT 'sum',    -- sum|count|avg|max|min|last
    direction       TEXT NOT NULL DEFAULT 'higher_is_better',
    decimal_places  SMALLINT NOT NULL DEFAULT 0,
    icon            TEXT,
    color           TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    archived_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (organization_id, key)
);
```

`direction` matters: for "Calls Made" higher wins; for "Average Response Time" lower wins. Ranking must read this rather than assume descending.

### `metric_fact` — the big one

One row per measurable event. This table will hold millions of rows and is the reason Postgres was chosen.

```sql
CREATE TABLE metric_fact (
    id                   BIGINT GENERATED ALWAYS AS IDENTITY,
    organization_id      BIGINT NOT NULL,
    metric_definition_id BIGINT NOT NULL,
    subject_user_id      BIGINT NOT NULL,     -- who gets credit
    subject_team_id      BIGINT,              -- team at time of event (snapshot)
    value                NUMERIC(18,4) NOT NULL,
    occurred_at          TIMESTAMPTZ NOT NULL,
    source_type          TEXT NOT NULL,       -- manual|csv|connector
    data_source_id       BIGINT,              -- FK to data_source, NULL if manual
    external_id          TEXT,                -- dedupe key from the source system
    raw                  JSONB,               -- original source row
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, occurred_at)
) PARTITION BY RANGE (occurred_at);
```

Four decisions worth understanding:

**1. Partitioned by month on `occurred_at`.** Postgres stores each month in its own physical table. A query for "this quarter" reads three partitions and ignores the rest — this is called partition pruning and it's what keeps leaderboards fast as history grows. Retention becomes `DROP TABLE metric_fact_2024_01`, instant, instead of a `DELETE` that would thrash the table for an hour.

> The partition key must be in the primary key. That's why the PK is `(id, occurred_at)` — a Postgres requirement for partitioned tables, not a modeling choice.

**2. `subject_team_id` is a denormalized snapshot.** The team an agent was on *when the event happened*. If they transfer teams in June, May's leaderboard must not retroactively change. Reading `user_account.team_id` live would rewrite history every time someone moves.

**3. `external_id` + `data_source_id` make syncs idempotent.** A partial unique index means re-running a sync updates rows instead of duplicating them — which will happen constantly once connectors exist.

```sql
CREATE UNIQUE INDEX idx_fact_dedupe
    ON metric_fact (data_source_id, external_id, occurred_at)
    WHERE external_id IS NOT NULL;
```

**4. `raw JSONB` keeps the original row.** When a field mapping turns out wrong, the correct values can be re-derived from what was already pulled instead of re-syncing months of history from a warehouse.

Working indexes:

```sql
CREATE INDEX idx_fact_leaderboard
    ON metric_fact (organization_id, metric_definition_id, occurred_at, subject_user_id);
CREATE INDEX idx_fact_user
    ON metric_fact (subject_user_id, occurred_at);
```

---

## Goals

### `goal`

```sql
CREATE TABLE goal (
    id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id      BIGINT NOT NULL REFERENCES organization(id),
    metric_definition_id BIGINT NOT NULL REFERENCES metric_definition(id),
    name                 TEXT NOT NULL,
    description          TEXT,
    target_value         NUMERIC(18,4) NOT NULL,
    comparator           TEXT NOT NULL DEFAULT 'gte',  -- gte|lte
    period_type          TEXT NOT NULL,   -- daily|weekly|monthly|quarterly|yearly|custom
    period_start         DATE NOT NULL,
    period_end           DATE NOT NULL,
    recurrence           TEXT,            -- NULL = one-off, else matches period_type
    status               TEXT NOT NULL DEFAULT 'active', -- draft|active|completed|archived
    created_by_user_id   BIGINT NOT NULL REFERENCES user_account(id),
    archived_at          TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### `goal_assignment`

Separating assignment from the goal lets one goal ("Close $50k this month") apply to fifteen agents without fifteen goal records to keep in sync.

```sql
CREATE TABLE goal_assignment (
    id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    goal_id       BIGINT NOT NULL REFERENCES goal(id) ON DELETE CASCADE,
    scope_type    TEXT NOT NULL,          -- user|team|organization
    user_id       BIGINT REFERENCES user_account(id),
    team_id       BIGINT REFERENCES team(id),
    target_override NUMERIC(18,4),        -- per-assignee target if different
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (
        (scope_type = 'user'         AND user_id IS NOT NULL AND team_id IS NULL) OR
        (scope_type = 'team'         AND team_id IS NOT NULL AND user_id IS NULL) OR
        (scope_type = 'organization' AND user_id IS NULL     AND team_id IS NULL)
    )
);
```

The `CHECK` constraint makes an invalid assignment impossible to store. Cheap to write, and it prevents a whole category of bug where application code forgets a case.

**Progress is computed, not stored.** Aggregating `metric_fact` over the goal's period is the single source of truth. A cached `current_value` column would drift the moment a late-arriving fact or a corrected sync landed. Caching happens at the materialized-view layer, where it can be refreshed wholesale — see [07-goals-and-targets.md](07-goals-and-targets.md).

---

## Leaderboards and competitions

### `leaderboard`

A saved configuration, not stored results.

```sql
CREATE TABLE leaderboard (
    id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id      BIGINT NOT NULL REFERENCES organization(id),
    name                 TEXT NOT NULL,
    metric_definition_id BIGINT NOT NULL REFERENCES metric_definition(id),
    scope_type           TEXT NOT NULL,   -- organization|team|custom
    scope_team_id        BIGINT REFERENCES team(id),
    include_subteams     BOOLEAN NOT NULL DEFAULT true,
    entity_type          TEXT NOT NULL DEFAULT 'user',  -- user|team
    period_type          TEXT NOT NULL,
    display_limit        SMALLINT DEFAULT 10,
    visibility           TEXT NOT NULL DEFAULT 'org',   -- org|team|private
    is_tv_enabled        BOOLEAN NOT NULL DEFAULT false,
    config               JSONB NOT NULL DEFAULT '{}',
    created_by_user_id   BIGINT NOT NULL REFERENCES user_account(id),
    archived_at          TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### `competition` / `competition_participant`

Phase 2. Detailed in [09-competitions.md](09-competitions.md).

```sql
CREATE TABLE competition (
    id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id      BIGINT NOT NULL REFERENCES organization(id),
    name                 TEXT NOT NULL,
    description          TEXT,
    metric_definition_id BIGINT NOT NULL REFERENCES metric_definition(id),
    format               TEXT NOT NULL,   -- individual|team|head_to_head
    starts_at            TIMESTAMPTZ NOT NULL,
    ends_at              TIMESTAMPTZ NOT NULL,
    status               TEXT NOT NULL DEFAULT 'draft',
    prize_description    TEXT,
    created_by_user_id   BIGINT NOT NULL REFERENCES user_account(id),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE competition_participant (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    competition_id BIGINT NOT NULL REFERENCES competition(id) ON DELETE CASCADE,
    user_id        BIGINT REFERENCES user_account(id),
    team_id        BIGINT REFERENCES team(id),
    final_rank     SMALLINT,
    final_value    NUMERIC(18,4)
);
```

`final_rank` and `final_value` are written once when a competition closes. Unlike live goal progress, a finished competition's result is frozen history and must never be recomputed — a late-arriving fact should not change who won last month's contest.

---

## Supporting tables

### `notification`

```sql
CREATE TABLE notification (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organization(id),
    user_id         BIGINT NOT NULL REFERENCES user_account(id) ON DELETE CASCADE,
    type            TEXT NOT NULL,   -- goal_hit|rank_change|competition_start|...
    title           TEXT NOT NULL,
    body            TEXT,
    link_url        TEXT,
    payload         JSONB NOT NULL DEFAULT '{}',
    read_at         TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_notification_unread
    ON notification (user_id, created_at DESC) WHERE read_at IS NULL;
```

A **partial index** — it only indexes unread rows. The unread badge query is the hot path and it stays fast forever, because the index never grows past the number of genuinely unread notifications.

### `audit_log` — built

Who changed what. Required for trust: if a leaderboard changes, someone must be able to find out why.

```sql
CREATE TABLE audit_log (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organization(id) ON DELETE CASCADE,

    -- SET NULL, not CASCADE: if the actor's account is removed, the record of
    -- what they did must outlive them.
    actor_user_id   BIGINT REFERENCES user_account(id) ON DELETE SET NULL,
    actor_email     VARCHAR(320),      -- frozen copy; see below

    action          VARCHAR(64) NOT NULL,   -- user.role_changed, user.suspended, ...

    target_user_id  BIGINT REFERENCES user_account(id) ON DELETE SET NULL,
    target_email    VARCHAR(320),

    details         JSONB,             -- {"org_role": {"from": "agent", "to": "admin"}}
    ip_address      INET,
    occurred_at     TIMESTAMPTZ NOT NULL
);

CREATE INDEX ix_audit_log_org_time    ON audit_log (organization_id, occurred_at);
CREATE INDEX ix_audit_log_target_time ON audit_log (target_user_id, occurred_at);
```

**Emails are denormalised copies, frozen at the time of the action.** Joining to
`user_account` at read time would let a rename silently rewrite history, and a
deleted account would blank out rows that are the whole point of the table.

**One `details` JSONB rather than a column per field.** The shape differs per
action, and a table with thirty mostly-null columns is harder to read than one
that says exactly what happened. It is queried rarely, so the flexibility costs
nothing. It must never contain a password, token, or client secret — every admin
can read this table.

**`occurred_at` has no `DEFAULT now()`.** The application supplies it, so the
timestamp is the moment the action was decided rather than the moment the
transaction happened to flush.

**Both indexes lead with the filter and trail with the time**, matching the two
ways the table is read: an organization's recent activity, and everything ever
done to one person. Both are time-ordered.

### `metric_definition` / `metric_fact` — built

See [06-metrics-engine.md](06-metrics-engine.md). Three schema decisions worth
repeating here:

**`value NUMERIC(18,4)`, never `DOUBLE PRECISION`.** Binary floating point
cannot represent 0.1 exactly, so summing currency drifts.

**`subject_team_id` and `subject_office_id` are snapshots**, copied at write
time rather than joined live. Moving one agent between teams was measured to
shift 563 historical facts when joined live, and none when read from the
snapshot. Office needed its own column for the same reason — it was reachable
only through `team.office_id`, which is current state, so a team changing office
would have moved 2,649 facts between offices.

Every grouping key a leaderboard can use is therefore a column on `metric_fact`,
never a join to live structure.

**Partial unique index** on `(organization_id, metric_definition_id,
external_id) WHERE external_id IS NOT NULL` — idempotent connector re-syncs,
without constraining manual entries that have no external id.

**`corrected_at` / `corrected_by_user_id`** mark a row a person has written or
edited. A column rather than a derivation from `audit_log`, because the
connector sync must check it per row, and because it cannot be added
retroactively — a correction made before the column existed is
indistinguishable afterwards.

### `session`

Server-side sessions. See [03-auth-and-users.md](03-auth-and-users.md).

```sql
CREATE TABLE session (
    id            TEXT PRIMARY KEY,        -- opaque random token
    user_id       BIGINT NOT NULL REFERENCES user_account(id) ON DELETE CASCADE,
    expires_at    TIMESTAMPTZ NOT NULL,
    ip_address    INET,
    user_agent    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### `data_source` / `sync_run` — Phase 3

Defined in [15-data-integrations.md](15-data-integrations.md). Stubbed here so the shape is visible early:

```sql
CREATE TABLE data_source (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id BIGINT NOT NULL REFERENCES organization(id),
    connector_key   TEXT NOT NULL,        -- google_sheets|snowflake|sql|csv|...
    name            TEXT NOT NULL,
    config          JSONB NOT NULL,       -- non-secret connection settings
    credentials_ref TEXT,                 -- pointer to encrypted secret storage
    field_mapping   JSONB NOT NULL,       -- source column → metric/user/date
    sync_schedule   TEXT,                 -- cron expression
    status          TEXT NOT NULL DEFAULT 'inactive',
    last_sync_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Credentials are never stored in `config`. See [17-security.md](17-security.md).

---

## Open questions

Flagged for discussion before implementation:

1. **How is a manager tied to a team?** Today a manager has `org_role = 'manager'` and a `team_id` like anyone else, so "their team" is simply the one they belong to. That works for one manager per team. If a team ever needs two managers, or a manager over several teams, this needs an explicit link — decide when the case actually appears.
2. **Goal recurrence** — when a monthly goal recurs, does it spawn a new `goal` row each period, or does one row with a recurrence rule get evaluated per period? Spawning is easier to reason about and lets a single month be edited; a rule is less clutter.
3. **Metric hierarchies** — should a metric be able to derive from others (e.g. `close_rate = deals_won / deals_created`)? Powerful, but a meaningful jump in engine complexity. Recommend deferring past v1.

## Related docs

- [06-metrics-engine.md](06-metrics-engine.md) — how facts become scores
- [07-goals-and-targets.md](07-goals-and-targets.md)
- [08-leaderboards.md](08-leaderboards.md)
- [05-roles-and-permissions.md](05-roles-and-permissions.md)
