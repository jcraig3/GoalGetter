# Architecture

## Stack

| Layer | Choice | Why |
|---|---|---|
| Frontend | React 19 + TypeScript + Vite 8 | Data-dense UI needs the biggest component ecosystem. Vite for fast rebuilds, no framework magic. |
| Styling | Tailwind CSS 4 | Utility classes keep styling local to components. Colors map to CSS custom properties, so theming needs no `dark:` variants. |
| Backend | Python 3.13 + FastAPI | Auto-generates OpenAPI → typed TS client. Pydantic validates dirty inbound data at the edge. Readable. |
| ORM | SQLAlchemy 2.0 | Also the engine behind the "connect any SQL database" connector — one interface, many dialects. |
| Migrations | Alembic | Versioned, reversible. Required for safe self-hosted upgrades. |
| Database | PostgreSQL 18 | Window functions, recursive CTEs, partitioning, JSONB, materialized views, exact NUMERIC. See below. |
| Scheduling | APScheduler (in-process) | Sync jobs with retries and no message broker. |
| Auth | bcrypt · Authlib *(OIDC, planned)* | Local accounts and OIDC behind one interface. Sessions are database rows, not JWTs, so access can be revoked instantly. |
| Packaging | Docker Compose | nginx, api, postgres, db-backup, Caddy for HTTPS and cloudflared for a tunnel, plus a dev-only build watcher. `docker compose up` and it runs. |

### Why Postgres specifically

GoalGetter is **two workloads in one database**:

- **Transactional** — users, teams, goals, connector configs. Small, relational, frequently updated.
- **Analytical** — metric facts. Millions of append-mostly rows, aggregated over date ranges and ranked.

Most databases are good at one. Postgres is the best single system at doing both acceptably, which means shipping one database instead of two. The features that carry the product:

- **Window functions** — a leaderboard *is* `RANK() OVER (PARTITION BY team_id ORDER BY score DESC)`. Ties, dense ranks, and "moved up 3 places" via `LAG()` all happen in the database instead of in Python over a full result set.
- **Recursive CTEs** — the org structure is a tree. "Everyone under this manager at any depth" is one query instead of a loop that hits the DB N times.
- **Table partitioning** — `metric_fact` partitioned by month. Date-range queries skip irrelevant partitions; retention is `DROP PARTITION` instead of a `DELETE` that thrashes.
- **JSONB + GIN indexes** — store each connector's raw source row beside the normalized columns, so a bad field mapping can be re-derived without re-syncing.
- **Materialized views** — precomputed leaderboard snapshots. TV mode reads a tiny table instead of aggregating millions of rows every poll.
- **`NUMERIC`** — exact decimals. Ranking people by revenue in floating point produces numbers that are off by cents, and someone always notices.
- **`LISTEN`/`NOTIFY`** — free pub/sub, so a finished sync can push a live update without running Redis.
- **Transactional DDL** — a failed migration rolls back completely. When shipping into networks you can't SSH into, that's the difference between "retry the upgrade" and a support call.

> **Important mental model:** data pulled from Snowflake/Excel/Sheets **lands in Postgres** and is by far the largest thing in it. Connectors do not query the source live when a leaderboard loads — that would be slow, expensive, and would break whenever the source was unreachable. A sync job pulls on a schedule, normalizes, and writes to `metric_fact`. Postgres is the single source of truth the app reads from.

## Containers

```
┌──────────────────────────────────────────────────────────┐
│                    docker compose                         │
│                                                           │
│  ┌────────────┐   ┌────────────┐   ┌─────────────┐       │
│  │    web     │   │    api     │   │  postgres   │       │
│  │            │──▶│            │──▶│             │       │
│  │ nginx      │   │ FastAPI    │   │ PostgreSQL  │       │
│  │ built SPA  │   │ uvicorn    │   │ 18          │       │
│  │ :80        │   │ :8000      │   │ :5432       │       │
│  └────────────┘   └────────────┘   └─────────────┘       │
│         │                                  │              │
│         └── proxies /api → api             │              │
│                                            ▼              │
│                                    ┌─────────────┐        │
│                                    │  db-backup  │        │
│                                    │ cron, 3am   │        │
│                                    └─────────────┘        │
│                                                           │
│  ┌────────────┐  development only — absent in production  │
│  │  webbuild  │  rebuilds the SPA on save                 │
│  └────────────┘                                           │
└──────────────────────────────────────────────────────────┘
```

Only `web` publishes a port. No Redis, no message broker, no worker container.

### One compose file per environment difference

`.env` sets `COMPOSE_FILE`, so `docker compose up -d` is the command in both
places and only the overlay changes:

```
docker-compose.yml        shared: images, ports, env, healthchecks
docker-compose.dev.yml    base images, mounted source, webbuild watcher
docker-compose.prod.yml   built images, code baked in
```

| | development | production |
|---|---|---|
| api | `python:3.13-slim`, source mounted, `--reload` | built image |
| web | `nginx:alpine`, config + build mounted | built image |
| webbuild | rebuilds on save | absent |

