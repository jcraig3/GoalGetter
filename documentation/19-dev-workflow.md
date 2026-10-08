# Development Workflow

How to work on GoalGetter day to day.

## Local setup

Install as in [the README](../README.md#getting-started) (the setup script
writes `.env` with fresh secrets), then point `.env` at the development
overlay, so source edits apply without rebuilding:

```bash
COMPOSE_FILE=docker-compose.yml:docker-compose.dev.yml
```

Then `docker compose up -d`. Changes to `web/src` rebuild in about half a
second (refresh to see them), and changes to `api/` reload in about a second.
The same command with the production overlay runs production — see
[01-architecture.md](01-architecture.md#one-compose-file-per-environment-difference).

| | development | production |
|---|---|---|
| api | `python:3.13-slim`, source mounted, `--reload` | built image, code baked in |
| web | `nginx:alpine`, config and build mounted | built image |
| webbuild | rebuilds the frontend on save | does not exist |
| https | Caddy, the same in both; serves nothing until HTTPS is on | the same |
| tunnel | cloudflared, the same in both; idle until a Cloudflare tunnel is on | the same |

The everyday checks:

```bash
docker compose exec -T api python -m pytest -q                                              # backend tests
docker compose exec -T webbuild sh -c 'npx tsc --noEmit -p tsconfig.json && npx vitest run'  # frontend
docker compose exec postgres psql -U goalgetter -d goalgetter                                # database shell
```

**A blank page usually means a failed frontend build.** Run
`docker compose logs webbuild --tail 30` and look for `Build failed`.

| Service | URL |
|---|---|
| **App** | http://localhost:8080 |
| API (direct, development only) | http://localhost:8000 |
| API docs (Swagger) | http://localhost:8000/docs |
| Postgres | `docker compose exec postgres psql -U goalgetter -d goalgetter` |

Development differences: source mounted instead of baked into images,
dependencies installed at container start, uvicorn `--reload`, a `webbuild`
watcher rebuilding the SPA on save, the API port published, and
`SECURE_COOKIES=false`.

**The app is served by nginx in development too**, from a real production
build — not a Vite dev server. That keeps routing, headers, caching, and
same-origin cookie behaviour identical to production. The cost is no
hot-module reload: a save rebuilds in about a second and you refresh.

`http://localhost:8000/docs` is genuinely useful — FastAPI's interactive docs let you call any endpoint with a real session without writing a client.

### Adding a dependency

Both `api` and `webbuild` install at container start, so a new package needs a
restart of that service — not a rebuild:

```bash
cd web && npm install <package>     # or edit api/pyproject.toml
docker compose restart webbuild     # or: docker compose restart api
```

Forgetting this produces a blank page: the build fails on an unresolved import
but still writes a bundle, so nginx keeps serving a broken one. Check
`docker compose logs webbuild` for `Build failed` before debugging anything else.

### Where things are

```
GoalGetter/
├── setup.ps1, setup.sh      first-time setup: writes .env with fresh secrets
├── .env.example             every setting, explained
├── docker-compose.yml       shared services
├── docker-compose.prod.yml  built images (the default)
├── docker-compose.dev.yml   mounted source, live rebuilds
├── docker-compose.frontdoor.yml  ports for the Windows front door (added by its installer)
├── api/                     FastAPI app, migrations, tests
├── web/                     React app
├── nginx/                   serves the app, proxies /api
├── caddy/                   HTTPS inside Docker: Caddy's starting config (the app sends the rest)
├── windows/                 the Windows front door: installer and its Caddy config
├── docker/                  Dockerfiles, backup script
├── deploy/                  optional auto-pull deploy script
├── volumes/                 your data: database, backups, certificates (gitignored)
└── documentation/           design docs, roadmap, hosting guide
```

## Demo data

Goals, leaderboards, and dashboards are built before any connector exists, so
there is nothing to develop against until you generate some:

```bash
docker compose exec api python -m app.seed_demo --days 120   # ~3,000 facts
docker compose exec api python -m app.seed_demo --clear      # remove them again
```

Re-running with the same `--seed` replaces rather than duplicates, so it is safe
to run repeatedly. It only ever removes rows it wrote (`external_id` prefixed
`demo:`), so anything you enter by hand while testing survives.

It is a module rather than an endpoint on purpose: nothing reachable over HTTP
can trigger it.

## Scheduled jobs

```bash
docker compose exec api python -m app.jobs             # run everything once
docker compose exec api python -m app.jobs --dry-run   # report, change nothing
```

They also run hourly inside the API process, started by the FastAPI lifespan.

**Every job must be idempotent**, and the guarantee belongs in the database
wherever it can. `spawn_due_goals` relies on a partial unique index rather than
checking whether a copy already exists: a check-then-insert is a race that two
replicas — or one restarted between the two statements — will lose.

That property is what makes scheduling boring. A missed run catches up on the
next one, a double run is harmless, and a container dying mid-job leaves
nothing half-done. It is also why the loop is hourly rather than
daily-at-a-time: running more often than needed costs a few indexed queries and
removes every "the container was down at 02:00" question.

## The API client — **not yet generated**

The intended end state is a generated client, so a renamed Pydantic field breaks
TypeScript compilation instead of failing silently at runtime:

```
1. Change a Pydantic model or route in api/
2. FastAPI regenerates /openapi.json automatically (reload)
3. npm run generate:api           → rewrites web/src/api/generated/
4. tsc fails at every affected call site
```

**None of that exists today.** `web/src/api.ts` is a hand-written `fetch`
wrapper, and each page declares its own response interfaces. That means a
renamed field is currently caught by *reading*, not by the compiler — the one
real cost of not having built this yet.

Worth adding when the API surface stops changing shape every phase; generating
against a moving target mostly produces churn. Until then, when you rename a
field in a Pydantic model, grep the web source for the old name.

Current check:

```bash
docker compose exec webbuild npx tsc --noEmit -p tsconfig.json
```

## Migrations

```bash
# after changing a SQLAlchemy model
docker compose exec api alembic revision --autogenerate -m "add goal_assignment"
# ALWAYS read the generated file before committing
docker compose exec api alembic upgrade head
```

**Always read what `--autogenerate` produced.** It's good at detecting added and removed columns, and unreliable at renames — it usually emits a drop plus an add, which silently destroys data. Renames need to be written by hand.

Rules:
- One migration per logical change.
- Never edit a migration that has been merged. Write a new one.
- Data migrations are separate from schema migrations.
- Test both `upgrade` and `downgrade` locally before committing, even though production downgrades aren't supported.
- Adding an index to `metric_fact` uses `CREATE INDEX CONCURRENTLY`, which cannot run inside a transaction — Alembic needs `op.execute` with autocommit for those.

## Branching & commits

```
main                 always deployable
feat/goal-pace-marker
fix/leaderboard-tie-ranking
docs/update-metrics-engine
```

Conventional-style prefixes: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`.

Squash-merge to `main` so history reads as one commit per change.

## Testing

```bash
docker compose exec api pytest                        # ~20s, 270 tests
docker compose exec api pytest --cov=app              # with coverage
docker compose exec api pytest tests/test_periods.py  # one file
docker compose exec api pytest -k "scope" -v          # by name
```

**Tests run against a real Postgres**, in a database called `goalgetter_test`
that is created on the first run. Never SQLite: the reason for choosing
Postgres was window functions, `NUMERIC`, partial indexes, and `AT TIME ZONE`,
and a green SQLite suite would prove nothing about production. A separate
database also means a test can never disturb data you are looking at.

**The schema comes from the real migrations.** `Base.metadata.create_all()`
would build what the *models* describe — exactly what a broken migration fails
to produce — so every run also proves the chain applies cleanly.

**Each test rolls back.** The session joins an open transaction with
`join_transaction_mode="create_savepoint"`, so handlers really do call
`db.commit()` and nothing survives the test.

### Writing one

Fixtures are builders, not fixed objects — `make_user`, `make_team`,
`make_metric`, `make_fact`, `sign_in`. A test that needs "an agent on another
team" says so in one line:

```python
def test_a_manager_does_not_see_another_team(db, make_team, make_user):
    stranger = make_user("agent", make_team("SMB"))
    manager = make_user("manager", make_team("Enterprise"))
    assert stranger.id not in visible_user_ids(db, manager)
```

Three habits that have each caught a real bug here:

1. **Assert the exact set, not a sample.** "The manager sees their teammate"
   passes even when the manager also sees every admin in the organization.
   `assert names == {...}` is what found that.
2. **Test the refusal too.** That a permitted action works is half the test;
   that the forbidden one is refused *and leaves nothing behind* is the half
   that matters for permissions and audit.
3. **Prove a new test can fail.** Reintroduce the bug, watch it go red, put it
   back. A test that has never failed has not been checked.

### Tests do not ship

They are permanent in the repository and absent from the production image. The
prod build runs `pip install .` without the `dev` extra, so pytest is not
installed, and `.dockerignore` excludes `api/tests` and `*.test.ts` from the
build context — otherwise the files would sit in a layer where nothing can run
them.

Deleting them is never the plan. They are what makes a change to
`visible_user_ids` or `periods.py` safe to make at all, and they have already
caught two security bugs that using the app did not.

### Priority order for anything new

1. **Period boundary math** — pure, and a wrong boundary silently corrupts
   every number downstream.
2. **Permission scope** — a bug here is a data leak.
3. **Aggregation and ranking** — ties, `lower_is_better`, empty sets.
4. **Import validation** — malformed files, unmatched users, duplicates.

| Layer | What it covers |
|---|---|
| Unit | Period math, pace calculation, formatting, scope resolution |
| Service | Business logic against a real test database |
| API | Endpoints via `TestClient`, including permission cases |

**Tests run against a real Postgres, not SQLite.** The whole point of choosing Postgres was window functions, recursive CTEs, partitioning, and `NUMERIC`. SQLite supports none of that the same way, so a passing SQLite test suite would prove nothing about production behavior. Each test gets a transaction that rolls back.

**Priority order for what to test first:**

1. **Period boundary math** — pure functions, and a wrong week boundary silently corrupts every number downstream. Cover: week start settings, fiscal year offsets, DST transitions, month-end edge cases.
2. **Permission scope resolution** — every role against a multi-level org tree. A bug here is a data leak.
3. **Aggregation and ranking** — including ties, `lower_is_better` metrics, empty sets, and single-entity sets.
4. **Import validation** — malformed files, unmatched users, duplicate rows.

### Frontend

```bash
docker compose exec webbuild npx vitest run     # 31 tests
docker compose exec webbuild npx vitest         # watch
docker compose exec webbuild npx tsc --noEmit -p tsconfig.json
```

Vitest only so far — no Playwright, no component rendering. Everything tested
is a **pure function**: input filtering, range messages, value formatting.
That is deliberate, and it is where the subtle bugs are.

**Export the function the component actually calls.** The first version of
`Field.test.ts` reimplemented the keystroke rule as a local `typeInto` helper.
Every test passed — and deleting the filter from the component changed nothing,
because the tests were exercising a copy. `filterInput` is now exported and the
test calls it, which a mutation confirmed: removing the filter fails two tests
instead of none.

**Where validation lives.** Field rules are convenience, never the gate. Every
constraint they express is also enforced by the API, and usually by a CHECK
constraint underneath it — verified by pointing curl at the endpoint with
exactly the values the field refuses.

## Testing — priority order for anything new

## Code style

Followed by hand today. **No linter, formatter, or CI is wired up yet** — the
conventions below are the ones the codebase actually follows, so a tool added
later should agree with what is already there rather than rewrite it.

### Python
- `ruff` for lint and format. One tool, no Black/isort/flake8 stack to reconcile.
- `mypy` in strict mode on `app/`.
- Type hints on every function signature — they're what generates the OpenAPI schema.
- Docstrings on services, not on obvious CRUD.

### TypeScript
- `eslint` + `prettier`.
- `strict: true` (this one *is* enforced — `tsc --noEmit` is the current gate).
- Named exports; default exports only for route components.

## Architectural rules

These matter more than style, because violating them causes real bugs:

1. **Routers hold their own queries — there is no service layer.** An earlier
   plan had one; it was dropped because every "service" would have been a
   single function called from a single router, which is indirection without
   separation. Extract one the first time two routers need the same logic, not
   before.
2. **Every handler takes the acting user and enforces scope itself.**
   `require_role(...)` at the edge, `visible_user_ids()` / `can_see_user()`
   inside. See [05-roles-and-permissions.md](05-roles-and-permissions.md).
3. **Scope goes in the query, never in a post-filter.** See [17-security.md](17-security.md).
4. **Every number rendered goes through one formatter.** Ad-hoc formatting will
   disagree with itself — a metric's `unit` and `decimal_places` decide how it
   is displayed, in one place. *(The shared component lands with 1d-iii, when
   there is finally a number to render.)*
5. **Every privileged mutation writes an audit log entry**, in the same
   transaction as the change. See `api/app/audit.py`.
6. **All period math uses the org timezone.** Never the server's, never the
   browser's. `occurred_at AT TIME ZONE :org_timezone` before bucketing.
7. **`web/src/` is flat**: `pages/` for routes, `components/` for shared UI.
   `components/` never imports from `pages/`. There is no `features/` layer —
   it was removed as premature.

## Adding a feature — the standard path

Vertical slice, in this order:

```
1. Document it in documentation/  (or update the existing doc)
2. SQLAlchemy model + Alembic migration
3. Pydantic schemas (Create / Update / Read)
4. Service with scope enforcement + tests
5. Router with response_model + permission dependency
6. npm run generate:api
7. TanStack Query hooks
8. UI components
9. Tests
```

Documentation first is deliberate — writing down what a feature does surfaces the open questions before they become half-built code. That's what this whole `documentation/` folder is for.

## Debugging

```bash
docker compose logs -f api
docker compose exec postgres psql -U goalgetter goalgetter
```

For slow queries — the aggregation query is the one that will need attention first:

```sql
EXPLAIN (ANALYZE, BUFFERS) SELECT ...;
```

Look for sequential scans on `metric_fact`. That means an index isn't being used or partition pruning isn't happening, which is the difference between a 20ms leaderboard and a 4-second one.

## CI

On every PR:

1. `ruff check` + `ruff format --check`
2. `mypy`
3. `pytest` against a real Postgres service container
4. `eslint` + `tsc --noEmit`
5. `vitest`
6. **Regenerate the API client and fail if it differs from what's committed**
7. `docker compose build`
8. `pip-audit` + `npm audit`

Step 6 is the guard that keeps the frontend and backend contracts honest.

## Documentation

Docs live in `documentation/` and are part of the deliverable, not an afterthought.

- Update the relevant doc **in the same PR** as the change.
- When an open question gets resolved, replace it with the decision and the reasoning.
- Record *why*, not just *what*. The reasoning is what's valuable when revisiting a decision in six months.

## Related docs

- [01-architecture.md](01-architecture.md)
- [14-api-conventions.md](14-api-conventions.md)
- [16-deployment.md](16-deployment.md)
- [18-roadmap.md](18-roadmap.md)