Development installs dependencies at container start, so adding a package needs
a restart rather than a rebuild. Production bakes them into the image, so a
container start never depends on reaching a package registry — and a code
change produces a new image, which makes Compose recreate the container without
any "which services changed?" scripting.

**Why nginx serves the SPA:** the React app builds to static files. nginx serves them and proxies `/api` to FastAPI, so the browser sees one origin. That avoids CORS entirely and lets session cookies work without `SameSite` gymnastics.

**Why nginx resolves its upstream at request time** (`resolver 127.0.0.11` plus a variable, rather than a literal hostname): with a literal `proxy_pass http://api:8000`, nginx resolves the name at startup and exits with "host not found in upstream" if the API container isn't up. Deferring resolution means nginx boots regardless and simply returns 502 until the API answers.

### Planned, not yet built

**In-process scheduling (APScheduler).** Sync jobs will run inside the FastAPI process with retries and backoff, removing a broker, a worker container, and an entire class of "is the queue drained?" debugging. Job functions will be written to be near-identical to Celery tasks, so moving to a real queue later is a contained change. Arrives with the first scheduled job — goal recurrence or connector sync. Trigger to move to Celery: many connectors syncing concurrently, or syncs long enough to affect API responsiveness.

## Repository layout

What exists today:

```
GoalGetter/
├── docker-compose.yml              # shared services
├── docker-compose.dev.yml          # base images + mounted source
├── docker-compose.prod.yml         # built images
├── .env / .env.example             # COMPOSE_FILE picks the overlay
├── .dockerignore / .gitattributes
├── api/
│   ├── app/
│   │   ├── main.py                 # wires routers together, nothing else
│   │   ├── config.py               # settings from env (pydantic-settings)
│   │   ├── db.py                   # engine, session dependency
│   │   ├── security.py             # password hashing
│   │   ├── sessions.py             # session issue/validate, current_user
│   │   ├── models/                 # SQLAlchemy models
│   │   └── routers/                # health, setup, auth
│   ├── alembic/                    # migrations
│   └── pyproject.toml
├── web/
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx                 # routes
│   │   ├── auth.tsx                # AuthProvider, RequireAuth
│   │   ├── api.ts                  # fetch wrapper
│   │   ├── theme.css               # design tokens
│   │   ├── components/             # shared UI
│   │   └── pages/                  # Login, Setup, Dashboard
│   ├── index.html
│   └── package.json
├── nginx/conf.d/default.conf       # SPA + /api proxy
├── postgres/                       # *.sql run once on an empty database
├── docker/                         # Dockerfiles — production only
├── deploy/auto-pull.sh
├── volumes/                        # runtime data (gitignored)
└── documentation/
```

**Folders are added when a feature needs them, not up front.** `services/`,
`jobs/`, and `connectors/` on the API side, and a generated API client on the
web side, appear in later phases. An earlier attempt scaffolded all of them
empty and the result was harder to navigate, not easier.

**Why `services/` exists separately from `routers/`:** routers should only parse input, check permission, call a service, and shape the response. All real logic goes in services. This keeps business rules testable without spinning up HTTP, and means the same logic can be called from a scheduled job as from an endpoint.

## Request flow

```
Browser
   │  GET /api/leaderboards/12
   ▼
nginx ──proxy──▶ FastAPI router
                    │  1. session cookie → current user
                    │  2. RBAC: may this user view this leaderboard's scope?
                    │  3. call leaderboard service
                    ▼
                 Service layer
                    │  build the aggregation query
                    ▼
                 Postgres  (window function does the ranking)
                    │
                    ▼
                 Pydantic response model → JSON
```

## Type safety across the language boundary

The one real cost of a Python backend with a TypeScript frontend is losing shared types. This is how it's neutralized:

```
FastAPI  ──auto──▶  openapi.json  ──codegen──▶  web/src/api/  (typed TS client)
```

FastAPI emits an OpenAPI spec from the Pydantic models with no extra work. A generator turns that into a fully typed TypeScript client. Rename a field in Python, regenerate, and the frontend fails to compile — which is exactly the behavior a single-language stack would give you.

**Rule: `web/src/api/` is generated. Never hand-edit it.** Regeneration is part of the dev workflow — see [19-dev-workflow.md](19-dev-workflow.md).

## Where things deliberately are *not*

- **No Redis in v1.** Caching goes to Postgres materialized views. Pub/sub, if needed, uses `LISTEN`/`NOTIFY`.
- **No WebSockets in v1.** Leaderboards and TV mode poll on an interval. Sales data doesn't change fast enough to justify the complexity, and polling survives network blips that break sockets. Revisit if the polling load becomes real.
- **No microservices.** One API. The connector engine is a module, not a service.
- **No GraphQL.** The client's needs are known and stable; REST with a generated client is less machinery for the same result.

## Related docs

- [02-data-model.md](02-data-model.md) — schema
- [14-api-conventions.md](14-api-conventions.md) — endpoint and error conventions
- [16-deployment.md](16-deployment.md) — Docker and configuration
- [19-dev-workflow.md](19-dev-workflow.md) — local setup, codegen, testing
