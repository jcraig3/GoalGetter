# Roadmap & Build Order

The sequencing rule: **make the core loop work end to end before making any part of it broad.**

One metric flowing from entry → goal → leaderboard → celebration is worth more than ten half-built connectors, because it's the first point at which the product can be used and judged.

---

## Phase 0 — Skeleton

**Goal:** an empty app that runs, with the development workflow proven.

**Build order: one layer at a time, each finished and working before the next
starts.** A first attempt built all three simultaneously; each layer accumulated
decisions before the previous one had been looked at, and the result was
over-designed. It was deleted and restarted. That attempt is preserved in git
(`de84db8`) if a detail needs recovering.

### 0a. Docker — done

- [x] `docker-compose.yml` with `postgres` only
- [x] Named volume for data; port not published (use `docker compose exec`)
- [x] `.env` / `.env.example` so one compose file serves local and production
- [x] Healthcheck, so later services can wait on `service_healthy`

**Verified:** container healthy, `psql` connects, data survives a restart.

> **Postgres 18 changed the mount point.** The volume goes at
> `/var/lib/postgresql`, not `/var/lib/postgresql/data`. The image stores data
> in a major-version subdirectory (`18/docker`) so a future `pg_upgrade --link`
> stays inside one mount point; mounting `.../data` makes the container refuse
> to start with a long explanatory error.

### 0b. Web — done

- [x] `web/` — React 19 + Vite 8 + TypeScript + Tailwind 4
- [x] nginx config + `docker/web.Dockerfile` (multi-stage) — config later moved to `nginx/conf.d/`
- [x] `web` (nginx) and `webbuild` (watcher) services
- [x] Dark-first design tokens in `src/theme.css`

**Verified:** page serves on :8080 from a production build, SPA fallback works
on a deep link, security headers present on both HTML and assets, hashed assets
cached for a year and `index.html` not cached, edit-to-served in ~0.5s.

Deliberately deferred until there is something for them to do: React Router,
API client, test runner, ESLint.

> **File watching does not work through a Windows bind mount.** Docker Desktop
> does not forward filesystem events from a Windows path into a Linux
> container, so the watcher never rebuilds. The fix is polling, set in
> `vite.config.ts`:
>
> ```ts
> watch: { chokidar: { usePolling: true, interval: 300 } }
> ```
>
> Two traps here. `CHOKIDAR_USEPOLLING` — the usual environment-variable
> workaround — is **not** honored. And Vite 8 builds with **rolldown**, whose
> re-exported `WatcherOptions` type does not declare `chokidar`, so this needs
> a cast even though it works. Measured both ways: with the option an edit is
> served in ~0.4s; without it, edits are never picked up at all.

### 0c. API — done

Kept deliberately thin. The health endpoint does not justify a database, a
settings layer, or a codegen pipeline; each arrives with the first feature that
needs it.

- [x] `api/` — FastAPI with `GET /api/health`
- [x] `docker/api.Dockerfile`, non-root user
- [x] nginx proxies `/api` → api, so the browser sees one origin
- [x] `depends_on: postgres: condition: service_healthy` wired ahead of need
- [x] Only port 8080 published; api and postgres reachable only inside the network

**Verified:** the page fetches `/api/health` through nginx and renders the
result; `:8000` is not reachable from the host; API edits reload in ~1.4s.

**Deferred, with the trigger for each:**

| Deferred                        | Arrives with                                  |
| ------------------------------- | --------------------------------------------- |
| SQLAlchemy, Alembic, migrations | the first real model (Phase 1a, users)        |
| Settings / secrets validation   | the database connection (arrived in 1a-i)     |
| Standard error shape            | the first endpoint that can fail meaningfully |
| OpenAPI → TypeScript codegen    | the first endpoint returning real data        |
| Tests, linting, CI              | the first real logic                          |

> **The two watchers behave differently.** Vite's needs `usePolling` to see
> edits through a Windows bind mount; uvicorn's `--reload` detects them
> natively with no configuration. Don't assume a fix for one applies to the
> other.

### Restructure — dev/prod overlays

Adopted after reviewing three existing stacks (`docker-spa-setup`, `my-app`,
`ithub`). `.env` sets `COMPOSE_FILE`, so `docker compose up -d` means
development locally and production on the server, with nothing else changing.

|          | development                                    | production  |
| -------- | ---------------------------------------------- | ----------- |
| api      | `python:3.13-slim`, source mounted, `--reload` | built image |
| web      | `nginx:alpine`, config + build mounted         | built image |
| webbuild | watcher                                        | absent      |

Three fixes carried over from IT Hub, each solving a problem we had:

**nginx resolves its upstream at request time**, via `resolver 127.0.0.11` and
a variable, rather than a literal hostname. A literal `proxy_pass http://api:8000`
makes nginx _refuse to start_ when the API isn't up. Verified: with the API
stopped, nginx starts, serves the SPA, returns 502 for `/api`, and recovers on
its own when the API returns — zero restarts.

**`map $http_upgrade $connection_upgrade`** so ordinary API calls stop being
told to become WebSockets.

**`.gitattributes` with `*.sh text eol=lf`.** `core.autocrlf` is on, so a
Windows clone would have produced CRLF shebangs — which don't execute on Linux.
The container would have failed to start with a confusing error.

> **A healthcheck can lie.** `wget http://localhost/` inside the web container
> failed with "connection refused" while the site served fine from the host:
> `localhost` resolves to `::1` first and `listen 80` binds IPv4 only. A false
> unhealthy is worse than none — an orchestrator acts on it by killing a
> working container. Use `127.0.0.1`.

Postgres data is a bind mount (`./volumes/postgres`), matching the other
projects. Measured ~4× slower than a named volume for bulk writes on Windows,
which is irrelevant at current data volume; revisit if seeding realistic
`metric_fact` volumes gets slow. It survives `docker compose down -v`, which a
named volume does not.

### Development mirrors production

One compose file. nginx serves built files locally exactly as it will in
production, on one origin, so routing, cookies, and headers behave identically.

Two differences remain, both about _how code reaches the container_ rather than
how it runs: locally the API mounts source and runs `--reload`, and a watcher
rebuilds the SPA. Production bakes both into images. Making these identical
would mean a `docker build` per keystroke.

### Carried forward from the first attempt

Findings worth not rediscovering:

1. **nginx `add_header` does not inherit into a `location` block that sets its
   own.** A `Cache-Control` header on `location /` silently discarded the
   server-level `X-Frame-Options`, leaving the HTML framable. Repeat security
   headers in every location block that sets any header, and verify with a real
   request.

2. **Tailwind ignores unknown utility classes silently.** A token renamed from
   `border` to `edge` left `border-border` in the markup; it produced no CSS, no
   error, and no failed build — the borders simply vanished. Worth a test that
   compiles every utility found in source through Tailwind's own compiler.

    Two earlier versions of that test passed on the very bug they were written
    for: an allowlist of "custom" prefixes missed the stale name, and a
    per-candidate diff was defeated by the compiler being stateful across
    `build()` calls. **Test a guard by reintroducing the bug.**

3. **Generate types, not a client.** `@hey-api/openapi-ts` with its client
   plugin vendored 16 files / 57.6 KB into `src/`, of which 12 were an HTTP
   client runtime that nothing imported. `openapi-typescript` emits one 5.2 KB
   file of types; pair it with `openapi-fetch` (a real dependency in
   `node_modules`) for type-checked URLs. Library code belongs in
   `node_modules`, generated types belong in `src/`.

4. **Postgres has transactional DDL**, so a failed migration rolls back
   completely — which is what makes running `alembic upgrade head` automatically
   on container start safe.

---

## Phase 1 — Foundation

**Goal:** a usable product. Data comes in via CSV/Excel import, goals get set, leaderboards work.

### 1a. Auth & users

Built in slices: **i** database layer · **ii** first-run setup · **iii** login
and sessions · **iv** login page and route guard · **v** SSO.

#### 1a-i — done

- [x] SQLAlchemy 2.0 + Alembic, migrations applied on container start
- [x] `organization` and `user_account` tables
- [x] `/api/health/ready` reporting database reachability

**Verified from an empty database:** migration applies on boot, defaults land,
and every constraint rejects what it should — duplicate email differing only by
case, invalid `org_role`, nonexistent organization, out-of-range
`week_starts_on`.

Two things worth carrying forward:

**`default=` is not `server_default=`.** `default=` is applied by SQLAlchemy in
Python and never reaches the schema, so any insert that bypasses the ORM — a
seed script, a data migration, a manual fix in `psql` — hits NOT NULL with
nothing to fill it. Columns that are NOT NULL with a sensible value need
`server_default`. This was caught by testing the constraints rather than
assuming them.

**One integer width for the whole schema.** `Mapped[int]` defaults to
`INTEGER`, which produced a `BIGINT` foreign key pointing at an `INTEGER`
primary key. `type_annotation_map = {int: BigInteger}` on `Base` makes every
key BIGINT — overkill for users, correct for `metric_fact`, and it removes a
class of mismatch.

#### 1a-ii — done

- [x] bcrypt password hashing (cost 12), 72-byte input guard
- [x] `GET /api/setup/status`, `POST /api/setup`
- [x] Setup screen, shown only while the deployment has no users
- [x] Routes split into `app/routers/`

**Verified:** setup creates the org and admin; running it a second time returns
409; short passwords and malformed emails are rejected; the stored value is a
`$2b$12$` hash with no plaintext anywhere; the same password hashes differently
each time (salting works).

**Setup can only run while zero users exist**, so it is not a permanent
backdoor. A Postgres advisory lock serialises concurrent attempts, so two
simultaneous requests cannot both create an admin.

> **Never write the build output into the watched folder.** Vite wrote to
> `web/dist`, which sits inside the watched source directory, so every build
> triggered the next one — **161 idle rebuilds in 30 seconds**, plus
> intermittent 403s because Vite clears the output directory at the start of
> each build. Chokidar's `ignored` option does not fix it (rolldown ignores
> it); the output has to physically live outside the watched tree. It now
> builds to `/dist` in the container: 0 idle rebuilds, edits still served in
> under a second.

#### 1a-iii — done

- [x] `session` table, `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`
- [x] `current_user` dependency — declaring it is what makes an endpoint require auth
- [x] HTTP-only, SameSite=Lax cookie; `SECURE_COOKIES` for production
- [x] Sliding 7-day expiry, extended only past the halfway mark

**Only the SHA-256 of the token is stored**, never the cookie value. If the
table leaked, raw tokens would let an attacker resume every active session;
hashes are useless for that. Plain SHA-256 is right here — the token is 32
bytes of randomness, so there is nothing to brute-force.

**Verified:** login issues an HTTP-only cookie · `/me` works with it and 401s
without · logout deletes the row and the cookie stops working · the raw token
appears nowhere in the database · **suspending an account in SQL invalidates
the live session on the very next request** — the concrete argument for
database sessions over JWT · wrong password, unknown email, and suspended
account all return the same message.

> **A fake hash is not a timing-safe fallback.** Login verified against
> `"$2b$12$" + "."*53` when no account matched, intending to keep response
> time constant. That string is not a valid bcrypt hash, so bcrypt rejected it
> instantly instead of doing the work, and a nonexistent email answered
> **43ms faster** — exactly the account-enumeration leak the fallback was
> supposed to close. Fixed by hashing a random string at import so the dummy
> is real. Gap is now within noise and no longer directional.
>
> The lesson generalises: a mitigation nobody measured is a comment, not a
> defence.

#### Login rate limiting — done

- [x] `login_attempt` table, indexed on (email, time) and (ip, time)
- [x] 5 failures per account / 15 min · 20 failures per IP / 15 min
- [x] A successful sign-in clears that account's failures
- [x] `prune()` for 30-day retention — **not yet scheduled**, no scheduler exists

**Two limits, because they stop different attacks.** The per-account limit stops
one address being guessed repeatedly. The per-IP limit stops one attacker
spraying many addresses, where no single account ever reaches its own limit —
verified with 22 addresses at one attempt each.

Attempts are stored in the database, not in process memory: an in-memory
counter is wiped by `docker compose restart api`, which makes it useless as a
defence, and it would not hold across replicas.

> **Early rejection leaked which accounts were locked.** Returning immediately
> when rate-limited skips bcrypt and answered in **14ms against 244ms** for a
> normal failure. That 17× gap is an oracle — a fast reply tells an attacker
> the account exists _and_ is currently locked. Fixed by verifying against the
> dummy hash before refusing; measured again at 0.221 / 0.199 / 0.210s, which
> is noise.
>
> The cost is that an attacker can still make the server do bcrypt work. That
> is a connection-level concern for nginx or Cloudflare, not for this layer.
>
> Third time this pattern has appeared: **a mitigation nobody measured is a
> comment, not a defence.**

**Verified:** lockout engages on the 6th attempt · the _correct_ password is
rejected while locked · a successful sign-in clears prior failures · wrong
password, unknown email, lockout, and correct-password-while-locked all return
an identical message · the per-IP limit catches spraying.

**Design note:** the window is fixed, not sliding — 5 attempts per 15 minutes,
so roughly 480 guesses per day per account. Against a 12-character minimum and
bcrypt at cost 12, that is not a meaningful threat, and it avoids a permanent
lockout an attacker could trigger deliberately against a real user.

#### 1a-iv — done

- [x] React Router — `/login`, `/setup`, `/` (dashboard)
- [x] `AuthProvider` holding the signed-in user, hydrated on load
- [x] `RequireAuth` route wrapper, remembering the intended destination
- [x] Login page, setup page, placeholder dashboard with sign-out
- [x] Shared `Field` component, `api.ts` fetch wrapper

**Verified:** every route serves the SPA (fallback works) · signing in moves to
the dashboard and signing out returns to login · setup redirects away once the
deployment has users · **a forged session cookie is still rejected with 401**.

> **`RequireAuth` is user experience, not security.** It decides what to
> render, nothing more. Every endpoint enforces authentication server-side, so
> bypassing the guard in the browser yields an empty page and 401s. Anything
> protected only by a hidden component is not protected.

The frontend now has three real folders and nine files:

```
src/
├── App.tsx        routes
├── auth.tsx       AuthProvider, RequireAuth
├── api.ts         fetch wrapper
├── theme.css
├── components/    Field
└── pages/         Login, Setup, Dashboard
```

`components/` appeared only when a second page needed the same input, rather
than being created up front.

#### 1a-vi — invites — done

- [x] `user_token` table — one mechanism for invitations _and_ password resets
- [x] `POST /api/users/invite` returning a copyable link, `resend-invite`
- [x] `POST /api/auth/accept-invite` — set a password, sign in immediately
- [x] `GET /api/users` list, Users page, accept-invite page
- [x] A manager may invite agents only; roles above that are admin-only

**Verified:** invited account cannot sign in until accepted · raw token appears
nowhere in the database (only its SHA-256) · a link works **once** — replay is
refused · a garbage token returns the identical message · resending revokes the
previous link · duplicate email returns 409 · manager inviting an admin returns
403 · the link resolves through the real URL and the new account can sign in
afterwards.

**The invite link is shown to the admin, not only emailed.** Many internal
deployments have no SMTP on day one, and the tool must be fully usable without
it — paste the link into Slack. Email becomes an enhancement rather than a
dependency.

**An admin never sets someone else's password.** The invitee chooses it from the
link, so there is no moment where a shared secret sits in a chat message.

> **One token table, two purposes.** Invitations and password resets are the
> same mechanism: issue a random secret, deliver it out of band, exchange it
> once. Two tables would duplicate the hashing, expiry, and single-use logic,
> and the copies would drift. `purpose` distinguishes them, and `consume()`
> refuses a token presented for the wrong one.

#### 1a-vii — user lifecycle — done

- [x] Change role and name via `PATCH /api/users/{id}`
- [x] Suspend, reactivate, archive
- [x] Suspending ends every live session immediately
- [x] Last-admin protection on demote, suspend, and archive
- [x] Role dropdown and lifecycle actions in the Users table

**The last active admin cannot be demoted, suspended, or archived.** One click
would otherwise lock everyone out of a self-hosted deployment permanently —
there is no support line, and the only way back would be editing the database by
hand. Same reasoning as the SSO break-glass rule, and the error says what to do:
_"Make someone else an admin first."_

**You cannot suspend or archive yourself.** Almost always a misclick, and the
consequence is signing yourself out of an account you may be the only admin for.

**Suspend vs archive.** Suspend revokes access and is reversible — "they have
left" or "something is wrong". Archive is a soft delete that also hides them
from the list. Neither removes the row: metric history and past leaderboard
positions are part of the company's record, and deleting a user would make last
quarter's results reference nobody.

**Verified:** last admin cannot be demoted/suspended/archived, and the guard
relaxes once a second admin exists · suspending a signed-in user drops their
session rows from 2 to 0 and their next request returns 401 · they cannot sign
back in · reactivating restores access · reactivating someone who never accepted
their invitation returns them to `invited`, not `active` — they still have no
password, so `active` would be a lie · archiving hides them from the list while
the row survives · a manager gets 403 on role change and suspend.

> **Changing a role needs no session invalidation, but suspending does.**
> Permissions are re-read from the database on every request, so a demotion
> takes effect on the next call. Status is checked the same way — but sessions
> are deleted anyway, so a reactivated account starts clean rather than resuming
> a session issued before the suspension.

#### 1a-viii — passwords — done

- [x] `POST /api/auth/change-password` — self-service, proves the current one
- [x] `POST /api/users/{id}/reset-password` — admin issues a link
- [x] `POST /api/auth/reset-password` — consumes it
- [x] `/reset-password` page, change-password on the account panel
- [x] 32 tests

**There is deliberately no self-service "forgot password" endpoint.** It would
have to deliver the link somewhere, and this deployment has no SMTP — so the
link could only come back in the HTTP response, which means anyone could
request a reset for the admin's address and be handed it. That is not a smaller
version of the feature; it is an account-takeover endpoint. Invitations already
work admin-issued for the same reason. When SMTP exists, self-service becomes a
matter of mailing the link instead of returning it.

**Issuing a reset is admin-only, narrower than inviting.** A manager may invite
a _new_ person, because that creates an account nobody was using. Resetting an
_active_ account's password takes it over and locks its owner out. The
escalation is small — an agent sees less than their manager does — but
impersonating a specific person is not something a team lead needs, and it is
far easier to grant later than to withdraw.

**A reset does not sign you in; accepting an invitation does.** A reset answers
a possible compromise, and the safe assumption is that the link may have been
read by someone other than its owner. Signing in with the new password is what
proves you are the one who chose it.

**Changing keeps your current session and ends every other one.** A password
change is the standard response to "someone else may have my password" — if the
other sessions survived it, the change would achieve nothing against exactly
the threat it exists for. A reset ends all of them, including any the attacker
holds.

**A reset clears the lockout.** Otherwise someone locked out by an attacker's
guessing could not use their new password until the window expired.

**The current-password check is rate limited** on the same counter as sign-in.
It is a guessing oracle against a session left open on a shared machine.

**Verified:** the full recovery path on the live stack — five failures produce
a 429 with `Retry-After: 298`, an admin issues a link, the reset returns 204,
replaying the same link returns 400, the lockout is gone and the new password
signs in · a wrong current password 400s and leaves the old one working · a
correct change 204s and the caller stays signed in · a second device's session
is ended while the caller's survives · an invite token cannot be used to reset
and a reset token cannot accept an invite · both halves are audited, with no
password anywhere in the row.

> **A CHECK constraint the code had never satisfied.** `user_token` allowed
> `purpose IN ('invite', 'password_reset')`, and the new code issued `'reset'`.
> It surfaced as a `CheckViolation` from deep inside a commit, naming neither
> the caller nor the valid values — ten tests erroring with one useless
> message. `tokens.issue()` now validates the purpose against the same tuple
> the constraint uses and raises immediately, saying what is allowed. The TTL
> also moved from `INVITE_TTL if purpose == "invite" else RESET_TTL` to a map
> keyed by purpose: the if/else silently treated _any_ unknown purpose as a
> reset, which is how a typo would have quietly produced a 2-hour invitation.

- [x] **`/api/auth/me` returning a capability map** — done in 1c
- [x] **`<Can do="...">`** on the client, replacing the direct role comparisons
      that were scattered through `AppShell`, `Teams`, and `Users` — done in 1c

**Not doing:** a full SSO end-to-end test against a live tenant. Every rejection
path is verified; the success path needs a real Microsoft-issued token.
Deliberately deferred — but it is the one item marked done that is not proven.

### 1b. Organization structure

Built in slices: **i** teams and the tree · **ii** membership · **iii**
reparenting · **iv** org settings. User invites land between i and ii, because
membership needs more than one person to exist.

#### 1b-i — done

**Teams are flat.** They were first modelled as a tree, so a company could run
divisions → regions → teams → pods. That bought recursive queries, cycle
prevention, depth limits, and a rule about archiving a team with children — in
exchange for a hierarchy this product does not need. A sales floor has teams,
and leaderboards compare them directly. Simplified before anything depended on
the extra structure.

- [x] `team` table, flat
- [x] `GET /api/teams` (with `include_archived`), create, rename
- [x] Archive, restore, and delete
- [x] Teams page with inline create and rename

**Archive vs delete.** Archiving hides a team from pickers while leaving history
intact — a leaderboard for last quarter must still be able to name the team that
won it. Deleting is permitted only while nothing references the team, so it
exists for one case: a team created by mistake. The guard is already written in
`delete_team`, ready for the membership check.

**Verified:** create, rename, archive, restore, delete · archived teams are
excluded by default and returned with `include_archived=true` · deleting leaves
a 404 on later access · an agent can view teams but gets 403 on any mutation.

> **Removing the tree removed four separate mechanisms**, not just a column:
> the recursive CTE, depth tracking, the archive-with-children guard, and the
> whole reparenting slice. Worth noticing how much complexity a single
> structural assumption carries — and how cheap it is to remove before other
> code depends on it.

#### 1b-ii — done

- [x] `user_account.team_id` — one team per agent
- [x] `PATCH /api/users/{id}` to assign or clear a team
- [x] Member counts on `GET /api/teams`
- [x] Unassigned people highlighted in the Users table
- [x] Team deletion now blocked while people are assigned

**One team per agent, not a join table.** Several teams per person would force
every leaderboard to answer "does this person count twice?", and a sales floor
puts someone on one team. Adding a join table later is a contained change;
unpicking one that aggregations already depend on is not.

`team_id` is nullable because _invited but not yet placed_ is a real state — and
one worth surfacing, since an unassigned agent is silently missing from every
team leaderboard. The Users table marks them in amber rather than leaving the
cell blank.

**Verified:** assign and reassign · counts update · explicit `team_id: null`
unassigns while an omitted field leaves it alone · a nonexistent or archived
team returns 404 · a manager gets 403 (admin-only at the time; scope resolution
in 1c has since given managers a scoped version of this) · deleting a team with
2 members returns 409 naming the count.

> **`None` in JSON is ambiguous** — it can mean "set this to null" or "I did not
> send this field". Pydantic's `model_fields_set` distinguishes them, which is
> what makes `{"team_id": null}` unassign while `{}` changes nothing. Any
> partial-update endpoint needs this distinction; without it, saving one field
> silently clears the others.

#### ~~1b-iii reparenting~~ — dropped

Not applicable to flat teams. Cycle prevention, move confirmation, and subtree
resolution all disappear with the hierarchy.

#### Roles simplified to three — done

`viewer` was dropped. **admin · manager · agent**, each with a distinct job:

| Role        | Job                                                                                        |
| ----------- | ------------------------------------------------------------------------------------------ |
| **agent**   | The people whose performance is measured — the players. Synced from the identity provider. |
| **manager** | Sets goals, manages agents, moves people between teams — within their own team.            |
| **admin**   | The few who control the deployment: settings, integrations, users, metrics.                |

`viewer` existed for wall-mounted TV displays, but those authenticate with a
**signed display URL**, not an account — so the role protected nothing and added
a column to every permission table.

**Verified:** the API rejects `viewer` on invite and role change, and the
database CHECK constraint rejects it even when the API is bypassed entirely.

> **Alembic does not compare CHECK constraints.** Autogenerate produced an empty
> migration for this change; it had to be written by hand. Two things that
> migration needed and autogenerate would never have known:
>
> 1. **Convert existing rows before tightening the constraint.** `UPDATE ... SET
org_role='agent' WHERE org_role='viewer'` runs first, or the `ALTER` fails
>    on rows the new constraint rejects. A migration that passes on an empty
>    database and fails on a real one is the worst kind.
> 2. **`op.f()` around the constraint name when dropping it.** Base's naming
>    convention (`ck_%(table_name)s_%(constraint_name)s`) otherwise prefixes an
>    already-complete name a second time, producing
>    `ck_user_account_ck_user_account_org_role_valid` and a failed migration.

**Managers gained the powers described above in 1c.** Moving people between
teams and managing agents needed `visible_user_ids()` to answer "which people?"
first. Goals remain outstanding only because goals do not exist yet.

#### 1b-iv — done

- [x] `GET /api/organization` — readable by anyone signed in
- [x] `PATCH /api/organization` — admin only
- [x] Settings page: name, timezone, week start, fiscal year start, currency
- [x] Timezone validated against the real tz database, currency against a list

**These are not cosmetic.** `timezone`, `week_starts_on`, and
`fiscal_year_start_month` decide what "today", "this week", and "this quarter"
mean, and every leaderboard and goal calculation reads them. They belong in the
database beside the data rather than in an environment variable that could drift
from what historical rows assumed.

**Readable by everyone, editable by admins.** Any screen showing a date or a
currency needs them — a leaderboard has to know which timezone "today" means.
Only writing is restricted.

**Verified:** invalid timezone rejected by name · unsupported currency rejected
· `week_starts_on=9` and `fiscal_year_start_month=13` rejected at 422 by
Pydantic bounds before reaching the database CHECK constraint · partial update
leaves other fields untouched · a manager can read (200) but not write (403).

> **Validate a timezone against the actual tz database**, not as a free string.
> `zoneinfo.available_timezones()` is the source of truth. An invalid zone does
> not fail at the point it is saved — it fails later, inside a date
> calculation, and presents as _wrong numbers_ rather than an error. Bad data is
> most dangerous when it is accepted quietly.
>
> The timezone picker uses `Intl.supportedValuesOf('timeZone')` in the browser
> rather than an endpoint returning ~600 zones. The browser already has the tz
> database; shipping our own copy would mean maintaining one that goes stale.

### 1b-v. Offices — done

```
Office (Phoenix)
├── Team: Enterprise → agents
└── Team: SMB        → agents
```

- [x] `office` table, `team.office_id` (nullable)
- [x] Offices page with team and agent counts
- [x] Office selector on the Teams page
- [x] Delete blocked while teams reference the office; archive/restore instead
- [x] Channels nav item — the TV guide, one channel per office

**This does not reinstate the hierarchy that was removed.** The old design was
_arbitrary-depth, self-referencing teams_ — that is what needed recursive
queries, cycle prevention, and depth limits. Office → Team → Agent is **two
fixed levels across separate tables**: an office cannot contain an office, so
there is nothing to recurse and no cycle to prevent. It is one nullable column.

**An agent's office is derived from their team, never stored twice.** Storing it
on the user as well would allow "Phoenix agent on a Dallas team", and every
report would then have to decide which one wins.

**Verified:** Phoenix rolls up 2 teams / 5 agents and Dallas 1 / 1, matching
their teams · deleting an office with teams returns 409 naming the count · an
empty office deletes cleanly · explicit `office_id: null` unassigns while an
omitted field leaves it alone · a nonexistent office returns 404 · a manager can
read offices but not create them.

> **Counting across two levels needs two subqueries, not one join chain.**
> Joining `office → team → user` in a single pass multiplies rows: an office
> with 2 teams and 5 agents would report 5 teams, because each team row repeats
> once per agent. Separate grouped subqueries, joined back independently, keep
> each count correct. This is the classic fan-out trap in SQL aggregation.

#### Channels — listed, not yet playable

The Channels tab is a **TV guide**: one channel per office, showing what each
office's screens will play. The feed itself — rotating leaderboards, goal
progress, live competitions, celebrations — needs metrics to exist, so it
arrives with leaderboards (1f) and competitions (phase 2). The guide is real
data with a disabled "Open feed" button rather than a fake preview.

**Open question:** whether a channel stays one-per-office or becomes a saved
configuration (a specific team, or a mix). Office-level is the current shape.

### 1c. Roles & permissions — done

- [x] Org roles: `admin | manager | agent`, enforced by a CHECK constraint
- [x] `require_role(...)` dependency, used by the SSO and teams endpoints
- [x] `visible_user_ids()` scope resolution (`app/scope.py`)
- [x] Service-layer scope enforcement (scope filters the query, never the response)
- [x] Managers can now assign teams, within their own scope
- [x] Capability map in `/api/auth/me`, replacing direct role comparisons in the UI
- [x] `<Can do="...">` and `<RequireCapability>` on the client
- [x] `audit_log` table, audit writes on every privileged mutation
- [x] `GET /api/audit` and a Recent activity panel on Settings

**Two questions, kept apart.** _Scope_ asks which people's data you may see;
_capabilities_ ask which actions you may perform. An admin has both. A manager
holds `users.assign_team` — the capability says yes, and scope narrows it to
their own team. Merging the two would mean re-answering "which rows?" inside
every permission check.

| Role        | Scope                                                   |
| ----------- | ------------------------------------------------------- |
| **admin**   | Everyone in the organization                            |
| **manager** | Their own team, plus agents on no team, plus themselves |
| **agent**   | Themselves                                              |

**Managers see unassigned agents on purpose.** Without that, a manager could
never pull a newly invited person onto their team — they would be invisible
until an admin placed them. That is the setup failure this product should be
surfacing, not hiding.

**Out of scope returns 404, not 403.** For a user a manager may not see,
confirming the account exists is itself information they are not entitled to.
403 says "that person exists and you can't touch them"; 404 says nothing.

**The capability map is resolved server-side and sent with `/api/auth/me`**, so
the UI asks "may I?" rather than re-deriving rules from a role string. Nav
items, route guards, and buttons all read the same list. Adding a fourth role
later changes one map in `app/scope.py` and the interface follows — no component
edits. Every capability is enforced on the endpoint as well; hiding a button
protects nothing.

**Audit rows commit in the same transaction as the change they describe.** They
cannot disagree: a rolled-back role change takes its audit row with it, and a
change can never be applied without being recorded. `record()` only adds to the
session — the handler's existing `db.commit()` writes it.

Actor and target emails are **copied into the row**, not joined at read time. A
rename or a departure would otherwise silently rewrite history, and the foreign
keys are `ON DELETE SET NULL` so a deleted account loses the link but not the
record of what it did.

**Verified:** a manager sees their team plus unassigned agents and not other
teams · pulling an unassigned agent onto their team works · pushing someone onto
a team they don't manage returns 403 · a manager changing a role returns 403 ·
acting on an out-of-scope user returns 404 · an agent gets 403 on
`GET /api/users` and holds only `teams.view`/`offices.view` · four privileged
actions wrote four audit rows · **five refused actions wrote zero rows, and none
half-applied** · a manager gets 403 on `GET /api/audit`.

> **Test the refusals, not just the permissions.** The first run of the
> out-of-scope check reported a hole — a manager PATCHing user 13 got 200. The
> code was right; the _test_ was wrong, because it assumed an id without
> checking who it belonged to (13 was already on the manager's own team). A
> security test that names the wrong subject proves nothing in either direction.
> Confirm the fixture before trusting the verdict.

> **A Python ternary silently picks one branch.** `visible_user_ids()` was first
> written as `UserAccount.team_id == actor.team_id if actor.team_id else
UserAccount.team_id.is_(None)` — which evaluates to a _single_ condition, so
> managers with a team never saw the unassigned agents the docstring promised.
> Two conditions need an explicit `or_()`. The docstring said one thing and the
> query did another; only running it caught the difference.

> **`visible_user_ids()` had to land before leaderboards.** Nothing needed it
> yet because no per-person data existed. The moment it does, retrofitting scope
> into queries that already work is exactly how data leaks — scope filters the
> query, and a query written without it has to be rewritten rather than adjusted.

**Also closed here:** `POST /api/users/{id}/resend-invite` was missing its scope
check, so a manager could reissue an invitation link for anyone in the
organization — including an admin. That link sets a password. Found by applying
the same rule to every handler rather than only the one being written.

### 1d. Metrics

Built in slices, because this is the largest single piece in phase 1:
**i** definitions · **ii** facts and demo data · **iii** aggregation ·
**iv** admin correction · **v** CSV import.

#### 1d-i — done

- [x] `metric_definition` table with CHECK constraints on unit, aggregation, direction
- [x] Eight seeded defaults, added when an organization is created
- [x] `GET/POST/PATCH /api/metrics`, archive, restore, delete
- [x] `POST /api/metrics/seed-defaults` — the recovery path
- [x] Metrics admin UI under Manage

**`key` is immutable.** Connectors, saved import mappings, and goals all
reference it, so renaming it would break each of them silently. `name` is the
editable label; `PATCH` with a `key` returns 422 rather than accepting it and
quietly dropping it, so a client is never told it renamed something it didn't.

**Defaults are seeded at organization creation, not by a migration.** Migrations
are structural and must behave identically forever; business defaults change as
the product learns what teams actually track. Seeding at setup lets the list
evolve without rewriting history. `POST /api/metrics/seed-defaults` is the
recovery path, and how an existing deployment picks up defaults added later.

The seeder skips by **key**, so a rename survives re-seeding. An absent key is
re-added — including a deleted one, which is what "restore defaults" should do.
Archiving, not deleting, is how you permanently opt out of a default.

**`direction` is not cosmetic.** "Calls Made" ranks descending; "Average
Response Time" ranks ascending. Every ranking and goal-progress calculation
reads it, and assuming bigger-is-better anywhere produces a leaderboard that
celebrates the worst performer. The form says so next to the control.

**Verified:** seeding twice creates 8 then 0 · a fresh organization gets all 8 ·
a rename survives re-seeding while a deleted key comes back · `Calls Made` as a
key returns 422 with the pattern explained · an unknown aggregation returns 422
· a duplicate key returns 409 · **the database CHECK rejects `median` even when
the API is bypassed entirely** · `PATCH {"key": ...}` returns 422 · redefining
the aggregation writes a `metric.redefined` audit row while a plain rename
writes none · archive hides it from the default list and restore brings it back
· a manager gets 403 on create but 200 on read.

> **Two naming-convention traps in one migration.** `ck` interpolates
> `%(constraint_name)s`, so naming a check `metric_definition_unit_valid`
> produces `ck_metric_definition_metric_definition_unit_valid`. But `uq` is
> `uq_%(table_name)s_%(column_0_name)s` — it never interpolates the given name,
> so an explicit `org_key` would be used **verbatim** as a schema-global index
> name. Checks take the bare name; unique constraints take the full one. Caught
> by reading the generated migration instead of trusting it.

> **Reads of metric definitions are open to every role.** An agent's dashboard
> has to know that Revenue Closed is currency with 2 decimals in order to format
> it. The definition is _what is measured_; it contains nobody's numbers. The
> page itself is admin-only, so there is no orphan page without a link to it.

#### 1d-ii — done

- [x] `metric_fact` table
- [x] Covering index for the leaderboard query, plus a per-person index
- [x] `subject_team_id` snapshot at event time
- [x] Partial unique index on `external_id` for idempotent re-syncs
- [x] `python -m app.seed_demo` generator, with `--clear`
- [x] Delete guards: a metric that has been measured, and a team history names

**`value` is NUMERIC(18,4), never a float.** Binary floating point cannot
represent 0.1 exactly, so summing a column of currency drifts. A revenue
leaderboard that is off by cents is a leaderboard nobody trusts.

**`subject_team_id` is a snapshot copied at write time, not a join.** This is
the one that would have been expensive to retrofit. Measured directly: moving
one agent from Enterprise to SMB moved **563 historical facts** between teams
when the query joined `user_account.team_id` live, and moved **zero** when it
read the snapshot. Without it, "who won Q1" changes every time somebody
transfers.

**No `updated_at` on this table**, unlike every other one. It holds millions of
rows, facts are corrected rarely, and the audit log already records who changed
what — a second timestamp per row is 8 bytes × millions to answer a question
something else answers better.

**The `external_id` unique index is partial** (`WHERE external_id IS NOT NULL`).
A connector replaying the same rows collides instead of silently doubling every
number; manual entries carry no external id and are unaffected. Postgres does
not collide NULLs in a unique index anyway, but the partial index is also much
smaller.

**Not partitioning yet.** 06-metrics-engine.md calls for monthly partitions and
a partition management job, and its own guidance is to add them when the table
gets large. At 500 users × 50 facts/day the covering index carries the query.
Partitioning an empty table buys complexity against a problem we can't yet
measure. `EXPLAIN` confirms `ix_metric_fact_leaderboard` is used with all three
leading columns as index conditions. Revisit with real row counts.

**Verified:** 3,081 facts across 120 days · re-running with the same seed
replaces rather than doubles · **zero facts land on a weekend and all fall
between 08:00 and 18:00 in the organization's timezone**, which is what proves
the local-time math (writing UTC midnight would have produced hour 0 and
weekend rows) · deleting a measured metric returns 409 naming the count ·
deleting a team history names returns 409 · archive still works · a metric with
no facts still deletes · `--clear` removed 3,081 generated rows and left a
hand-entered manual fact untouched · replaying an `external_id` is refused by
the index while two NULL-external manual rows coexist.

#### Demo data

    docker compose exec api python -m app.seed_demo --days 120
    docker compose exec api python -m app.seed_demo --clear

A module, not an endpoint — nothing reachable over HTTP triggers it. Every row
carries `source_type='import'` and an `external_id` prefixed `demo:`, so
`--clear` removes exactly what it created and nothing else. A seed script that
deletes data it did not create is one nobody runs twice.

Two details that matter more than they look:

**A fixed talent multiplier per person**, so the same people are consistently
ahead across every metric and month. Per-day noise alone produces a leaderboard
that reshuffles completely on each refresh, which reads as a ranking bug rather
than a demo.

**Revenue is derived from deals won**, not drawn independently. A board where
the top closer has the lowest revenue looks broken, and every correlation the
demo data lacks is a class of bug the UI cannot reveal.

Roughly 6% of working days are skipped per agent, so "no rows for this period" —
a real state the UI must handle — actually gets exercised.

#### 1d-iii — done

- [x] `app/periods.py` — org-timezone period math, half-open windows
- [x] `app/aggregate.py` — the single aggregation + ranking query
- [x] `POST /api/metrics/query`
- [x] `RANK()` / `DENSE_RANK()`, flipping to `ASC` for `lower_is_better`
- [x] `<MetricValue>` — one formatter every number goes through
- [x] Standings panel on the dashboard, so the numbers are checkable by eye

**Windows are half-open: `[start, end)`.** The end of one period is exactly the
start of the next. A closed interval double-counts anything on the boundary; a
gap loses it. Half-open is the only option that does neither — which is why the
code never writes `<= end`.

**Boundaries are computed in the organization's timezone**, then converted to
UTC for the query. Proved with a fact at **23:30 New York = 03:30 UTC the next
day**: it counts on the 13th and not the 14th. Bucketing by UTC would have it
backwards, and that single bug would misreport every daily figure for anyone
west of Greenwich.

**Quarters and years are fiscal.** A company whose year starts in April has a
Q1 of April–June; reporting January–March as "Q1" would simply be wrong for
them.

**`previous()` steps back one day from the start and re-resolves**, rather than
subtracting a fixed duration. Months are 28–31 days and DST makes some days 23
or 25 hours, so "minus 30 days" drifts. This always lands inside the correct
previous period.

**Ranking happens in the database.** Postgres already holds the aggregated rows,
so `RANK()` is free there; sorting in Python means transferring the whole set
and reimplementing tie handling. `RANK()` gives `1, 2, 2, 4` — the honest
default, and how sales contests actually work. `DENSE_RANK()` (`1, 2, 2, 3`) is
a per-query flag.

**Values cross the wire as JSON strings, not numbers.** The server stores
`NUMERIC(18,4)` exactly; JavaScript numbers are IEEE doubles. Serialising a
large currency total as a number would throw away the precision the column was
chosen for in the very last step.

**A manager's team total is complete, not partial** — a property worth noticing
rather than assuming. Their visible set is _their whole team plus unassigned
agents_, and the team grouping excludes people with no team. So the one team row
they see covers every member of it. Scope narrows which teams appear, never the
accuracy of a team's number.

**Verified (23 period-math assertions, all passing):** `week_starts_on` 0 vs 1
puts the same date in different weeks · an anchor already on the week start
stays put · fiscal quarters roll correctly across the FY boundary in both
directions · `FY2026/27` vs `2026` labels · **end of period N is bit-for-bit the
start of N+1 for all five period types** · the US spring-forward day is 23h and
the fall-back day 25h · March spans 31 days minus 1h · a custom range includes
its end date · `previous()` crosses a year boundary and a fiscal boundary.

**Verified (engine):** rows sum to `total` for both groupings ·
`lower_is_better` inverts the ranking and flipping `direction` back inverts it
again on identical data · ties produce `1,2,2,4` and `1,2,2,3` under the two
rank modes · an admin sees 6 people, a manager 5, and the manager's Enterprise
total matches the admin's exactly · a 23:30-local fact buckets into the correct
local day · `limit` truncates rows without changing `total` · unknown metric
404, unknown period type 422, custom without dates 400, reversed custom range
400, unknown `group_by` 422, `limit=100000` 422, unknown field 422 ·
`EXPLAIN ANALYZE` shows `ix_metric_fact_leaderboard` reading 52 rows to produce 6.

> **`total` had to learn about `group_by`.** It was first written as "the
> organization-wide figure" and returned 1761 while the team rows summed to
> 1551 — the 210 belonging to an unassigned agent, who appears in no team row.
> The docstring said "the same filters" and the code applied a different set.
> On screen that reads as an arithmetic bug. Caught by checking that the parts
> add up to the whole, which is worth doing every time a UI shows both.

#### 1d-iv — test suite — done

Taken ahead of admin correction, because everything after this point compounds
on top of period math and scope, and both had already produced real bugs.

- [x] pytest against a real Postgres, in a separate database
- [x] Schema built by running the real migrations, not `create_all()`
- [x] Per-test transaction rollback via savepoints
- [x] **270 tests**, 81% coverage overall

| Area                                                                 | Coverage                       |
| -------------------------------------------------------------------- | ------------------------------ |
| `scope.py`, `periods.py`, `metrics_query.py`, `audit.py`, `setup.py` | 100%                           |
| `auth.py`, `teams.py`, `sessions.py`                                 | 98–99%                         |
| `aggregate.py`, `users.py`, `metrics.py`                             | 93–95%                         |
| `offices.py`, `rate_limit.py`                                        | 85–86%                         |
| SSO (`sso.py`, `oidc.py`, `admin_sso.py`)                            | 25–50% — deliberately deferred |

**A separate database, not the development one.** A test can then never disturb
data you are looking at, and the 3,000 demo facts cannot skew an aggregation
assertion.

**The schema is built by running Alembic**, not `Base.metadata.create_all()`.
`create_all` builds the schema the _models_ describe — which is exactly what a
broken migration would fail to produce, so the suite would pass against a
schema no deployment will ever have. Running the migrations means every test
run also proves the migration chain applies cleanly.

**Each test gets a transaction that is rolled back.** The session joins an
already-open transaction with `join_transaction_mode="create_savepoint"`, so
the `db.commit()` calls inside request handlers become savepoint releases —
handlers run exactly as they do in production while the outer transaction is
discarded. Deleting rows afterwards instead would leave debris whenever a test
failed midway, making the next run's failure a mystery.

**The suite was mutation-tested before being trusted.** Four deliberate bugs
were reintroduced and every one was caught:

| Mutation                                                            | Caught by |
| ------------------------------------------------------------------- | --------- |
| Ignore `metric.direction` (always rank descending)                  | 2 tests   |
| `total()` ignores `group_by` — _the bug actually shipped in 1d-iii_ | 1 test    |
| Half-open window becomes closed (`<= end`)                          | 1 test    |
| Week start uses Python's `weekday()` directly                       | 3 tests   |

A suite that has never been shown to fail is a suite nobody has checked.

##### Two real bugs found by writing the tests

> **A manager could see, and act on, an unplaced admin.** `visible_user_ids`
> admitted _anyone_ with no team, and an admin has no team by default. The
> docstring had always said "agents on no team" — the query said something
> else. The exposure: an admin account still in `invited` status was visible to
> every manager, so a manager could POST `resend-invite`, receive the link, and
> set that admin's password. Fixed by adding `org_role == "agent"` to the
> unplaced branch, with three named regression tests confirmed to fail against
> the old code.
>
> This is the **third** time a docstring and its query disagreed — the scope
> ternary, `total()` and `group_by`, and now this. All three were caught by
> asserting the exact expected set rather than a sample of it. Asserting only
> "the manager sees their teammate" would have passed on every one.

> **An audit write could fail the request it was recording.** `ip_address` is
> `INET`, and any value Postgres cannot parse as an address makes the INSERT
> raise — taking down the role change or suspension being logged. Fixed with
> `app/net.py:client_ip()`, which validates with `ipaddress` and stores NULL
> rather than guessing. Now used by the audit log, login attempts, and session
> creation — all three write to `INET` columns.

##### What is deliberately not covered

SSO end-to-end (25–50%). Every rejection path was verified by hand; the success
path needs a real Microsoft-issued token. Still the one item marked done that
is not proven — unchanged from 1a.

`seed_demo.py` (0%) is a development tool with no production path.

#### 1d-v — admin correction — done

- [x] `POST/PATCH/DELETE/GET /api/metric-facts`, scoped
- [x] `corrected_at` + `corrected_by_user_id` on `metric_fact`
- [x] Every write audited in the same transaction
- [x] Corrections page, reachable from Metrics rather than the sidebar
- [x] 38 tests, three mutations confirmed caught

**Agents have no write path at all.** Not a permission toggle that happens to
be off — the endpoints reject them. Hand-keyed numbers from the people being
measured is precisely what makes a leaderboard worthless.

**`source_type` is not an accepted request field.** Letting a caller label its
own row would allow a hand-typed number to arrive marked "connector", defeating
the entire point of distinguishing them. The endpoint sets `manual` itself.

**The correction flag is a column, not something derived from the audit log.**
Two reasons. The connector sync (phase 3) has to ask "did a human change this
row?" for every row it is about to overwrite, and answering that by scanning
JSONB in `audit_log` would be slow and fragile. And it cannot be added
retroactively — a correction made before the column existed is
indistinguishable afterwards, so the flag has to be in place from the _first_
correction, which is why it ships with this tool rather than with the
connectors that will eventually read it.

Editing an imported row keeps `source_type = 'import'` and sets the flag, so
the UI can say "edited by hand" rather than "entered by hand". Both are marked;
the distinction is preserved.

**Metric and subject are immutable on edit.** Moving an entry to a different
person is a delete and a create, not a correction — doing it in one step would
leave an audit row reading "value changed" while something else entirely
happened. The form says so rather than silently disabling the control.

**Deletion is hard, not soft.** `metric_fact` is the hot table, and a
`deleted_at` column would mean every aggregation query needs a
`WHERE deleted_at IS NULL` that somebody eventually forgets — silently
resurrecting deleted numbers. Nothing is lost: the audit row carries the
metric, person, value, and date, so a deletion is fully reconstructable. There
is a test asserting exactly that, because it is the only thing that makes the
hard delete defensible.

**Date bounds: two days ahead, five years back.** Not zero tolerance on the
future — a fact recorded in Sydney is already "tomorrow" for a server on UTC,
and refusing it would make the tool unusable there. Not unbounded either: a
typo'd year lands somewhere nobody looks and quietly inflates a yearly total
that has not been opened yet. Backdating stays generous because loading a year
of history before switching on a connector is a legitimate first-day task.

**The date input writes midday, not midnight.** A date-only field has no time,
and midnight sits exactly on a period boundary — one timezone conversion either
way and the entry lands in the wrong day.

**On the Corrections page and not the sidebar.** The doc called for it to stay
out of the main navigation; hiding it entirely would make it undiscoverable,
which is the failure mode this project explicitly avoids. It is linked from the
Metrics page, which is where someone already is when they notice a number is
wrong.

**Verified:** an admin records 25 → Dan's month moves 229 → 254 → edited to 40
→ 269 → deleted → back to 229, with the org total tracking every step · a
hand-entered row reports `source_type=manual, corrected=true` · a client
sending `source_type: "connector"` gets 422 · editing an imported row keeps
`import` but sets the flag · a no-op edit sets no flag and writes no audit row ·
a far-future date 400s while tomorrow is accepted · an archived metric 409s ·
an agent gets 403 on all four verbs · a manager sees only their own scope and
404s on an SMB agent · a refused write leaves the row untouched and the audit
log unchanged.

> **Mutations confirmed caught:** dropping the scope check on the subject
> (2 tests), marking rows corrected when nothing changed (2 tests), and
> deleting without the audit row (2 tests). The first attempt at the third
> mutation produced a syntax error rather than a behaviour change, so it proved
> nothing — a malformed mutation is a passed test that means nothing, and worth
> re-running properly.

#### ~~1d-vi — CSV / Excel import~~ — dropped

**Dropped, not deferred.** Data comes from integrations; hand-keyed numbers are
what make a leaderboard untrustworthy, and an import screen is a supported,
signposted way to produce them at scale. Building it would have contradicted
the principle the rest of the product is arranged around.

What it was for is covered: `seed_demo` for development, connectors for
production (phase 3), and the correction tool for the narrow case of fixing a
bad row.

The gap it leaves is real and worth naming: a deployment whose connector is not
configured yet has **no bulk way in**. If that turns out to matter, the answer
is a connector that reads a file — an integration with a mapping and a sync
history, marked `source_type='import'` and visible as such — not a page that
invites typing.

Nothing depends on it: `metric_fact` accepts `source_type = 'import'` already,
and the correction endpoints cover single-row fixes.

### 1e. Goals

Sliced: **i** one-off goals and progress · **ii** pace · **iii** recurrence and
the spawning job · **iv** guided creation.

#### 1e-i — done

- [x] `goal` table, one subject per goal
- [x] `app/goals.py` — progress off the aggregation engine
- [x] `GET/POST/PATCH/DELETE /api/goals`, archive, restore
- [x] Goals page with progress bars, "Your goals" on the dashboard
- [x] 51 tests, three mutations confirmed caught

**Progress is never stored.** It is the same `aggregate` query the leaderboards
run, narrowed to one subject, so a goal and a leaderboard showing the same month
cannot disagree. A stored `current_value` would be wrong the moment a connector
backfilled yesterday's data.

**The period is stored as it was chosen** — a type plus an anchor — not as
resolved timestamps. "August 2026" then survives a change to the organization's
timezone and keeps meaning the same thing as the August leaderboard.

**Four CHECK constraints**, because each describes a goal that could exist but
could never be rendered: exactly one subject matching `subject_type`; a valid
period type; period columns matching that type (custom needs both dates, every
other type needs an anchor); and a target greater than zero.

**Dropped from the original design: `goal_assignment` and `target_override`.**
One goal carrying several assignments means a join table, a second progress
path, and a rule for what the parent's percentage means when its children
disagree. One goal, one subject is a row — two goals expressing the same intent
are two rows, and a grouping can be added later if anyone asks. Building the
harder version first would have been designing against a guess.

**The percentage is uncapped at the top end** (to 1000%) while the bar clamps
to 100%. Beating a target is the point; a bar that renders at 150% of its
container breaks the layout.

**Verified against real demo data:** Dan W at 229/200 reads 114.5% and HIT,
229/500 reads 45.8% · Enterprise at 1174/1000 and revenue 347,344.64/150,000
over a quarter · the numbers match the standings panel exactly · a manager sees
their team's goals via `?mine=true` and gets "You can only set goals for your
own team" for another · an agent sees only their own and their team's · adding a
fact moves the percentage with no invalidation step · facts outside the period
do not count · a team goal uses the snapshot, so moving someone does not move
their history.

> **Mutations confirmed caught:** treating `lower_is_better` like a count
> (3 tests), joining live team instead of the snapshot (1), and dropping the
> manager's own-team check (1).

#### 1e-ii — pace — done

- [x] `app/pace.py` — elapsed time, expectation, projection, status
- [x] Pace marker on every progress bar
- [x] `GET /api/goals?needs_attention=true`
- [x] "Needs attention" on the dashboard, replacing the placeholder
- [x] 33 pace tests, four mutations confirmed caught

**Elapsed time is counted in WORKING DAYS, not calendar days.** This is the
decision the whole feature rests on.

A month goal checked on Monday morning has had two calendar days pass since
Friday and zero selling days. Calendar pacing would tell every agent they had
fallen behind over the weekend — every weekend, on a schedule — and a warning
that cries wolf predictably gets ignored within a fortnight, taking the honest
warnings with it. There is a test asserting Saturday, Sunday and Monday morning
all read the same, and another asserting a weekday still advances, so the first
cannot be satisfied by a function that never moves.

Mon–Fri with no holiday calendar is an **assumption**, not a fact about any
company. A team working Sunday to Thursday would be paced wrongly, and public
holidays count as working days. Worth making configurable once there is a real
calendar to configure it against; inventing the schema now would be guessing.

**The current day counts only once it is over**, so nobody is told they are
behind at 9am for work the day still has time to produce.

**Pace only applies to metrics that accumulate** — `sum` and `count`. An `avg`
is not "a third of the way" to anything on the 10th, and projecting a running
average linearly produces nonsense. Those goals still show elapsed time, which
is a fact about the calendar, but no expectation and no projection, because
there is no honest one. The bar says "averages are not paced" rather than
leaving a marker-less bar looking unfinished.

**A tolerance band of 5 points**, so a goal does not flicker between ahead and
behind on every recorded fact — instability reads as unreliability.

**A closed period reports `missed`, not `behind`.** Calling it behind implies
there is still time.

**Verified against live data** on Thu 13 Aug: 8 of 21 working days elapsed =
38.1%, today correctly not counted; 229 recorded projects to 601 for the month;
targets of 150 / 260 / 600 / 2000 produce hit / ahead / on_track / behind, and
only the last appears under `needs_attention`.

> **A goal with no data at all reported HIT.** Found by creating a
> `lower_is_better` goal against real data: nothing recorded reads as zero, and
> zero is under every cap, so "keep average response time under 60 seconds"
> congratulated an agent who had answered no calls. `current_value()` now
> returns whether any facts existed, and attainment requires them. A goal that
> rewards doing nothing is worse than no goal.
>
> The unit test that "covered" this had asserted `(0, 60) -> attained` — which
> is correct for a _measured_ zero, and exactly why the bug survived it. The
> two cases now have separate tests saying which is which.

#### 1e-iii — recurrence — done

- [x] `recurring`, `recurrence_ends_on`, `spawned_from_goal_id` on `goal`
- [x] Partial unique index making a duplicate spawn impossible
- [x] `app/jobs.py` — `python -m app.jobs`, with `--dry-run`
- [x] Hourly job loop in the API lifespan, under an advisory lock
- [x] "Repeat every period" on the goal form, marker on the card
- [x] 23 job tests, four mutations confirmed caught

**Idempotency is enforced by the database, not by the job.** A partial unique
index on `(spawned_from_goal_id, period_anchor)` makes a second spawn for the
same source and period impossible. The job does not check whether a copy
already exists — a check-then-insert is a race: two replicas, or one restarted
between the check and the insert, both see nothing and both write.

Proved by mutation: **dropping the index makes running the job twice create two
copies.** The index is load-bearing, not decorative.

Partial on purpose, so ordinary goals are untouched — two manual goals for the
same person, metric, and month with different targets (a minimum and a stretch)
stay perfectly legal.

**No template row.** A recurring goal is a real goal for its own period that
also spawns copies for later ones. A template would be a row with no progress
that every query then has to remember to exclude.

**Every copy points at the original**, never at the previous copy. A chain of
parent links would make "has this period been spawned?" a recursive walk;
pointing at the root makes it the one indexed lookup the unique index needs.
A copy never recurs further, so the chain stays one level deep and cannot fork.

**The target is copied, not referenced.** Raising next month's target must not
silently rewrite what last month was judged against.

**A long gap spawns only the current period.** Six months of missed runs do not
produce six back-dated goals nobody saw — targets for closed periods are noise,
and inventing the history of what was asked for is worse than a gap in it.

**A plain loop, not APScheduler.** The only schedule needed is "every so
often", and idempotency already handles missed and duplicate runs — which is
most of what a scheduler library buys. Hourly rather than daily-at-a-time
removes the whole "the container was down at 02:00" class of problem. It runs
in the API lifespan so a deployment is still one `docker compose up`, in a
thread so a slow query cannot block request serving, and under a non-blocking
advisory lock so several replicas do not duplicate the work.

**Verified:** created mid-month, the job reports `skipped` rather than spawning
· two more runs change nothing · Sep 1 spawns, Sep 28 skips, Oct 3 spawns, Oct
30 skips · restarting the API re-runs the job and the chain still holds three
goals · a custom range refuses to recur with a message, not a constraint name.

> **A recurring goal spawned a duplicate of itself on the very first run.**
>
> The API defaulted `period_anchor` to _today_, so a goal created on the 13th
> stored `2026-08-13`, while the job normalised to the period start,
> `2026-08-01`. Two different dates naming the same month — so the "already
> covered" check compared unequal values and spawned a second August goal.
>
> Fixed at both levels: anchors are now stored canonically (the period's start,
> whatever date the client sends), and the job compares _resolved periods_
> rather than raw dates, so rows written before that still behave.
>
> Every unit test had used `date(2026, 8, 1)` — the already-normalised form —
> which is exactly why twenty of them passed over it. **The fixtures were
> idealised, and only creating a goal through the real API exposed it.** Worth
> remembering when a fixture builds data by hand that a user would never
> produce that way.

#### 1e-iv — guided creation — done

- [x] `POST /api/goals/preview` — last 6 complete periods, average, best, suggestion
- [x] The preview wired into the goal form, with a "use this" button
- [x] Live assessment of the typed target against that history
- [x] Daily added to the period options
- [x] Editing an existing goal, rather than delete-and-recreate
- [x] Archived view, with restore and delete

**The form is ordered metric → subject → period → history → target.** The period
decides which history is relevant, and the history is what the target should be
argued from. Asking for the number first would make the panel below it a
post-hoc verdict rather than something to reason with.

**Six bars, drawn with divs.** A charting dependency would be ~60KB to render
six rectangles with no axes, tooltips, or interaction. Empty periods get a 2px
floor so they read as empty rather than absent — a gap in the row looks like a
rendering fault.

**The assessment is an observation, never a refusal.** "At or below the recent
average", "beyond the best of the last six" — a stretch target above anything
previously achieved is a legitimate thing to set on purpose, and so is an easy
one for someone returning from leave.

**A failed preview is silent.** It is an aid, not the task; it must never stop
someone setting a goal.

**Archived goals** get their own tab, dimmed and dashed so they do not read as
live. Their actions are Restore and Delete — editing a goal that no longer
counts would be confusing, and delete stays for ones archived by mistake. The
API has no "archived only" flag; narrowing an already-authorised list in the
browser is presentation, unlike scope, which stays in the query.

### 1e complete

Goals, pace, recurrence, and guided creation. **99 tests across
`test_goals_api`, `test_pace`, `test_jobs`, and `test_goal_preview`**, with
twelve mutations confirmed caught across the four slices.

**The current period is excluded from the preview.** It is partway through, so
counting it drags the average down and suggests a target below what the person
actually achieves.

**Empty periods are excluded from the average, not counted as zero.** Someone
who joined three months ago has empty periods before that; averaging them in
halves their target for a reason unrelated to performance.

**Suggestions round by magnitude, not by unit.** The first version kept full
precision for currency — "money is exact" — and produced a suggested revenue
target of **$216,026.54**, which is exactly the "reads as a calculation"
problem the rounding exists to prevent. 196k average now suggests $220,000.

**Editing:** target, name, period, and recurrence are editable; metric and
subject are not. Changing the period _kind_ without naming one re-anchors to
the current period — otherwise month → quarter → month landed a month earlier,
because August's start is also Q3's start.

> **Two verification mistakes, both mine, in one session.** A `curl -o
/dev/null` hid a 400 and made a correctly-refused PATCH look like a silent
> no-op; and a test expectation computed the rounding step from the average
> rather than the stretched value. Neither was a code fault. Both are the same
> shape as the malformed mutations earlier: **an unreadable result looks
> identical to a passing one.**

#### Two items from the original 1e checklist

- [x] **`<GoalCard>` with pace marker** — built as `<GoalProgress>`.

    There is no component called `GoalCard` because goals appear three ways: a
    full card on `/goals`, a compact item in "Your goals", and a row in "Needs
    attention". Those are genuinely different presentations, and the piece worth
    sharing is the bar — which is shared by all three. A wrapper with three modes
    would be worse than three small call sites over one component.

- [x] **Goal detail page** — deferred to after 1f/1g, deliberately, and built
      later (`/goals/:id`; Edit and Archive added in 5h).

    The list is done; there is no `/goals/:id` route. What a detail page is for
    is mostly things that do not exist yet:

    |                                  | Status                                               |
    | -------------------------------- | ---------------------------------------------------- |
    | Who contributed, for a team goal | Free — `group_by=user, team_id=X` already works      |
    | History of target changes        | Cheap — in `audit_log`, not exposed per goal         |
    | **Trend across the period**      | **Needs bucketed aggregation, which does not exist** |

    `aggregate.run()` groups by user or team, never by time bucket, so a trend
    chart needs new backend work — and it is the same work 1g dashboards needs.
    Building it now would produce a thin page plus a bucketing API shaped around
    one caller. After 1f and 1g it reuses their machinery and the page is worth
    opening.

    Revisit at the start of 1g, or sooner if anyone asks "why did this goal move?"
    and has nowhere to look.

### Integrations page — shell built

Tiles, a Connected/Available split, and a modal panel per integration. The
Microsoft 365 tile is **real** — it reads and writes the existing `sso_config`,
so enabling SSO genuinely moves it between the two lists and simultaneously
puts the button on the login page. SMTP is a tile plus a disabled panel showing
the fields it will need.

**Connections are organization-wide.** Whoever signs in while connecting is the
account used from then on, for everyone. Said on the page, because it is the
detail most likely to surprise someone.

The target for account-linked integrations (Excel, SharePoint) is an OAuth
popup — "sign in with Microsoft", consent, done — not a credentials form.
Microsoft 365 asks for issuer/client id/secret today only because provisioning
an app registration automatically needs admin consent through Graph, which is
phase 3.

**Verified:** enabling SSO moves the tile to Connected and turns Connect into a
settings cog, and `/api/auth/providers` starts advertising the button in the
same moment · disabling reverses both · the SMTP tile renders disabled with its
panel explaining what is missing.

### 1f. Leaderboards

Sliced: **i** the table, visibility, and results · **ii** the pages ·
**iii** medals and polish · **iv** TV display and the Channels feed.

#### 1f-i — done

- [x] `leaderboard` table with 8 CHECK constraints
- [x] Visibility model: `org` · `team` · `private`
- [x] `GET/POST/PATCH/DELETE /api/leaderboards`, archive, restore
- [x] `GET /api/leaderboards/{id}/results` with movement and a pinned viewer row
- [x] Rolling windows (`rolling_7`, `rolling_30`) in `periods.py`
- [x] 40 tests, five mutations confirmed caught

**A leaderboard deliberately breaks the scope rule.** Everywhere else since 1c,
an agent sees only their own numbers. A published board must show them every
entrant — a board of one row is not a ranking, and public ranking _is_ the
motivational mechanism.

The control moves from _who you are_ to _what the publisher chose to publish_,
and it stops at the board. Verified explicitly: an agent who can see every name
on an org board still gets 403 on `/api/users` and `/api/metric-facts`, and the
general query endpoint still narrows to them alone.

**The bypass is an explicit argument, not a boolean.** `aggregate.run()` takes
`visible=EVERYONE` at the call site rather than an `unscoped=True` flag. A
boolean on a security-critical function is the kind of thing that gets switched
on by accident; a named value that has to be passed is not. The sentinel is a
distinct object because `None` already means EVERYONE — without it, "unscoped"
and "forgot to pass anything" would be indistinguishable, and the unsafe one is
the easier mistake.

**Two questions kept apart:** `visibility` decides who may _look_; `scope`
decides who _appears_. A manager may build a board for their own team but
cannot publish one organization-wide — that is publishing their team's numbers
to everyone, which is not theirs to decide.

**Rolling windows exist because calendar boards are actively bad.** A monthly
board resets to near-empty on the 1st, so the boards people check most are
exactly the ones a calendar boundary damages most. A rolling window always has
data — and unlike every other period, it _includes today_, because a board
ignoring what happened this morning is not one anyone opens.

Their predecessor is the whole window before, not one day back. Re-resolving
from "the day before the start" would overlap by six days out of seven and
report nobody moving.

**Movement is computed, never stored** — a stored rank would be wrong the
moment a connector backfilled a day, exactly like a stored score. A new entrant
gets `null`, not `0`: arriving is not "did not move".

**`period_type` excludes `custom`.** A board pinned to a fixed past range stops
changing, which is the opposite of what a leaderboard is for.

**Verified:** an org board shows an agent all six entrants while `can_edit` is
false · a team board 404s for someone on another team · a private board is
absent from the list and 404s on read · a manager publishing org-wide gets a
sentence, not a constraint name · `RANK` gives 1,2,2,4 and `DENSE_RANK` gives
1,2,2,3 on the same data · a rolling board excludes an entrant whose only fact
is ten days old.

> **Mutations confirmed caught:** `can_view` always true (2 tests), dropping
> `visible=EVERYONE` (2), flipping the movement sign (1), letting a manager
> publish org-wide (2), and not filtering the list by visibility (2).

#### 1f-ii — the pages — done

- [x] `/leaderboards` — cards with each board's top three already filled in
- [x] `/leaderboards/:id` — the full table, with period stepping
- [x] `<LeaderboardTable>` — podium colours, movement, pinned viewer row
- [x] Builder modal, with the shape rules enforced in the form
- [x] Podium tokens in `theme.css`, tuned per theme

**The list shows the top three, not just names.** A list of board _names_ is a
menu; the point of a leaderboard page is to learn something without clicking.
One request per card, and there are a handful of cards.

**Movement is a glyph plus a number, never colour alone.** ▲2 and ▼2 differ by
shape as well as hue — roughly one man in twelve cannot rely on the colour.
A new entrant reads "new"; someone who held their place gets a dash rather than
"0", so the eye skips them and the movers stand out.

**The viewer's row is pinned below the cut**, with a rule above it. Being 14th
on a top-10 board is exactly when a person most wants to know where they are,
and a truncated board gives them nowhere to look. It is omitted when they are
already on screen — returning it anyway would draw them twice.

**Podium colours are real metals**, added as tokens rather than reused from the
palette: a gold that is really the warning amber reads as a warning, and the
top three is the one place in this product where a literal colour carries
meaning. Both themes have their own values — the dark-mode gold is invisible on
white.

**The builder only offers what it can save.** A manager cannot publish
organization-wide, so "Everyone" is absent from their options rather than
offered and rejected on submit. Scope and visibility move together, because
"visible to the team" needs a team to mean.

**Publishing org-wide carries a warning in the form** — it is the one place
this product shows someone data about colleagues they cannot otherwise see, and
that deserves saying rather than discovering.

**Rolling boards cannot be stepped through.** They are defined relative to
today, so a "previous" rolling window has no name anyone recognises.

**A team board highlights your team's row, not yours.** Matching a user id
against team ids would highlight nothing, or the wrong team.

**Verified against live data:** a top-3 board shows 3 of 6 with the admin
pinned at rank 6 and an agent pinned at rank 5 · stepping back a month changes
every figure and keeps the pinning · "up 1" appears where the order actually
changed · all three visibilities render their own badge.

#### Office leaderboards — done

- [x] `metric_fact.subject_office_id` — a second snapshot, backfilled
- [x] `group_by="office"` and an `office_id` filter in `aggregate`
- [x] `scope_type='office'` and `entity_type='office'` on `leaderboard`
- [x] Office scope in the builder, admin-only
- [x] Delete guard: an office history names cannot be removed

**Office needed its own snapshot, exactly like team.** Office was only
reachable through `team.office_id`, which is _current_ state — so a team moving
office during a restructure would have handed every past fact to the new one.
Measured before building it: one office held **2,649 facts through two teams**,
all of which would have moved.

This is the same reasoning as `subject_team_id`, where a single transfer was
measured to move 563 facts. Two snapshots, no joins to live structure: every
grouping key on a board is a column on `metric_fact`.

The migration backfills from `team.office_id`, which is the best available
answer and not a perfect one — any team that had _already_ moved has its
history attributed to the new office. From that point the value is frozen at
write time and stops drifting, which is the whole point.

**Office boards are admin-only to build.** An office spans several teams, so
scoping a board to one is a cross-team decision. A manager can build for their
own team and nothing wider.

**Verified:** Phoenix 229,176.75 vs Dallas 80,391.62 on a revenue office board
· an office-scoped board lists that office's five people · moving a team
between offices leaves the old office's historical figures unchanged · deleting
an office with 602 facts returns 409 naming the count · a manager gets "Only an
admin can build an office board".

> **Alembic silently left two CHECK constraints at their old definitions.**
> `entity_type IN ('user','team')` and the old `scope_matches_type` survived the
> autogenerated migration, so every `office` row was rejected by the database
> while the code believed it was valid. The plugin detects an _added_ check but
> not a _changed_ one — the identical trap that bit the `viewer` role removal in
> 1b, and the second time this project has paid for it.
>
> Fixed by hand in the same migration, drop-and-recreate with `op.f()`, plus a
> downgrade that clears office rows first because narrowing would otherwise
> fail on them.
>
> The test database also had to be dropped: it was migrated before the fix, and
> Alembic considers a revision applied by id, not by content. **Editing an
> applied migration does not re-run it.**

#### 1f-iii — done

- [x] Measured the board query at 4M facts before deciding anything
- [x] `INCLUDE (value)` on the leaderboard index — **7,423ms → 12ms**
- [x] CSV export, with formula-injection defence
- [x] ~~Result caching~~ — measured, not needed

**Caching was the wrong fix, and measuring is what showed it.**

At 4 million facts the board took **7.4 seconds**. The plan named the culprit:
an Index Scan reading 40,990 rows in 7,370ms — roughly 180μs per row, which is
random heap I/O, not index work. `ix_metric_fact_leaderboard` did not contain
`value`, so every matching row cost a heap fetch.

Adding `INCLUDE (value)` and letting VACUUM set the visibility map turned it
into a true Index Only Scan:

|                                                | Time       |
| ---------------------------------------------- | ---------- |
| Original index, 4M facts                       | 7,423 ms   |
| `INCLUDE (value)`, not yet vacuumed            | 2,116 ms   |
| `INCLUDE (value)`, vacuumed                    | **12 ms**  |
| End-to-end through the API, including movement | **~35 ms** |

A cache would have hidden a 600× fixable problem behind an invalidation
strategy, and every stale-data bug that comes with one. **The doc's own advice
— add optimisation when something is measurably slow — is only useful if you
also measure what is actually slow.**

> **My own comment was the misdirection.** The index carried a note saying
> "every column it touches is here, so Postgres can answer from the index
> without visiting the table". It did not; `value` was missing. The claim sat
> there unchallenged from 1d-ii until somebody measured — the fourth time in
> this project a comment and its code have disagreed.

> **Autogenerate does not compare INCLUDE clauses either.** It saw no change to
> the index and emitted nothing, exactly as it missed the changed CHECK
> constraints one migration earlier. Hand-written, with `CREATE INDEX
CONCURRENTLY` inside an `autocommit_block()` — building an index on
> `metric_fact` otherwise locks a table every write path touches.

##### CSV export

`GET /api/leaderboards/{id}/results.csv`, same visibility rules as the board.

**It exports every entrant, ignoring `display_limit`.** That is a drawing
decision; a truncated spreadsheet is the kind of thing that gets pasted into a
report without anyone noticing what is missing.

**Formula injection is the real risk, not commas.** A cell beginning `=`, `+`,
`-`, or `@` is executed as a formula by Excel, Sheets, and LibreOffice — and
names are user-supplied. `=cmd|'/c calc'!A1` as a display name becomes
executable the moment a colleague opens the export. Quoting does not help; the
spreadsheet strips quotes and evaluates what is inside. A leading apostrophe is
the fix, and numbers are exempt so a column of figures stays summable.

Also: a UTF-8 BOM, because Excel on Windows otherwise reads the file in the
local codepage and mangles every non-ASCII name; a sanitised
`Content-Disposition` filename, because a board named `../../etc/passwd` or one
containing a quote would otherwise reach a header; and a generator rather than
one string, because this is the one endpoint that can be asked for every row a
deployment holds.

**Verified:** 26 tests including seven injection payloads, the end-to-end case
with a hostile display name, an agent exporting a board they can read, a
private board 404ing, and a top-2 board exporting all five rows.

#### 1f-iv — done

- [x] `display` table — a screen authenticated by URL, token readable
- [x] `GET /api/display/{token}` — the only unauthenticated endpoint here
- [x] `/display/:token` page, outside the app shell
- [x] Channels rewritten: what is playing, and which screens are connected
- [x] "Show on wall displays" in the board builder
- [x] 24 tests, three mutations confirmed caught
- [x] Screens list carries each link, with open / copy / revoke per row

**A display URL is the entire credential.** A TV has no keyboard and nobody to
log it in, so it holds a long-lived secret in its address bar — and anyone who
photographs the screen has it. Three things make that acceptable:

- It grants **one channel, read-only**. Verified: presenting the token as a
  session cookie returns 401 from `/api/auth/me`, `/api/users`,
  `/api/leaderboards`, and `/api/metric-facts`.
- **Only boards published to the whole organization are eligible**, enforced
  by a CHECK constraint as well as the API. A wall screen has no audience
  control at all — anyone walking past reads it — so it can never show
  something its audience could not see by signing in.
- It is revocable in one click, and `last_seen_at` distinguishes a live
  screen from one unplugged months ago.

**The token is stored readably** — the one credential in this system that
is, and a deliberate exception.

It was hashed first, on the same reasoning as session tokens, and the URL was
shown once at creation. That failed the way it was actually used. A wall
display is set up by somebody walking to a TV, often days after the link was
issued, and the link frequently has to go to whoever is standing next to it.
An unrecoverable link means either reissuing constantly, or admins keeping the
URLs in a note somewhere far less protected than this table — so the hash
bought no real secrecy and cost the workflow.

What makes the trade affordable is how little the token grants: one channel,
read-only, boards already published to the whole organization, revocable in
one click, and displayed on a wall all day regardless. It is closer to an
unlisted URL than to a password. Only an admin can list them, which is the
control that actually matters and is covered by a test.

This is not a precedent. Session tokens, invitations, and password resets stay
hashed — each of those grants a person's full account, none of them needs to
be recoverable, and every one of them is single-use.

**Consequence:** `last_seen_at` now means "this link was fetched", not "a TV
fetched it" — an admin opening the link from their desk is indistinguishable
from the screen doing it, because it is the same URL. Named honestly rather
than worked around.

**`last_seen_at` is throttled to five minutes.** The column answers "is this
screen alive", a question nobody asks more than daily; writing on every poll
would be a database write every few seconds per screen, forever.

**An office channel plays that office's boards plus the organization-wide
ones.** A board about a different office is noise on that wall.

**The page never shows an error to a room.** A failed poll keeps the last good
board on screen with a small "Reconnecting…" note — a leaderboard from ten
minutes ago is far more useful to a room than a stack trace. Only a 404, which
means revoked, replaces it, because a screen frozen forever is worse than one
saying it has been disconnected. The refresh interval comes from the server, so
the rate is an operational setting rather than something baked into a browser
nobody can reach.

**Verified live:** a Phoenix screen with no session returns two slides —
`Calls - last 30 days` and `Offices by revenue` — while the token 401s on every
other endpoint and the feed contains no email addresses. Marking a private
board for display returns "a board on a wall display has to be visible to
everyone".

> **Mutations confirmed caught:** a revoked token still working, non-TV boards
> appearing on the wall, and an office screen showing every office's boards.

> **The API let a private board through to the database.** The CHECK constraint
> refused it correctly, but as an unhandled `IntegrityError` — a 500 rather
> than a sentence. Found by a test asserting the refusal and getting the wrong
> shape of one. The database is the guarantee; the API owes the readable
> answer, and this is the second time a constraint has been the only thing
> standing there.

### 1f complete

Leaderboards, pages, measured performance, CSV export, and wall displays.
**88 tests** across `test_leaderboards_api`, `test_csv_export`, and
`test_displays_api`, with eleven mutations confirmed caught.

#### Original 1f checklist

As first written; ticked when 1f closed, and kept for the record.

- [x] `leaderboard` table
- [x] Ranking query with `RANK()`, direction-aware
- [x] Movement calculation
- [x] Team aggregation (total and per-member)
- [x] Leaderboard builder with live preview
- [x] `<LeaderboardTable>` with medals, movement, pinned viewer row
- [x] ~~Result caching~~ — measured, not needed (see above)

### 1g. Dashboards

#### 1g-i — done

- [x] `GET /api/dashboard`, composed server-side per role
- [x] Personal: where you stand on every board you can open
- [x] Manager: quiet people, scoped
- [x] Admin: health — is data still arriving, and what is not wired up
- [x] CSV export on tables — done in 1f-iii for leaderboards
- [x] 23 tests, four mutations confirmed caught

**Three questions wearing one page**, and the arrangement is the feature:

| Role    | Question                              |
| ------- | ------------------------------------- |
| agent   | how am I doing, and where do I stand? |
| manager | who on my team needs me today?        |
| admin   | is this thing working?                |

Showing everyone everything would answer none of them. An agent cannot act on
a broken sync, and an admin hunting one does not want to scroll past their own
call count to find it. `health` is null rather than empty for non-admins —
there is a difference between "nothing wrong" and "not your concern", and the
client renders the panel only for the former.

**One request, composed on the server.** Letting the client assemble it would
mean asking for things it is not entitled to and handling the 403 — a worse
contract than the server answering "what should this person see first".

**Placements run through the same board service the leaderboard pages use**, so
a rank on the dashboard and a rank on the board cannot disagree. There is a
test asserting exactly that. They ignore `display_limit`: being 14th on a top-3
board is precisely when you want to be told.

**A board you do not appear on is skipped**, rather than shown as "unranked" —
a row saying you are nowhere is discouraging and tells you nothing you can act
on.

**The quiet-people window is seven days**, not two. A warning that fires
because somebody took Friday off is a warning people learn to ignore, and the
ignored warning is worse than none.

**Health exists for one failure in particular.** From the integrations doc: a
board showing three-day-old figures because a sync has been failing looks
exactly like one showing current figures. Silently stale data is the fastest
way to lose trust in the tool, so `last_fact_at` is on screen and turns amber
after three days.

**A revoked display is not counted as offline.** It was switched off on
purpose; reporting it forever would train people to ignore the number.

**The attention banner omits `goals_behind`** even though the API returns it —
the panel below lists those goals with the gap on each, and a banner naming the
count directly above a card naming them is repetition rather than emphasis. It
renders nothing at all when there is nothing wrong, because a permanent
"nothing needs attention" panel trains people to stop looking at the spot
warnings appear in.

**Verified live across all three roles:** an admin sees placements plus health
(last fact today, 193 facts this week, 0 unassigned, 0 screens offline); a
manager sees placements and no health; an agent sees placements and their own
behind-pace goal, and no mention of anybody else.

> **Mutations confirmed caught:** placements ignoring board visibility, health
> returned to everyone, quiet-people ignoring scope, and `display_limit`
> truncating a placement.

#### 1g-ii — trends — done

- [x] `aggregate.series()` — bucketed aggregation, in the org's timezone
- [x] `periods.bucket_unit()` / `bucket_starts()` — where the buckets fall
- [x] `Trend` on dashboard placements, and on goals behind `?trend=true`
- [x] `<Sparkline>` — hand-drawn SVG, +1.7 KB to the bundle
- [x] One index: 1,677ms -> 31ms for a year-long team chart
- [x] 30 tests, ten mutations confirmed caught

**It is the same query as everything else, with one more GROUP BY.** `series()`
lives in `aggregate` and is built from the same `_base_filters` and
`_aggregate_column` as `run()` and `total()`. A sparkline that ended somewhere
other than the figure printed beside it would be worse than no sparkline, and
sharing the filters is the only way to guarantee it cannot. There is a test
asserting the series sums to the period total, one asserting a goal's line ends
at its `current_value`, and one asserting a placement's line ends at the value
its rank was computed from. Verified on the dev data too: every board and goal
agrees exactly.

**What an empty bucket means depends on the aggregation**, and this is the part
that would have drawn a confidently false chart:

| aggregation     | a day with no facts | why                                     |
| --------------- | ------------------- | --------------------------------------- |
| `sum`, `count`  | zero                | nobody made a call; zero is the truth   |
| `avg, max, min` | unknown — a gap     | the average of no responses is not zero |
| `last`          | carry the last one  | the pipeline did not empty overnight    |

Zero-filling an average invents a daily collapse that never happened. The line
breaks at a gap rather than drawing through it, because a straight segment
across missing data is a measurement nobody took.

**Bucketing happens in the organization's timezone**, via `date_trunc`'s third
argument — the same rule as every period boundary. Truncating in UTC would file
an agent's last call of the day in Phoenix under tomorrow.

**Bucket edges are generated in Python, not by `generate_series`.** The step has
to be a _local_ day, and a local day is 23 or 25 hours long twice a year. There
is a test for March 2026 asserting the boundary moves from 05:00 UTC to 04:00
across the daylight-saving change and that consecutive edges still meet exactly.

**Only days and months — no week bucket.** Postgres `date_trunc('week', ...)`
always starts weeks on Monday, and an organization can set `week_starts_on` to
Sunday. A weekly bucket would disagree with every weekly period in the product,
and would do it silently: the chart would look right and be shifted by a day.

**Cumulative for `sum` and `count`, per-bucket for everything else** — the same
distinction `pace` draws. A goal of "500 calls this month" is chasing a running
total, so the line that answers "will I make it" is the climbing one, and the
target is drawn as a dashed rule across it. An average response time is not
chasing anything, and a running total of daily averages is not a number.

The client is told which it received, because the two are **scaled
differently**: a cumulative line is anchored at zero, and a per-bucket line to
its own range. Anchoring per-bucket at zero would flatten forty-to-fifty calls
a day into a straight line at the top of the box, hiding the only thing it was
drawn to show.

**Goal sparklines are opt-in (`?trend=true`), placements are not.** A trend is
one extra query per goal, and most callers of `/api/goals` are listing rather
than plotting. The dashboard asks for them; the goals page does not.

##### The benchmark that was measuring the wrong table

Worth recording, because the first answer was wrong in an expensive direction.

A year-long personal sparkline measured 1,393ms at 4M facts, and the fix looked
obvious: the leaderboard index leads with `occurred_at`, so "one person, all
year" scans the whole year for that metric and discards all but their rows. Two
covering subject-leading indexes brought it to 3.5ms — a 398x win, written up
and migrated.

Then the index list came out of the real database, and it had two indexes the
benchmark table did not: `ix_metric_fact_subject_time` and
`ix_metric_fact_office_time`. Re-measured against the schema this product
actually has:

| chart                       | today        | with new indexes |
| --------------------------- | ------------ | ---------------- |
| one person, a fiscal year   | 8.6 ms       | 8.6 ms           |
| one person, a month         | 1.3 ms       | 1.3 ms           |
| **one team, a fiscal year** | **1,677 ms** | **31 ms**        |
| **one team, a month**       | **148 ms**   | **3.9 ms**       |

The person case was already covered. The 398x speedup was real and entirely
redundant, and shipping it would have added a 259 MB index to the busiest table
in the system to fix a problem that did not exist. The team case was the actual
gap — there had never been a `subject_team_id` index, because nothing had asked
for a single team's line before.

So the migration is one small index, `(subject_team_id, occurred_at)`, matching
the shape of the two already there. A covering variant measured 18ms against
its 31ms for nearly double the size; half the size for 13 milliseconds on the
rarest chart in the product is the better trade.

**The lesson is narrower than "benchmark first" — it is that a benchmark is a
claim about a schema.** The synthetic table also had user and day derived from
the same modulus, which left most (person, month) pairs empty and made the
first round of timings measure nothing at all. Both mistakes look like results.

> **Mutations confirmed caught:** bucketing in UTC instead of the org timezone,
> returning only the buckets that had facts, zero-filling an average's empty
> buckets, dropping the carry-forward for snapshots, taking the earliest rather
> than latest snapshot in a bucket, bucketing a quarter monthly, stepping
> buckets by a fixed 24 hours, dropping the scope filter, ignoring the team
> filter, and resetting the running total on an empty bucket.

#### 1g-iii — goal detail — done

- [x] `GET /api/goals/{id}` — goal, contributors, and history in one request
- [x] `/goals/:id`, reachable from the goals list and the dashboard card
- [x] `goals.contributors()` — who made up a team's number
- [x] `goals.history()` — six earlier periods against today's target
- [x] 13 tests, eight mutations confirmed caught

**The list already answers "how far along".** This page exists for the two
questions a card physically cannot fit:

- **Who?** A manager looking at a team goal that is behind does not need the
  gap repeated — the bar says that. They need to know which people make it up.
- **Was the target ever realistic?** A team that closed 30, 28 and 33 deals in
  the last three months has a great deal to say about a target of 90, and none
  of it is visible on a progress bar.

**History is measured against today's target, and labelled as such.** It is
not a record of goals that existed then — most of those periods had no goal at
all, and a recurring goal's copies could each have carried a different target.
One line across the whole row is the only reading that stays consistent from
bar to bar; anything else puts bars of different meanings side by side. The
chart scales to include the target, so a bar that clears the line is visibly
over it.

**Six periods back.** A half-year of months, or two quarters of weeks — enough
to see a trend, few enough that each is a distinct bar rather than a smear.

**The contributor list is scoped, and is therefore shorter than the total above
it for an agent.** That is correct rather than inconsistent: the total is the
team's, because that is what the goal is, and the breakdown is what this
viewer is entitled to read. A custom period has no history at all, because
there is no rule for what comes before an arbitrary range.

**One request, composed on the server**, same as the dashboard. All three
answers describe the same period, and three round trips could disagree about
which one.

##### Four mutations that survived the first time

The tests passed and three of the eight mutations still lived, all for the same
reason: **the fixtures could not tell the two behaviours apart.**

- "Contributors returned for a personal goal too" survived because the test
  built a goal with no facts anywhere. An empty list proves nothing when there
  is nobody to wrongly include.
- "Contributors ignore the team filter" survived because every fact in the
  test belonged to the team being asked about.
- "History ignores the team and uses the whole org" survived for the same
  reason, one period earlier.
- "An empty past period counts as having data" survived because the test used
  a `higher_is_better` metric, where zero fails the target either way. It only
  bites on `lower_is_better`, where an empty month reads as having comfortably
  met "keep response time under 60 seconds" — the absence-is-not-achievement
  trap, resurfacing in a place it had already been fixed once.

Each was fixed by giving the fixture something to get wrong: a rival team with
a bigger number, a person on another team, a `lower_is_better` metric. **A
passing test proves nothing if the wrong answer and the right answer look the
same in that fixture.**

**Verified on the dev data:** a team goal's four contributors sum to exactly
the team's own figure, and the same past month (April, 361 calls) correctly
reads as meeting a target of 200 and missing one of 500.

**Done when:** an admin can install it, invite a team, build the org tree,
define metrics, set goals, and everyone sees accurate leaderboards and
dashboards — with trends, and a goal they can open and act on.

_(Originally this line said "import a spreadsheet". CSV import was dropped, not
deferred: production data comes from integrations, and the seeded dev data
covers the testing it was there for.)_

**This is the milestone that matters.** Everything after it is enhancement.

---

## Phase 2 — Engagement

**Goal:** the recognition half of the loop. This is where it stops being a reporting tool.

Phase 1 built the machine that knows the numbers. Nothing in it ever says
anything. A goal can be hit and the only way to find out is to go and look —
which is the difference between a tool people are told to open and one they
want to.

### The plan

Sliced like Phase 1, smallest useful layer first, each one usable on its own.

|        |                                                         | Depends on            |
| ------ | ------------------------------------------------------- | --------------------- |
| **2a** | Notifications — detection, storage, centre, preferences | —                     |
| **2b** | Celebrations — in-app overlay                           | 2a                    |
| **2c** | Recognition — shout-outs and the Achievements page      | 2a (TV half needs 2d) |
| **2d** | Authored channels — screens, ordering, IP allowlist     | —                     |
| **2e** | Competitions — lifecycle, settlement, freezing, formats | 2a                    |
| **2f** | Competition + achievement screens, TV takeover          | 2b, 2c, 2d, 2e        |

**Notifications come first** because they complete Phase 1's loop, and because
competitions depend on them to be worth building — `competition.results_final`
_is_ the payoff, and building the event before the announcer means building the
punchline before the joke.

**Recognition sits second on purpose.** It is the cheapest gamification in the
whole phase — no detection, no lifecycle, no settlement, essentially one
authored row — and a manager can use it the day it lands. Competitions are the
largest slice in Phase 2 and recognition is the smallest; putting the small one
first means the floor gets something to react to months before the big feature
is ready.

### Decisions taken before starting

Four questions were settled up front, because each one changes what gets built
rather than how.

**1. A competition is a distinct entity, not a mode on goals.** The detail is
in [Are competitions a separate thing from goals?](#are-competitions-a-separate-thing-from-goals)
below. The short version: a goal must keep recomputing when data is corrected,
and a competition must not. One table cannot do both without a flag that
changes the meaning of every query that touches it.

**2. Only latching events ship in the first cut.** The catalogue splits in two:

|                 | Examples                                                                               | Needs                    |
| --------------- | -------------------------------------------------------------------------------------- | ------------------------ |
| **Latching**    | `goal.achieved`, `goal.assigned`, `goal.period_ending`, `competition.*`, `recognition` | nothing — a unique index |
| **Oscillating** | `rank.changed`, `rank.overtaken`, `competition.lead_change`                            | a rank-snapshot table    |

A latching event happens once per subject per period and never un-happens. An
oscillating one can flip back and forth, and telling somebody "you moved from
5th to 3rd" requires knowing they were 5th — which means capturing every
entity's rank on every board every job cycle, the largest new write path in the
system, to power the noisiest and least valuable events. They are **deferred,
not cancelled**; the storage decision can be made later against a real
deployment rather than guessed at now.

**3. There is no stored "last known status", and no dispatch layer.**

Both fall out of the same realisation, and both delete work. See
[Detection without stored state](#detection-without-stored-state) below.

**4. Email is account plumbing, not a notification channel.**

Raised while planning, and it removed a whole abstraction. Email's real job in
this product is **invitations and password resets** — the two things that today
work by copying a link out of the UI and pasting it into Slack. SMTP arriving
with the integrations phase turns that into "it just arrives", which is the
actual win and has nothing to do with recognition.

Recognition reaches people through the app they already have open and the TV on
the wall. An internal sales floor does not need an email saying somebody hit
their number; it needs the screen to light up. So **Phase 2 ships no email
notifications**, and with in-app, celebration, and TV all reading the same
rows, there is nothing left to dispatch — no queue, no retry policy, no adapter
registry. If email ever becomes a notification channel, that is the point at
which a dispatch layer earns its place, and it will be added against a working
SMTP connection instead of imagined without one.

### Detection without stored state

The notifications design says the job "compares current progress against the
last known status". Taken literally that means a `last_status` column — stored
derived state, which this system does not have anywhere, for good reasons that
have not changed: it would be wrong the moment a connector backfilled, and it
would need invalidating from every write path.

It is not needed. **The notification row is itself the record that we
announced it.** Firing once is enforced the same way a recurring goal avoids
spawning twice — a partial unique index, not a check-then-insert:

```sql
CREATE UNIQUE INDEX uq_notification_once
    ON notification (organization_id, user_id, subject_type, subject_id,
                     period_anchor, event_key);
```

`event_key` is a canonical string — `goal.achieved`, `goal.threshold:75` — so
the 50% and 75% thresholds are distinct events without a second column. The
emitting job runs `INSERT ... ON CONFLICT DO NOTHING` and stops caring about
races entirely: two workers, or one worker restarted mid-run, cannot produce
two announcements because the second insert is impossible rather than merely
unlikely.

**This also removes the dedupe window.** The doc specifies a five-minute
collapse for identical events, which exists because a bulk import writing 400
facts would otherwise fire 400 times. For latching events the index already
guarantees one, permanently — the dedupe window was a workaround for the
oscillating events that are now deferred. What remains is a per-user daily cap
as a backstop, which is cheap.

**The job loop already exists.** `app/jobs.py` runs under
`pg_try_advisory_lock` on the interval in `main.py`, and `spawn_due_goals` is
already the pattern to copy: read, decide, insert idempotently, commit.

---

### 2a — Notifications

#### 2a-i — detection — done

- [x] `notification` table: unique-once index + partial unread index
- [x] `app/events.py` — the catalogue as code, `public` and `celebrate` per type
- [x] `notifications.detect()`, wired into the existing job loop
- [x] Recipient resolution — the subject, plus their team's manager
- [x] Per-user daily cap
- [x] 23 tests, eleven mutations confirmed caught

**Idempotency is the whole design, and it is one index.** No stored "last
notified status" anywhere: `emit()` inserts with ON CONFLICT DO NOTHING, so a
second announcement is impossible rather than unlikely. Verified against the
live dev data — the first pass emitted 32 notifications across 8 goals, and
every pass after it emits 0.

**`NULLS NOT DISTINCT` is load-bearing and nearly invisible.** Postgres treats
NULLs as distinct in a unique index by default, so an event with no period — a
competition starting — would re-insert on every job cycle forever. One clause
in a migration; a test asserts it directly, because nothing else would notice.

**The index is partial on `created_by_user_id IS NULL`**, so detected events
latch and authored ones repeat. That single clause is what will let a manager
send two shout-outs to the same person in 2c without the second being
swallowed as a duplicate.

**A bug this nearly shipped with.** `current_value` resolves scope from an
actor, and an agent's scope is themselves — so evaluating a team goal as one of
its recipients computes that member's contribution and announces it as the
team's total. Silently, and _low_, which is the worst direction for a
congratulation to be wrong in. Detection now runs as `_System`, which evaluates
the goal as the organization; the test has two people who each fall short of
the target and clear it together.

**`goal.period_ending` fires at 75% elapsed, and never at a goal already hit.**
A latching event has exactly one shot: spent on the 3rd it is gone by the 25th,
when it would have mattered. Announcing "you are running out of time" to
somebody who already hit their number would be the most irritating notification
in the product.

**`detect()` takes `now`.** Half of what it decides is "how far into the period
are we", and a test that cannot pin that can only assert whatever today happens
to make true. Found by a mutation that moved the threshold to 0% and passed.

##### Three mutations that were no-ops, not passes

Nine of eleven mutations were caught immediately. Three appeared to survive:
removing `NULLS NOT DISTINCT`, making the once-index total, and dropping
`period_anchor` from the key.

None of them had actually run. The test database is built by **running the
migrations**, not `create_all`, so editing `models/notification.py` changed a
file the tests never read. The mutations had to be made in the migration, with
the test database dropped so it was rebuilt — at which point all three were
caught.

**A mutation that changes nothing looks exactly like a test that catches
everything.** Same failure as the fixtures in 1g-iii, one level down: the check
has to be able to fail before a pass means anything.

#### 2a-ii — the notification centre — done

- [x] `GET /api/notifications`, mark-read, mark-all-read
- [x] `<NotificationBell>` — badge, panel grouped by day, keyboard-dismissable
- [x] 90-day retention prune, in the job loop
- [x] 20 tests, ten mutations confirmed caught

**Scope here is the WHERE clause, not a permission rule.** There is no
capability for "read notifications", because the recipient is a column and
there is no version of this that reads somebody else's. An admin has no special
access — reading somebody's bell would be reading their mail — and there is a
test saying so.

**`celebrate` is resolved from the catalogue at read time, not stored per row.**
Changing what celebrates then needs no backfill. An unknown `event_key` renders
as an ordinary row rather than throwing, so a notification written by a newer
API cannot break an older client's bell.

**Marking read is idempotent in the useful direction.** Re-opening the panel
must not rewrite when something was seen, so `read_at` is only ever set once.

**Mark-all-read is one UPDATE, not a loop.** Somebody back from leave can have
hundreds, and loading them to set a field on each would be hundreds of round
trips to express one statement.

**The bell polls; it does not hold a connection open.** Detection runs on a job
cycle measured in minutes, so a websocket would keep a socket alive per
signed-in person to deliver something that cannot arrive faster than the job
that finds it. When the celebration overlay in 2b needs to feel prompt, the
poll interval is the dial to turn.

**Unread is a dot, not a coloured row.** A tinted background behind text is the
first thing to fail a contrast check, and the dot survives any theme.

**Pruning deletes read and unread alike.** An unread notification from three
months ago is not something anybody is about to act on, and keeping it would
leave a badge that can only be cleared by reading rows nobody wants. This table
is a feed, not a record — `audit_log` is what answers "what happened and who
did it".

**Verified over real HTTP** against the dev data: the feed returned 2 unread
with `celebrate` set correctly, marking one read took it to 1, mark-all-read
took it to 0, and an unauthenticated request got 401.

##### The mutation that only checked itself

Widening the retention window from 90 days to 3,650 changed nothing: the prune
tests aged their rows by `RETENTION_DAYS + 1`, so they moved with the constant
they were supposed to be checking. A test written in terms of the value it is
testing can only ever confirm the code agrees with itself.

Fixed with absolute ages — 100 days is pruned, 30 is not. Same shape as the
fixtures in 1g-iii and the no-op mutations in 2a-i: **the check has to be able
to fail.**

#### 2a-iii — preferences — done

- [x] `notification_preference` — presence means muted
- [x] `GET`/`PUT /api/notifications/preferences`
- [x] Toggles on the account page, beside change-password
- [x] 8 tests, seven mutations confirmed caught
- [ ] ~~Quiet hours~~ — **deferred, because they would do nothing.** See below

**On the account page**, not in a settings area of its own. It is about you and
nobody else, which is the same reasoning that moved role, team and sign-out
there rather than leaving them on a dashboard everyone shares.

**Presence in the table means muted, and only deviations are stored.** Somebody
who has never opened the settings has no rows at all, so a new event in the
catalogue is on for everybody without a backfill. Materialising every
person-by-event combination instead would need a migration each time the
catalogue grew, and would get it wrong for anybody created between the
migration and the deploy.

**Preferences filter at READ, never at creation** — and this one nearly went
the other way, because suppressing the row is cheaper and looks equivalent.

It is not equivalent. The same rows feed the notification centre, the
Achievements page, and the wall screens. Suppressing at creation would mean
somebody who muted their own achievements quietly disappears from what the
_organization_ celebrates. **A preference is about your bell, not about whether
the thing happened.** Filtering at read also makes unmuting show what you
missed, which is what somebody switching a setting back on expects.

**PUT replaces the whole set** rather than accepting a diff. A toggle list has
no meaningful partial state, and replacing makes the request idempotent and
removes any ordering question between two switches clicked quickly.

**Labels come from the API, not the client**, so a new event appears in the
list as soon as the API knows about it rather than when somebody remembers to
add a string. An event missing from that map is simply not offered as a toggle,
which is the right default for anything not yet meant to be user-facing.

**Verified over real HTTP:** unread 2 with everything on, 1 with new-goals
muted, 2 again after unmuting — with all 19 `goal.assigned` rows still present
in the database throughout.

##### Quiet hours would have been a switch that does nothing

They were on the plan, and building them would have been wrong.

Quiet hours suppress an _interruption_. Phase 2 has no interruptions: with
email cut, an in-app notification is **pulled, not pushed** — it sits in a table
until somebody opens the bell. There is nothing to be quiet about at 9pm,
because nothing arrives at 9pm; it waits, which is what quiet hours would have
made it do anyway.

The one real interruption is the celebration overlay in 2b, and that only
appears to somebody who has the app open and is looking at it — by choice, at
whatever hour they chose to be there.

So the control would have had no observable effect, and a setting that does
nothing is worse than a missing one: it teaches people that the settings page
is decorative. Revisit when a channel exists that actually reaches out — push,
or email if it ever becomes a notification channel.

##### The mutation that found dead code

Seven of eight mutations were caught. The survivor was "store an unknown event
key rather than ignoring it", and the reason is that the guard it removed did
nothing: `muted = set(CATALOGUE) - wanted` already ignores anything outside the
catalogue, so `if key in events.CATALOGUE` could be deleted without changing a
single result.

The fix was to delete it. Tolerating a stale client's renamed key is a property
of the subtraction, which is the better place for it — nothing to keep in sync,
and nothing to mistakenly "fix" later. **Mutation testing usually finds a
missing test; here it found a line that was never doing anything.**

**The partial unread index is what keeps the badge fast forever:**

```sql
CREATE INDEX ix_notification_unread ON notification (user_id, created_at DESC)
    WHERE read_at IS NULL;
```

It only indexes unread rows, so it never grows past the number of genuinely
unread notifications no matter how much history accumulates. Same shape as the
partial index on `metric_fact.external_id`.

**Recipients are scope-checked, not just role-checked.** "The achiever and
their manager" has to mean the manager who can already see that person, or a
notification becomes a way to learn about somebody outside your scope.

**Quiet hours delay, they do not drop.** A goal hit at 9pm is still worth
knowing about at 9am. Dropping it would make the feature quietly lossy in a way
nobody could debug.

### 2b — Celebrations — done

- [x] `celebrated_at` on the notification row — shown once, across devices
- [x] `POST /api/notifications/{id}/celebrated`
- [x] `NotificationProvider` — one poll shared by the bell and the overlay
- [x] `<CelebrationOverlay>` — self-closing, escapable, backlog in order
- [x] 4 backend + 7 frontend tests, eight of nine mutations caught

**`celebrated_at` is a separate column from `read_at`, and that is the whole
design.** They answer different questions: "have you seen it in the list"
governs the badge, "have we already thrown confetti at you" governs the
overlay. Conflating them breaks in both directions — opening the bell would
cancel a celebration nobody saw, and a celebration somebody walked away from
would clear a badge they never looked at. Both directions have a test.

**Recorded on the server, not in the browser.** `sessionStorage` would replay
every celebration on a refresh and again in a second tab, and would do it
differently on a laptop and a phone.

**One poll, shared.** The bell wants unread; the overlay wants uncelebrated.
Two independent polls would double the requests and let the two disagree —
nothing is more confusing than a badge reading 3 beside a celebration for
something the badge has not noticed. `NotificationProvider` holds the single
fetch and both read from it.

**It closes itself after six seconds**, and Escape or a click closes it sooner.
A celebration that _must_ be dismissed is a modal, and a modal is a chore —
the opposite of the point. `role="alert"` rather than `dialog`, because it
takes no input and trapping focus would strand a keyboard user in something
they cannot act on.

**A backlog plays oldest first.** The feed arrives newest-first, which is right
for a list and wrong for a sequence of events: Monday's win should not play
after Friday's.

**Reduced motion is handled once, in CSS.** `theme.css` already collapses every
animation to 0.01ms under `prefers-reduced-motion`. The first version of the
overlay also checked `matchMedia` in JavaScript — two implementations of one
rule, and the CSS one is the one a future component cannot forget. The JS check
was deleted.

**The overlay carries no sound or media.** That belongs on the wall in 2f,
where a room has just watched somebody earn it. A song starting at a desk
because somebody opened a laptop is a different and much less welcome thing.

##### The second piece of dead code mutation testing found today

Eight of nine mutations were caught. The survivor was "reverse the feed in
place", which should have tripped the test asserting the input is not mutated —
except `.filter()` already returns a new array, so the defensive `.slice()`
before `.reverse()` could be deleted without changing a single result.

Deleted, with the test kept: the property still matters, it just comes for
free now. This is the second time in one session that a surviving mutation
meant **redundant code** rather than a missing test — the other was a
`if key in CATALOGUE` guard in 2a-iii that a set subtraction already handled.
Worth naming as its own signal: _a mutation that changes nothing is telling you
the line changes nothing._

**Reduced motion is not optional.** A full-screen animation is exactly the
thing that hurts people with vestibular disorders, and the OS already tells us.

**Walk-up media is in, and lands in 2f on the wall rather than here.** A
celebration can carry a song, GIF or YouTube clip — the way a batter has walk-up
music — as a per-person default with a per-shout-out override.

**URLs, not uploads.** A YouTube link with start and end offsets covers walk-up
songs completely and a hosted GIF URL covers the rest, which is a text column
rather than file storage, upload limits, orphan cleanup and a moderation queue.
Uploads can follow if anybody actually wants local files.

Sound was the original objection and it is answered operationally: a company
that does not want it mutes the TVs. Two things to settle when it is built —
browsers block unmuted autoplay without a user gesture, so a kiosk display needs
launching with the autoplay policy relaxed (a deployment note that must be
written down or every install reports "the sound does not work"), and the
display page's content security policy has to admit YouTube and image hosts
deliberately.

**Still not built:** virtual gongs, and media in the _in-app_ overlay. A song
playing at somebody's desk when they open a laptop is a different proposition
from one playing in a room that just watched them earn it.

### 2c — Recognition

An automated notification is **detected**; a shout-out is **authored**. Same
destination, different origin — so it rides every pipe 2a and 2b already built
rather than growing a second one.

#### 2c-i — shout-outs — done

- [x] `created_by_user_id` on `notification` — NULL means the system found it
- [x] `about_name` / `about_user_id` — who it is _about_, not who it is _for_
- [x] `POST /api/recognition`, scope-checked and audited
- [x] `DELETE /api/recognition/{id}` — own for a manager, any for an admin
- [x] `GET /api/achievements` — the public feed, deduplicated
- [x] **Achievements** page and nav entry, with a compose modal
- [x] `recognition.send` capability for admin and manager
- [x] 21 tests, eleven mutations confirmed caught

**One column separates a shout-out from an achievement**, and everything else
is shared. A shout-out reaches the bell, the celebration overlay, and (in 2f)
the wall through machinery 2a and 2b already built.

**`about_name` exists because addressed and about are different things.** A
team goal being hit sends a row to every member — one event, four recipients —
so a feed keyed on `user_id` would list the same news four times under four
names, none of which is the achiever. Stored at emit like `title`, for the same
reason: renaming a team must not rewrite what last month's announcement said.

**The feed is org-wide, deliberately unlike every other list here.** These are
the same rows that go on a wall screen anybody walking past can read, so
"public" has to mean the same thing at a desk and in a corridor. What keeps
that safe is the catalogue — only `PUBLIC_EVENT_KEYS` are eligible — not a
filter at the call site.

**DISTINCT ON collapses one event's copies into one entry.** Verified on the
dev data: 33 notification rows render as 6 feed entries, with team goals
appearing once under the team's name.

**Deleted rather than archived** — the only thing in this product that is. A
goal or a display is kept because somebody will ask what it was; a shout-out
with a typo in front of the whole floor has no such afterlife. The audit log
holds the record that it happened. Nobody can delete a _detected_ achievement:
un-hitting a target is not a thing.

##### Two bugs the tests found, both about time

**Ordering ties.** Two shout-outs sent in a row came back oldest-first.
`created_at` defaults to `now()`, which in Postgres is _transaction start_ — so
every notification from one detection pass carries an identical timestamp, and
a whole pass is one transaction. Sorting on the timestamp alone left those in
whatever order DISTINCT ON produced. Fixed by breaking the tie on id.

**A backfill that was nearly missed.** These columns are populated at emit, and
emitting is idempotent — the unique index means detection never revisits a row
it has already written. So every notification predating the migration would
have kept a NULL name _forever_, and the feed would render them blank. Caught
by running it against the dev data, where a re-detect reported "0 emitted, 32
already known" and the feed came back nameless. The migration now backfills
both shapes; all 33 rows have a name.

**A migration that adds a column populated at write time needs a backfill, or
the old rows are wrong permanently** — worth remembering, because idempotent
emitters make that failure silent rather than loud.

##### The mutation that only one organization could hide

Ten of eleven mutations were caught immediately. The survivor removed the
`organization_id` filter from the achievements feed — and every test passed,
because they all ran inside a single organization.

That filter matters more here than almost anywhere else: every other list is
_also_ narrowed by scope, so a missing tenant check would still trip something.
This feed is org-wide by design, which makes the tenant filter its only line of
defence. A second organization in the fixture caught it.

#### 2c-ii — walk-up media — done

- [x] `walkup_media` — one clip per person, set by them and nobody else
- [x] `media_url` / `media_start_seconds` / `media_end_seconds` on `notification`
- [x] `app/media.py` — allowlist, offsets, and kind derived from the URL
- [x] `GET`/`PUT /api/me/walkup`, plus a per-shout-out override
- [x] Account page section; optional override in the compose modal
- [x] 36 + 12 tests, thirteen mutations confirmed caught

**URLs, not uploads.** A YouTube link with offsets covers walk-up songs
completely and a hosted GIF covers the rest — three columns rather than file
storage, upload limits, virus scanning, orphan cleanup and a moderation queue.

**The allowlist is a security boundary, not a convenience.** A wall display is
a browser nobody is watching, pointed at whatever this module accepts, so "any
http URL" would let an admin aim every screen in the building at anything.
Only YouTube video links and image extensions pass; `javascript:`, `data:`,
`file:`, and arbitrary pages are refused. It also gives 2f's content security
policy a finite host list to admit deliberately.

Two attacks have their own tests: `youtube.com.evil.example` (a hostname that
merely _ends_ in the real one — matched against an exact set, not a suffix) and
a malformed video id, which is checked against `^[A-Za-z0-9_-]{11}$` because it
gets interpolated into an embed URL.

**Length is clamped, not rejected.** Somebody pasting a four-minute song has
not made a mistake, they have just not thought about the length — trimming to
fifteen seconds is a kinder answer than a validation error. A wall screen owes
the room its leaderboard back.

**Kind is derived from the URL, never stored.** A `kind` column beside the URL
is one more pair that can disagree, and this disagreement would only ever
surface on a screen in front of an office. There is a test asserting the two
code paths that answer "what is this" can never diverge.

**Media is frozen at emit, like `title` and `about_name`.** Changing your
walk-up song should soundtrack your _next_ win, not retroactively re-score
every one you have already had.

**A detected achievement plays the achiever's music too** — most celebrations
are detected, so a default that only applied to shout-outs would barely apply.
**A team achievement plays nothing:** a team has no walk-up song, and borrowing
one member's would credit the wrong person in front of the room.

##### A mutation my fixture could only catch by luck

Twelve of thirteen were caught immediately. The survivor made a team
achievement fall back to `recipients[0]`'s music — and passed, because the test
set a walk-up song only for Alice, while `recipients[0]` is whichever member
the query happened to return first. When that was Bob, the fallback produced
nothing and the assertion held.

Fixed by giving _every_ member a song, so any fallback to a member produces a
URL. A fixture that catches a bug only when the database returns rows in one
particular order is not catching it.

**Not built, deliberately:** uploads, virtual gongs, and media in the _in-app_
overlay. Nothing plays anywhere yet — 2f is where the wall learns to.

**One column, and one clause on an index.** A shout-out is a notification with
an author. But the once-only index from 2a would stop a manager praising the
same person twice, which is exactly what they should be able to do — two sales
in a week are two shout-outs. So the uniqueness applies only to detected
events:

```sql
CREATE UNIQUE INDEX uq_notification_once
    ON notification (organization_id, user_id, subject_type, subject_id,
                     period_anchor, event_key)
    WHERE created_by_user_id IS NULL;
```

Automated events latch; authored ones repeat. That is the whole difference, and
it is one `WHERE`.

**The Achievements page is one feed, both kinds.** "Marcus hit his call target"
and "Priya turned around the Henderson account" belong in the same list —
splitting them into automated and manual would be an implementation detail
leaking into the UI, and the manual ones are usually the better story.

**Scoped like everything else.** A manager can only recognise somebody they can
already see, or a shout-out becomes a way to discover people outside your
scope. Audited too, because it broadcasts to every screen in an office.

**Open, to decide when we build it:**

1. **Does a shout-out take over the wall, or join the rotation?** Immediacy is
   the point, so a takeover is tempting — but ten shout-outs must not hijack a
   screen for ten minutes. Likely: take over once, with a cooldown, then live in
   the achievements screen.
2. **Which screens does it reach?** Simplest honest default is the recipient's
   office plus org-wide channels — the same rule boards already follow — rather
   than making the sender choose every time.
3. **Can an agent recognise a peer?** Peer recognition is powerful and is also
   the one path with a plausible abuse story. Manager-and-admin first; peer
   nominations are a small addition later if it is wanted.

#### 2c-iii — achievement rules — done

Added after measuring against Spinify — see
[11-notifications-and-celebrations.md](11-notifications-and-celebrations.md#measured-against-spinify).

- [x] `achievement_rule` — metric, condition, threshold, scope, media, enabled
- [x] `notifications.detect_rules()`, in the existing job loop
- [x] Never retroactive: only facts occurring after the rule was created
- [x] Per-rule media, which beats the person's walk-up when both exist
- [x] Enable/disable org-wide, separate from each person's own mute
- [x] `events.is_public()` — one answer for fixed and runtime event keys
- [x] 20 tests, twelve of thirteen mutations caught
- [x] Admin API and `/achievement-rules` page — create, edit, disable, delete

**Renamed to "Announcements" in the nav** (2026-08-18). The page is what gets
celebrated automatically, and "Achievement rules" was the technical name for it.
The manual feed keeps the name Achievements.

**Archive removed from rules; disable replaces it.** `archived_at` was
`enabled = false` one way only — the list filtered archived rules out and no
endpoint could restore one, so archiving a rule hid it permanently. Two
mechanisms for one outcome and one of them a trapdoor. Delete now really deletes,
which is safe because **nothing holds a foreign key to a rule**: a notification
carries its announcement — name, number, media — copied onto the row at emit, so
the history outlives the rule and there is nothing to cascade.

Migration `50b62b1669a1` switches already-archived rules off _before_ dropping the
column. Without that data step, dropping it would un-hide every archived rule, and
any still holding `enabled = true` would start announcing again on the next job
pass — rules an admin believed they had deleted would begin celebrating things.
Off rather than deleted, because the button they pressed promised the rule would
stop firing, not that it would be erased.

- [x] Recognition can target a team, not only a person
- [x] `/users/:id` — a person's settings, reachable by a pencil on the list
- [x] 49 tests, fifteen mutations confirmed caught

**Rules are admin-only, unlike shout-outs.** A rule fires on every screen in
the building every time it matches, and setting the bar too low does not fail
loudly — it just turns the wall into noise, which is the failure this whole
feature exists to avoid.

**A team shout-out is one event with many recipients**, exactly like a team
goal being hit: every member's bell, one row on the feed, under the team's
name. It carries no walk-up media, because borrowing one member's would credit
the wrong person in front of the room.

**Managers and admins can now set somebody else's walk-up media**, from a
pencil on the people list that opens `/users/:id`. This reverses an earlier
decision, and the docstring that argued for it was rewritten rather than left
to contradict the code — the "comment outliving its code" failure has bitten
this project more than once. A manager is bounded to their own team by
`can_see_user`, an agent editing a colleague gets 403 rather than 404 (they can
already see their teammates, so pretending otherwise is a lie they can
disprove), and changing somebody else's is audited while changing your own is
not.

##### A bug found by a test that was passing for the wrong reason

`test_archiving_a_rule_keeps_what_it_announced` failed because a rule created
through the API gets _today's_ timestamp, while the fixture's facts are dated
12 August — so the never-retroactive guard correctly ignored them. Two
neighbouring tests had been passing **vacuously** for the same reason: they
asserted "nothing was announced" and got it from the wrong cause entirely.

Fixing them exposed a real gap. An admin sets the bar at $50,000, sees nothing
for a week, lowers it to $5,000 — and every deal from that week suddenly
qualifies and announces at once. A backfill flood arrived at from the other
direction.

The fix: **the watermark advances past every fact examined, not just those that
matched.** Work done while the bar was higher stays examined. There is a test
that lowers a threshold and expects silence, then records new work and expects
exactly one announcement — so the rule is not simply dead either.

##### The third piece of dead code mutation testing found

`rule.last_fact_id = max(rule.last_fact_id, highest)` — the guard could not
fire, because the query already filters `id > last_fact_id`, so anything it
returns is larger by construction. Deleted.

Three in one session: a `if key in CATALOGUE` guard a set subtraction already
handled (2a-iii), a `.slice()` before a `.reverse()` on an array `.filter()`
had already copied (2b), and this. **A mutation that changes nothing is telling
you the line changes nothing.**

**Idempotency came free**, as expected: a rule firing on fact 91,204 is keyed
`("metric_fact", 91204, "achievement:7")`, so the existing unique index gives
exactly-once with no new machinery. The event key carries the rule id, so two
rules on one metric are two events and neither suppresses the other.

**The backfill guard is the important part.** A connector syncing six months of
history inserts thousands of rows with _fresh ids_ and _old timestamps_ — so
the id watermark alone lets every one through, because they are all new to it.
`occurred_at >= rule.created_at` is what actually protects the wall, and it is
Spinify's stated "cannot be applied retroactively". There is a test that
inserts 59 historic facts and one current one and expects exactly one
announcement.

**The watermark is explicitly not a correctness mechanism.** A test resets it
to zero and asserts nothing is announced twice — the index is what guarantees
that. A mutation deleting the watermark therefore _passes_, correctly: it costs
time, not duplicates.

##### A flag that nothing read

A mutation made rule achievements private and every test still passed. The
cause was two mechanisms for one question: the feed matched achievement keys by
prefix, while `events.achievement()` separately declared them `public=True`.
Flipping that flag changed nothing, because nothing consulted it.

Fixed with `events.is_public()` as the single answer for both fixed and runtime
keys, with the SQL prefix match demoted to a prefilter. **A field nothing reads
is worse than no field — it looks like the control and is not.**

**The capability this adds:** a celebration that fires off _work_, not off a
goal. A goal is a target over a period; "closed a deal over $5,000" is neither,
and it is most of what a sales floor actually celebrates.

**Idempotency comes free.** The unique index already keys on
`(subject_type, subject_id, event_key)` — so a rule firing on fact 91,204 is
`("metric_fact", 91204, "achievement:7")`, and exactly-once needs no new
machinery.

**Two guards against a backfill firing hundreds of celebrations.** A connector
syncing six months of history inserts thousands of facts with new ids and old
timestamps, and without care every one would be announced. So:

- a high-water mark on the rule, so a pass never rescans what it has seen; and
- `occurred_at >= rule.created_at`, which is Spinify's "cannot be applied
  retroactively" rule and the one that actually protects the wall.

The index is the backstop if either is wrong.

### 2d — Authored channels

Full design in [Authored channels](#authored-channels) below. Independent of
competitions, so it can run in parallel or slip without blocking anything.

#### 2d-i — the channel model — done

- [x] `channel` and `channel_screen` tables
- [x] `display.office_id` → `display.channel_id`, seeding a channel per office
- [x] Screen kinds: leaderboard, **goal**, **achievements**, image, video, message
- [x] `app/channels.py` — one renderer for the wall and any preview
- [x] Authoring API, and `/channels/:id` with drag-and-drop ordering
- [x] Per-screen dwell time, and a rotation-length total
- [x] 18 tests
- [x] IP allowlist — moved to **2d-iii**

**The migration seeded rather than reset**, which was the whole risk. Verified
by dumping what each display showed before and after: both walls came back with
`Calls - last 30 days, Offices by revenue`, same order, from an authored
channel instead of a query. The downgrade round-trips too.

**`is_tv_enabled` did not become dead — it changed question.** It used to mean
"is on a wall". Now a `channel_screen` answers that, and the flag means "may go
on a wall", guarded by the CHECK that ties it to org visibility. Two different
questions, both real; the alternative was a flag nothing read, which this
session has already produced three times.

**A private board is refused when it is authored, not when it renders.** An
admin is told immediately rather than finding a blank slide on a wall. The
renderer checks again anyway — two guards cost nothing and a wall has no
audience control at all.

**A screen that cannot render is skipped, never blanked.** An archived board, a
deleted goal, an empty achievements panel: the rotation moves past it. A wall
going black in front of an office reads as the product being broken; one fewer
slide reads as nothing.

**Reordering sends the whole order, not a move.** The editor already knows the
final arrangement, so there is no half-applied shuffle to reason about, and two
people dragging at once end with one of the two orders rather than an
interleaving. A screen the client did not mention keeps its place at the end,
so a stale tab cannot delete one by omission.

**Archiving a channel is refused while a television still plays it.** The
alternative strands those screens on "display disconnected" with nothing to
explain why and whoever did it three rooms away.

**Each screen carries its own dwell time**, so the wall re-arms a timeout per
slide instead of running one interval. A board is scanned in a few seconds; a
message has to be read. The editor shows the total rotation length, which is
the number an admin actually wants — how long until the board they are looking
for comes round again.

**Video is muted.** A wall that starts making noise on its own is how a feature
gets switched off entirely. Sound belongs to the celebration takeover in 2f,
which is a deliberate moment rather than a rotation.

**Verified live:** authored a channel with a message, two boards, a goal and a
recent-wins panel, reordered it, and confirmed the wall renders all five in the
new order with per-screen timings.

#### 2d-ii — audience and lifecycle — done

- [x] `channel.scope_*` — an audience every screen inherits
- [x] `channel_screen.scope_*` — the per-screen override, NULL for almost all
- [x] `notification.about_team_id` / `about_office_id`, snapshotted at emit
- [x] Archive, restore, and permanent delete, with icon buttons
- [x] 34 tests, nine mutations confirmed caught

**Researched against Spinify first, and it does this differently.** A Spinify
channel has a name, an RSS ticker and a TV URL — no scope at all. The filtering
lives in the _content_: a competition names its entrants explicitly, so the
Phoenix wall shows Phoenix things because somebody made Phoenix competitions.
Coherent, and it means a board per office.

We went further, deliberately. **A channel has an audience and every screen
inherits it**, so a wall is right by default and spillover is something
somebody chose rather than something they forgot. The per-screen override is
the deliberate exception — the company-wide board on a floor that otherwise
shows only itself.

**The migration seeded the audience too.** Each channel had been created from
an office, so matching the name back to it means the upgrade _delivers_ the
separation rather than leaving every wall open until somebody notices. Verified
live: Phoenix → Phoenix, Dallas → Dallas, and the Phoenix wall's "Offices by
revenue" went from two rows to one.

**The clearest leak was the wins panel**, which had no scoping whatsoever —
Dallas watched Phoenix's news scroll past. Fixed with `about_team_id` and
`about_office_id` **snapshotted at emit**, following the same rule as
`metric_fact`: a win belongs to the office somebody was in when they earned it,
so transferring must not move last month's news onto a different floor. There
is a test for exactly that.

**A board about another office is refused when it is authored.** "Nothing shows
up and I do not know why" is the worst possible way to learn this.

**Where board scope and wall audience meet, the board wins.** Unreachable
through the API — the authoring check makes the conflict impossible — but
pinned by a direct unit test rather than left as a branch nobody has an opinion
about. A board titled "Dallas calls" quietly showing Phoenix numbers would be
actively misleading, which is worse than the spillover the audience prevents.

**Delete is refused while a television still points at it**, even though the
client asks for confirmation and the request was for a simple dialog. The
foreign key cascades, so deleting a channel takes the _display rows_ with it —
a link somebody already opened on a TV stops working and leaves no record it
existed. A dialog is not enough for something whose consequences are three
rooms away from the person clicking. Archive has the same guard; both name how
many screens are in the way.

#### 2d — UI tidy-up

- [x] `components/Tabs.tsx` — `Tab` and `ArchiveTabs`, shared
- [x] Active / Archived tabs on offices, teams and channels
- [x] Channel actions as icons: edit, archive, restore, delete
- [x] Channel settings behind a cog on the editor, not a second link

**A tab rather than a checkbox, because archived things are a different list.**
What you can do to them differs — restore and delete, not edit — so mixing them
into one list means every row has to say which kind it is. The checkbox was
asking the reader to do that sorting.

**`Tab` came out of the goals page**, which had it first, rather than being
copied a third time. Three copies of a button style is how a design system
quietly stops being one.

**One door into a channel.** The card had "Arrange screens →" beside a
"Settings" button, which is two links doing nearly the same thing. Now it is a
pencil, and the cog lives inside — the name and audience are settings _of the
thing being edited_, so they belong behind the same door as its screens.

#### 2d — drag-and-drop polish

- [x] An insertion line showing where the screen will land
- [x] Above or below, decided by which half of the row the cursor is in
- [x] Arrow keys on the drag handle, so the order is not mouse-only
- [x] `reorderIds()` extracted and tested — 9 tests

**The line sits in the gap between rows**, absolutely positioned and
`pointer-events-none`. That last part matters: a line that swallowed the
`dragover` event would make the row beneath it stop responding, and the
indicator would stick where it was.

**Above or below is measured against the row's own box**, not tracked as an
index — so it stays correct when rows are different heights, which they are: a
message screen is taller than a board.

**The off-by-one is why `reorderIds` is a separate function.** Dropping _below_
row 20 is not index 20; and the index has to be measured in the list with the
dragged row already removed, or a downward move lands one slot early. Both are
the kind of thing that looks right until the one case where it is not, so they
are tested directly rather than through a simulated drag — including an
exhaustive check that a reorder is always a permutation, never losing or
duplicating a row.

**Arrow keys on the handle**, because native HTML5 drag has no keyboard
equivalent at all. Without it the running order was mouse-only. The handle
became a real `button` with an `aria-label`, which costs nothing visually — it
was already there as a grip.

#### 2d — corrections

Four things, three of them bugs.

- [x] A tab shows only its own set
- [x] Dragging works downward as well as up
- [x] A goal screen says whose goal it is
- [x] Channels lose archiving; teams, offices and goals keep it

**`include_archived` means "both".** Right for the checkbox it was built for,
wrong for a tab — the Archived tab was listing active rows too. Narrowed in the
client rather than the API, because the parameter has a second caller that
genuinely wants both.

**Dragging down did nothing, and the cause was where the handler was bound.**
`onDrop` sat on each row, so it only fired when a row was under the cursor at
the moment of release — and a downward drag usually ends in the _gap_ below a
row, or past the last one. Moving up worked because you release over the row
you are displacing. The list now owns the drop, with `onDragOver` on the `<ol>`
to make it a valid target at all.

**A live goal screen was labelled "Deleted goal".** The label fell through to
that whenever `goal.name` was empty, which is most goals — three of five in the
dev data. It now falls back to the metric name, **and names the subject**:
`Calls Made — Priya Raman`, in the picker, the editor row, and as the subtitle
on the wall. That is the real answer to "how do we know whose data a screen
shows": a goal already carries exactly one subject, and we simply never said so.

**Channels lose archiving, and the reason is worth keeping.** Not database
bloat — the config tables hold tens of rows against `metric_fact`'s thousands,
and there were zero archived rows anywhere. The real asymmetry is that
`metric_fact` references team and office with `ON DELETE NO ACTION`, so
**Postgres refuses to delete either once any history exists**. Archiving is not
a preference there, it is the only retirement available. Goals earn it too:
"we hit 4 of 5 last quarter" needs them.

A channel earns nothing. No fact, notification or export points at one, and
nothing about last month gets harder to answer once it is gone. Dropping it
removed a tab, three endpoints, a column and a state.

**`reorderIds` moved to its own module.** Its test had been importing the page,
which drags in the router, the auth context and the HTTP client — and hung the
test runner outright. A test of insertion arithmetic should reach ten lines,
not a page tree.

#### 2c-iv — media precedence, and five fields that lied

- [x] `required` on every field that says "optional"
- [x] `achievement_rule.allow_personal_media`, on by default
- [x] A rule's clip is a **fallback**; a person's own music wins
- [x] 4 new tests, four mutations confirmed caught

**Five fields said optional and were mandatory.** `Field` defaults `required`
to true, so a hint reading "leave empty" was a promise the browser broke with
"please fill out this field". Fixed on all five, and the reason written where
the next person will see it — the default itself is right, the call sites were
not.

**The precedence was backwards.** A rule's media used to override everybody's
walk-up music. That is the wrong way round for the common case: most people
never open their settings, so a rule's clip is best understood as the
**fallback everybody gets**, with the few who have chosen their own keeping it.
Setting a rule's media used to silently overwrite every choice on the floor.

**`allow_personal_media` restores the old behaviour per rule**, for the win
that should always sound the same — a gong for a record month. Off with no
media set is a deliberate silence: the announcement still appears on screen, it
just plays nothing. All three states have a test.

**The hint changes with the switch**, because "played for anyone who has not
chosen their own" and "played for everyone" are different promises, and a
static sentence would be wrong half the time.

#### 2d-iv — only what belongs on this wall

- [x] `app/eligibility.py` — one rule for the picker and the validation
- [x] Refused when authored, skipped when rendered
- [x] `GET /api/channels/{id}/eligible` — the picker's list, served
- [x] 12 tests, ten mutations confirmed caught

**The rule, in one sentence: a channel may show anything not tied to a
different office or team.** Organization-wide goes anywhere — the company
board belongs on every wall. Anything narrower goes only where it is related.

**This closed a real hole, not just a picker inconvenience.** A goal names its
own subject, so the channel audience had nothing to narrow — and a Dallas
agent's goal on a Phoenix channel rendered Dallas's numbers on a Phoenix wall,
at full size, with their name on it. The audience filter added in 2d-ii simply
did not apply to goal screens. The dev data happened to have every goal in
Phoenix, which is why nothing looked wrong.

**Served, not filtered client-side.** `/eligible` returns what this channel may
show, so the picker and the save use the same rule. Two copies drift, and the
version nobody notices is the quiet one — a picker omitting something the
server would have accepted.

**Where something belongs:**

|                            |                           |
| -------------------------- | ------------------------- |
| Goal for a person          | the office of their team  |
| Goal for a team            | that team, and its office |
| Board scoped organization  | everywhere                |
| Board scoped office / team | that office / team        |

##### "Tied to nowhere" turned out to mean two opposite things

A company board is tied to nowhere because it is **about everywhere** — it
belongs on any wall. Somebody on no team is tied to nowhere because they are
**placed nowhere** — they are not in Phoenix, so their number does not belong
on Phoenix's wall.

Both were `Where(None, None)`, so an unplaced person's goal was offered on
every screen in the building. Caught by reading the live output rather than by
a test: the docstring already said "only fits a channel with no audience" while
the code returned `EVERYWHERE`. **The comment was right and the code was
wrong** — the same disagreement this project has now hit five times, and the
first time the comment won.

##### A fourth piece of redundant defence

`fits()` opened with "if either side is everywhere, allow" — and a mutation
proved both lines could be deleted without changing a single answer, because
the fallthrough already said it. The rule is now the two conflict checks and a
default, which is the whole of it.

#### 2d-iii — IP allowlist — done

- [x] `channel.allowed_ips`, checked on the display feed
- [x] `net.real_client_ip()` — trusted-proxy resolution by hop count
- [x] `trusted_proxy_ips` and `trusted_proxy_hops` settings
- [x] A field in channel settings, one address or range per line
- [x] 27 tests, thirteen mutations confirmed caught

**The strongest answer to the readable display token from 1f-iv.** That token
is the whole credential and sits in a browser's address bar on a wall all day,
so the realistic leak is somebody photographing a screen. An allowlist makes
the photograph useless: the link only works from the office network. Spinify
has nothing equivalent — this one is ours.

**Empty by default, and it has to be.** A deployment behind a NAT nobody has
written down would otherwise blank every screen on upgrade, and the person
diagnosing it is standing in front of a television.

**403 with a reason, not the 404 the token uses.** Everywhere else a refusal
here is deliberately indistinguishable — missing, revoked and malformed tokens
all 404, so probing tells you nothing. This one differs on purpose: the token
is valid and the _location_ is wrong, and whoever hits it is overwhelmingly an
admin who has plugged a television into the wrong network. The message names
the address the server actually saw, which is the one fact they need. What it
concedes is that somebody outside learns the link is real — and they still
cannot use it, which is the entire point.

##### The forgery that worked, and why the tests missed it

The first implementation walked `X-Forwarded-For` from the right and took the
first hop that was not in the trusted ranges. That is a widely repeated recipe
and it is **wrong here**. On Docker the real client also arrives from a private
address — 172.21.0.1 sits inside 172.16.0.0/12 — so the walk skipped the
genuine hop as "another proxy" and returned whatever the caller had prepended.

A live request with `X-Forwarded-For: 203.0.113.9` against a channel locked to
203.0.113.0/24 returned **HTTP 200**. Twenty-one unit tests passed throughout,
because every one of them modelled a chain by hand rather than the chain nginx
actually sends: `$proxy_add_x_forwarded_for` **appends** the peer it saw, so a
forged header arrives as "what the client wrote, then the client's real
address".

The fix is to stop inspecting and start counting. nginx appends, so with one
proxy in front the **last** entry is the truth and everything left of it is
whatever the client chose to send. `trusted_proxy_hops` says how many appenders
there are; a load balancer in front makes it 2. A chain shorter than configured
falls back to the socket peer, which is the proxy and will not match an office
allowlist — failing closed.

**The tests now build their fixtures through a `through_nginx()` helper** that
appends the way nginx does, so a chain in a test has the same shape as a chain
in production. Re-verified live: the same forged request now returns 403, and
the message reports 172.21.0.1 — the real address, not the forged one.

**A unit test of a protocol is only as good as its model of the protocol.**
Mine were internally consistent and collectively wrong, and only a real request
through the real proxy showed it.

**The migration must seed, not reset.** Every office gets a channel pre-filled
with the boards its screens show today, in the order they currently appear.
Nobody's wall goes blank on upgrade and nobody re-authors a working setup.

**The IP allowlist is the security item.** The display token is stored readably
(1f-iv), and the argument for that is that it grants little and is revocable.
An allowlist bounds it further — a leaked link is useless from outside the
office network. It does not depend on anything else here and could ship first.

### 2e — Competitions

#### 2e-i — the engine — done

- [x] `competition`, `competition_participant`
- [x] `aggregate.run(team_ids=…)` — rank _within_ a named entrant set
- [x] Scoring: `competitions.standings()`, live or frozen from one call
- [x] Lifecycle job: `scheduled → active → ended → closed`
- [x] Settlement window, default 24h
- [x] Freezing `final_rank` / `final_value` / `reached_at` on close
- [x] `min_participation`, both tie-breaks, `lower_is_better`
- [x] Gap to the place above
- [x] Creation flow with a historical preview — **2e-ii**
- [x] Countdown, provisional-results banner, pinned viewer row — **2e-ii**

**Ranking happens inside the entrant set, not after it.** `aggregate` grew a
`team_ids=` filter for this. Ranking against the whole organization and then
hiding the non-entrants would give a different, wrong number: second of two is
not second of forty. The user-side equivalent already existed as `visible=`.

**No `format` column.** Head-to-head is what two entrants _look like_, not a
third kind of thing to store. A stored format could disagree with the
participant count, and this session has been bitten twice by exactly that shape
of pair — a comment disagreeing with its code.

**`min_participation` leaves an entrant unranked, not last.** They were in the
contest and did not qualify; those mean different things, and a table that
placed them last would say the wrong one.

**Mutation testing: 14 mutants, 13 killed.** Six survived the first pass and
each was a real gap:

| Survivor                    | Why it lived                                                                                               |
| --------------------------- | ---------------------------------------------------------------------------------------------------------- |
| team filter removed         | every team that existed was an entrant, so filtered and unfiltered matched                                 |
| tie-break timestamp ignored | the earliest finisher was also first alphabetically _and_ first created — three orderings agreeing by luck |
| scheduled starts early      | only the "starts on time" direction was tested                                                             |
| `reached_at` window end     | no facts existed after the whistle to drift the timestamp                                                  |
| fake admin actor            | **dead code of mine** — see below                                                                          |
| state filter widened        | provably equivalent — see below                                                                            |

The fake actor was the interesting one. `aggregate` reads its actor for exactly
one purpose: resolving `visible` when the caller did not pass it. This module
always passes it, so the actor was never read, and flipping it from `admin` to
`agent` changed no answer. It is now `NO_ACTOR = None` — worse than useless as
a fake admin, because it would have quietly handed organization-wide visibility
to any future call that stopped passing `visible`, where `None` raises. **Fifth
piece of my own dead code found by mutation testing this session.**

The state filter in `advance()` is the one mutant with no test to write:
`draft`, `closed` and `cancelled` match none of the branches, so widening the
`IN` list cannot change a result. It stays as an index seek on
`ix_competition_org_state`, and is now commented as such rather than left
looking like a guard.

**Verified live against dev data**, which has caught what unit tests missed
repeatedly this session. Four real people, `calls_made`, a closed contest, then
a 999,999 correction dated inside the window for whoever came last: the
leaderboard for that window moved them to first, and the competition winner did
not change.

**Scoring is the existing engine.** `aggregate.run()` over `starts_at →
ends_at`, the same `RANK()` that draws every leaderboard. A competition is not
a new way to measure; it is a defined entrant set, a defined end, and a frozen
result.

**Freezing is the one deliberate inversion of "never store computed values",
and it needs the sharpest test in Phase 2:** correcting an August fact must
change August's _leaderboard_ and must not change August's _competition
winner_. Everything else in this system is derived because derived numbers stay
correct; a competition result is the opposite, because a prize was handed over
on the strength of it.

**The settlement window is why `ended` and `closed` are different states.** A
deal closed at 4:55pm that syncs at 5:10pm should count. Announcing a winner
and then changing it is far worse than a day's delay.

**The historical preview is already built.** `goals.history()` from 1g-iii —
six earlier periods of the same metric and subject — is exactly the "is this
target realistic?" tool the creation flow needs, pointed at entrants instead of
a subject.

**Deliberately deferred:** brackets and tournaments, relay formats,
handicapping. Each is a real chunk of scheduling and progression logic and none
is needed to prove the feature.

#### 2e-ii — the competition UI — done

- [x] `POST/GET/PATCH /api/competitions`, publish, cancel, settle-early
- [x] Entrant add/remove, locked once the contest starts
- [x] `POST /api/competitions/preview` — the same entrants over a past window
- [x] `competitions.view` / `competitions.manage` capabilities
- [x] `Competitions.tsx` — Live / Upcoming / Finished / Drafts, counted tabs
- [x] `CompetitionDetail.tsx` — standings, head-to-head, pinned viewer row
- [x] `competitionClock.ts` — countdown, phase, tab, ordinal, datetime-local
- [x] `components/Select.tsx` — one shared dropdown

**Entering a contest is consent to be ranked in it.** This is the only endpoint
in the product where one person's numbers are deliberately shown to another. The
scope rule therefore governs _seeing the contest_, not seeing the table: **you
are in it, or you could see every entrant anyway.** One sentence, and it lands
correctly for all three roles without a special case — an agent sees the
contests they compete in, a manager sees a contest confined to their own people,
an agent does not see a manager-versus-manager contest in another office.

**Two real leaks and a real bug, all found by mutation testing**, 22 mutants over
the router:

| Mutant                              | What it exposed                                                                                                                                                                                                                                                                                          |
| ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `all` → `any` on entrant visibility | The leak test signed in an _agent_, who can see nobody but themselves — so both versions returned false and the test passed either way. A **manager** is the only role whose visible set spans some people and not others, which makes it the only fixture that can tell the two apart.                  |
| team check inert                    | Chasing it found that a non-admin can only ever see all members of their _own_ team, so the member-by-member check computed the same answer as "your team is in it" — **except for two empty teams**, where `all()` over no members is vacuously true and showed that contest to the whole organization. |
| empty-draft branch, both directions | A flat `False` was right for everybody except the one person standing in the middle of the creation flow: a manager **404'd on the draft they had just created**. Both opposite mutants passing is the signal that nothing had pinned the line down.                                                     |

**The preview bug live data caught and the unit test agreed with.** The
historical preview first measured the equally-long window ending at
`starts_at` — which is history only if the contest begins today. Planning a
contest for next month produced a "history" running a fortnight into the future,
every number zero. The test asserted exactly what the code did, so it passed. The
anchor is now `min(starts_at, now)`, and there is a test per direction. Fourth
time this session that running against real dev data found what the suite could
not.

**`spread` is the number the creation flow exists for.** Not a target — a
competition has no target — but "the leader did 3.4× the bottom of the field",
which answers _will this be worth watching?_ before anybody is told they are
competing. A walkover is worth discovering while the entrant list is still
editable.

**Frozen and live standings come from one function.** `standings()` decides
which; no caller has to remember. `standings_for()` was split out so the preview
rehearses a contest through exactly the real scoring path rather than a second
copy of it.

**The countdown ticks at the rate its size deserves.** `tickInterval()` reads the
nearest deadline on screen: one second when seconds are visible, ten minutes for
a week-long gap. A fixed one-second tick is 600 renders a minute producing
identical pixels.

**`Placeholder.tsx` is now orphaned** — competitions was the last stub route. Left
in place rather than deleted, since Phase 3 and 4 may want it again; say the word
and it goes.

**Six pages had each grown their own `Select`**, drifted into four shapes (one
`children`, one `disabled`, two `hint`, one neither). `components/Select.tsx` is
the superset and the new pages use it. Migrating the other six is mechanical and
deliberately left as its own pass rather than folded into a feature — the /goals
black-screen incident came from exactly that kind of "while I am here"
structural edit.

#### 2e-iii — announcements — done

- [x] `competition.started`, `competition.won`, `competition.finished` event types
- [x] Emitted from `advance()` (start) and `close()` (result)
- [x] Winner announcement is public + celebrated, carries their walk-up media
- [x] `POST /{id}/unpublish` — back to draft from anywhere but settled
- [x] `DELETE /{id}` — draft and cancelled only

**This closed a comment/code disagreement of my own.** `advance()`'s docstring
said _"closing writes the result down, and an announcement goes out with it"_ —
and nothing emitted. A contest settled in total silence: the job froze a result,
handed out a winner, and told nobody. Sixth such disagreement this session, and
the first where the comment described a whole feature rather than a detail.

**Three events, against a catalogue that argues for staying small.** Justified
because each fires **once per contest per person**: somebody in four competitions
a year hears eight things. Unlike a goal, these carry a deadline, which is what
makes them worth an interruption.

**A win is public; a placing is not.** `competition.won` reaches the wall and the
celebration overlay. `competition.finished` — "you came 4th of 9" — stays in the
bell, for the same reason `goal.period_ending` does: a screen is read by whoever
walks past, and coming fourth is not theirs to know. The invariant test now
asserts the _rule_ (nothing public unless it is a celebration) as well as the
list, and the list tripped when `competition.won` was added, which is the wire
working.

**Two bugs found by running it rather than testing it:**

| Bug                                                         | Cause                                                                                                                                                                                                                                                                         |
| ----------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| The start announcement reached 2 of 3 entrants              | `audience()` filtered on account status; the per-entrant lookup did not. Somebody still on an unaccepted invitation was told they finished third in a contest nothing had told them had started. **Two functions computing the same thing** — collapsed into one `_people()`. |
| `cancel` logged every transition as coming from `cancelled` | `was=competition.state` was read _after_ the assignment. My new `delete` had the same shape — attributes survive on a deleted instance until the session expires it — so both now capture before mutating.                                                                    |

**A team id is not a person's id, and no natural test can prove it here.**
`walkup_for()` takes a user id; team ids come from a separate sequence that also
starts at 1, so in a fresh organization team 3 and user 3 both exist and passing
the wrong one plays _that person's_ song for their team's win. Nothing raises. The
shared test database has run its sequences thousands apart, so the collision
cannot be created by adding rows — the guard is its own function (`_win_media`)
purely so the branch can be asserted directly.

**Seventh piece of redundant defence, and the first kept on purpose.** The
organization clause in `_people()` cannot change an answer: entrant ids always
come from one competition's participants, which are org-validated on the way in,
and ids are globally unique so an out-of-org id matches nothing. A mutation
removing it survives and no honest test can kill it. It stays — this query decides
who receives a notification — but the comment says plainly that it is defence
against a future unvalidated caller, rather than pretending to be covered.

#### 2e-iv — the lifecycle UI — done

- [x] `LifecycleBar` — status pill, what it means, and the ways out
- [x] Save as draft / Save & publish, side by side at creation
- [x] `CompetitionForm` edits as well as creates, with entrant diffing
- [x] "N entrants are not ranked" under a table with a `min_participation` floor
- [x] `MyCompetitionsCard` on the dashboard

**Editing had no UI at all.** The PATCH endpoint existed and nothing called it, so
a typo in a contest name meant cancelling it and starting over. One form now does
both; entrants are diffed against what was there when it opened, because
participants are their own endpoints rather than a field.

**Publishing was a one-way door.** A contest with the wrong metric could only be
cancelled, and it then sat under Finished for good. `unpublish` returns it to draft
from every state except settled — the one refusal, because a frozen result has
already been announced and reopening it would make a winner provisional after the
fact.

**Words, not icons, for state changes.** Icons are right for actions repeated down
a list of rows. A transition happens once, changes what a room full of people can
see, and is worth reading before clicking. The old UI was a red X beside a Publish
button, which answered neither _can anyone see this yet_ nor _how do I undo it_ —
both now stated in a sentence under the status pill.

**Delete and Cancel are never offered together**, asserted as an invariant in
`competitionClock.test.ts`. They would read as two words for the same thing. A
draft has nothing to cancel; a running contest must be cancelled rather than
vanish from under its entrants; a settled one is the record of a prize somebody
received and is refused outright.

**"Unranked, not last" needed the page to say so.** Choosing to leave a
below-threshold entrant out of the table was right, but the table then omitted
them silently — somebody would have asked why they were missing. It now says how
many and why.

### 2f — Competitions and achievements on the wall

- [x] `competition` as a channel screen kind — **2f-i**
- [x] TV celebration takeover, with a cooldown — **2f-ii**
- [x] Shout-outs reaching the wall — already true, see below

Last because it needs everything above it, and because a takeover that
interrupts the wrong screen at the wrong moment is worse than no takeover.

#### 2f-i — a competition on the wall — done

- [x] `channel_screen.competition_id`, widened CHECK constraints
- [x] `eligibility.competition_where()` — the narrowest place holding every entrant
- [x] `channels._competition()` renderer, `WALL_STATES`, `WALL_ROWS`
- [x] Offered in `/eligible` and the channel editor, filtered by audience
- [x] `CompetitionScreen` on the wall: prize, countdown, standings

**Shout-outs already reached the wall.** `_achievements` decides what to show with
`events.is_public`, not a list of its own — so `recognition` was included the day
it became public, and `competition.won` arrived the same way in 2e-iii. That
single source of truth is why this item needed no work; a hard-coded list here
would have needed editing three times by now.

**Autogenerate missed both CHECK constraints.** Alembic diffs columns and foreign
keys, not CHECKs, so the generated migration added `competition_id` and left
`kind_valid` refusing the very row the feature exists to write. It would have
failed on insert, after the model, the API and the UI all agreed it was allowed.
Dropped and recreated by hand — and the names passed are the **bare** ones
(`kind_valid`), because the metadata naming convention adds the `ck_<table>_`
prefix and passing the stored name asks Postgres to drop
`ck_channel_screen_ck_channel_screen_kind_valid`.

**Where a competition belongs is not the same question as where a goal belongs.**
A goal names one subject; a competition names many, so the rule is the narrowest
place that contains every entrant:

A competition belongs to a **set** of offices — the one thing here with many
subjects, so the single-slot `Where` cannot express it:

| Wall              | Shows the contest when                          |
| ----------------- | ----------------------------------------------- |
| organization-wide | always — the company's own wall                 |
| an office         | that office is involved                         |
| a team            | that team is entered, or its office is involved |

**Corrected after the fact (2026-08-19).** The first version returned `EVERYWHERE`
for any multi-office contest. That reads as "it goes on both walls" and is right
for the two offices competing — but `EVERYWHERE` fits _every_ wall, so a third,
uninvolved office showed it too. Verified by probe: a Phoenix-versus-Dallas
contest rendered on Austin's wall. Replaced with `competition_offices()` and
`competition_fits()`; nine mutants, all killed, including one that restores the
old leak.

**`entries` is shared with leaderboard slides**, using the same keys, because a
competition table _is_ a ranked list — a second field for the same shape would
mean the wall rendering it two ways and two sets of medal colours to keep in step.
`movement` is null rather than 0: there is no previous period to have moved from,
and 0 would claim it held its place.

**A settled contest shows its frozen table and no countdown.** The wall reads the
same `standings()` the app does, so it cannot disagree with the trophy — verified
by correcting a fact after close and watching the wall not move. "0s left" beside a
final result reads as a stopped clock rather than a finished contest.

**Drafts and cancelled contests are refused at authoring**, not just skipped at
render. Both would be a slide saying nothing, and an admin should hear about it
while choosing rather than watch a rotation skip past.

**Mutation testing: 12 mutants, 11 killed.** The survivor was equivalent, not a
gap: `len(offices) == 1 and None not in offices` — teams with no office produce
`{None}`, and `Where(office_id=None)` _is_ `EVERYWHERE`, so both branches returned
the same value. Removed, with a test pinning the teamless case instead. **Eighth
piece of redundant defence found this way**, and unlike the organization clause in
`_people()` this one had no security purpose — it was a distinction the code only
looked like it drew.

One test premise turned out to be impossible: setting `competition_id` to NULL to
simulate a dangling screen is refused by `payload_matches_kind`. That is the
constraint working, so the test now asserts the real behaviour — deleting a
competition cascades its screen away — and the renderer's `is None` guard is
documented as defence for an unreachable state, exactly as the board and goal
columns beside it already say.

#### 2f-ii — the celebration takeover — done

- [x] `channels.celebrations()` — recent wins worth stopping a room for
- [x] `GET /api/display/{token}/celebrations`, polled every 10s
- [x] `celebrationQueue.ts` — what to play, when, and what to forget
- [x] `CelebrationTakeover` on the wall, with sound
- [x] The rotation holds its place underneath

**Three durations, and they answer different questions.**

| Constant                       | Question                                    | Value |
| ------------------------------ | ------------------------------------------- | ----- |
| `CELEBRATION_LIFETIME_SECONDS` | how long a win stays worth interrupting for | 300   |
| `CELEBRATION_HOLD_SECONDS`     | how long one without media holds the screen | 10    |
| `CELEBRATION_COOLDOWN_SECONDS` | the quiet gap between two                   | 5     |

A win **with** media holds for its clip instead, capped by `media.MAX_CLIP_SECONDS`
— which is the reason that cap exists. Cutting a walk-up off halfway is worse than
the extra few seconds.

All three are server-side and sent to the wall, for the same reason
`refresh_seconds` is: pacing a display is an operational setting, not something
baked into a browser nobody can reach to update. **Tune them here.**

**The screen remembers, not the server.** `notification.celebrated_at` is
per-person, for the overlay in the app; a wall has no person, and two televisions
on the same channel should both celebrate a win rather than racing to claim it. So
the server offers a _window_ of recent wins and each screen tracks what it has
played. The window is also what stops a television switched on in the morning
firing a night's worth of celebrations back to back — verified by planting nine
hourly wins and getting none.

**The handoff to the achievements slide is the point of the lifetime.** Past five
minutes a win stops interrupting and keeps appearing in the rotation. Checked live:
aged one past the window, watched it vanish from the takeover feed and stay on the
slide.

**`forget()` keeps a fortnight of uptime from filling a browser.** Ids the server
has stopped offering are dropped from the "already played" set — safe precisely
because a win that aged out can never be offered again, so forgetting it cannot
cause a replay.

**Mutation testing: 10 mutants, 9 killed, and the survivor was the interesting
one.** Swapping `celebrate` for `public` changed nothing, because today every
public event is also a celebration and the two sets coincide. They mean different
things though — `public` is _permission_ (a screen is read by whoever walks past),
`celebrate` is _significance_ — and neither implies the other. The predicate is now
the conjunction, with a test for each half using a synthetic event type, so an
event worth interrupting one person with but not worth putting on a wall cannot
land there by default.

**Sound plays here and nowhere else.** The in-app overlay is deliberately silent —
a song starting because somebody opened a laptop is a different and much less
welcome thing. Autoplay-with-sound needs the page to have been interacted with,
which a wall satisfies because a person opens the link once and leaves it running.

**The wall does not re-parse a URL.** `media_id` comes from the server, because
`app/media.py` is the one place that knows which YouTube shapes are accepted and a
second copy of that regex in the browser would disagree with it the first time
either changed.

---

### What Phase 2 is not

- **No email notifications** — see decision 4. Email is invitations and
  password resets, and it arrives with SMTP in Phase 3.
- **No rank-change events** — deferred with their snapshot table.
- **No Slack or Teams** — Phase 4, and both are webhooks once the rows exist.
- **No browser push** — not planned. Permission prompts are hostile and
  adoption is poor.
- **No light theme.** One display theme for now, by decision; the palette is
  already defined if that changes.
- **Reports** (period comparison, goal attainment, team comparison) stay on the
  list but are the first thing to cut if Phase 2 runs long — they are analysis,
  not engagement, and nothing else depends on them.

**Done when:** hitting a goal produces a visible moment — in the app, and on
the wall — without anybody going to look for it; an admin can author what plays
on each screen; and two teams can be put head to head with a result that stays
true after the fact.

### Authored channels

Raised during 1f. **Not being built in Phase 1** — it depends on competitions,
and half of what a channel would play does not exist yet. Recorded now because
it changes the shape of the display model, and because Phase 1 is quietly
building on vocabulary that contradicts it.

**The target, matching Spinify:**

A **channel** is an authored playlist with a name, an optional IP allowlist,
and an **ordered** list of screens. A **screen** is one slide in that rotation:
a **goal**, a leaderboard, an image, a YouTube video, a message — and a
competition, if competitions turn out to be their own thing (see below). A
**TV** opens a channel's link and cycles through its screens in the order an
admin arranged, drag-and-drop.

Goals are the important addition to that list. A goal is a metric with a
target and a pace marker, which is exactly the thing a room can act on before
the month closes — more so than a ranking, which tells you where you are but
not whether you are going to make it.

**What we have today is a narrower special case.** A `display` row is a TV
link scoped to an office, and its slides are _derived_: every TV-enabled,
org-visible leaderboard matching that office, ordered by name. There is no
authoring step, no ordering, and a leaderboard is the only thing that can
appear. That was the right amount to build for 1f — it puts boards on walls,
which is the whole point — but it is a subset of the model above, not a
different one.

**The migration, when we get to it:**

- New `channel` table: name, `allowed_ips`, organization.
- New `channel_screen` table: channel, `position`, `kind`
  (`goal` | `leaderboard` | `image` | `video` | `message`, plus
  `competition` once that is settled), and the payload for that kind.
  `position` is what drag-and-drop writes. A **goal screen is a first-class
  kind**, decided rather than assumed — it is expected to be the most-used one
  of the lot.
- `display.office_id` becomes `display.channel_id` — a TV points at an
  authored channel instead of deriving one from an office.
- The existing office-derived behaviour becomes a **seed**: on migration, each
  office gets a channel pre-filled with the boards that office's screens are
  showing today, in the order they currently appear. Nobody's wall goes blank
  and nobody re-authors what already works.

**One thing is worth doing before then, and it is a rename.** Our UI currently
calls the list of TV links "Screens", which under the vocabulary above means
the opposite thing — a screen is a _slide_, not a television. Every week we
build on the wrong word makes the eventual rename touch more code and more
muscle memory. Renamed in the UI now; the model still says `display`, which is
unambiguous either way.

**The IP allowlist is not cosmetic.** The display token is stored readably
(see 1f-iv), and the argument for that is the token grants little and is
revocable. An allowlist bounds it further: a leaked link is useless from
outside the office network. That makes it the most valuable item in this
section from a security standpoint, and it does not depend on competitions —
it could ship on its own if the readable token ever feels too loose.

### Are competitions a separate thing from goals?

Raised at the end of Phase 1. **Mostly already answered** —
[09-competitions.md](09-competitions.md) has carried a
competition-vs-leaderboard-vs-goal table since it was written, and it says the
same thing this section works out below. Repeated here because the roadmap's
own shorthand had drifted from it: several Phase 2 lines say "competition"
where they mean "the number on a screen", which is a goal.

The observation that prompted it is correct: the thing a wall screen should
show is usually a **goal**, not a "competition". Goals are what get tracked
from metrics, they already have targets and pace, and they are what a room can
act on. Everywhere Phase 2 says "competition" as a shorthand for "the number
on the screen", it means a goal.

**But there is a real distinction underneath, and it is not about the data —
it is about when the number stops changing.**

|             | measured against | ends            | recomputes after it ends |
| ----------- | ---------------- | --------------- | ------------------------ |
| goal        | a **number**     | at period end   | **yes, forever**         |
| leaderboard | **each other**   | never — ambient | n/a                      |
| competition | **each other**   | at a set moment | **no — frozen**          |

A goal has to keep recomputing. That is a feature: when a connector backfills
yesterday's deals or an admin corrects a fact, everyone's progress should
update, and it does, because progress is a query and never a stored column.

A competition must do the opposite. Once it closes and somebody has been told
they won, a late-arriving fact must **not** silently change the winner three
days later. That is what "settlement window" and "result freezing on close"
in the checklist above are for, and it is the one behaviour that cannot be
expressed as a goal without contradicting how goals are defined to work.

So the shape that seems right:

- A competition is **not** a third way to measure. It reuses the metric, the
  period, and the aggregation query, exactly as goals and leaderboards do.
- What it adds is a **defined entrant set** ("Phoenix versus Dallas", not
  everyone), a **defined end**, and a **frozen result** written at close.
- Head-to-head is the interesting format precisely because it is relative:
  two teams on deals closed this month, where one of them wins. A goal cannot
  express that — both teams could hit 50 and both would simply have hit it.

The user-facing framing that falls out of it: **a goal is you against a
number, a competition is you against someone else.** Both can be a screen on a
channel; a competition just also has a moment where it is over.

**Head-to-head is already a planned format**, not a new idea —
[09-competitions.md](09-competitions.md) lists `individual`, `team`, and
`head_to_head`, and describes the last as "two large numbers side by side",
which is exactly the two-teams-on-deals-this-month case.

**What is genuinely still open**, to decide together when Phase 2 starts:

1. Can a competition be built _from_ an existing goal ("turn this month's team
   goal into Phoenix vs Dallas"), or is it authored separately? The doc does
   not say, and it is the difference between a one-click action on a goal and
   a whole second creation flow.
2. Does a head-to-head need its own scoring, or is it a two-entrant
   leaderboard with an end date and a settlement rule?
3. Does freezing store the full standings, or only the winner? Storing the
   standings answers "what did it look like when it closed" a year later, at
   the cost of a table that duplicates a query.
   **Decided:** a goal is a screen type in its own right, independent of
   competitions. The screen kinds are **goals, leaderboards, competitions (once
   we settle what they are), images, and video** — with goals expected to be the
   common case, since they are the thing tracked from metrics that a room can act
   on before the period closes.

**Candidate to pull forward:** the **webhook/API connector**. It's cheap, needs no OAuth, and lets a technical customer integrate anything immediately. Strong value for low cost — see [15-data-integrations.md](15-data-integrations.md).

---

## Phase 3 — Integrations — **complete**

**Goal:** data flows in automatically. Built last, with full attention.

### What Phase 3 delivered

|                                    |                                                                                 |
| ---------------------------------- | ------------------------------------------------------------------------------- |
| **3a** Framework                   | The connector contract, the pipeline, webhooks, the connect flow, source health |
| **3b** Connectors                  | **Fourteen**, on four engines                                                   |
| **3c** Help page                   | Generated from the connectors, so it cannot go stale                            |
| **3d** Directory sync              | People from a Microsoft tenant, proposed and approved                           |
| **3e** One connection per provider | One credential per provider, several capabilities on it                         |
| **3f** Salesforce sign-in          | The last pasted-token connector, gone                                           |
| **3g** Email (SMTP)                | Invitations and reset links arrive instead of being pasted                      |
| **3h** The sweep                   | Everything the docs promised for Phase 3 without a slice number                 |

> **This said "sixteen" until an audit counted them.** Nobody had, since the number
> was written once and carried forward — probably counting SQL's dialects as
> separate entries. Worth correcting rather than shrugging at: a count in a roadmap
> gets repeated into a README and then into something somebody says out loud.

**Fourteen connectors** in six groups: Google Sheets and Excel; HubSpot, Salesforce,
Pipedrive and Close; Freshdesk and Zendesk; Gong and Aircall; SQL (five dialects)
and Snowflake; the webhook and the generic JSON API.

**Four engines, not fourteen connectors** — the bet 3b was designed around, and it
paid: the last four REST providers were roughly forty lines of spec each.

### What is verified, and what is not

**Verified:** 1,938 backend tests and 306 frontend tests, every new module mutation
tested to completion, and the whole directory flow probed end to end against the dev
database.

**Not verified:** _no connector has run against a live account, and no mail has been
sent through a real relay._ The specs are read
from each provider's documentation, and endpoint names, page sizes and filter
parameters are exactly the sort of thing that changes without anybody saying so. The
Test button reports each provider's own words, which is where a mismatch will show
up. **That is the QA pass**, and it is deliberately scheduled after the MVP rather
than three times against a surface that was still moving.

### What live probing and mutation testing caught in Phase 3

Worth listing in one place, because the pattern is the argument for the method — a
green suite proved none of these:

1. **A `partial` run advanced the watermark**, so answered quarantine questions lost
   their rows for ever.
2. **A source with no external id appended its rows on every sync** — four passes,
   four copies of the same fact.
3. **A truncated read reported itself as a clean success**, so the watermark moved
   past rows nobody had read. Two comments claimed it was "reported on the run"; it
   was reported in a log file.
4. **HubSpot was reading ten records a page**, because cursor paging never sent a
   page size — silently capping a large tenant at a quarter of its deals, every
   sync.
5. **Snowflake could never have appeared**, because the driver's import name was
   guessed from its package name.
6. **`/common/` was wrong for a single-tenant Entra app**, and a test asserted it
   confidently.
7. **A fresh Microsoft connection asked for tenant-wide read access** to features
   that do not exist yet.
8. **Passing an empty params dict wiped a URL's query string**, which broke Graph
   paging on the `@odata.nextLink`.
9. **`/api/admin/sso` had no tests at all** — which is how it came to hold a second
   copy of a credential for a whole phase.
10. **A migration backfilled `now()` for every row**, marking every abandoned draft
    as finished.

### 3a. Framework

#### 3a-i — tables, contract, secrets — done

- [x] `data_source`, `source_mapping`, `connector_credential`, `sync_run`,
      `user_identity`
- [x] `metric_fact.data_source_id`, and the idempotency key corrected
- [x] `Connector` protocol + registry (`app/connectors/`)
- [x] `app/credentials.py` — the only module that touches ciphertext
- [x] 22 tests, ten mutations confirmed caught

**Decisions taken with you before writing any of it:** webhook connector first
(no OAuth, so it is the honest test of the abstraction), 90-day backfill default,
detect-and-warn on two sources feeding one metric, direct mapping plus filters
plus a multiplier rather than an expression language, per-deployment OAuth
credentials in Settings rather than a hosted relay, **human corrections win over a
sync** with the conflict counted, and **quarantine rather than auto-create**
people.

**The idempotency key was wrong and is the reason this slice matters.**
`uq_metric_fact_external` was `(organization, metric, external_id)`. Two
connectors can legitimately issue the same id — a Salesforce opportunity and a
spreadsheet row are both plausibly "1042" — so the second connector's rows would
have silently _updated_ the first's instead of adding their own. Totals stay
plausible, which is the worst kind of data bug. `data_source_id` is now in the
key. The metric stays in it too, because one source row feeds several metrics: a
closed deal is both a "deals won" count and a "revenue" amount.

**`metric_fact.data_source_id` is `ON DELETE RESTRICT.`** Deleting a source must
not delete the measurements it collected — a settled competition was computed from
them — and nulling the column would break the key above, so re-connecting the same
source would import everything twice. A source that has written facts is disabled,
not deleted: the same rule as a metric that has been measured.

**Secrets are one encrypted blob, not a column per field.** A webhook has a shared
secret, OAuth has two tokens and an expiry, a database has a password — a column
per possibility is a schema that grows with the connector list. `expires_at` is
deliberately outside the blob, because the scheduler asks "does this need
refreshing?" every pass and decrypting every credential to answer that would be
slow and needless exposure. `put()` **replaces** rather than merges: a merge leaves
a stale refresh token behind when a provider rotates one, and that breaks days
later with nothing in the logs from the day it actually broke.

**One mutation survived, and it was the fixture's fault again.** `available()`
sorts case-insensitively; the test used "Alpha", "Middle", "zeta", which sort
identically either way because uppercase precedes lowercase in ASCII. Renamed to
"apple" / "Banana" / "Cherry", which only hold that order if case is folded — and
real connector names are "HubSpot" and "webhook".

#### 3a-ii — the pipeline — done

- [x] `app/mapping.py` — filters, value, multiplier, date, external id. Pure.
- [x] `app/identity.py` — match, quarantine, ignore
- [x] `app/sync.py` — orchestration, upsert, correction protection, backoff
- [x] Wired into the job loop, **first in the pass**
- [x] 96 tests, 51 mutations confirmed caught

**Sync runs first in the job pass.** Everything after it reads `metric_fact` — a
goal detects as achieved, an announcement rule fires, a competition settles — so
syncing first means all of that sees the numbers that arrived since the last tick
rather than celebrating them an hour late.

**`mapping.py` is pure and has no database.** That is where the fiddly work lives:
`"$1,200.50"` and `1200.5` are the same amount, `(1,200)` is negative, `"100"` and
`100` compare equal, and a bare `2026-08-18` is not an instant until somebody says
whose midnight it is. None of that should need a Postgres container to test, and
all of it happens in one place so seven connectors cannot each get it subtly wrong.

**A bare date is interpreted in the source's timezone**, falling back to the
organization's, then UTC. A spreadsheet exported in Sydney and read in Phoenix
otherwise lands a deal on the wrong day — and for a daily goal, in the wrong period
entirely. Verified live: `2026-08-18` from a Phoenix source stored as
`2026-08-18T07:00:00Z`.

**The window is measured from the last successful run's _start_, not its finish.**
A deal reported a minute after it closed would otherwise fall in the gap. Overlap
costs nothing because the upsert is idempotent, which is the entire reason
`external_id` exists — and a **failed** run does not advance the window, or a
failure would silently skip whatever happened during it.

**Backoff never polls faster than the configured interval.** A nightly warehouse
that failed must not be retried every five minutes just because the curve starts
there.

**`_upsert` looks the row up rather than using `ON CONFLICT DO UPDATE`**, and that
is a deliberate cost. The decision depends on a column of the _existing_ row — has
a human corrected it — and while a conflict clause could express that, it would
give up the conflict **count**, which is what makes "the human wins" visible
instead of silent.

**Mutation testing: 51 mutants across the three modules, all killed.** Three
survived a first pass:

| Survivor                                    | Why                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| ------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| bad timezone raises instead of falling back | Two different exception types are reachable — `ZoneInfoNotFoundError` for a typo, `ValueError` for `/etc/localtime` — and only the first was tested, so narrowing the catch survived.                                                                                                                                                                                                                                               |
| `map_to` leaves the pending count           | `pending()` filters on `user_id IS NULL`, so a mapped row drops out of the list whatever its count says. Now asserted directly.                                                                                                                                                                                                                                                                                                     |
| the email-shape guard in `_by_email`        | **Equivalent, not a gap.** An identifier with no `@` cannot equal an email, so the query returns nothing either way. The guard is an optimisation — a sync resolving thousands of rows would otherwise pay a round trip each to learn that `0051x000ABCdef` is not an email — and the comment claiming it was the reason names are never matched was wrong. The query only ever looks at `email`; that is where the property lives. |

#### 3a-iii — the webhook connector — done

- [x] `webhook_event` inbox table
- [x] `app/connectors/webhook.py` — the first real connector
- [x] `POST /api/hooks/{token}` — parks, then processes immediately
- [x] HMAC signatures, optional; size cap; batch payloads
- [x] 41 tests, 21 mutations, 19 killed and 2 documented as untestable

**It pushes; the protocol pulls.** Reconciled with an inbox rather than by
special-casing the pipeline: the endpoint parks a payload, and `fetch` reads the
inbox. So a webhook goes through the same mapping, identity resolution and
correction rules as a warehouse query instead of having a private path into
`metric_fact`.

**Parked _and_ processed immediately.** Durable and retryable, but a closed deal
reaches the wall in seconds rather than at the next hourly tick — which is the
point of all the celebration work. A failure costs nothing because the payload is
already stored.

**A sender is never punished for our configuration.** A mapping pointed at the
wrong column is a `partial` run and a message on the Integrations page, not a 500
for whoever posted the data — a 500 teaches senders to retry payloads we already
have. Unknown token is **404, never 401**, so a wrong key cannot learn that the
endpoint exists.

**No `processed` flag on the inbox.** The pipeline is already idempotent, so
`fetch(since)` returning everything in the window is enough, and re-reading writes
nothing. A flag would add a state machine whose half-set failure mode is worse than
a repeated no-op.

**Batch rows get one id each** (`batch-7#0`, `batch-7#1`). Ten rows in one delivery
sharing an id would collapse into a single fact, because the id is exactly what
makes the sync idempotent.

**`LocalContext` replaced the `source_id` argument, and finding out why was the
useful part.** The webhook connector first opened its own `SessionLocal()`. That is
wrong twice over: it reads the inbox on a different connection from the one writing
the facts, so the two are not one transaction — and it sees an empty database under
test, because the suite runs inside a transaction that is never committed. The
second problem is how the first was found. `fetch` and `discover` now take one
optional `local=` carrying the session and the source id; every pulling connector
ignores it.

**Two surviving mutants, both deliberate.** Swapping `hmac.compare_digest` for `==`
passes every assertion, in the signature check and the token check. Constant-time
comparison is a property of _how long_ a function takes, not of what it returns, and
a test that measured timing would be flaky enough to be deleted within a month.
Verified by reading and documented in place, so the next person to see the surviving
mutant knows it was considered.

Two real gaps it did find: non-dict rows in a **bare** list were unfiltered (the
wrapped-batch path was tested, the bare one was not), and `fetch` ignored which
inbox was its — every test had a single source, the same single-fixture blindness
that hid a cross-organization leak earlier in this project.

#### 3a-iv — the sources and mappings API — done

- [x] `app/routers/data_sources.py` — 14 endpoints: connectors, sources, credentials,
      test, discover, preview, sync now, mappings, quarantine
- [x] 55 tests, 33 mutations, all killed
- [x] Verified live over HTTP against dev data, which is where the two real bugs
      below were found

**A live probe found what 1,300 tests did not, for the fifth time in this project.**
Both findings were in the sync window, and both were serious.

**The window advanced past rows it had only quarantined.** `since_for` accepted the
last `ok` **or `partial`** run, and a run that holds rows for a quarantine question
is `partial`. So the documented promise — answer "this identifier is Sam" and the
next sync re-reads the rows that raised the question — was false: the window had
moved past them, and the data was gone for good. The same applied to the wizard's own
order of operations, where a test event arrives before any mapping exists. `ok` only
now, and the docstring explains why there is deliberately no silent expiry: an
unanswered question pins the window, which costs a query, while advancing past it
costs the data. The condition is already visible as `partial` with a count of waiting
identifiers.

**The test that should have caught it passed, because the stub connector ignored
`since`.** It handed back every row it was given regardless of the window — so a
window bug was invisible to every test that used it. A stub that cannot say "no"
cannot test a window. It now filters, and `test_mapping_the_person_then_re_syncing_
writes_the_held_rows` fails against the old rule. Making it honest also exposed
`test_re_reading_the_same_row_writes_nothing` as newly vacuous — it was passing by
reading nothing rather than by re-reading and finding the fact already there — and
forced a distinction worth having: a row's **availability** is when the source learned
it, not when it happened. A connector that filters on `closed_at` rather than a
modified timestamp will never deliver a late edit, which is a trap every connector in
3b has to avoid.

**Preview was built on the sync window too**, so it showed an empty table right after
a sync — exactly when somebody is trying to work out why their mapping is wrong. It
asks over the source's own backfill window now, consults no run history, and keeps
the **newest** rows rather than the first ten of ninety days.

**The endpoint URL had nowhere to be seen.** "Secrets never come back" is right for a
signing secret and wrong for a webhook token, which is an address somebody has to
paste into their CRM — a token that cannot be read is a feature that cannot be used.
`display.url` already makes the same trade. One declaration on the connector,
`endpoint_credential = "token"`, now drives all three behaviours that follow from it:
generated on creation, refused on a credential write (an address somebody picked is
one somebody can guess), and returned as part of the URL. `POST …/endpoint/rotate`
replaces a leaked one without deleting the source and its history.

It is read through `endpoint_credential_of` rather than declared on the `Connector`
protocol, deliberately: a member on a `runtime_checkable` Protocol is a member
`isinstance` demands, which would make all six pull connectors write
`endpoint_credential = None` to declare the absence of something.

**Two smaller ones, both from the same probe.** A credential write **replaced** the
stored dict, so an admin turning on signatures would save a signing secret and
silently destroy the endpoint token — merged now, with `put` still replacing for the
token-refresh reasons of its own. And pydantic ignores unknown keys by default, so
`{"tokn": …}` validated, stored nothing under the name meant, and blanked the real
secret while reporting success; unknown keys are refused by name now.

**The mutation that mattered most.** "Show an endpoint for a connector that fetches"
survived, because the test's stub had no credentials at all. Given a pull connector
whose secret is named `token` — which most REST connectors have — that mutant
publishes a private API key as a public URL. The endpoint has to be decided by what
the connector _is_, never by what its credentials are called.

#### 3a-v — the connect flow — done

- [x] `sourceWizard.ts` — the auto-suggested mapping, where to resume, and the
      health badge. 39 tests, 31 mutations, all killed
- [x] `dataSources.ts` — wire types and paths in one place
- [x] `ConnectSource.tsx` — the five steps
- [x] `MappingEditor.tsx` — pickers with reasons, filters, and the live preview
- [x] `DataSource.tsx` — a source's own page: endpoint, quarantine, mappings, runs
- [x] Data sources on the Integrations page, above the sign-on catalogue
- [x] Walked the whole flow live through nginx, then removed the probe data

**The source is created at step three, not at the end.** A webhook's endpoint is
generated server-side and cannot be shown until the row exists — and asking
somebody to fill in five steps before finding out whether the connection works is
the shape of wizard people abandon. The cost is a real source left behind by an
abandoned setup, which is why the list says _setup unfinished_ and links back into
the flow rather than pretending it is not there. `resumeStep` opens on the first
question still unanswered, so nothing is retyped.

**Everything the flow saves is switched off.** Preview needs a mapping to exist
server-side, so the editor persists every edit — and a mapping left
`enabled: false` imports nothing. An abandoned setup therefore does no harm, and
"turn it on" at step five is the moment data starts flowing. Verified live: with
the mapping off, a sync reads nothing and reports _no mappings configured_.

**The preview comes from the server, through the same code the real sync uses.**
Computing it in the browser would be a second implementation of the interesting
logic, and the two would agree right up until somebody fixed a bug in one of them.

**Every guess shows its reason.** "These values look like email addresses",
"Named like an amount", "No number column, so each row counts as one". A guess an
admin cannot see the reasoning for is a guess they have to verify from scratch,
which costs more than being asked outright — and a wrong guess with its reason
showing is obvious at a glance instead of mysterious three weeks later. On a real
payload the live probe sent, all four columns were guessed correctly.

**Column roles are guessed from kind first, name second.** A column of dates beats
a column merely _named_ `date`. Names match on **words**, not letters, because `id`
inside `paid` would otherwise nominate the money column as the row identifier —
and a wrong external id makes re-imports either duplicate or overwrite the wrong
fact. That one is a test rather than a comment.

**Mutation testing found two pieces of my own dead code.** A guard in front of
`best(fields, [], ID_WORDS)` re-checked what the function already returns null for.
And the "prefer a text column for the person" fallback was unreachable for the case
the test used, because the _email_ lookup's own name-match fallback got there
first — the test had to be rewritten with columns that nothing names before it
could tell the two apart. One survivor was left deliberately: making the
`!enabled` branch also fire for an unmapped source is unreachable, because the
mappings check returns first. It was removed from the list rather than left as a
permanent survivor, which is how you train yourself to ignore survivors.

**`sourceHealth` is ordered by what an admin can act on, not by severity.** A
source nobody finished setting up reports as _setup unfinished_ rather than _never
synced_ — the second is true and useless. Lateness is measured from `next_run_at`,
what the scheduler actually promised, rather than recomputed from the interval,
because two places calculating the same moment is two places to drift. Grace is a
whole interval floored at ten minutes: the job loop ticks rather than firing to the
second, and a badge that cries wolf at two minutes is a badge nobody reads by the
end of the week.

#### 3a-vi — staleness where the data is read — done

- [x] `GET /api/data-freshness` — per metric, when a fact last landed and the
      bare scheduling facts of the sources feeding it. 15 tests, 14 mutations,
      all killed
- [x] `currencyOf` + `agoInWords` in `sourceWizard.ts`, sharing `isLate` with the
      integrations list. 54 tests, 45 mutations, all killed
- [x] `DataCurrency.tsx` on the leaderboard view, goal detail and live
      competitions
- [x] All four states checked live against real data, then the probe removed

**Everyone can read it, not just admins.** The people being ranked are the ones
who notice their deal is missing, and "a feed behind these numbers is failing" is
a far better answer for them than silence. So the payload is deliberately thin — a
status word, three timestamps, an interval, per metric. No source names, no
connector types, nothing about configuration. An agent can learn that the numbers
are stale without learning what the organization has plugged in, and there is a
test asserting the source's name and connector never appear in the body.

**The judgement lives in the client, and there is only one of it.** `isLate`
already decides what overdue means and is mutation-tested; a second definition in
Python would have agreed right up until somebody adjusted one. The endpoint
returns facts and the client decides — which is why the fields it returns are
exactly the ones `isLate` reads, and why that is also asserted.

**Silence when all is well.** A healthy feed produces a small grey "Data as of
four hours ago" and nothing more. A banner on every page saying everything is fine
is a banner people stop seeing, and then it fails on the day it matters.

**A hand-entered metric is never stale.** Nobody promised it would refresh, so
warning about it invents a problem — and a manual correction must not count as a
sync either, or somebody typing a number by hand would make a dead feed look
alive. That second one is the failure this whole endpoint exists to reveal, so it
is a test rather than a comment.

**A settled competition shows nothing.** Its results are frozen, so there is
nothing to be current about.

**Two surviving mutants, both unobservable and both documented in place.**
Removing the organization filter from the facts and mappings queries leaks nothing
— the results are keyed by metric id and only ever read for metrics the
organization-scoped query returned — so no test can catch it. They stay because
they keep the scan off every other tenant's rows, which on `metric_fact` is the
difference between an index range and the whole table. A third "survivor" was a
badly-built mutation of mine that never produced the per-metric query it claimed
to; the property is covered instead by measuring the query count at two sizes and
asserting it does not grow, which is a stronger guarantee than any single mutant.

#### 3a-vii — managing a connection once it exists — done

- [x] `data_source.archived_at` + migration
- [x] `POST …/archive` and `…/restore`; `?include_archived=` on the list
- [x] Editable settings on the source page — name, interval, backfill
- [x] A collapsed _Removed (n)_ disclosure on the Integrations page
- [x] 66 API tests, 42 mutations, all killed

**A source that had imported one measurement could not be removed at all.** Delete
is refused once facts exist, because `metric_fact.data_source_id` is what answers
"where did this number come from" and orphaning it makes a number unauditable — so
a test webhook stayed in the list forever. There was also no way to rename a source
or change its schedule without deleting and reconnecting it.

**Three ways to stop, each named for what it does to the data** rather than to the
row, because that is the question somebody actually has:

|            |                                                                                        |
| ---------- | -------------------------------------------------------------------------------------- |
| **Pause**  | Stops syncing. Credential kept, one click back.                                        |
| **Remove** | Forgets the credential, disables it, hides it. **The numbers stay and keep counting.** |
| **Delete** | Only before it has imported anything — then there is no provenance to keep.            |

**Removing does three things and all three are the point.** The credential is
forgotten, so a removed webhook endpoint stops accepting deliveries immediately —
anything less is a removal in name only, and it is verified live rather than
assumed. It is disabled. It is hidden.

**`due()` filters on `archived_at` as well as `enabled`.** Archiving sets both, so
the extra clause is belt and braces — but "a removed integration does not run" must
not depend on a second column staying in step. Tested by re-enabling an archived
source directly in the database and asserting it is still not due, and `PATCH`
refuses to re-enable one without restoring first.

**Restore brings back the row, its history and its mappings — not its credential.**
Enabling it would produce a source that fails on its next run and reports it as a
_failure_ rather than the unfinished setup it is. It lands on exactly the state the
connect flow already resumes from.

**Two interaction bugs, both from adding a state to something that already had
states.** `sourceHealth` reported a removed source as _setup unfinished_ and offered
to resume it, because archiving forgets the credential and that is what the check
reads — `archived` is now tested first, above everything. And `data-freshness` would
have put _importing is paused_ on a leaderboard working perfectly well from a
replacement source, because archiving disables the old one. Both are tests now, and
both are the same shape: a new state that existing logic silently misreads.

### 3a — complete

Framework, pipeline, webhook connector, API, connect flow, staleness, and
management. **1,351 backend tests and 199 frontend tests**, every module in the
phase mutation-tested with all mutants either killed or documented as
unobservable.

The recurring lesson of the phase, in one line: **five separate bugs were found by
walking the real HTTP flow against real data, after the tests were green** — a
window that discarded quarantined rows, a preview that showed an empty table, a
credential write that wiped the endpoint token, an endpoint URL with nowhere to be
seen, and a type-guesser that would not suggest `$1,250.00` as a number.

### 3e. One connection per provider — **backend and page done**

**The problem, stated exactly.** An admin who wants Microsoft SSO _and_ Excel data
today creates **one** app registration in Entra and then pastes the **same client id
and the same client secret into two different forms on the same page**:

|            | Stored in      | Asks for                                               | Callback                           |
| ---------- | -------------- | ------------------------------------------------------ | ---------------------------------- |
| SSO        | `sso_config`   | issuer, client id, client secret, scopes, button label | `/api/auth/sso/callback`           |
| Connectors | `oauth_client` | client id, client secret                               | `/api/integrations/oauth/callback` |

Neither knows the other exists. Rotating a leaked secret is two jobs. The
Integrations page shows a "Microsoft" row under **Provider sign-ins** and a
"Microsoft 365" card under **Sign-on and notifications**, and nothing on the page
says they are the same app registration — because nothing in the code knows they
are.

**One Entra app registration can serve all of it.** Worth stating plainly, because
the whole proposal rests on it: an app registration holds _several_ redirect URIs,
and delegated scopes are requested per authorization request rather than fixed on
the app. So one registration can be used for `openid profile email` in a sign-in
flow and `Files.Read.All offline_access` in a connector flow. The same is true of
Google.

#### The model: one credential, several capabilities

**`oauth_client` becomes the single home for a provider's credentials**, and gains
one field: `tenant_id`. Microsoft needs it in two places and currently has it in
neither properly —

- SSO derives its issuer from it: `https://login.microsoftonline.com/{tenant}/v2.0`,
  which is also what validates the `iss` claim on a token.
- The connector spec currently hard-codes `/common/` in its authorize and token
  URLs, which works for a multi-tenant app and is wrong for a single-tenant one.

**`sso_config` keeps only what is genuinely about signing in** — `enabled`,
`button_label`, `auto_provision`, `require_sso` — and loses `issuer`, `client_id`
and `client_secret_encrypted` to the provider credential.

**What a provider connection powers becomes a list of capabilities**, each of which
is a thing the deployment has switched on:

| Provider  | Capabilities                                                                                 |
| --------- | -------------------------------------------------------------------------------------------- |
| Microsoft | Single sign-on · Excel data · Directory sync (3d) · Notification email via Graph `Mail.Send` |
| Google    | Google Sheets data · (single sign-on, if we ever add it)                                     |

**The scopes to request are derived from the capabilities that are on.** That is the
part that makes this simpler rather than merely tidier: instead of an admin working
out which permissions a feature needs, the page tells them — _"you have SSO and
Excel switched on, so add these two permissions and these two redirect URIs"_ — one
list, generated from what they ticked.

#### It may also delete a whole integration

`Mail.Send` on the same Microsoft app registration sends invitations and password
resets through Graph, with no SMTP server, no separate credential, and no separate
form. An earlier Microsoft 365 project already does exactly this.
For a Microsoft 365 shop that removes the SMTP setup entirely; SMTP stays for
everyone else, as the fallback rather than the only route.

#### Sketch of the UI

The two sections collapse into one, and a provider is one card:

```
CONNECTIONS

┌──────────────────────────────────────────────┐
│ ⊞ Microsoft 365                  Connected   │
│                                              │
│ Powering:                                    │
│   ☑ Single sign-on                           │
│   ☑ Excel spreadsheets                       │
│   ☐ Sync people from your directory          │
│   ☐ Send email (instead of SMTP)             │
│                                              │
│ Tenant · acme.onmicrosoft.com    [ Settings ]│
└──────────────────────────────────────────────┘
```

One card, one credential, one form behind Settings, and a checklist that doubles as
the explanation of what the connection is _for_. A provider with nothing switched on
reads "Not connected" and the checklist becomes the reason to connect it.

**Cost, honestly.** This is a migration that moves two encrypted secrets between
tables and rewrites both the SSO settings panel and the provider-sign-ins list —
several hours, and it touches authentication, which is the one area where a mistake
locks people out. `allow_local_login` is the existing way back in and would have to
be verified before and after. Worth doing, but not to be done casually, and better
done **before** 3d adds a third consumer of the same credential than after.

#### 3b-xvii — auditing all fourteen connectors — done

A systematic pass rather than a reread: fill every REST connector's config with
plausible values, capture the request it actually builds, and look at all of them
side by side. Three real bugs, none of which any test caught, and one of which the
audit's own fix introduced before a test caught _that_.

##### 1. Cursor connectors never asked for a page size — HubSpot was reading ten at a time

`_pages` set the page-size parameter for `page` and `offset` paging and not for
`cursor`. So a cursor connector got whatever the provider defaults to, and
**HubSpot's default is ten**.

The compounding is what makes this bad rather than merely wasteful. HubSpot has no
modified filter, so it re-reads _everything_ every sync (a deliberate trade — see
3b-xii). At ten records a page, twenty thousand deals is two thousand requests, and
`MAX_PAGES` cuts it off at five hundred — so that customer would have imported a
quarter of their deals, every time, for ever, with nothing anywhere saying so.

Fixed by asking for the page size whatever the paging style. Pipedrive was also
affected; its own default happens to be kinder, but relying on a provider's default
is relying on something that can change without notice.

##### 2. The fix immediately over-reached, and a test caught it

Gong pages by cursor and documents **no** page-size parameter, so the corrected
engine started sending it a `per_page` it never asked for. Its spec now says
`size_param=""` and the engine leaves it alone.

Worth recording because it is the argument for writing the test at the same time as
the fix rather than after it: the test that proved the HubSpot fix worked is the one
that found the Gong regression, in the same run.

##### 3. A truncated read reported itself as a clean success — and lost the rows

The one that matters. Both engines had a row cap, and both handled hitting it the
same way: log a line and stop. Two comments claimed the truncation was _"reported on
the run"_. It was not. The run reported **`ok`**, and an `ok` run advances the
watermark — so the next sync asked for changes since a point _past_ rows nobody had
ever read, and they were never read again.

Silent, permanent data loss, on exactly the sources most likely to hit it: a first
sync with a ninety-day backfill on a busy source.

A `Truncated` exception now carries it, raised **after** the rows already read so
those are kept, and recorded by the sync — which makes the run `partial`, and a
partial run does not advance the watermark. **The consequence is a source that gets
stuck**, reading the same first hundred thousand rows and saying so on every run.
That is deliberate and is the better failure: stuck and complaining can be fixed by
narrowing the query or the backfill, and silently lossy cannot be fixed at all
because nobody knows it happened.

**Three tests had to be rewritten**, including one named
`test_the_row_cap_stops_rather_than_raises`. They had encoded the bug as the
specification, which is the most expensive kind of test there is.

##### What the audit confirmed was already right

- Every connector's URL formats fully — no `{placeholder}` survives into a request.
- An unconfigured connector refuses with a sentence naming what is missing, rather
  than calling a nonsense URL.
- `external_id` is left to the mapping rather than guessed at, and the wizard's
  suggestion already picks `id` out of a REST payload — so the duplication trap
  from 3a stays closed.
- Every window is sent in the shape its provider reads: epoch for Zendesk and
  Aircall, ISO for Gong and Close, a `WHERE` clause for Salesforce.

#### 3f. Salesforce sign-in — done

Salesforce took a pasted access token, and Salesforce access tokens expire within
hours — so unlike every other connector this one stopped working on its own, with
nothing to explain why. It now signs in like Sheets and Excel.

**It cost a catalogue entry and a spec change**, which is exactly what 3e was
supposed to buy. The refresh machinery, the popup, the token storage and the
per-connection credential all existed; Salesforce needed a `Provider`, an
`OAuthSpec`, and a credential model with two fields nobody types.

**One engine change, and it removed a hardcoded assumption rather than adding one.**
`endpoints_for` filled `{tenant}` with `common` when a connection named none —
Microsoft's word for "whichever directory this account belongs to", which means
nothing to anyone else. Salesforce's login host says _which Salesforce_: production,
a sandbox, or a company's own My Domain. So the fallback moved onto the spec as
`default_tenant`, and Salesforce's is `login.salesforce.com`.

`refresh_token` in the scope list is the permission worth naming: it is Salesforce's
spelling of offline access, and without it the connector is straight back to working
for two hours.

##### A test that named a provider instead of a property

`test_each_takes_a_token_rather_than_signing_in` was parameterised over HubSpot,
Salesforce and Pipedrive — and became false the moment Salesforce started signing
in. It now asks the question that actually decides: **does this provider issue a
credential that lasts?** With Salesforce as the stated exception, and why.

#### 3e-ii — telling an admin exactly what to grant, and where to find it — done

Two halves of the same complaint: the connection said _what_ it needed in the
provider's raw vocabulary, and the connectors said _where_ to find things one hint
text at a time.

**Permissions are described, not just listed.** A scope string on its own is not
actionable. In Entra, `Files.Read.All` exists **twice** — once as a _delegated_
permission and once as an _application_ one, on different tabs, meaning different
things — and picking the wrong one produces a connection that authorises cleanly
and then returns 403 on every read. Some also need a tenant admin to press _Grant
admin consent_, a separate button nobody presses unless told, and until it is
pressed the permission does nothing at all.

So each permission now carries its kind, whether consent is needed, and **what it
is for**:

| Permission                 |           |               | Needed for         |
| -------------------------- | --------- | ------------- | ------------------ |
| `openid` `profile` `email` | delegated |               | Single sign-on     |
| `Files.Read.All`           | delegated | admin consent | Excel spreadsheets |
| `offline_access`           | delegated |               | Excel spreadsheets |

The last column earns its place. `offline_access` reads like noise next to
`Files.Read.All`, and an admin trimming the list to what looks necessary produces a
source that works for exactly one hour and then stops — which is the single most
confusing failure this whole phase has. Saying what it is for is what stops it being
pruned.

`Capability.scopes` is now derived from `permissions` rather than stored beside it,
so the list an admin is told to grant and the list actually requested are the same
list. A test asserts they cannot diverge.

**Every connector says where its credentials come from.** `setup_steps` on the
connector, read through `setup_steps_of()` with a default — the same optional-
capability pattern as `oauth_of` and `endpoint_credential_of`, for the same reason.

The division of labour is the point. **The field hint says what a box means; the
steps say how to get to the screen the value is on.** A four-step route through
somebody else's product, told one sentence at a time next to the field each sentence
ends at, is a route nobody follows.

> **In HubSpot: Settings (the cog, top right) → Integrations → Private apps.**
> Create a private app, or open an existing one. On the Scopes tab, tick the read
> scope for what you are importing — `crm.objects.deals.read` for deals. Create the
> app and copy its access token. It starts with `pat-`.

Thirteen of the fourteen connectors have them. **A property test enforces it**: any
connector asking for a credential must say where to find it. The exemption is
narrow and stated — a webhook hands out an address rather than asking for one — so
a new connector cannot quietly ship without instructions.

This also filled in credential fields that had no hint at all, including the SQL
connector's username and password, where "a read-only account" is the single most
important thing to say.

#### What was actually built

`app/providers.py` is the new piece: the catalogue of providers, their capabilities,
and the three derivations that used to be scattered — the issuer, the permissions to
request, and the callbacks to register.

**The credential moved and `sso_config` shrank.** It now holds `enabled`,
`provider`, `scopes`, `button_label`, `auto_provision`, `require_sso` — the four
decisions that are genuinely about signing in, plus a pointer to the connection that
does it. `oauth_client` gained `tenant_id` and `issuer`.

**A union, not a replacement.** The provider list is the catalogue **plus** whatever
the connectors declare. The first version made the catalogue authoritative, which
silently ended the property that shipping a connector is a self-contained job — a
test using a fake connector caught it immediately. Anything not in the catalogue
gets a definition derived from its own spec.

**Capabilities are derived, never stored.** Sign-on is active because `sso_config`
says so; data is active because a live, non-draft source uses a connector for that
provider. A stored list of ticked boxes would be a third thing that could disagree
with the other two.

##### Three bugs this turned up

**1. `/common/` was wrong, and a test was asserting it.** The Excel connector
hard-coded `login.microsoftonline.com/common/` in its authorize and token URLs.
That serves a _multi-tenant_ app registration and returns an error for a
single-tenant one — which is the kind the setup steps produce and the kind most
companies make. `test_the_endpoints_carry_a_tenant_segment` asserted the wrong thing
confidently. Endpoints now carry `{tenant}`, filled from the connection, falling
back to `common`.

**2. `/api/admin/sso` had no tests at all.** Not thin ones — none. That is how it
came to hold a second copy of a credential `oauth_client` already had, with nothing
noticing for a whole phase. `test_provider_connections.py` is 18 tests and exists
because of this.

**3. A fresh Microsoft connection asked for permissions to features that do not
exist.** The setup panel listed `User.Read.All`, `GroupMember.Read.All` and
`Mail.Send` alongside the ones it needs, because the fallback for "nothing switched
on yet" was _everything available_ rather than everything **built**. Two of those
need tenant-wide admin consent, so the panel was asking an admin to hand over read
access to every user in the company for a feature that does nothing. **Found by
looking at the real page, not by a test** — the seventh time in this phase that live
probing has caught something a green suite did not.

##### The page

Two sections collapsed into one. **Connections** is a card per provider, each
carrying the checklist of what that one credential powers — ticked for what is on,
hollow for what is not, and marked _not built yet_ for what is coming. Opening a
card gives the credential form and, for a provider that can sign people in, the
sign-in settings underneath it: one panel, because it is one connection.

**The setup steps moved to the server.** They were a table in `ProviderSetup.tsx`,
which meant the permissions an admin was told to grant lived in a different file —
and a different vocabulary — from the scopes actually requested. Both now come from
`app/providers.py`, so they cannot disagree.

SMTP stays where it was, as the one thing on the page that genuinely is not an
application registered with a provider.

### 3d. Directory sync — people from the tenant — **planned, not started**

**The problem.** Today every person in GoalGetter is typed in by hand. That is fine
for ten and miserable for two hundred, and it is the same objection that killed CSV
import for metrics: a list maintained by hand is wrong the week after somebody
joins. Meanwhile the Microsoft tenant already knows every employee, their job title,
their department and whether they still work here.

**The shape.** Once a Microsoft tenant is linked on the Integrations page, a new
**Manage → Users → Directory sync** tab lets an admin say how tenant accounts become
GoalGetter people, and rules decide who gets which role.

**Manual stays the default.** Nothing changes for a deployment that never links a
tenant, and linking one does not silently create two hundred accounts. See "nobody
appears without being approved" below.

#### What the reference implementation already proves

There is a working version of exactly this in an earlier staff-directory
project, pointed at business cards instead of leaderboards.
It is worth reading before writing any of this, because it has already been through
contact with a real tenant. What it settled on:

**1. Sync writes to a staging table, not to the real people table.** Graph users
land in their own table keyed by `entra_id`, each with a status — `pending`,
`approved`, `declined`, `archived`, `hidden`. Only an approved row becomes a real
card. **This is the same shape as our quarantine for unmatched metric rows**, and
for the same reason: an automated guess about identity has to be answerable before
it becomes a fact.

**2. Nobody appears without being approved.** New accounts arrive as `pending`. An
admin approves in bulk from a filtered list. For us, that answers the "by default
agents are manually added" requirement without a separate mode to maintain: sync
always proposes, an admin always disposes, and the first bulk-approve is the moment
a company opts in.

**3. Rules are matched by specificity, not by order.** Each rule sets any
combination of department, job title and group, and leaves the rest as "Any". The
match is scored — department 4, title 2, group 1 — and the highest score wins, so
_Sales + Account Executive_ beats _Sales_. This is much better than first-match-wins
because the admin does not have to keep the list in the right order for it to be
correct. It also detects two rules with identical filters on save and warns that the
first wins.

**4. A changed title does not silently change what a person is.** When sync notices
an approved user whose rule now resolves differently, it moves them **back to
pending review** rather than reassigning them. Applied to us: somebody promoted from
Account Executive to Sales Manager should not have their leaderboard role changed
under them without a human seeing it.

**5. Leavers are archived, never deleted.** Disabled in the tenant, or simply not
returned by Graph any more, means archived — the record survives, so history
attached to it survives. That matches how we already treat removed data sources.

**6. Not every tenant account is a person.** The reference filters out shared
mailboxes and room accounts by reading `mailboxSettings.userPurpose`, and skips
accounts with no qualifying licence. Without this, a sync produces leaderboard
entries called "Conference Room B". It uses Graph's `$batch` endpoint, 20 requests
at a time, so this costs a handful of calls rather than one per user.

#### Built so far

**3d-i — the rule engine.** `app/directory/rules.py`, with no database and no HTTP
in it: which rule wins is the most decision-dense part of this and needs no tenant to
exercise, so it lives where it can be tested exhaustively. 31 tests, 29/29 mutants.

Two mutation survivors were worth the run on their own. One was a test that could
not fail — the punctuation example, `Sales — EMEA` versus `Sales EMEA`, stays
different _even with punctuation stripped_, because the dash leaves a double space
behind. The other was a line that did nothing: `conflicts` sorted conditions before
comparing them, but `conditions()` already builds them in a fixed order. Removing the
sort exposed a real gap — nothing tested that _every_ condition is compared, so
Phoenix and Dallas rules for the same department could have been reported as a false
conflict, which is the most ordinary pair of rules a company will ever write.

**3d-ii — the staging tables and the reconcile.** `directory_person` and
`directory_rule`, plus `app/directory/reconcile.py`. 26 tests, 22/22 mutants.

`directory_rule` has **no position column**, deliberately: order does not decide
anything, and a column for it would invite somebody to make it matter later.
`directory_person` is keyed on `(organization, provider, external_id)` — a test
caught the first version leaving the provider out, which would have let two people
from two directories collide on a shared id.

The reconcile is three rules, and every awkward case is one of them applied:

1. **A decision outranks the directory.** Declined stays declined; without that,
   declining somebody lasts until the next sync and they are re-proposed hourly for
   ever, which is how a feature gets switched off.
2. **Nothing changes silently.** New people arrive pending. An approved person whose
   rule now resolves elsewhere goes _back_ to pending with a reason rather than being
   reassigned — a promotion must not move somebody on a leaderboard without a human
   seeing it. And deleting a rule sends nobody back, because a stampede is not a
   signal.
3. **Absence means archived, never deleted.** Anything attached to a person still
   says where it came from. Somebody who returns is proposed again rather than
   silently restored: leaving and rejoining is exactly when a human should look.

All five mutation survivors here were the same shape — cases the fixtures never
reached. A declined person being counted as "waiting" (the badge would show work
that does not exist), a promotion within the same team (team-only comparison missed
it), and an archived row being tidied away on the _third_ pass rather than the first.

**3d-iii — the Microsoft Graph provider.** `app/directory/microsoft.py`, 17 tests.

**Nobody signs in for a directory sync**, which is the thing that shapes the whole
module. The permissions are _application_ ones and the job runs at three in the
morning with no user at a keyboard, so the token comes from the client credentials
grant rather than the authorization-code flow every connector uses. No popup, no
refresh token — a fresh token per run, thrown away after.

**Graph offers a delta query and this deliberately does not use one.** A delta says
what changed; reconcile needs to know what is _absent_. A tenant of two thousand
people is three requests at Graph's largest page size.

**Most of the work is deciding what is not a person.** A tenant is full of accounts
that would otherwise become leaderboard entries called "Conference Room B": shared
mailboxes, rooms and equipment (found by asking what each mailbox is _for_, twenty
at a time through `$batch` — the only reliable signal Graph offers), guests, and
accounts with no address at all. Disabled accounts _are_ people, returned marked, so
reconcile archives them rather than silently dropping them — which is how a leaver
gets noticed at all.

**Microsoft Teams are Microsoft 365 groups**, so group membership costs the same
token and no separate integration, which is what makes it a rule condition rather
than a project. One unreadable group does not cost the sync: its rules match nobody
that round, rather than every person vanishing — which reconcile would read as the
whole company leaving.

**3d-iv — applying an approval.** `app/directory/apply.py`, 18 tests.

New people arrive `invited`, not `active` — through exactly the same door as anybody
an admin types in. An account that already exists is **linked, not overwritten**: the
worst outcome available is two rows for one human, each carrying half their numbers,
so matching is case-insensitive on email. And a person added by hand keeps their
name, role and team, because the directory has no better claim to those than the
admin who typed them.

`differences()` computes where the account and the directory disagree, rather than
storing a flag — a stored one would need clearing when either side changed, and the
clearing is the part that gets forgotten.

##### Three bugs found while building these

**1. httpx wipes a URL's query string when handed an empty params dict.** Graph's
`@odata.nextLink` is a complete URL carrying a `$skiptoken`; passing `params={}`
stripped it, so paging would have re-requested page one until the page cap. Found by
a test written to kill a mutant — the mutant was about merging parameters _in_, and
the test discovered they were being thrown _away_.

**2. A cached `None` relationship.** `apply` reads `row.account` to find an existing
link, which loads it as `None` for a first-time apply and caches that. Setting only
`user_account_id` left the cached `None` in place, so `differences` on the same row
a moment later reported nothing. Setting the relationship as well as the key fixes
it.

**3. A test fixture that silently discarded its own transport.** Three tests grabbed
`httpx.Client` _after_ the fixture had patched it, wrapped it with a custom handler,
and had that handler overwritten on the way through. Two of them passed anyway,
because the fixture's own tenant happened to answer correctly — they were asserting
nothing at all. The fixture now takes a handler, and the real client is captured at
import.

**3d-v — the sync entry point.** `app/directory/sync.py`, 19 tests, 17/17 mutants.
Provider → reconcile → apply, on the hourly job pass.

**Daily, not hourly.** People join and leave on a scale of days, and reading somebody
else's API twenty-four times to notice one joiner is how an integration gets switched
off at the far end. A failed run still counts as an attempt, so a bad credential is
not retried every tick — which is how an authentication endpoint gets an account
locked.

**Before the metric sync in the same pass**, deliberately: a person approved from the
directory becomes an account, and the sync below matches rows to people by email, so
somebody who joined today has an account to match against rather than spending a pass
in quarantine for no reason.

**A failed read reconciles nothing at all.** The most dangerous thing this module
could do is act on a partial list: reconcile archives anybody absent, so half a
directory looks exactly like half the company leaving.

**Applying runs every pass, not only on approval**, and is idempotent — so somebody
approved before the rules were written becomes an account eventually without an admin
pressing anything twice. One person's problem (no email address, usually) is reported
against them rather than stopping everybody else's account, the same way a mapping
error works on the metric side.

##### The one capability that is stored

`oauth_client.directory_sync_enabled`. Everything else on a connection is derived —
signing in because `sso_config` says so, data because a source uses it — and this one
cannot be: **a connection existing says nothing about whether a company wants two
hundred accounts proposed from it.** Connecting Excel must not do that, and no
derivation could tell the difference. Worth stating plainly, because an exception to
a rule that is not written down is how the rule gets forgotten.

##### Two mutation survivors

`_describe` passes a provider's own words through whole rather than prefixing a class
name — and the test asserted `"401" in error`, which passed just as happily when the
message read `DirectoryProblem: Microsoft refused...`. Now an exact match.

And `applied` counts accounts created _this pass_: without the already-applied
filter, a settled company would report its entire staff as newly applied every day
and the number would stop meaning anything.

**3d-vi — the admin endpoints and the screen.** `routers/directory.py` with 28
tests, and a Directory sync tab under Users with its wording in
`pages/directorySync.ts` — 35 tests, 32/32 mutants on the first pass.

**A tab under Users, not a page of its own**, because _"who is in here?"_ is the
question somebody is already asking when they need this, and the answer is one list
away. The tab is hidden entirely for anybody who could not act on it — an agent
seeing a tab that 403s is worse than an agent not knowing it exists.

**Three states, three different next actions.** Nothing connected: point at
Integrations rather than showing a switch that cannot be flipped. Connected but off:
one switch, and what turning it on will do. On: the rules, and the people waiting.
Showing all three at once is how a settings screen becomes something people avoid.

**Selection defaults to everybody in the waiting list.** The first use is a company
of two hundred arriving at once and the overwhelmingly common answer is "yes, all of
them"; approving one row at a time is the chore that makes somebody give up and keep
typing names in by hand. Each row says where the rules _would_ put them, before the
button is pressed — finding out afterwards means undoing it by hand.

**A rule reads back as a sentence**, because a row of four mostly-empty boxes does
not say what it does, and "Any" repeated across three columns is exactly the shape
that gets misread as an _or_. _"Anyone in Sales at Phoenix becomes a manager on
Phoenix Sales."_ A rule with no conditions says _"Everyone else"_ rather than showing
an empty subject — it is the rule most likely to surprise somebody later.

**A shadowed rule is flagged on the row that does nothing**, not on the one that
works: that is the row somebody has to change, and a message at the top of the table
saying "rules 2 and 5" makes them count.

Two refusals in the API are worth naming. **The switch will not turn on without a
connection**, and the message names the page where the fix is. And **a person the
directory has stopped returning cannot be approved** — they are gone, so approving
them would create an account for somebody who no longer works there, and the next
pass would archive it again. A button that lies.

##### Two things the wording module had to get right

A failed run reports **the provider's words and no counts at all**. A failed run has
counts of zero, and "0 people" beside an error reads as _the directory is empty_ —
the most alarming wrong conclusion available on this screen.

And the tab badge shows nothing rather than a zero. A badge reading `0` is a
permanent visual alarm meaning "everything is fine", which teaches somebody to stop
seeing badges.

##### Probed end to end against the dev database

Connect → switch on → sync → approve → sync → accounts → drop somebody from the
tenant → archived. Four people read, one already-disabled arriving archived rather
than proposed, two approved becoming `invited` accounts on the rule's team, and a
leaver archived on the next pass. Dev data restored afterwards: 3,083 facts, 7 users,
1 source, nothing left behind.

#### 3d is feature-complete

Everything is built and tested. What remains is the live pass against a real tenant,
below.

#### When this gets tested against a real tenant — **after Phase 4**

Decided deliberately: live verification waits until the MVP is complete and QA
starts. Everything above is built and read as documented, and **none of it has
touched a real Entra tenant** — only an app registration with granted admin consent
proves the endpoints and permissions are the ones Microsoft still serves. That is
worth doing once, against a surface that has stopped moving, rather than three times
against one that has not.

#### Decisions taken

**1. A rule assigns a role and a team. Office is a consequence, not an assignment.**

This one changed shape on contact with the schema. A person's office is _already_
derived — `user_account.team_id` → `team.office_id` — and there is no
`user_account.office_id`. Assigning an office independently would let a person sit
in the Phoenix team while assigned to the Dallas office, which nothing in the
product could then resolve.

So **office belongs on the left side of a rule, not the right**: it is something to
match _on_, not something to set. The tenant's `officeLocation` becomes a condition,
which is the more useful half anyway —

| Match on                                                 | Assign     |
| -------------------------------------------------------- | ---------- |
| Department, job title, office location, group membership | Role, team |

_Sales + Phoenix → team "Phoenix Sales"_, and the office follows from that team.

**Anything the rules cannot place stays unassigned.** `team_id` is already nullable,
so a person with no matching rule is a real account with no team, surfaced under a
**Needs assignment** filter for an admin to place. That is deliberately the same
answer as an unmatched metric row: propose, never guess.

**2. A human edit wins, and the difference is flagged for as long as it differs.**

Same rule as metric facts, with one addition that matters here. Overwriting an
admin's edit on the next sync is unacceptable, but so is silently diverging from the
tenant for ever — "why does this say Sam Rivera when Entra says Samantha Rivera" is a
question somebody will eventually ask.

So each synced field records what the tenant last said alongside what the app shows.
When they differ, the person's row carries a quiet marker with both values and a
one-click _use the tenant's value_. `audit_log` already has a JSONB `details`
column, so the change itself has a home without new tables.

**3. Provider-shaped from day one, Microsoft first and properly.**

Microsoft 365 is the priority and the only one that will have a real test account, so
it gets built first and built well. But the protocol is written for directories in
general rather than for Graph, so Google Workspace is a second module rather than a
refactor. This is the same bet the REST engine made, and that one paid for itself by
the third provider.

**4. A sibling of the metric pipeline, sharing its plumbing but not its pipeline.**

**The deciding argument: the metric pipeline appends events; a directory reconciles
state.** `sync.py`'s correctness rests on `since_for` and a watermark that only
advances on a clean run — it asks "what changed since Tuesday" and appends what comes
back. A directory sync has to do the opposite: read the _whole_ current membership,
then archive every existing row it did **not** see. There is no watermark that
expresses _this person left the company_, and bolting a full-snapshot mode onto a
pipeline whose entire correctness story is watermarks is exactly the hidden
complexity this project keeps refusing.

Everything else points the same way: the destination is `user_account` rather than
`metric_fact`; the mapping is name/title/department rather than
metric/subject/occurred*at/value; identity resolution is \_inverted*, because the
metric pipeline matches rows to people who already exist and this one creates them.
And `data_source` carries backfill windows, endpoint tokens and mappings that would
all be dead weight, for a thing that is one-per-provider rather than many-per-org.

**What is shared is real, though, and is shared by importing rather than by
abstracting:**

| Reused                            | From                                |
| --------------------------------- | ----------------------------------- |
| OAuth token refresh               | `app.oauth.ensure_fresh`            |
| Secret storage                    | `app.credentials` (same Fernet key) |
| HTTP retries, rate limits, paging | `app.connectors.rest.request_json`  |

No new framework, no generalised base class — three imports. **And no `data_source`
row at all:** the connection is a capability toggle on the Microsoft provider
connection (see 3e), so switching directory sync on is a checkbox rather than
another wizard.

The one genuine cost is a second run-history surface. Better a second small one than
a first one that has to lie about what a watermark means.

#### Microsoft Teams is a capability, not another integration

Worth recording, because it looked like a separate project and is not. Teams and
their membership come from Graph `/groups?$filter=groupTypes/any(c:c eq 'Unified')`
and `/groups/{id}/members` — **the same credential, the same token, the same
client.** Under 3e's capability model that is one more checkbox on the Microsoft
card, not a new connection for an admin to set up.

Which makes group membership available as a rule condition, and that is the strongest
of the four: a department is a string somebody typed into Entra, while membership of
_Phoenix Sales_ is a fact somebody actively maintains.

#### Sketch of the UI

Two screens, both under **Manage → Users**, because that is where somebody already
goes to ask "who is in here?":

- **Directory sync** — the connection status, "Sync now", and the rules table
  (Department / Job title / → Role, each defaulting to "Any"). Absent entirely when
  no tenant is linked, replaced by one line pointing at Integrations.
- **The existing Users list, with a Pending filter** — where approving happens,
  rather than a second list somewhere else. A count badge on the tab is what tells
  an admin there is anything to do.

### 3h. The sweep — done

SMTP was nearly missed because it had no slice number, so the rest of the docs were
swept for the same failure: **anything promised for Phase 3 that no numbered item
owned.** Three findings, one of them a real feature gap.

#### 1. The admin dashboard never mentioned data sources

`10-dashboards.md` promised _"data source sync status and last-error (Phase 3)"_ on
the admin dashboard, and the health payload had no mention of sources at all.
`metrics_without_data` was the closest thing and is **not the same question**: a
metric fed by two sources still has recent data when one of them has been failing
for a week.

That matters because **a broken sync is invisible on a leaderboard** — it looks
exactly like a quiet week. The admin dashboard is the one page where somebody should
not have to go hunting.

Three counts now, and they are separate because the fixes differ:

- **failing** — the last run errored. There is a message to read, and the card shows
  the most recent one, in the provider's own words. "Something went wrong" sends
  somebody hunting; "the credential was refused" tells them where to go.
- **overdue** — due to check and did not. Usually the background job is not running
  at all, which no per-source error would ever say. One interval of grace, because a
  number that flickers on every tick is a number an admin learns to ignore.
- Neither counts a **draft** nor a **removed** source, the same rule the sources list
  follows: an abandoned click is not an alarm.

#### 2. Two documents still described CSV import as shipped

`06-metrics-engine.md` said facts are written by "manual entry, CSV/Excel import, or
(Phase 3) connectors", and listed CSV import in its table of write paths as a Phase 1
feature. It was dropped during Phase 3 and replaced by a **live** spreadsheet
connector — which is the meaningful difference: a connector re-reads the sheet, where
an upload snapshots it and is wrong by lunchtime.

`metric_fact.SOURCE_TYPES` still contains `import`, and that is deliberate rather
than missed: a Phase 1 deployment may hold real imported rows, and dropping the value
from the check constraint would make them unwritable. The **demo seeder** is now its
only active writer, which is a mildly dishonest label for demo data — renaming it to
`seed` is a small migration nobody has needed. Both places now say so.

#### 3. Five open questions had all been answered

`15-data-integrations.md` still presented its five open questions as open. All five
were decided during the phase, and **two went against the leaning written down** —
which is why they are kept with their answers rather than deleted:

- the webhook stayed in Phase 3 rather than moving to Phase 2, and building it first
  exposed that **a self-hosted deployment usually cannot receive a webhook at all**,
  which reordered SQL ahead of Google Sheets;
- there is no acceptable alternative to per-deployment app registration — but the
  question was the wrong shape, and what removed the friction was making **one
  registration serve every feature** rather than avoiding registration.

### 3g. Email (SMTP) — done

**This was nearly missed, and the miss is worth recording.** Phase 3 was declared
complete while the Integrations page still carried a card reading _"Coming soon"_.
The roadmap had said, back in Phase 2's _what this is not_: **"Email is invitations
and password resets, and it arrives with SMTP in Phase 3."** It was never given a
slice number, so it fell through a list that ran 3a to 3f and looked finished.

A scheduled item with no slice number is an item nobody counts.

#### The rule the whole thing is built on

**Email is an enhancement, never a dependency.** Every flow that sends a message
already produced a link an admin could hand over, and it still does — with a mail
server configured, and when that server is down, misconfigured, or refusing the
from-address. Nobody should be unable to join because a relay had a bad afternoon.

So `mail.send` **reports rather than raises**, and the invite response carries both
the link and what happened to the email. An invitation is created, committed, and
_then_ mailed — a message can never describe a link that failed to save.

`Sent.attempted` distinguishes "no mail server configured" from "it did not work",
because those need different words and lead to different pages. A deployment that
has deliberately never set up mail is not told off on every invitation.

#### Decisions worth stating

**A username and password are not required.** An internal relay that accepts
anything from inside the network is a normal, correct setup, and demanding
credentials it does not want would make the configuration most likely to work
impossible to save. Login only happens when there is something to log in with.

**Three connection types, `none` among them, named plainly** rather than hidden.
Somebody choosing an unencrypted relay should have to choose it — but it has to
actually work, because that is what an internal relay is.

**The from-address is checked at save time**, not once per invited person. A blank
sender produces a message every server rejects, and discovering that one invitation
at a time is the worst way to find out.

**The test button sends to the admin pressing it**, not to an address they type. The
question is _"does mail from here arrive"_, and their own inbox is the one they can
go and check.

#### Two things the tests caught

`looks_like_an_address` accepted `@acme.com` — an `@` with nothing before it. Caught
by a parameterised case written for the opposite reason.

And the non-ASCII header test asserted `message["From"]`, which `EmailMessage`
**decodes on read** — so it returns `Ünité <…>` however the header is stored, and
the assertion would have passed whether or not the encoding ever happened. Rewritten
against the serialised bytes, and against the _property_ — headers are ASCII, no raw
UTF-8 survives — rather than a particular encoding, since which of base64 or
quoted-printable the library picks is its business.

#### What this leaves

Two things that were already deferred and stay deferred, now against a working mail
server rather than an imagined one:

- **Self-service password reset.** There is deliberately no _forgot password_
  endpoint, because with nowhere to send a link it could only return one in the HTTP
  response — an account-takeover endpoint rather than a smaller feature. With SMTP
  it becomes a matter of mailing the link instead of returning it. Phase 4.
- **Email as a notification channel.** Still not wanted: recognition reaches people
  through the app they have open and the screen on the wall. If it ever becomes one,
  a dispatch layer earns its place then — and now it would be built against a working
  connection instead of an imagined one, which was the whole argument for waiting.

Microsoft's `Mail.Send` capability stays listed and unbuilt on the Microsoft
connection. For a Microsoft 365 shop it would remove this setup entirely; SMTP
remains the universal fallback either way.

### 3c. Setup instructions for users — done

- [x] An integrations help page: one section per connector, numbered steps for
      registering the provider app and linking an account
- [x] One button on the Integrations page — _"Need help?"_ — rather than help text
      scattered through the wizard

**Nothing on the page is typed by hand, and that is the whole design.** The steps
come from each connector's `setup_steps`, the fields and their explanations from the
same JSON schema the wizard's form is built from, and the permissions from
`app/providers.py`. A hand-written manual describing a wizard is a manual that is
wrong within a month — and wrong documentation is worse than none, because somebody
trusts it.

**Being last paid for itself.** Written when it was first planned, this page would
have described a flow that then changed four times: five wizard steps became three,
two credential forms became one connection, `Anything else` became `Custom
connections`, and Salesforce stopped taking a pasted token. Every one of those would
have left a paragraph quietly lying.

**No screenshots, and that is a decision rather than an omission.** They need real
accounts on fourteen products, they go stale the moment a vendor reskins a settings
page, and the part that actually gets somebody unstuck is the numbered route through
someone else's menus — which is on the page, generated, and cannot drift.

Four sections: what a source and a mapping _are_ (the three ideas that make the
wizard feel arbitrary if nobody says them), registering an application once per
deployment, one entry per connector, and the five failures this project has actually
hit — a mismatched redirect URI, a permission added but not consented to, a missing
offline-access scope, a query with no `:since`, and a sync reporting itself
incomplete.

**Last on purpose, and asked for explicitly.** Screenshots of a wizard that is
still moving are screenshots that have to be retaken. The value of this page is
that it matches what a user actually sees, so it gets written once the flow has
stopped changing.

The connect step is the one place a low-skill-curve promise can break: OAuth app
registration is the hardest thing we ask an admin to do, and it happens once per
deployment. Nothing else in the product needs a manual.

#### 3a-viii — only show what is running — done

- [x] `data_source.activated_at` + migration, backfilled for existing rows
- [x] Cancel in the connect flow deletes the draft outright
- [x] `sweep_drafts` in the scheduled pass, 24-hour TTL
- [x] The list leaves out drafts _and_ removed sources by default
- [x] Connector cards on the Integrations page, replacing the single Connect button

**The list answers one question: what is feeding my leaderboards.** Two things were
appearing on it that are not an answer to that — a connect flow somebody abandoned,
and a source they had deliberately removed. Both are now left out by the API rather
than filtered by the page, so the two cannot disagree about what counts as active.

**Cancelled means cancelled.** The source has to exist from step three onwards
because a webhook's endpoint is generated server-side, so backing out used to leave
a row behind reporting itself as _setup unfinished_. Cancel deletes it; anything
abandoned another way is swept within a day. Safe because a draft has imported
nothing — its mapping, if it has one, was saved switched off.

**The backfill was wrong the first time, and real data said so within minutes.**
The migration originally stamped every existing row with `now()`, reasoning that
anything already in the table predated drafts and so could not be one. Exactly
backwards: a source abandoned last week _is_ a draft, and marking it finished pinned
it to the list forever reporting _setup unfinished_ with no way to tidy it away —
which is the bug this slice existed to fix. The backfill now asks the data: a source
counts as finished if it has an enabled mapping or has written facts, and everything
else was a draft when the migration ran.

**Sixth time real data has found something the tests could not**, and this one is
worth naming for a reason the others were not: a test here would have passed with
the wrong rule, because I would have written it to match what I believed. A
migration backfill is a judgement about data that already exists, and the only thing
that can contradict it is the data.

**`activated_at` is a column rather than an inference, and the inference is the
reason.** "No credentials and no enabled mapping" describes a draft — and describes
a _restored_ source, and a _paused_ one, equally well. Three states that look
identical from outside and must be treated completely differently: one swept, two
kept. A guess would have deleted somebody's paused source, so the fact is recorded
instead. Both directions are tested, and the sweep test that matters is the one
asserting a source paused two hundred days ago is still there.

**A removed source keeps its provenance and loses its visibility.** Its facts still
point at it, so a number on a leaderboard can still say where it came from, and its
own page still loads by URL — but it is finished business and not in the way.

**Connector cards instead of one button.** A button hides the answer to "does it
work with our CRM?" behind a click, and that is the other question people arrive
with. Clicking a card skips the first wizard step, since the question it asks has
already been answered. This wants a search box once the list passes a dozen; at two
it would be chrome around nothing.

### 3b. Connectors, in order

- [x] Webhook / generic API — done in 3a-iii, as the honest test of the abstraction
- [x] **Generic SQL (SQLAlchemy)** — 3b-i, below
- [x] Google Sheets — proves the OAuth abstraction end to end - [x] **3b-ii-a: the OAuth framework**, below. Proven with a fake provider - [x] 3b-ii-b: the registration form (3b-ix), the sign-in button in the
      wizard (3b-vi) and the Sheets connector itself (3b-viii)
- [x] Snowflake — a dialect on the SQL engine, 3b-iii. Ships as an optional extra
      rather than in the image, because its driver is large and most deployments
      will never install it
- [x] Salesforce — 3b-xii
- [x] HubSpot — 3b-xii

**Fourteen connectors ship**, in five real categories plus the escape hatches:

| Group                   | Connectors                                                                                               |
| ----------------------- | -------------------------------------------------------------------------------------------------------- |
| Spreadsheets            | Google Sheets, Excel                                                                                     |
| CRM                     | HubSpot, Salesforce, Pipedrive, Close                                                                    |
| Helpdesk                | Freshdesk, Zendesk                                                                                       |
| Calls and conversations | Gong, Aircall                                                                                            |
| Databases               | SQL database (PostgreSQL, MySQL, MariaDB, Snowflake; Redshift and SQL Server as build extras), Snowflake |
| Custom connections      | Webhook, Any JSON API                                                                                    |

The last row is two general-purpose tools, not a leftovers bin — every named
product is filed under what it actually is.

### 3b's real shape: four engines, not thirty-five connectors

The target is parity with the connector list a commercial competitor offers —
roughly thirty-five names. Building thirty-five connectors is not the way to get
there, because they are not thirty-five different problems. Sorted by what they
actually _are_:

| Bucket      | What it really is                                        | Names                                                                                                                                                                                                                                    | Cost each                                                                                          |
| ----------- | -------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| **SQL**     | A query against a database                               | PostgreSQL, MySQL, MSSQL, Redshift, Snowflake                                                                                                                                                                                            | A line in the dialect table plus a driver. **Engine done in 3b-i.**                                |
| **REST**    | Call a URL, page through JSON, filter by "changed since" | HubSpot, Salesforce, Zendesk, Freshdesk, Pipedrive, Zoho, Dynamics, Gong, Outreach, Close, Bullhorn, Aircall, Kixie, JobAdder, Agentbox, CloudCall, Nooks, HighLevel, Follow Up Boss, GetAccept, LockedOn, MRI, Rex — around twenty-five | Engine once, then a **declarative spec** per provider                                              |
| **Files**   | Rows under a header row                                  | Google Sheets, Excel/M365, FTP                                                                                                                                                                                                           | One engine, then each is small                                                                     |
| **Inbound** | Something posts to us                                    | API, Webhook, Zapier                                                                                                                                                                                                                     | **Done in 3a-iii.** Zapier and most "generic API" integrations are a webhook with a different logo |

Four of the names on that list are not data sources at all. **Slack** and
**Microsoft Teams** are places to _send_ things — they belong with notification
delivery in Phase 4. **PowerBI** and **Tableau** are reporting tools sitting on the
same warehouses the SQL engine already reads, so they are a worse route to the same
numbers.

**The declarative REST connector is the load-bearing idea.** One engine; each
provider described by a small spec — base URL, how it authenticates, how it pages,
which field means "modified at", where in the response the rows are. This is how
Airbyte and Fivetran ship hundreds of sources without hundreds of codebases, and it
is the only approach that makes this list finishable.

**Two things not to pretend about.** Each REST provider still needs somebody to
read its documentation, find the right endpoint, and understand its pagination and
its date filter — the engine turns that from days into hours, not into nothing. And
**most of them cannot be verified without an account on the far side.** Unit tests
prove the spec is read correctly; only a trial login proves the endpoint is the
right one. Live verification against real data has caught five real bugs in this
phase, so for any connector that matters, a trial account is worth more than
another day of test-writing.

#### Revised 3b order

1. [x] **More SQL dialects** — 3b-iii below. MySQL and MariaDB ship; Snowflake,
       Redshift and SQL Server are optional extras
2. [x] **The REST engine + Freshdesk** — 3b-iv below
3. [x] **Generic "API" connector** — 3b-v below
4. [x] **Google Sheets and Excel** — 3b-viii and 3b-x below
5. [x] **The CRMs by demand** — HubSpot, Salesforce, Pipedrive — a spec each.
       3b-xii below
6. [x] **Search and categories in the connector picker** — 3b-xiii below, landed
       with the CRMs at the point nine options made a flat grid a wall
7. [x] **Snowflake as a connector of its own** — 3b-xiv below
8. [x] **Four more providers on the REST engine** — Zendesk, Gong, Aircall and
       Close — 3b-xv below
9. [x] **Real brand marks** — 3b-xvi below

**Reordered: SQL before Google Sheets.** The original order put Sheets first to
prove OAuth. SQL goes first instead for two reasons that only became clear once
the webhook connector existed. **A self-hosted deployment usually cannot receive a
webhook at all** — a SaaS provider on the public internet cannot reach an internal
server, so for a lot of companies an outbound database connection is the only
integration that is possible without opening a port. And SQL needs no OAuth, so it
isolates "does the pull half of the framework work" exactly the way webhook
isolated "does the abstraction work". OAuth then gets its own slice rather than
being debugged at the same time as pagination and streaming.

**Build one connector completely before starting the next.** Each has its own auth quirks, rate limits, and pagination behavior; batching them produces several 80%-done integrations, which is worse than one that works.

#### 3b-i — the SQL connector — done

- [x] `app/connectors/sql.py` — dialect table, query validation, streaming reads
- [x] `/api/connectors` carries each connector's JSON Schema; the wizard builds the
      form from it
- [x] `connectorForm.ts` + `SchemaForm.tsx` — a form the connector describes
- [x] 38 connector tests against a real database, 30 mutations, all killed
- [x] 37 form tests, 31 mutations, all killed
- [x] Walked live: bad query refused, good query tested, columns discovered, all
      four mapping roles guessed correctly, preview, sync, idempotent re-sync, and
      a late edit re-imported

**The admin writes the query.** Not a table name and a column picker. Somebody who
can reach the database already knows what a closed deal looks like in it, and any
abstraction over that is a worse SQL that still has to be learned. What the
connector insists on is the one thing that is easy to get wrong and silent when you
do.

**The query must use `:since`, and the refusal says why in the words that matter:**
_use the column that says when a row was last modified, not when the event
happened._ That is the trap from 3a stated where it will actually be read — a query
filtered on `closed_on` never returns a deal edited a week later, so the edit is
never imported. Verified live: a deal amended today, closed three days ago, came
back and updated its fact while keeping its original date.

**Three guards, and only one of them is the regex.** `_check_query` refuses
anything that is not a `SELECT`/`WITH` and scans for write keywords — but a regex
can be talked around, so the connection also runs in a `READ ONLY` transaction with
a statement timeout, and there is a row cap. The read-only transaction is asserted
against a real server, because "we sent the statement" and "the server honoured it"
are different claims: `CREATE TABLE` on that connection is refused by Postgres.

**Comments are stripped before both checks, in both directions.** `-- delete this
later` is a note, not a write; and `-- WHERE updated_at >= :since` does not count as
using the window, which is the dangerous half — a commented-out filter reads as
present and every sync then re-scans the table.

**Results stream.** `stream_results` gives a server-side cursor, so a million-row
result never exists in the API process at once. That claim is tested twice, because
being a generator is not enough on its own — a generator that reads everything
before its first `yield` streams nothing. One test asserts the connector _asks_ for
streaming; another asserts against a real server that asking produces a
`ServerCursor` and not asking produces an ordinary `Cursor`.

**The dialect table is checked by import, not by belief.** Five databases are known
and only the ones whose driver is installed are offered — this build reaches
PostgreSQL, and the others report _needs `pymysql` installed in the API image_
rather than failing on connect. Adding one is a line in the table plus a
dependency.

**The form is generated from the connector's own schema.** Every label, hint,
placeholder and choice in the setup step comes from `SqlConfig` through its JSON
Schema, so a connector arrives with its own form — which is what the protocol meant
by generated rather than hand-built, and it is the difference between the seventh
connector costing a day and costing a week. It also puts the sentence explaining
`sslmode` next to the person who knows what it is for.

**Two bugs in my own work, found the usual two ways.** `poolclass=None` reads like
"no pool" and means "the default" — a `QueuePool` holding idle connections open
against somebody else's database between syncs, directly contradicting the comment
above it. Found by asserting the class rather than re-reading the line. And a
discovery test could not tell "type a column from a later row" from "read one row
and stop", because the fixture's only nullable column was text — where both
behaviours give the same answer. It needed a nullable _numeric_ column before the
test could discriminate.

**One thing worth knowing about SQLAlchemy:** `Connection.execution_options()`
mutates the connection rather than returning a copy, so checking streamed and
unstreamed behaviour on one connection reports streaming twice and proves
nothing.

---

#### 3b-xvi — the actual logos — done

Every connector card wore either a hand-drawn approximation or a coloured letter
tile. The reasoning behind the letter tiles was sound — a near-miss of somebody
else's trademark looks like a knock-off, on the one page where looking legitimate
matters — but it was answering the wrong question. The right one is: **where do the
real paths come from?**

**Simple Icons** (simpleicons.org), which is CC0 and takes each mark from the
brand's own press kit. Seven of the fourteen are in it: Snowflake, Salesforce,
HubSpot, Zendesk, Google Sheets, Excel and Aircall. Those are now the real shapes.

**Copied, not depended on.** `npm i simple-icons` for seven icons pulls three
thousand, and the constraint at the top of `logos.tsx` still holds: a self-hosted
deployment may be air-gapped, so nothing may be fetched at runtime.

**Four keep letter tiles** — Pipedrive, Freshdesk, Gong and Close — because those
companies asked to be removed from Simple Icons. Drawing them from memory anyway
would be worse than the tile, and the tile is at least honest about being a
stand-in.

**Products now differ from their identity providers.** Google Sheets shows the green
sheet rather than Google's G, and Excel the green X rather than Microsoft's four
squares — but "Sign in with Microsoft" still shows the squares, because that is not
Excel and putting Excel's mark on it would answer a different question.

**The card subtext went with it.** Every card carried a line of explanation, and on
almost every card that line read "GoalGetter fetches on a schedule". A caption that
does not vary is not information — it is noise that doubles the height of the grid
and slows every scan. The fetch-or-receive distinction still matters, and it still
appears on the _connect_ step, where it changes what somebody does next.
`summarise()` had exactly one caller and was deleted with it rather than left
behind as dead code.

#### 3b-xv — four more providers on the REST engine — done

Zendesk (`support.py`), Gong and Aircall (`calls.py`), Close (added to `crm.py`).
Roughly forty lines of spec each, which is the engine doing its job.

**Between them they found a real gap in it.** Three of the four sign requests with
Basic auth where _both halves are secrets_ — Gong an access key and a secret,
Aircall an id and a token, Zendesk an email and an API token. The engine supported
only a key-as-username with a constant placeholder for the password, because
Freshdesk — the only provider on it until now — ignores that half.

So `AuthStyle` gained `basic_password_field`: the _name_ of a credential to use as
the password rather than a value, so a spec stays declarative and no secret sits in
a module-level constant. `_auth_basic` still falls back to the constant when there
is no stored password, because a provider that ignores that half must nonetheless
receive the placeholder — some reject an empty string outright. Close is the case
proving the fallback has to be overridable rather than removed: it documents a
genuinely blank password.

**Zendesk needed one thing no spec could express.** Its username is the agent's
email with `/token` appended. Asking somebody to type that is a form field nobody
fills in correctly first time, and the failure is an unexplained 401 — so the
connector composes it, and refuses with a sentence when the email is missing.

##### What the mutation testing found: an unknown `since_format` was silently ISO

`format_since` handled `epoch` and `date` and returned ISO for anything else. That
is a fallback for a value that should never be wrong — and it was wrong immediately:
Zendesk's spec was first written with `since_format="unix"`, which is not a name the
function knows, so it would have sent an ISO string to a parameter that reads Unix
seconds. The provider then answers with either everything or nothing, and never says
which.

A spec is code we write, not user input, so an unrecognised style now raises. The
lenient branch existed to be safe and did the opposite.

**Also worth naming: getting a `since_param` wrong is survivable, and not by
accident.** Almost every API ignores a query parameter it does not recognise, so a
misspelled filter degrades into a full read every sync — expensive, but correct, and
`external_id` makes the extra rows harmless. The two mistakes that are _not_
survivable are a wrong `rows_at`, which silently reads nothing, and a wrong external
id, which duplicates everything. The tests weight accordingly.

#### 3b-xiv — Snowflake as a connector of its own — done

Snowflake was already a dialect in the SQL connector's dropdown. It is now its own
entry in the picker as well, which took two changes:

**It ships in the default image.** It was an optional build extra, and a connector
whose every attempt ends in "no driver installed" is worse than one that is absent.
About 22 MB of wheels, most of it botocore pulled in for staged-file loading we
never use — the honest price of the entry being real. Redshift and SQL Server stay
extras.

**A preset, not a second connector.** `SnowflakeConnector` subclasses `SqlConnector`
and translates its config: account into host, `database/schema` into the one field
the dialect spells that way, warehouse and role into driver options. Read-only
transactions, the statement timeout, the row cap, the server-side cursor and the
`:since` refusal are all inherited — a second copy of them would be a second thing to
fix. What it buys is that an admin is asked for a warehouse and a role rather than
for a host, a port, and two `name=value` lines in an advanced box.

##### The bug this uncovered: Snowflake could never have appeared

`available_dialects()` probes each driver by importing it, and derived the import
name from the pip package name by swapping dashes for underscores. That is right for
`sqlalchemy-redshift`. It is wrong for `snowflake-sqlalchemy`, which imports as
`snowflake.sqlalchemy`.

So a build running `--build-arg API_EXTRAS="[snowflake]"` — the documented way to get
Snowflake, in a comment in `pyproject.toml` — installed the driver and the dialect
still never appeared. Silently, with nothing anywhere to read.

The dialect table now records three separate things, because they _are_ three
separate things: the URL prefix, the package to install, and the module to import.
And the test that was missing is there, phrased as a property rather than a list of
names: **whichever drivers this image happens to have, every one of them must be
reachable.** It fails on the old code and passes on the new, which is the point.

#### 3b-xiii — search and categories in the connector picker — done

Nine connectors is the point at which a flat grid stops being a list and starts
being a wall. A search box and four headings, in the two places the question is
asked: the wizard's first step, and the "add another" grid on the integrations
page.

**One component, because the two grids differed only in whether a card was a link
or a button.** That is not enough difference to justify two copies of a search box
to keep in sync — `components/ConnectorPicker.tsx` takes either `to` (renders
links, for a page somebody might middle-click) or `onChoose` (renders buttons, for
a wizard step that acts in place).

**All the deciding lives in `pages/connectorPicker.ts`, which has no React in it.**
Four decisions, each testable on its own:

- **`groupOf`** — Spreadsheets, CRM, Helpdesk, Calls and conversations, Databases,
  Custom connections, in that order. Ordered by how likely somebody is to want one,
  not alphabetically — and the last group's name says what it _is_, the pair of
  general-purpose tools you build your own integration with, rather than what it is
  not. It was called "Anything else" first, which read as a leftovers bin and
  invited dropping an unclassified product into it. An unlisted connector falls into it rather than vanishing:
  the wrong group is a much smaller failure than not appearing. Every connector this
  build ships is placed on purpose, so that last group holds exactly the two
  general-purpose tools and nothing else.
- **`matches`** — substring, case-folded, trimmed, and searching **more than the
  display name**. People search for the thing they have, not the name we gave it:
  _postgres_ has to find the SQL connector, _xlsx_ has to find Excel, _zapier_ has
  to find the webhook. That is an `ALSO_KNOWN_AS` table, and it is the difference
  between a search box that works and one that punishes you for not knowing our
  vocabulary.
- **`needsStructure`** — under six connectors, a search box and four headings are
  chrome around a list that was already one glance.

**A search that matches nothing is where the escape hatch gets named.** Somebody
typing the name of a system we have no connector for is exactly the person who
needs to know that a webhook works with anything that can send an HTTP request. So
the empty state says that, rather than apologising.

##### What the mutation testing changed

21 mutants, and the first run killed 14. All four survivors were the same failure
and it is worth naming because it has now happened five times in this phase:
**the fixture could not tell right from wrong.**

- _"the haystack is case-sensitive"_ and _"the display name is not searched"_ both
  survived because every connector's key is a lowercase echo of its own name —
  `hubspot`/HubSpot. The key rescued every query, so neither line was under test.
- _"the provider name is not searched"_ survived because _google_ and _microsoft_
  are also in `ALSO_KNOWN_AS`.
- _"a group is not sorted"_ survived because the fixture list was **written in
  alphabetical order**. The test asserted a sorted result against input that was
  already sorted.

Fixed by making the fixtures discriminate: the connector list is now deliberately
shuffled, with a comment saying why, and three tests use a synthetic connector
whose key spells nothing, so each of the three searched fields can be removed and
noticed. 21/21.

#### 3b-xii — three CRMs on one engine — done

HubSpot, Salesforce and Pipedrive, in `api/app/connectors/crm.py` — one file,
because there is almost nothing in each. That is the REST engine paying off: a
provider is a `RestSpec` and two small Pydantic models.

**Their incremental stories differ, and that is the whole content of the work:**

- **Pipedrive** has `updated_since` on its v2 endpoints. Clean. v2 rather than v1
  precisely for this — v1 has no modified filter on its list endpoints.
- **Salesforce** takes an entire SOQL query in one parameter, so the window has to
  go _inside_ it as a `WHERE` clause. That is what `since_template` on the spec was
  added for. The connector composes the clause itself on `LastModifiedDate` rather
  than letting an admin write one, because a query filtered on `CloseDate` looks
  right and silently never returns an opportunity edited after it closed — the same
  trap the SQL connector refuses a query for.
- **HubSpot cannot filter at all.** Its list endpoints have no modified parameter;
  filtering needs a POST to a search endpoint, which this engine does not do. So
  HubSpot **reads everything every sync**. Deliberate: a full read is expensive,
  while a wrong filter silently misses edited records, and `external_id` makes the
  re-reading harmless. Expensive and right beats cheap and wrong.

**HubSpot also returns almost nothing by default** — a deal comes back with an id
and a couple of system fields unless the request names the properties it wants. A
source configured without them discovers three columns and none of them are the
amount, which is a confusing enough failure to be worth handling in the connector
rather than in a hint.

32 tests against a fake HTTP server (`httpx.MockTransport`), 22/22 mutants. **None
of it is verification against a live account**, and the module docstring says so:
endpoint names, page sizes and filter parameters change without anybody telling us,
and no unit test can notice. Each connector's Test button reports the provider's own
words, which is where a mismatch will show up.

#### 3b-xi — five steps to three — done

- [x] `STEPS` is `Choose · Connect · Map`; `resumeStep` returns 2 or 3
- [x] Choosing a connector creates the source, so a card is one click to a connect
      screen rather than one click to another question
- [x] Name, interval and backfill behind a _Name and schedule_ disclosure
- [x] An `advanced` flag on config fields, rendered behind a disclosure by
      `SchemaForm`, applied across every connector
- [x] 241 frontend tests, all suites green, flow walked live

**Two of the five steps were asking questions that did not need answering yet.**

The name-and-schedule screen came _before_ anybody knew whether the connection
worked, and every answer on it had a sensible default and was already editable on the
source's own page. It is now a disclosure on the connect step, saved on the way out —
one PATCH at a natural moment rather than a second Save button to forget.

The closing summary restated what the step before it had already shown. The mapping
editor displays ten real rows as the facts they would become; that _is_ the
confirmation, and a screen putting it into prose was a click charged for nothing.
"Turn it on and sync now" moved under the preview.

**The `advanced` flag is the bigger win, and it is one mechanism applied everywhere.**
A connector marks a field `advanced` in its own schema and the form tucks it behind a
disclosure — nothing hidden, just not in the way:

| Connector        | Visible | Advanced |
| ---------------- | ------- | -------- |
| Webhook          | 1       | 0        |
| Google Sheets    | 2       | 1        |
| Excel            | 2       | 1        |
| Freshdesk        | 2       | 0        |
| SQL database     | 4       | 2        |
| **Any JSON API** | **5**   | **11**   |

That last row is the point. Pointing at an arbitrary API genuinely needs fourteen
answers and there is no honest way to guess them — but showing all fourteen made the
three that matter impossible to find, while hiding the other eleven would have made
the connector useless for the case it exists to serve. Behind a disclosure it is
neither.

**Advanced is not optional.** A required field that happens to be tucked away is
still required and the form still says so — there is a test for that, because the
tempting shortcut is to conflate the two.

**What the flow is now**, walked live end to end: click a card, copy the endpoint and
send one event, confirm the auto-suggested mapping, turn it on. Three screens, and the
name, interval and history were all set to sensible values nobody had to type.

#### 3b-x — Excel on Microsoft 365 — done

- [x] `app/connectors/grid.py` — the spreadsheet transform, extracted and shared
- [x] `app/connectors/excel.py` — a spec, two models and one request
- [x] 26 Excel tests, 25 grid tests, 36 mutations across both, all killed

**Excel is Google Sheets wearing a different badge**, and the file is short because
that was designed for rather than discovered. Both read a rectangle of cells whose
first useful row names the columns, so `rows_from`, `fields_of` and `kind_of` moved
into `grid.py` and are now tested once instead of twice badly. Two things differ and
only two: which identity provider signs you in, and which URL returns the cells.

**Two ways Microsoft's OAuth differs from Google's, and both bite silently.**
`offline_access` has to be _in the scopes_ — Microsoft has no equivalent of Google's
`access_type=offline`, so leaving it out produces a source that works for an hour and
then stops. And `Files.Read` only reaches files the signed-in account owns, which is
exactly not a shared team workbook; `Files.Read.All` is the one that works. Both are
tests, because both are invisible until the day they matter.

**A sharing link, not a file id.** Graph identifies a file by an internal id and what
an admin has is a link from the Share button — so the link is resolved first, in its
own request. Asking them to find the id instead would be asking them to use Graph
Explorer to import a spreadsheet. The encoding is Microsoft's documented base64url
form, and it has its own test because a wrong one produces a 400 about a malformed id
that says nothing about the link somebody pasted.

**The workbook is addressed through the drive it lives in**, not `/me/drive` — which
would only find a file the signed-in account owns, and a team's workbook is usually
in somebody else's OneDrive or a SharePoint site.

**Only the used range is read.** A workbook's grid is a million rows of nothing;
asking for the used range is the difference between reading a table and reading a
spreadsheet.

**One mutation survivor was a fixture that could not discriminate**, again. The
share-token test asserted the base64 padding was stripped — using a URL whose length
happens to be divisible by three, so base64 adds no padding and stripping it is a
no-op. It passed with the stripping removed. Now parametrised over two lengths that
force one and two padding characters.

**Microsoft shares its registration with anything else Microsoft.** Keyed by
provider, not by connector, so a future Teams or Dynamics connector needs no second
app registration — and Settings already lists Microsoft alongside Google without
either being mentioned by name in that page's code.

#### 3b-ix — the app registration form — done

- [x] `ProviderSetup.tsx` — one component, used inline in the connect flow and on
      the Integrations page
- [x] A _Provider sign-ins_ section listing what is registered and what is not
- [x] Numbered console steps, a deep link, and the redirect URI as a copy field
- [x] Walked live: registered, checked the secret never comes back, and confirmed
      the sign-in button now produces a genuine Google consent URL

**Inline the first time, on the page afterwards.** The connect flow shows the
registration step in place when it is needed, rather than sending somebody to
another page and expecting them to find their way back. Once saved it never appears
there again, because it is a once-per-deployment job and not part of connecting a
source. The Integrations page keeps a copy for rotating a leaked secret or fixing a
mistyped client id — the same component, because two forms would be two things to
keep in step.

**The redirect URI is a copy field, not a sentence.** A mismatch is the single most
common setup failure and the error a provider returns for it does not say what it
expected, so the exact string is presented with a button rather than described.

**The steps are per provider and name what the console calls things.** Google's
include _choose Internal if this is a Workspace account_, which is the one line that
decides whether somebody meets Google's review process at all — the difference
between five minutes and a fortnight.

**The section is absent when nothing needs it.** No connector in the build signing
in to anything means no section, rather than an empty form inviting pointless work.

**Removing a registration leaves connected sources alone**, and the confirmation
says so: their access keeps working until it expires and then fails with a message
naming this as missing. Nothing they imported is affected.

#### 3b-viii — Google Sheets — done

- [x] `app/connectors/sheets.py` — both auth modes, the header-row transform, the
      row-identity choice
- [x] `request_json` extracted from the REST engine so its retry and rate-limit
      handling is reusable by a connector that is not a `RestSpec`
- [x] The **Sign in with Google** button and its popup in the wizard
- [x] 44 tests, 36 mutations, all killed

**One button, and a disclosure.** The service account is the only route for a
non-Workspace account, so the capability stays — but it sits behind _"Not on Google
Workspace? Use a service account instead"_ rather than as a second full section. Two
sections asking for the same thing two ways is the reader working out which one
applies to them, every single time.

**Neither is a mode anybody has to choose.** Whichever credential
is present is the one used: a stored key means service account, a stored token means
a signed-in account. A separate "which mode" setting would be one more question and
one more way for the answer and the credential to disagree.

_Sign in with Google_ is the two-click path and right for a Workspace company. A
**service account** is right for a plain Gmail account, where the OAuth route runs
into Google's review process — and better in general for a connection that should
belong to the organisation rather than to whoever clicked, because an OAuth source
dies when that person's account is suspended. Its setup is genuinely simpler too:
paste the key, then **share the spreadsheet with the address inside it**, which is
the ordinary Share button.

**The service-account token is minted per use rather than cached.** It lasts an hour
and a sync runs at most every few minutes, so caching would save one request in
twelve at the cost of somewhere to keep it and a staleness bug to find later.

**This is the one connector that reshapes what it reads.** A spreadsheet's header row
_is_ its field names; every other source hands over named fields already. Without
the transform the mapping would be choosing between `column 3` and `column 4`. Three
details in it each exist because of a real spreadsheet: **short rows are padded**
(Google omits trailing empty cells, so dropping short rows would lose every record
with an empty note), **wholly empty rows are skipped** (the blank space under every
table), and **unnamed columns are dropped** (a spare column beside the table would
otherwise arrive as a field called `""`).

**A spreadsheet has no idea when a cell changed**, so `since` is ignored and every
sync reads the whole tab. Sheets are small enough that this is cheap; what it costs
is correctness, so **the sheet needs a column holding something unique per row** and
`sync` refuses a row without one.

**A first version made that a setting**, offering "its position in the sheet" as the
alternative — and that was over-design of the worst kind: a choice between correct
and silently wrong, invented to work around a rule added an hour earlier. Position
looks like an id and is not one. Insert a row and every row below shifts up a
number, each claiming its neighbour's identity and overwriting that neighbour's
figure; the numbers stay plausible, which is the worst way for a number to be wrong.
Removed, along with the field, so the safety comes from there being no option rather
than from a default. **A sheet nobody can add a column to is now unsupported**, and
that is the honest trade.

**Cells are read unformatted**, so a currency cell arrives as `1250.5` rather than
`"$1,250.50"` — the mapping parses either, but a raw number cannot be got wrong by a
locale. The exception is dates: a date cell comes back as a serial number
indistinguishable from a quantity, so a sheet should hold `2026-08-21` as text. The
connector cannot fix that and the field hint says so.

**Two secrets are deliberately not echoed.** Google's error body for a rejected
service-account key can quote the assertion back, and the assertion is signed with
the customer's private key — so only the status is reported. The scope asked for is
read-only spreadsheets and nothing else.

**Five mutation survivors, and one was a fixture that could not discriminate.** The
"a column blank in the first row is typed from a later one" test used a sheet with a
single column — so the blank row was dropped as an empty row and the record never
existed to be retyped. It needed a second column to keep the row alive. The other
four were plain gaps: trimmed headers, a boolean cell, a token response with no token
in it, and a warning whose consequence half was untested.

**Two tests elsewhere had to change**, and they were right to. Both asserted that
nothing in the build signs in to anything — true until Sheets shipped. Replaced with
the property: every provider Settings offers is one a registered connector needs, so
the list follows the build rather than being edited alongside it.

#### 3b-vii — connector marks — done

- [x] `connectorMark.tsx` — one lookup, used by the connector cards, the source
      list, the wizard's first step and a source's own page
- [x] `GoogleLogo`, `InitialLogo`, and a `DatabaseIcon` for SQL

**Three tiers, and which tier a connector lands in is a judgement about honesty
rather than about effort.**

A **real brand mark** only where it can be reproduced faithfully — Microsoft's four
squares, Google's G. Simple, published, instantly recognised, and a wrong version of
either looks like a phishing page.

A **letter tile in the brand's colour** for every other named product. A
hand-approximated logo is worse than no logo: it misrepresents somebody else's
trademark and looks like a knock-off, which on an integrations page gives exactly
the wrong impression. Dropping in an official SVG later is one line in that file.

A **plain icon** for the ones that are not brands. A webhook is a protocol and "any
JSON API" is a category; giving either a logo would be inventing a product that does
not exist. SQL gets a database rather than a plug, which is the small point of the
map existing at all — "some sort of connection" is true of every row on the page and
therefore tells a reader nothing.

**The lookup is not on the API.** The backend says a connector is called
`freshdesk`; what that looks like is the frontend's business. Sending an icon name
over the wire would mean shipping a connector required touching a schema.

**Not tested, and worth saying why.** Asserting which component a lookup returned
needs a DOM renderer, and this project has no React testing library — adding one for
a three-branch lookup that TypeScript already checks would be a dependency bought to
test presentation. It is verified by looking at it.

**One thing to know before Google Sheets.** The _Sign in with Google_ button has its
own published branding rules — minimum size, exact wording, a specific asset — which
are stricter than showing the mark on a card. That is a separate job from this file
and belongs with the Sheets connector.

#### 3b-vi — the popup sign-in — done

- [x] The callback returns a page that messages its opener and closes, instead of
      redirecting the whole browser
- [x] Falls back to navigating when there is no opener
- [x] 56 tests, 45 mutations, all killed

**A sign-in button, not a page you get sent away to.** The connect flow opens a
popup; the callback closes it and hands the outcome back through `postMessage`. The
wizard is still sitting there behind it, which is what makes this feel like the
two-click experience the product is aiming at rather than a redirect that loses your
place.

**One response handles both cases.** A blocked popup, a pasted callback URL, a
provider that lost the window — all arrive in an ordinary tab with no opener, and
the same page navigates instead. Two responses that handled them separately could
disagree, and the one that gets exercised least is the one that breaks.

**The message is posted to our own origin, never `"*"`.** It is the signal that a
credential was stored, so any page able to receive it could act on it.

**The outcome rides in a `data-` attribute and is read with `JSON.parse`.** It
carries a provider's own words — `error=</script><script>alert(1)</script>` is a
thing a hostile provider can send to an endpoint that has no session behind it — so
it is data at every step rather than text interpolated into a script.

**One mutation survivor was a guard made unreachable by a better one.** An earlier
version also escaped angle brackets at the JSON level, from when the payload _was_
interpolated into the script body. Once it moved to an attribute, `html_escape` was
doing the whole job and the second layer could not be distinguished by any test.
Removed — with a note saying it has to come back if the payload ever moves back
inside the script.

**And one limit worth naming.** Whether the popup-versus-tab branch is _taken_
correctly cannot be asserted from Python, because the branch is JavaScript this
suite cannot run. The test asserts the guard's condition is present, which is the
honest edge of what is reachable without a browser test runner — the same category
as the `compare_digest` note in the webhook connector.

#### 3b-v — nothing is written without a row id, and the generic API connector

**The important half of this slice is a bug, not a feature.** Building the generic
connector meant thinking again about sources with no stable row id, and a probe
against the real pipeline found this:

| pass | status  | read | written | facts total |
| ---- | ------- | ---- | ------- | ----------- |
| 1    | partial | 2    | 1       | 1           |
| 2    | partial | 2    | 1       | **2**       |
| 3    | partial | 2    | 1       | **3**       |
| 4    | partial | 2    | 1       | **4**       |

A source whose mapping names no external id, with **one unanswered quarantine
question**, appended its good rows again on every single sync. Hourly, that is
twenty-four phantom measurements a day inflating a leaderboard.

**Both halves of the cause were individually correct.** `_upsert` can only recognise
a row it has seen before by its `external_id`, and without one it inserts — which was
documented as a known cost. And a `partial` run does not advance the watermark,
deliberately, so rows held for a quarantine question can be re-read once it is
answered. Neither is wrong. Together they are an inflation engine, and no test
existed that put them in the same room.

**So a row with no id is now a configuration error**, reported per row like any
other, with a message naming the fix. Loud and stopped beats silent and wrong, and
it is what a warehouse tool does: Fivetran and Airbyte both require a primary key
for anything but append-only loading. Webhook sources are unaffected — the connector
supplies its own delivery id — which is exactly why this lived undiscovered: every
existing test used a stub that provided one.

The preview goes through the same check, so it cannot promise an import that would
then be refused. And two UI hints were quietly wrong: both promised the source's own
id as a fallback, which only a receiving connector has.

- [x] `_identify` in `app/sync.py`, with the two messages a blank id needs — no
      column named, versus a named column that was empty on this row
- [x] Six tests, including the four-pass compounding case as a regression
- [x] `app/connectors/api.py` — the generic connector
- [x] 75 tests, 69 mutations across the three REST files, all killed

**The generic connector is the engine with its spec on the form.** So "we do not
support that yet" is never a dead end: anything with a JSON endpoint and a key can
feed GoalGetter today. It is also how a named connector gets prototyped — get the
paging and the date filter right against a real API, and the working settings _are_
the spec.

More fields than anything else in the product, deliberately. Pointing at an
arbitrary API needs those answers and there is no honest way to guess them, so they
are asked plainly with a sentence each rather than hidden behind a wizard that
guesses wrong. Everything but the URL has a default, and paging defaults to a single
request — asking for page two of something that does not page can return page one
again, and a loop reading the same hundred rows five hundred times is worse than
reading one page.

**A live probe turned the hardest step into a guided one.** Pointing it at a real
endpoint returned _"Connected. The first page returned 0 records"_ — true, and
useless: the response was an object and the records path was empty. There are three
reasons for an empty result and an admin cannot tell them apart from outside, so the
Test button now says which:

- the configured path holds an empty **list** — normal, nothing changed;
- the path holds nothing but there **are** lists elsewhere — names them, so
  `rows_at` becomes a choice rather than a guess;
- there is **no list anywhere** — almost always the wrong URL, so it says so and
  lists the keys that did come back.

That third case only appeared because the probe pointed at a status endpoint. The
first version of the fix reported it as "normally empty", which would have sent
somebody away satisfied with a source that could never import anything.

#### 3b-iii — more SQL dialects — done

- [x] `pymysql` in the default image: **MySQL and MariaDB**, pure Python, ~50 KB
- [x] Snowflake, Redshift and SQL Server as optional extras, with an `API_EXTRAS`
      build argument so a deployment enables one without editing code
- [x] `_build_url` split from `_url`, so a dialect this build has no driver for can
      still have its URL tested

**Three dialects offered, six known, one verified — and the numbers being different
is the honest part.** `available_dialects()` checks by import, so a database whose
driver is absent is never offered; a `VERIFIED` tuple records which have actually
been run against a real server, and it contains PostgreSQL alone. Claiming otherwise
would be exactly the confidence this phase has been bitten by six times.

**What is testable about a database this build has never spoken to is the URL.**
Whether the driver holds a real conversation is not; whether the prefix is spelled
correctly is, and a typo there is a connection attempt against nothing. That needed
`_build_url` separating from `_url` — the combined function refused an uninstalled
dialect before assembling anything, so the one testable part could not be reached.

#### 3b-iv — the REST engine, and Freshdesk on it — done

- [x] `app/connectors/rest.py` — auth styles, four paging strategies, JSON paths,
      the window, rate-limit retries
- [x] `app/connectors/freshdesk.py` — a spec and two models, nothing else
- [x] 55 tests, 50 mutations, all killed

**A provider is data, not code.** Freshdesk is a `RestSpec` plus a config model and
a credential model; the engine does the rest. That is the whole bet of this phase:
the next twenty-odd providers are a spec each, and if Freshdesk had needed its own
request loop then every one of them would need theirs.

**Freshdesk went first among the REST providers because it has no OAuth** — an API
key in HTTP Basic. Same reasoning as webhook before SQL and SQL before OAuth: prove
the engine against a real provider's paging and filtering without a consent flow in
the way.

**Driven by `httpx.MockTransport` rather than a patched method.** The transport sits
where the socket would, so the requests under test are real requests: the paging
loop pages, the auth header is on the wire, the retry retries. Patching `client.get`
would only prove the code called something.

**Knowing when to stop paging is the hard half, and it gets the most tests.** A
wrong rule either drops most of the data or asks forever, and both look like success
— one returns a plausible row count, the other returns a timeout. The rule is
ordered by how much the provider told us: a cursor it handed back, then a flag it
set, then arithmetic on the row count. Arithmetic last, because it is the only one
that can be wrong: a final page that happens to be exactly full looks like a middle
page, which costs one wasted request rather than missing rows.

**Rate limits are honoured rather than fought.** A 429 with `Retry-After` is a
provider asking politely, and ignoring it is how an integration gets blocked for
everyone on that account. Capped, because a sync that sleeps for ten minutes is a
sync that has stopped. A 401 is never retried — hammering an authentication endpoint
is how an account gets locked.

**No error message quotes a URL.** One auth style puts the credential in the query
string, so a message naming the URL would write an API key into the run history,
where the entire point is that credentials are encrypted.

**Freshdesk's `updated_since`, not `created_since`** — a ticket opened last month and
resolved today has to come back, and a filter on the creation date never returns it.
That is the trap from 3a, and it now has a test in a third place.

**A blank setting is checked separately from a missing one, and mutation testing is
not what found it — the first test run was.** `{domain}` with `domain=""` formats to
`https://.freshdesk.com/api/v2`: no placeholder left, structurally a perfectly good
URL, and it fails at DNS with a message about a hostname rather than about the box
somebody left blank. The two checks are also _ordered_: a placeholder the form does
not offer at all is a connector bug, and reporting it as "not filled in" sends
somebody hunting for a box that was never on the page.

**One survivor was dead code again.** An explicit `None`/dict/list branch in
`_kind_of` returned `"string"` — which every one of those already reaches by falling
through. Deleted, with the _policy_ it was standing in for left where it is actually
enforced: `_fields_of` does not unwrap nested values because there is no unwrapping
code, not because a branch says so.

#### 3b-ii-a — the OAuth framework — done

- [x] `oauth_client` table + migration — one registration per provider
- [x] `app/oauth.py` — spec, PKCE authorize URL, exchange, refresh, `ensure_fresh`
- [x] `app/routers/oauth_clients.py` — Settings registration, plus authorize and
      the unauthenticated callback
- [x] `connectors.oauth_of()`, the same optional-capability pattern as
      `endpoint_credential_of`
- [x] Every path that hands credentials to a connector — sync, test, discover —
      routed through `ensure_fresh`
- [x] 49 tests, 40 mutations, all killed

**Framework before connector, again.** Driven by a fake provider for the same
reason the pipeline was driven by a stub connector: the dance, the storage and the
renewal should be proven before a real provider's quirks are in the way. Google's
endpoints arrive with the Sheets connector.

**One manual step, and it is unavoidable.** There is no hosted relay, so no central
service holds a Google client secret on a deployment's behalf — each one registers
its own OAuth application and pastes two values into Settings. Everything after
that is a sign-in button. Registering is per-deployment and happens once;
connecting a source is per-source and takes seconds. The redirect URI is displayed
because a mismatch is the most common setup failure and the error a provider
returns for it does not say what it expected.

**The refresh merges, and `credentials.put` still replaces.** A refresh response is
usually just an access token, so replacing would discard the refresh token and the
source would work for an hour and then stop for good — while a provider that
rotates sends a new one, which merging still picks up. Both directions are tests,
because only one of them fails visibly.

**Providers are derived from the connectors.** Settings offers a registration only
when something in the build can use it, and stops offering it when that connector
is removed — a page inviting somebody to register an app nothing will call is a
page inviting pointless work.

**Removing a registration leaves live sources alone.** Their access tokens keep
working until they expire and then fail with a message naming what is missing.
Revoking working integrations as a side effect of tidying up Settings would be a far
worse surprise than a sync that stops and says why.

**`authorize` returns a URL rather than redirecting.** The caller is `fetch` from a
single-page app; a 303 would be followed inside the XHR and the consent screen
would arrive as a JSON parse error.

**The callback is unauthenticated by necessity** — a provider redirect carries no
session cookie for a cross-site navigation — so the sealed flow cookie _is_ the
credential. Encrypted rather than signed, because it holds the PKCE verifier;
`httponly`; scoped to the callback path; ten-minute life; and carrying the source id,
since the redirect URI is registered with the provider and cannot vary per source.
A tampered cookie fails to open rather than quietly changing which source receives
the tokens.

**Mutation testing found nine real gaps, several of them security-relevant.** The
worst was a PKCE test that could not tell a hash from the secret: it asserted the
string `code_verifier` was absent from the authorization URL — which is the
_parameter name_, absent either way, while the mutant sent the verifier itself as
the challenge. It now recomputes the S256 hash from the cookie and compares. Also
missing: any cross-organization test of `client_for` (another tenant's registration
would have authorized this one's source), the state in the URL matching the state in
the cookie, `HttpOnly` on the flow cookie, a callback with a matching state and no
code, and the audit entry's "was the secret touched" flag in its false case.

**One mutant showed the code was too broad rather than the test too narrow.**
Catching `Exception` around the cookie decrypt could not be distinguished from
catching `ValueError`, because `crypto.decrypt` documents a `ValueError` contract
and `json.loads` raises a subclass. Narrowed to what can actually happen.

---

### 3i. QA against a real warehouse

**Phase 3 said "pending QA" for weeks, and the QA found things a test suite
structurally could not.** A live Snowflake account, somebody else's data, and an
afternoon of connecting it.

**What the warehouse taught us.** Snowflake separates storage from compute, so a
session can authenticate perfectly and run nothing: the `SELECT 1` probe passed
without a warehouse and lit a green tick in front of the one misconfiguration the
button exists to catch. It now asks the session what it actually got. Key-pair
needs `ALTER USER`, which most people connecting for the first time cannot run on
themselves, so programmatic access tokens were added beside it — a PAT is not a
password to the driver, and handing one over as one is refused in a way that reads
as a bad token.

**What the data taught us.** A view built to feed a leaderboard tool has one row
per person and a number that moves, with the period in the column name —
`amount_today`, `amount_month`. Three assumptions broke at once: that every source
can say when something happened, that a column named `..._month` is a month
number, and that "count the rows" is always a useful metric. Dateless mappings now
date a fact by when its number last changed; period suffixes are read as periods;
and the row-count metric is offered only where a row is an event.

**What the roster taught us.** Two systems in one company disagree about how an
address is built — `pparker@` in the CRM, `peterp@` in the directory, both Peter
Parker. Exact email matched 139 of 495 people. Username matching closes part of
that gap, and refuses where two people fit; the rest were genuinely not in the
directory, which is a different problem and now says so.

**What the QA itself taught us.** Every UI bug that afternoon — a picker showing a
value its state did not hold, a blocker asking for a column the panel could not
express, three hints contradicting behaviour that had changed under them — was
invisible to a suite of four hundred passing tests, because not one of them
rendered a component. Render tests were added and found three more on the first
run. Separately, thirteen backend tests had been failing since the first of
September: they were written with literal dates and asserted against boards whose
period is "this month". Nothing about the product had changed; the calendar had
moved.

---

## Phase 4 — Customization & Depth

**Goal:** the wall stops being a report and becomes something a room reacts to.

**What changed the shape of this phase.** Two research passes over Spinify — its
public knowledge base, and a look-only session in a live 157-user account — are
written up in [`research/spinify-feature-inventory.md`](research/spinify-feature-inventory.md)
and [`research/spinify-ui-walkthrough.md`](research/spinify-ui-walkthrough.md).
The conclusion was that **GoalGetter's gap was never structural**: users,
metrics, competitions, achievements, channels and displays already map one to
one. What was missing is the presentation layer — styles, themes, interstitial
moments, per-person flair, and the points economy that gives a wall something to
celebrate between sales.

Three of their weaknesses set the direction here, and each is a decision rather
than a feature:

> **Customization was scattered across five pages**, so "why is this screen
> green?" had five possible answers. Ours is one system with inheritance.
>
> **230 hand-built designs with no search or filter** — a 41,000-pixel scroll.
> Ours is a handful of layouts times themes times backgrounds: fewer things to
> build, more combinations to choose from.
>
> **No live preview anywhere.** Their celebration editor is forty fields you
> fill in blind and then walk to a TV to check. Ours renders the real screen
> beside the form.

Everything is in scope except the AI features, which need an external model and
would break the air-gap principle — templates, random variants and bundled media
do the same job offline.

---

### 4a. Image storage — done

The first file storage in this product, and it stayed out deliberately: `media`
takes URLs and `Avatar` drew initials, both documented as "uploads can follow if
anybody wants them". Staff photos are what wanted them.

- [x] `stored_image`, content-addressed by SHA-256 of the stored bytes
- [x] Validation by **decoding**, never by filename — two opens, because Pillow's
      `verify()` checks structure rather than content and a truncated JPEG passes it
- [x] Normalised to one 400×400 square: centre-crop _then_ resize, honouring the
      phone orientation tag before discarding it
- [x] Re-encoded from pixel data, which is what actually drops EXIF — a phone
      photo carries the device, the owner's name and where it was taken
- [x] Size capped before decode _and_ by pixel count, because a decompression
      bomb is a small file that becomes an enormous bitmap
- [x] Served immutable for a year, safe because the URL is the hash

> **In Postgres, not on a volume.** The compose file backs up the database
> nightly and nothing else, so an uploads directory would have been a second
> backup path existing only in somebody's memory. Four hundred and fifty faces at
> forty kilobytes is twenty megabytes, and a row and its bytes commit together —
> an orphaned file is not a thing that can happen.

**Verified:** 23 tests, including that "Peter Parker" in an EXIF Artist tag does
not survive storage.

### 4b. Profile photos — done

- [x] **Two slots per person**: what the directory has, and what somebody chose
- [x] M365 sync — metadata batched twenty at a time, bytes fetched only for the
      faces that changed, so a 450-person tenant is 450 requests the first night
      and about 20 thereafter
- [x] Individual upload, and **bulk upload** from a zip named by username
- [x] Faces on the app shell, account, user detail, leaderboards, the wall and
      the achievement feed
- [x] Wall fetches through the display's own token, so a revoked display loses
      the faces at the same moment it loses the board

> **Two columns rather than one, and that is what makes "revert" mean
> anything.** With a single slot a nightly sync would overwrite the headshot
> somebody uploaded, or the upload would win for ever and there would be nothing
> to revert _to_.

> **The bulk matcher is the identity matcher.** `pparker.jpg` finds Peter Parker
> exactly the way `pparker@` in a Snowflake view does — exact email, then login
> forms derived from the name, then a refusal where two people fit. A second
> matcher for filenames would be a second place to fix the day a surname has an
> apostrophe in it.

**Verified:** 27 tests. Photo editing widened from admin-only to admin _and_
manager during the build: a face looks like the one personal part of a profile,
which is true of colleagues and not of whoever manages the roster — and most
people here never sign in, because the directory created their account.

### 4c. Appearance foundation — done

- [x] `appearance` JSONB on organization, channel and screen
- [x] `resolve()` merging outermost-first, `None` meaning inherit at every level
- [x] Validated on the way in, so an unknown key is dropped rather than carried
- [x] **Appearance** nav tab: brand colours with per-field reset, slogan,
      bundled fonts, font scale, panel opacity/blur/corners, name display
- [x] Light / dark / follow-my-system for the app, independent of the wall

> **Sparse on disk is what "inherit" looks like.** A field nobody chose stays
> absent, so a later change to the built-in default still reaches them — and
> "reset to inherited" is a real control rather than a guess about which default
> to write back.

> **Backgrounds merge field by field, except `kind`, which replaces.** A screen
> saying "solid blue" over the organization's photograph means the photograph is
> _gone_; merging would leave the asset sitting there unused.

> **Only brand colours are overridden, not greys and text.** An organization
> choosing purple has not asked for purple body text, and allowing it would put
> an unreadable wall one colour picker away.

**Found on the way:** `data-theme='light'` had existed in `theme.css` since
Phase 0 and **nothing had ever set it** — the light theme was written and
unreachable. Also a real bug: validating the JSON inside the handler raised
`ValidationError` _after_ the request was accepted, which FastAPI reports as a
500, so a font scale of nine came back as "internal server error" rather than
naming the field. Now typed at the request edge.

**Verified:** 31 backend, 17 frontend.

### 4d. Live preview — done

- [x] Every wall screen extracted from `DisplayFeed` into `components/wall/`
- [x] `WallPreview`: the real screen at 16:9, scaled by transform
- [x] Sample data, so a wall can be designed before any connector works
- [x] Wired into the Appearance page, with a picker for each screen kind

> **The extraction is the feature.** A preview built to _imitate_ the wall would
> pass its own tests for ever while drifting from what a TV shows. The two now
> share one renderer, and a test asserts they produce identical content from the
> same slide.

> **Scaled by transform, not by smaller type.** A wall is designed at 1920×1080;
> re-specifying every size for a preview would mean two sets of numbers and a
> preview that lies about line wrapping. What wraps here wraps there.

The only thing the two callers differ on is now a parameter: `ImageUrl`, a
builder rather than a token — so the screen components never learn what a
display token is, and **a preview needs no token to exist**. That is what lets
an editor show a channel before the channel has been created.

`DisplayFeed` went from 444 lines to 151.

**Verified:** 13 frontend tests, including preview and wall rendering
byte-identical content.

---

### 4d-ii. Per-item appearance — done

A board, a goal or a contest now carries a look of its own, so "Shark Week is
blue everywhere it appears" is one setting rather than one per television.

- [x] `appearance` JSONB on `leaderboard`, `goal` and `competition`
- [x] The chain is `organization → item → channel → screen`, merged server-side
      and attached to each slide
- [x] `AppearanceFields`: one shared control, collapsed until wanted, every
      field saying what it inherits and offering reset only once set
- [x] Embedded in the board, goal and competition editors, with the live
      preview beside it
- [x] A running competition can be restyled from its card, by itself

> **The item sits before the channel, deliberately.** A venue's concerns beat a
> thing's own identity: "this TV is in a lobby, show initials only" has to win
> over "this contest is themed red", because legibility and privacy belong to
> the room the screen is in, not to the contest being shown.

> **Looking writes nothing.** Opening the panel, reading what the defaults are
> and closing it again leaves the item inheriting. Writing every placeholder on
> sight would mean a later change to the organization's brand stopped reaching
> anything anyone had ever glanced at — a test holds this.

> **Restyling is not a rule change.** A contest's entrants, dates and metric
> lock when it starts; how it is _drawn_ was never one of those, and a running
> contest is exactly when somebody wants to recolour it — it is on the wall
> this week. It gets its own small form rather than the edit form with most of
> it greyed out, because eight fields that refuse to change and one that does
> not is a puzzle, not an editor.

**Found on the way:** a goal's own look was being handed to `Trend` instead of
to `GoalRead` — one misplaced line — so it was stored, never returned, and
every goal editor would have opened showing the organization's defaults no
matter what had been saved. Pydantic ignored the unknown field rather than
raising, and a goal with no trend line lost it silently. Caught by writing the
goal tests for parity with the board and contest ones.

Also: the organization's resolved appearance is what every
per-item control needs for its placeholders, and three editors opened in one
sitting would have asked for it three times. Cached per page load, and
invalidated when the Appearance page saves.

**Also fixed:** `npm run typecheck` had been red on three test files since
Phase 3 — fixture types, not product code, but a red typecheck hides the next
real error. Green again.

**Verified:** 15 backend, 8 frontend.

---

### 4e. Layouts

One layout engine per shape, each reading theme tokens — so a colourway is a
preset, not new code.

- [x] **Podium**: top three on steps, optional list below
- [x] **Goal gauge**: a dial, or one big number — chosen per goal or per screen
- [x] The org-wide "Big Epic Goal" a floor can pull toward together
- [x] **Comparison**: two to four boards side by side on one slide
- [x] **Player spotlight**: photo, stats, streak, recent wins — a person, a
      board, or both
- [x] Per-screen options: rows, show/hide scores, font scale — every one of
      them settable at any of the four layers
- [ ] ~~Filterable gallery with favourites~~ — **not built, deliberately.**
      There are two ranked layouts and two goal layouts. A gallery with filters
      and favourites over four options is more interface than the thing it
      organises, and the control it would replace is a picker beside a live
      preview of the real screen — strictly more informative than a thumbnail.
      Worth revisiting when 4l's game boards make the list long enough to
      browse.

> **Player spotlight is the highest-confidence item in the phase**, and it came
> from an observation rather than a feature list: in a real 157-user account,
> nearly every custom message was a hand-made image of one rep. Admins are
> opening an image editor because the product has no template for it.

> **The board-sourced form is the feature; the named person is the request.** A
> screen naming a person is an uploaded image with extra steps — it goes stale
> the moment somebody overtakes them. A screen naming a _board_ is "whoever is
> leading", answered fresh every time a television refreshes. Both together
> mean "this person, on this board", which is how a manager keeps a spotlight
> on the new starter they are encouraging rather than on whoever happens to be
> winning.

> **A streak is the only statistic there that is about the person.**
> "Fourteenth this month" resets on the first and says nothing about effort.
> Counted in the organization's timezone, and **yesterday counts as current** —
> numbers arrive during the day, so requiring today would reset every streak in
> the building overnight and restore it by lunch. See `app/streaks.py`.

**Found on the way:** the Appearance tab offers "Their nickname" as a way to
display names, and **no nickname exists anywhere in the data model** — not on
`user_account`, not in any payload. Choosing it silently falls back to the full
name. The same class of thing as `data-theme='light'` in 4c: a setting that was
written and never wired. Added to 4g below.

`eligibility.person_where` came out of `goal_where`, which already contained it
— a spotlight has the same hole a goal does, in that it names its own subject
and leaves the audience filter nothing to bite on.

**Verified:** 17 spotlight, 11 streak, 12 frontend.

**Comparison** is the other half of 4e. A screen pointing at two to four boards
at once, each panel drawn with the same component as a full board and keeping
its own units.

> **A question no single board can answer.** "Who is calling and who is
> closing" is two boards, and a rotation showing them ninety seconds apart asks
> the room to hold one in their head while they wait for the other. Side by
> side, the person who is top of one and bottom of the other is visible in a
> glance.

> **A join table, not four nullable columns.** Four columns would encode the
> limit in the schema, let the same board appear twice, and leave "which order
> are they in" with no answer. The 2-4 rule lives in the router because it is a
> statement about legibility on a television rather than about integrity — and
> a screen that has lost a board to a deletion should keep showing the rest
> rather than become unstorable.

> **Losing one board does not blank the screen.** A comparison of three that
> has become a comparison of two is still the comparison. Blanking it would
> punish the room for an edit made somewhere else.

> **Each panel keeps its own units**, or seven deals print as $7.00 — a screen
> that looks right and says something false. Both the server and a render test
> hold this.

**Found on the way:** clearing the panels _after_ setting the new kind
triggered an autoflush of a half-edited row and failed the payload CHECK, so
editing any comparison into anything else was a 500. The existing
`test_changing_a_screens_kind_clears_the_old_payload` caught it immediately.
The clear now happens while the row is still consistent.

`Board` came out of `WallScreen` while doing this, with a `size` prop — a
second renderer for the small version would have drifted, and the panels on a
wall would have stopped matching the board in the slide before them.

**Verified:** 13 comparison, 7 frontend.

---

### 4e-ii. The wall honours its appearance — done

**Most of the Appearance tab did nothing.** 4c built the storage, the
validation, the inheritance and the editor; 4d built a preview that applied it.
Nobody checked what the _television_ read, and the answer was two settings out
of eleven. An audit, and then the wiring:

| Setting                        | Before                                                    | Now                             |
| ------------------------------ | --------------------------------------------------------- | ------------------------------- |
| Brand colours                  | Applied in the app and the preview, **never on the wall** | Applied per slide               |
| Accent                         | A CSS variable nothing read                               | A real token                    |
| Font, font scale               | Variables nothing read                                    | A `.wall` scope, type in `em`   |
| Panel opacity / blur / corners | Variables nothing read                                    | `.wall-panel`                   |
| Name display                   | `displayName()` never called anywhere                     | Applied server-side, everywhere |
| Deadline format                | Never consumed, and no control for it                     | Four formats, with a control    |
| Slogan                         | Editable, rendered nowhere                                | On the wall header              |
| Channel and screen appearance  | Columns since 4c, **no API at all**                       | Readable and writable           |
| Ranked / goal layout           | Worked                                                    | Worked                          |
| Logo, background               | Editable or stored, rendered nowhere                      | **Still inert — next**          |

> **The wall never applied its own appearance.** `applyAppearance` was called by
> the app shell and by the preview and by nothing else, so an admin chose a
> brand colour, watched the preview turn green and the television stayed
> indigo. A shared renderer does nothing if one of its two callers never
> applies the theme — which is the exact failure the shared renderer exists to
> prevent, arrived at from the other direction.

> **Font scale had to be `em`, not `rem`.** Tailwind's sizes are `rem`, which
> is relative to the document root — so a scale applied to the wall element
> changed nothing, and applying it to the root would resize the whole app
> around the preview. `text-wall-*` are Tailwind's own values in `em`, so
> `text-wall-4xl` is `text-4xl` at scale 1 and one number on `.wall` moves all
> of them.

> **`first_initial` is a privacy setting, so it belongs on the server.**
> Trimming the string in a browser has still sent every surname to a television
> whose address bar is visible in the room. A test asserts the surname is not
> in the response at all — not that the screen displays an initial.

> **And it is applied in one place**, because a wall careful about surnames on
> the leaderboard and careless about them in the celebration that takes over
> the top of it is not careful at all. The docstring warned about exactly this
> case before anything called the function.

> **A team's name is never trimmed.** "Enterprise" becoming "E." is a bug
> wearing a privacy setting's clothes. Nor is a title somebody typed: "Rep of
> the month" must not become "Rep".

**Verified:** 10 name tests, 8 deadline-format tests, 7 wall-honours render
tests. Full suites: 2376 backend, 565 frontend.

---

### 4e-iii. Backgrounds, logos, and the last of 4e — done

The two settings left inert after 4e-ii, plus the one shape a goal could not
express.

- [x] **Backgrounds** drawn on the wall and in the preview: a colour, a
      gradient, a photograph, a YouTube loop — each with darkening and blur
- [x] **Logo upload**, with its own normaliser, drawn on the wall header
- [x] `POST /api/images/{kind}` — one endpoint, named kinds, admin only
- [x] **Channel and screen appearance UI**, so all four layers are reachable
- [x] **Rows** and **show scores** as settings, honoured by every ranked screen
- [x] The accent colour given a job, having been a token nothing read
- [x] **The organization goal** — one figure the whole floor adds to

> **A logo cannot go through the photo normaliser.** That one centre-crops to a
> square and encodes JPEG, which turns a wordmark into its middle third and
> puts a white rectangle behind a transparent mark. 600×80 is a normal logo and
> would fail the photo rule outright — `MIN_SIDE` is 200.

> **A background is fitted, not cropped.** A television is 16:9 and the
> photograph somebody chose probably is not. Cropping on upload decides the
> framing permanently and invisibly; the screen covers with CSS instead, which
> is reversible and which the preview shows.

> **Dim and blur belong to the background, not to the panels.** A photograph
> behind white text is unreadable at ten feet, and the fix is to darken the
> photograph rather than to make every panel opaque — which hides the
> photograph entirely and raises the question of why it is there at all.

> **`video` is not a background kind yet.** A stored video needs
> `stored_asset`, which 4g generalises `stored_image` into. A kind that
> validates, saves and then draws nothing is the failure this phase spent a day
> undoing, so it goes in when there is somewhere to put the file.

> **An organization goal names nobody.** Both subject columns stay null and the
> CHECK says so; inventing a sentinel id would make every query that joins a
> subject have to know about it. It is readable by everybody — a shared figure
> each person sees their own slice of is not a shared figure — and settable
> only by an admin, which is the same bar as publishing a board to everyone.

**Found on the way:** four real bugs, all caught by the tests written for the
feature rather than by review.

- `subject_type` was `VARCHAR(8)`, which fitted "user" and "team" exactly and
  rejects "organization" outright.
- `_owned` refused an organization goal to everybody except admins — its
  team-id comparison read `None != actor.team_id` as a mismatch — so the one
  goal designed to be shared was the one nobody could open.
- Two places named a goal's subject by looking up `subject_user_id` with no
  branch for the new type, so a company target rendered as "Deleted user"
  under a warning about a null primary key.
- Clearing a screen's panels autoflushed a half-edited row into a CHECK it
  fails. Latent for as long as a no-op edit left the row clean; adding a field
  that is always assigned made every edit dirty and turned it into a 500. Fixed
  with `no_autoflush` rather than by reordering, so the next person to add a
  lookup there does not have to know about it.

**Verified:** 16 brand-image, 11 wall-appearance, 15 organization-goal, 14
background render, 7 end-to-end. Full suites: **2425 backend, 579 frontend**,
typecheck and production build clean.

### 4f. Moments

- [x] **Overtake banner** — "Clark Kent passed Peter Parker into 1st"
- [x] **Winner / champion screen** after a competition closes
- [x] **Milestones** as one control: None / Important only / All
- [ ] Bundled trophies, entrance animations, a sound pack — **moved to the
      game-expansion work**, not dropped. Two of the three are gated on real
      art and real audio rather than on code, and the third has a better home
      once there is something to win: trophies belong beside the badge art and
      cosmetic unlocks in 4j/4l, not bolted to a celebration on their own. A
      wider pass on game interaction follows the "still open from earlier
      phases" list.
- [x] **Merge tags** in celebration text, with a picker and a live preview
- [x] **Replay on wall**, for the manager who missed it
- [x] Message _variants_ picked per win — the air-gapped answer to AI rewriting

### 4f-i. The two that people talk about — done

> **An overtake is a moment, not a fact.** Nobody opens a page to ask who
> passed whom last Tuesday, and the standings already say where everybody is
> now. Making it an event would have meant a table, a sweep and a row per
> overtake to say something only worth saying while somebody is looking at it.
> Detected in the browser instead: no new writes, nothing to back up.

> **Compared against the last time that board was on the wall**, not against
> the last poll. A board holds the screen for twenty seconds out of a
> two-minute rotation, so almost every overtake happens while it is off screen.
> "What changed since I last looked at this?" is the question a room has, and
> it is the one that fires often enough to be worth building.

> **A pass is a pair changing order, not a rank improving.** Somebody climbs
> two places because two people above them left the company; announcing that as
> an overtake is congratulating them on a resignation. A new entrant appearing
> above somebody has not passed them either — they were not racing yet.

> **A settled contest gets a different screen, not a different row.** While it
> runs a room wants the table: where am I, who is close, how long is left. Once
> it is over the only question left is who won, and a table answers that in the
> same size type it answers "who came seventh". No setting for it: a contest
> that has finished cannot become unfinished, so the choice would be between
> the right screen and a worse one, offered permanently, to be got wrong once.

> **Milestones is one control with three answers**, because three intentions
> actually exist — leave the rotation alone, stop for the big ones, stop for
> everything. Which events are "big" is a property of the event type beside
> `public` and `celebrate`, not an admin setting: an admin can write an
> achievement rule that fires on every closed deal, and a takeover every few
> minutes is how a takeover teaches people to ignore takeovers.

**Found on the way:** the banner's first version cleared itself in a second
effect, which React runs _after_ the one that announces — so on a slide change
the clear won and a banner could only ever appear while a slide stayed put.
Merged into one effect, because clearing the last banner and deciding the next
one are the same decision.

**Verified:** 11 overtake, 7 banner timing, 10 champion, 12 milestone.

### 4f-ii. What a celebration says — done

An achievement rule announced itself in a fixed shape: its name as the heading
and "Peter Parker — $6,200" underneath. Correct, and the same sentence every
time, which is what makes a floor stop looking up.

- [x] `achievement_rule.message` — one alternative per line, empty keeps the
      fixed shape
- [x] Four merge tags, served from the catalogue that validates them
- [x] A picker that inserts at the caret, and a preview with the tags filled in
- [x] Refused at the moment it is written, by name, with what was available

> **The air-gapped answer to "make it feel less repetitive".** The product this
> borrows from asks a language model to reword each announcement. That needs an
> outbound connection, a per-win latency budget, and a willingness to put text
> nobody wrote on a wall in front of the floor. Writing three lines and picking
> one does the same job, costs nothing, and the words are always words somebody
> chose.

> **Seeded by the win, not random.** The same piece of work always produces the
> same sentence, so a wall re-reading its feed cannot quietly reword an
> announcement somebody already read. Hashed rather than modulo, because
> consecutive ids would cycle through the alternatives in order and read as a
> rota rather than as variety.

> **Four tags, not an expression language.** Every one of them always has a
> value, which is what keeps a message from rendering with a hole in it — a
> team tag is an obvious fifth until somebody on no team wins something and the
> wall reads "Peter Parker on closed a big one".

> **Rendered once, when it fires, and stored on the row.** The message is what
> was said at the moment somebody earned it; filling the tags in again at read
> time would let a transfer or a rename quietly rewrite last month's
> announcement.

> **The preview is the point of the control.** A merge tag is the one kind of
> text where what you type is not what anybody reads, so the filled-in version
> has to be on screen while you write it — otherwise the first proofread
> happens on a television. It uses example values rather than a real
> colleague's figure, which would be a small privacy leak on a settings page.

**Found on the way:** pressing a tag button takes focus off the textarea first,
so the browser reports a caret at zero and every tag landed at the front of the
sentence. The caret is remembered on `select` instead, with "never touched"
meaning append.

**Verified:** 21 merge-tag, 8 message-field render.

### 4f-iii. Replay on wall — done

For the manager whose team's best moment of the week happened while the room
was in a meeting, and whose only record of it is a line in a feed somebody has
to be told to go and read.

- [x] `celebration_replay` — a request, aimed at one channel, alive for two
      minutes
- [x] **Play on wall** on the achievements feed, with a channel picker
- [x] Private wins refused, by the same rule the feed itself obeys

A "Test screens" button shipped alongside it and was removed the same day: it
put a fake celebration on a wall to prove the wall worked, which is a thing
somebody does once and a control everybody else has to read past forever. The
server path it was the only caller of went with it — an unreachable branch is
worse than a missing one.

> **A row, not a rewritten notification.** Bumping the win's timestamp to make
> it recent again would rewrite when it happened, and a record of what happened
> is the one thing that must not move.

> **A celebration's id became a string.** The same win can arrive twice — once
> because it happened, again because somebody pressed replay — and a screen
> remembers what it has played by id. A win id and a replay id are two things;
> a single number would have made the second look like the first, and the wall
> would have silently skipped exactly what it was asked to show.

> **A replay ignores the milestone setting and the five-minute window,
> deliberately.** That setting is about which wins are worth interrupting a
> room for _on their own_; a replay is somebody deciding this one is. And "the
> manager who missed it" missed it because it was not recent — refusing to play
> anything older than five minutes would refuse the entire feature.

> **202, not 201.** Nothing is guaranteed to have happened: a television that
> is switched off misses it, and the honest answer is "asked for".

**Found on the way, and much worse than the feature: a celebration never
ended.** The dismiss timer was set at the end of the effect that also _chose_
the celebration — and that effect depends on the celebration being shown.
Setting it re-ran the effect, React ran the previous run's cleanup first, and
the cleanup cleared the timer. Every celebration ever played stayed on the wall
until somebody reloaded the page.

> **The scheduling was tested and the component was not**, which is exactly
> where it lived: `celebrationQueue.ts` decided correctly what to play and for
> how long, and the component cancelled its own timer a millisecond later. The
> dismissal is now its own effect, whose cleanup fires only when the shown
> celebration changes.

It surfaced because a test card was the first celebration anybody had watched
end to end on a real television. Every no-media win had the same fault since
Phase 2.

**Verified:** 12 replay, 7 takeover render (the file that would have caught
it), and the celebration queue's own 16 re-pointed at the new id shape.

### 4g. Person flair

- [x] **Nicknames** — closing the inert name style found in 4e
- [x] Avatars generated locally — **a colour per person, not a library of
      drawings**. See 4g-iv for why that is the smaller and better answer.
- [x] **Uploaded walk-up audio** — the most-loved feature in their testimonials
- [x] Birthday and work anniversary, with a weekend rule
- [x] Self-service toggles: which fields an agent may set for themselves
- [x] Generalise `stored_image` to `stored_asset` for audio and backgrounds

### 4g-i. Nicknames — done

The Appearance tab has offered "Their nickname" as a way to write names on a
wall since 4c, and there was nothing behind it: choosing it silently fell back
to the full name. The same class of thing as the light theme that was written
and unreachable.

- [x] `user_account.nickname`, forty characters, empty rather than null
- [x] `PATCH /api/users/{id}/profile` — yours, or anybody's if you run the place
- [x] Used by every name on a wall, including the celebration over the top
- [x] A field on the account page and on a person's page

> **The column was never the point.** Storing a nickname is easy; the work was
> making one name rule reach a board, a spotlight, a comparison panel, the
> recent-wins strip and the takeover — the same "one place" the surname rule
> needed, and for the same reason. A wall careful on the leaderboard and
> careless in the banner that interrupts it is not careful at all.

> **Looked up only for the style that needs it.** Every other name style is a
> transformation of the name already in hand, so a wall not asking for
> nicknames queries nothing. When it does ask, it is one query per slide rather
> than one per row.

> **The photograph's permission rule, not the roster's.** Role, team and name
> are decisions about where somebody sits and belong to whoever runs the
> roster. A nickname is a decision about _them_ — so it is theirs, or anybody's
> if you run the place. Most people here will never sign in, which is the same
> reasoning that widened photographs beyond admins.

> **Falling back is the honest answer.** Most people will never set one, and a
> board of empty cells is worse than a board of names.

**Verified:** 13 nickname.

### 4g-ii. Uploaded walk-up audio — done

Walk-up music was a YouTube link. That works, needs no storage, and requires
somebody to find their song, copy the address and know which second to start
at — which is most of the reason a floor ends up with three songs between forty
people. What everybody has is a file.

- [x] `stored_image` generalised to `stored_asset`: nullable dimensions, a
      duration, and a name that is true
- [x] `app/assets.py` — the store, split from the things that validate what
      goes in it
- [x] `app/audio.py` — header checked, length read, tags stripped
- [x] `POST /api/me/walkup/audio`, and an upload control beside the link field
- [x] Played on a wall through the display's own token

> **Renamed rather than joined by a second table.** Two content-addressed blob
> stores would be two sets of the same de-duplication, the same cache headers
> and the same per-organization scoping — and the third asset kind would make
> three. The reasoning for putting bytes in Postgres was never about images.

> **Null dimensions, not zero.** Audio has no width. A zero would be a lie
> every reader has to know about; null says "this kind does not have one".

> **Metadata, not a decoder.** Re-encoding would mean ffmpeg — tens of
> megabytes in the image and a subprocess per upload — to do a job the caps on
> size and length already do. What is genuinely needed is the length, so
> fifteen seconds can be enforced rather than hoped for, and the removal of
> tags: an MP3 from a phone carries a name, a comment and a full-size album
> cover, none of which anybody thinks they are uploading with a sound.

> **An `asset:` scheme in the column that has always held a URL.** Everything
> downstream of a clip — the notification row, the celebration payload, the
> wall — carries one string for "what to play". A parallel asset id beside it
> would mean every one of those learning which of the two to read, and a pair
> that can disagree about what a screen is doing. The scheme is
> self-describing, so nothing can mistake it for a link.

> **A long track is cut, not refused.** Somebody uploading a whole song has not
> made a mistake; playing its first fifteen seconds is what they expect, and
> stopping the rotation for three minutes is not.

> **The wall gets a digest, not a path** — exactly as it does for a face — so
> nothing on a screen learns what the scheme is, and the clip is fetched
> through the token that already scopes that display. The display's image route
> became an asset route in the process: it has always served whatever was in
> the store, and now that includes sounds.

One dependency added: `mutagen`, pure Python, for the length and the tag
stripping.

**Verified:** 18 walk-up audio, and the 54 image tests re-run unchanged against
the renamed table.

### 4g-iii. Birthdays and work anniversaries — done

Two events nobody earns, marked on a working day near the date.

- [x] `birthday_month` / `birthday_day` — no year, ever
- [x] `started_on` — year and all, because the year is the feature
- [x] `app/occasions.py`: leap days, weekends, and counting years by calendar
- [x] Its own sweep, in the organization's timezone
- [x] Set on the account page; a start date sits with team and role

> **A birthday is a month and a day, and deliberately not a year.** A wall
> saying "happy birthday" needs the date; nothing here needs somebody's age,
> and a column that holds it is a column that leaks it — to every admin, every
> export, and every later feature that assumed it was there to be used. A start
> date keeps its year, and the asymmetry is the point: "three years today" is
> the whole of what an anniversary says, and when somebody joined is a company
> fact rather than a personal one.

> **The same split decides who may set what.** A birthday is theirs, so it
> follows the photograph's rule. A start date is a company fact, so it sits
> with team and role where a manager sets it — an agent inventing their own
> would be a number on a wall nobody checked.

> **A weekend date moves to the Friday before, not the Monday after.** A
> greeting that arrives late reads as an afterthought, and a wall saying "happy
> birthday" on Monday about Saturday is worse than one saying it on Friday
> about Sunday. Everybody in the room can do the arithmetic.

> **Anchored on the year, not on the day it is marked.** The weekend rule puts
> the same birthday on a different date in different years, and anchoring on
> that date would let one fire twice the moment the rule shifted it.

> **29 February lands on the 28th in a common year**, rather than being
> skipped. Somebody born on a leap day has a birthday every year; the calendar
> is what is inconvenient.

> **Nothing on somebody's first day.** "Zero years today" is a sentence about
> their first morning, and they have enough happening.

**Found on the way:** `test_only_celebratory_events_are_public` failed, which
is the tripwire working — making an event public is a decision about what a
room full of people sees, and it is supposed to cost a deliberate edit.

**Verified:** 17 occasion, 18 end-to-end.

### 4g-iv. A colour per person — done

The roadmap said "built-in avatar library, generated locally". What shipped is
narrower than that on purpose, and the narrowing is the interesting part.

- [x] `avatarColour(name)` — deterministic, twelve hues, legible in both themes
- [x] `initialsOf(name)` — one copy, replacing three
- [x] Applied to the app avatar, the podium, the spotlight and the champion

> **An illustrated avatar set means shipping art**, which this phase has
> already deferred once for backgrounds and game boards. It also answers the
> wrong question: a cartoon face is worse than initials for recognising a
> colleague on a board from across a room, and it invents a likeness for
> somebody who did not choose one.

> **What initials actually lacked was distinctness.** Four hundred people in
> the same indigo circle are four hundred identical circles, and the letters
> were doing all the work at the size a wall draws them. So the letters stay
> and the circle carries a colour — no assets, no network, no invented faces.

> **Twelve hues, not 360.** Adjacent hues are indistinguishable at the size an
> avatar is drawn, so a continuous range buys nothing and makes two colleagues
> look identical as often as a coarse one does.

> **The same in light mode and dark.** An avatar is a self-contained chip with
> its own text on it: it does not need to match the page, it needs to be
> legible against itself. 42% lightness keeps white text above 4.5:1 for every
> hue, which a lighter shade does not for yellows and greens.

> **Seeded on the name, and stability is the property that matters.** A colour
> that changed between a leaderboard and a profile would be worse than no
> colour, because the eye learns it and is then wrong.

**Still open if you want the literal thing:** a pickable set of illustrated
characters, for people who would rather not have their face on a wall. That is
an art-assets job and belongs with 4k's background library.

**Verified:** 11 colour tests.

### 4g-v. Self-service toggles — done

Three things about somebody are theirs rather than the roster's — their
photograph, their details, and the clip that plays when they win. The answer to
"may they set it" was decided in code and the same for every deployment.

- [x] `self_photo`, `self_details`, `self_walkup` on the organization
- [x] Three switches in Settings, beside the other company-wide decisions
- [x] All on by default

> **It is not the same for every deployment.** A company with HR headshots
> wants one uniform set of photographs; a floor that has heard one person's
> walk-up song nine hundred times wants a manager to choose them. Most places
> want neither, which is why every switch defaults to on.

> **Agents only.** A manager and an admin can already set these for anybody, so
> a switch that also bound them would be a rule with no purpose — and one that
> locked an admin out of their own photograph would be a support call rather
> than a policy. Turning a switch off does not stop the thing happening; it
> moves who decides.

> **Columns rather than one JSON blob**, unlike `appearance` beside them.
> Appearance earned JSON at nineteen fields and growing; this is the complete
> set of things about a person that are not roster facts, and it is three.

> **Three switches, not one.** A company wanting uniform headshots has said
> nothing about nicknames, and a floor tired of one song has said nothing about
> either.

**Verified:** 14 self-service, plus a Settings render test asserting the
switches survive a save — they share a payload with the brand and the
timezone, so a page that forgot one would quietly re-open something an admin
closed.

**4g complete.** Full suites at the end of it: **2558 backend, 648 frontend**,
typecheck and production build clean, every migration round-tripped.

### Directory sync: add somebody hidden — done

Asked for while 4g was in progress, and it belongs with the roster rather than
with a phase.

The panel offered two answers — add them, or never ask again — and the gap
between those is where most of a directory actually sits. A company of four
hundred has contractors, service accounts and whole departments that do not
sell: none of them belong on a leaderboard, and all of them belong in the
roster.

- [x] `hidden` as a directory decision, beside `approved` and `declined`
- [x] Creates a real account, hidden from the first moment
- [x] **Add** and **Add hidden** as the two primary actions; **Don't add**
      kept, quieter, with the same undo it always had

> **"Don't add" was the wrong tool and the only one there was.** It creates no
> account at all, so those people exist nowhere — they cannot be found, given a
> photograph, or moved onto a team when they do start selling.

> **Hidden from the first moment, not hidden a moment later.** An account
> created visible and hidden on the next line is on a leaderboard for that
> line, and on a wall if the timing is unlucky.

> **A status, not a flag on approval.** It records what somebody decided, which
> is what the other three do — and it has to survive a sync, which is a
> property of the status list rather than of a boolean beside it.

**Verified:** 6 new directory tests, and one existing refusal re-pointed: its
message named "approved" when two statuses now add somebody, so it names the
act instead.

### 4h. Display operations

- [x] **TV pairing code** — a four-character code beats typing a token with a
      television remote, and matters more for self-hosted than for anyone else
- [x] Keyboard: pause, next, previous, fullscreen
- [x] Duplicate a channel or a competition
- [x] Reassign a display and force a reload, remotely

> **Every wall screen is a 10-foot interface, and that is a rule rather than a
> setting.** A layout here is read from about three metres away by somebody who
> is not looking for anything — so type is large, contrast is high, a screen
> carries one idea, and nothing on it needs a second glance to parse. It is not
> offered as an option because the alternative is not worth offering: a wall
> nobody can read from their desk is a wall nobody reads.

### 4h-i. Pairing a television — done

Typing a display URL with a remote control is the worst part of setting one up:
thirty-odd characters of base64 in an address bar, entered on an on-screen
keyboard with four arrow keys, by somebody standing on a chair. It matters more
here than anywhere else — a hosted product can email the link to a laptop, and
a self-hosted wall is often a television on a network with no mail client on
it.

- [x] `/pair` on the screen: one short address, the only thing ever keyed in
- [x] `display_pairing` — a code for the human, a secret for the screen
- [x] **Pair a screen** beside **Create a link** in the display form
- [x] The code changes itself every ten minutes, unattended

> **The code is for the human; the secret is for the screen.** Four characters
> have to be readable across a room and typeable with a remote, which makes
> them short enough to guess — so they never authenticate anything. The screen
> keeps a long secret from the moment it asks, and that is what polls. Guessing
> a code lets somebody claim a pairing they cannot then read, which a test
> asserts directly.

> **The alphabet is the interesting part.** Every character that can be misread
> is a support call: `0` and `O`, `1` and `I` and `L`, `5` and `S`, `8` and
> `B`. All gone, upper case only so nobody wonders whether case matters. That
> leaves 27 characters and 531,441 codes — and the question was never "can this
> be guessed", it is "can two screens in one building show the same four
> characters". They cannot: codes are unique among the ones currently waiting.

> **One open endpoint, and it grants nothing.** A television has no account, so
> asking for a code cannot need one. The row it creates points at no
> organization and no channel; the only way it becomes a display is an admin
> signing in and claiming it. Until then it is four characters and a secret
> that unlock an empty seat.

> **A bound, not a rate limit.** The failure worth preventing is somebody
> filling the code space so the four characters an admin reads belong to a
> screen they do not own. Fifty waiting pairings across the deployment makes
> that impossible rather than merely slow, and no honest deployment sets up
> fifty televisions in the same ten minutes.

> **What it makes is an ordinary display** — same token, same revocation, same
> everything. Pairing is a way of _delivering_ the URL to a television that
> cannot be typed into, not a second kind of display.

> **404 rather than 204 once a code expires**, so the screen shows a fresh one
> instead of waiting for a claim that will never come. A screen left on
> overnight is offering a working code in the morning.

**Found on the way:** the code alphabet had a duplicated character, which would
have quietly biased every code toward it. A test now asserts the alphabet has
no repeats, which is the sort of thing nobody notices by reading.

**Verified:** 19 pairing.

### 4h-ii. Keys, copies and a screen you cannot reach — done

Three operational gaps, each of which had the same shape: the thing you need
is possible, and doing it means standing at a television.

- [x] **Keyboard on the wall**: space to hold, arrows to step, `f` for
      fullscreen
- [x] **Duplicate a channel**, with every screen, panel and appearance layer
- [x] **Duplicate a competition**, with its rules and its entrants
- [x] **Reassign a display** without re-typing its URL
- [x] **Reload a screen** from three rooms away

> **Nothing about the keys is documented on the screen.** A wall with a legend
> of shortcuts along the bottom has one for ever, read by four hundred people
> who will never press a key. A wall runs unattended for months and then,
> twice a year, somebody is at it with a keyboard — setting it up, showing a
> visitor, or trying to read the board that just went past.

> **Stepping by hand pauses too.** Somebody pressing the arrow wants to look at
> what they landed on, not watch it leave. And pausing says "Paused", because a
> rotation that stops looks identical to one that broke.

> **A copy is a draft of its own, not a link.** Editing one afterwards leaves
> the other alone — which is the whole reason somebody duplicated rather than
> pointing a second display at the same channel.

> **No televisions come with a copied channel.** One that arrived already on a
> wall would put an untouched duplicate in front of an office before anybody
> had changed the thing they copied it to change.

> **A copied competition keeps its window's length, not its dates.** A copy of
> a contest that ran last March, dated last March, has already finished. It is
> moved to start now and run for as long as the original did, and it arrives as
> a draft whatever the original is now — the dates are the one thing that
> always needs checking.

> **Reassigning beats revoking and re-pairing.** A television showing the wrong
> channel used to be a job with a ladder: revoke, make a new display, walk to
> the screen, type a new URL. The token was never the thing that was wrong.

> **A reload marker rather than a message queue.** The wall already polls every
> minute, so this rides along in the answer it was going to fetch anyway. The
> screen remembers the value it first saw and reloads when it changes — null is
> the ordinary case, so "first seen" is what matters rather than "not null".
> For the browser that has been open since a deploy three weeks ago, and the
> one that has wedged: both look identical from a desk.

**Verified:** 9 keyboard render, 15 duplicate, 7 reassign and reload.

### 4i. Reporting tab — done

Mostly surfacing maths that already existed: `pace.py` knew whether a goal was
behind, `goals.py` knew what it had reached, and nothing said it to a manager
as a page.

- [x] **Manager overview**: percent on pace, health chips, coaching gaps naming
      _what_ is missing
- [x] **Per-competition report**: predicted end score, score vs predicted across
      past runs, all-time high, current vs first, current vs previous
- [x] **History**: hit-target rate, streaks, CSV export beyond leaderboards

> **The one thing here that is new is the sentence at the end.** A progress bar
> says where somebody is, a pace marker says where they should be, and neither
> is something you can hand to a person. "On four a day, needs eleven for eight
> working days" is a conversation, and nothing in the product said it before.
> That sentence lives in one tested function rather than in the page, because a
> rendering bug is visible and a sentence that reads "needs 0 a day" to somebody
> four hundred short is not.

> **Hit counts as on pace.** A finished goal is not a worry, and a page
> reporting 60% while a third of its goals were already met would be reporting
> on its own arithmetic rather than on the team.

> **Every rate is per working day.** "Twelve a day" over a fortnight holding two
> weekends is a target somebody misses by a third while doing exactly what they
> were told.

> **A gap with no name on it is not a coaching gap, it is a statistic.** The
> subject is resolved in the service even though it costs a lookup per behind
> goal; the list is capped at eight and ordered worst-first, so the eight are
> the eight that matter and nobody is asked to scroll a report.

> **"Past runs" means comparable contests, not repeats of this one.** A
> competition is an event somebody scheduled — there is no link from one to the
> one it succeeds, and a duplicate is deliberately a draft of its own. So the
> set is every _settled_ contest on the same metric and the same kind of
> entrant, and each is named on screen rather than melted into a line.

> **The bars are past results; the line is this run's forecast.** Nothing stores
> what an earlier contest was predicted to reach part-way through, and inventing
> that retrospectively would be drawing a number nobody ever saw. The card says
> which is which — "On pace to finish at" while it runs, "Final score" once it
> is settled — because a prediction and a result are not the same claim.

> **Track records are batched by metric, not walked per goal.** Six periods
> times two hundred goals is twelve hundred aggregations for one page; every
> goal on one metric and one period shape shares the same six answers, so the
> cost is set by how many metrics an organization has.

> **A manager's page, and agents are refused at the edge.** Not because the
> figures are secret — a manager still only sees their own team, one goal at a
> time, by the same scope rule the goal list obeys — but because every answer on
> it is a list of people to talk to, which is a job rather than a view.

**Fixed on the way:** an organization goal's history read as all zeros. The
walk had a branch for a team and a branch for a person, and an organization
goal fell into the second, where it filtered rows down to `subject_user_id` —
null for that shape. The one goal whose history is easiest to compute was the
only one that never showed any.

**Verified:** 40 backend, 33 frontend.

### 4j. Economy — done

- [x] **Points ledger** — one row per award, with its source; a balance is a sum
- [x] **Seasons**, from the start
- [x] Tiers, with thresholds suggested from the real distribution
- [x] Badges, manual or "fired N times within a period" — art is placeholder,
      see 4j-iii
- [x] Cosmetic unlocks, so points have a use without building a store
- [x] Prize wheel

> **Seasons are not a refinement.** In their live account the top dozen reps sat
> at 165K–178K points against a 100K top tier, and lifetime points equalled
> reward points because nothing is ever spent. Their economy is visibly dead at
> the two-year mark. Building tiers without seasons inherits that.

### 4j-i. The ledger and the season — done

The two that everything else hangs off, built together because the second
cannot be added afterwards without choosing between wiping balances people
earned and keeping the thing it exists to prevent.

- [x] `point_award` — one row per award, with its source and its reason
- [x] `season` — non-overlapping windows, enforced by the database
- [x] `point_value` — what each event is worth here, defaults in code
- [x] Points on an achievement rule, priced where the rule is written
- [x] Awards wired into goals, rules, competitions and recognition
- [x] Season table, personal balance, statement, and the admin panels

> **A ledger, never a running total.** A `points` column on `user_account` is
> one number incremented from four code paths, and the first time two of them
> race — or a job restarts mid-pass — it is wrong with nothing to compare it
> against. A balance is a sum, so a corrected row corrects the balance, and
> "why do I have 4,200?" is a query rather than an apology. The same reasoning
> that keeps leaderboards derived; the settled competition remains the one
> stored number in the product, and it earns it.

> **A mistake is corrected by writing the opposite row**, which is why points
> may be negative and why there is no `updated_at` on the table. A ledger row
> that records when it was last changed is a ledger row somebody has changed.

> **Idempotent by the index `notification` already uses.** The jobs that pay
> points out are the jobs that announce things: loops over state that is a
> query rather than a column, restartable mid-pass. The row *is* the record
> that we awarded it. `NULLS NOT DISTINCT` is load-bearing — without it every
> award with no period would insert again on every cycle, forever — and the
> partial clause on `awarded_by_user_id IS NULL` is what lets a hand-written
> award repeat, because a manager who gives somebody 50 points twice meant to.

> **`season_id` is deliberately not in that key.** An achievement somehow
> re-detected after a rollover must not pay out again into the new season.

> **The first award opens the first season.** An economy that refuses to pay
> until an admin has visited a settings page is an economy nobody switches on.
> It is aligned to the organization's fiscal quarter, so the first reset lands
> on a boundary the business already plans against. Reading the page never
> starts one.

> **Overlapping seasons are unstorable, not merely rejected** — an EXCLUDE
> constraint over `daterange(starts_on, ends_on, '[]')`, which is what lets
> "which season is this award in?" have exactly one answer. Inclusive at both
> ends: a season runs *through* its last day, and a half-open range would drop
> everything earned on the final afternoon.

> **Who is told and who is paid are different lists.** A manager hears about
> their agent's goal; paying them for it would put every manager at the top of
> a scoreboard made of other people's work. A team goal pays every member,
> because a balance somebody can spend has to belong to a person. An
> organization goal pays nobody — moving every balance by the same amount
> changes no ranking and teaches people the number is weather.

> **Recognition is the one award that can be farmed**, because it is the one a
> colleague hands out freely rather than something a rule detects. The defence
> is a latch rather than a limit — once per sender, per recipient, per day — so
> the second shout-out still happens, still lands on the wall, and simply does
> not pay again. Recognising yourself pays nothing.

> **An achievement rule's points live on the rule**, capped low, and the cap is
> the point: a rule fires on *every* matching record, so it is the one award
> whose volume nobody can predict when they write it. An admin who wants a big
> number there almost always wants a competition, which pays once and has a
> winner.

> **Everybody sees the whole season table**, which is the opposite of every
> other ranked thing here. A league narrowed per viewer shows an agent four
> people and calls it a league. What stays narrow is everything behind the
> number: a statement is your own, and awarding by hand is scoped like any
> other write.

> **Re-pricing changes nothing already awarded.** A ledger row records what was
> paid at the time; a balance moving overnight for work somebody did last month
> is the fastest way to stop people believing the number.

> **A net of zero is not a score.** Somebody never awarded anything does not
> appear, so somebody whose award was corrected back to nothing must not
> either — otherwise two people with no points are shown differently and one of
> them is at rank 1 with a zero beside their name. Negative balances do show:
> being docked is a thing that happened.

> **The lifetime total exists and ranks nothing.** It is a career figure, shown
> on somebody's own statement. The moment it becomes the scoreboard, the
> scoreboard is unwinnable again for everybody who joined last year.

**Verified:** 76 backend, 29 frontend. One migration, round-tripped.

### 4j-ii. Tiers — done

- [x] `tier` — a name and a number of season points, ordered by the number
- [x] Thresholds suggested from the season's real distribution
- [x] The rung somebody holds, and the distance to the next one
- [x] Tiers on the season table and on the balance card

> **A tier read against a number that only grows is a tier everybody
> eventually has.** Theirs sat at 100,000 with a top dozen between 165,000 and
> 178,000 — all Platinum for over a year, with nothing above it and no way to
> tell second place from twelfth. So a rung is measured against the *season*
> balance, which is why this could not be built before seasons were.

> **The two ways a rung goes wrong look nothing alike from inside the form.**
> Too high and nobody aims at it; too low and holding it says nothing. Neither
> is visible while you are typing round numbers, and both are obvious the
> moment you look at what people actually scored — so the suggestion is a
> button, and every suggested rung says how many people would hold it. That
> count is the number that settles the argument.

> **Percentiles, not round numbers.** 12,480 looks less tidy than 10,000 and is
> worth more: it is the number that puts a quarter of the floor above it, which
> is a statement about this team rather than about base ten. Round it
> afterwards — what matters is that you are rounding something real.

> **The distribution is of people, not of awards.** Somebody who earned 900 in
> one win and somebody who earned it in thirty are the same height; percentiles
> over raw ledger rows would put the second one much higher.

> **Below eight scoring people there is no suggestion at all**, and the page
> says why rather than showing an empty ladder. With four people the 95th
> percentile is "the highest score", and a top rung exactly one person can
> stand on is the failure this exists to prevent, arrived at by way of the
> thing meant to prevent it.

> **The ladder is replaced wholesale, not a rung at a time.** Editing it row by
> row means passing through states the unique index forbids — two rungs briefly
> at one height while you shuffle them — which would leave an admin stuck
> halfway through a sensible edit.

> **Moving a rung moves who is standing on it, immediately, and rewrites
> nothing.** A tier is read from a balance at the moment somebody looks; it is
> not stored on the person. There is no migration to run when the ladder
> changes and no history to correct.

> **"1,200 to Gold" is the only part of a ladder that changes behaviour.** The
> badge rewards what already happened; the distance is the reason to do
> something this week. Somebody below the bottom rung gets the distance too,
> because they are exactly who a ladder is for.

> **No colour or icon column.** A tier is a name and a number; how it is drawn
> belongs to the appearance layer like everything else that is drawn.

**Verified:** 35 backend, 6 frontend.

### 4j-iii. Badges — done

- [x] `badge` — given by hand, or counted from an achievement rule firing N
      times in a week, month or season
- [x] `badge_award` — who holds what, latched per window like every other
      detected award
- [x] Detection in the jobs pass, after the rules it counts
- [x] "Almost there" progress, and badges held several times shown once
- [x] Optional points on earning, through the ordinary ledger
- [x] Admin panel to define them; "Give a badge" for anyone who can recognise
- [x] Bundled badge art — placeholder marks at first; **drawn in 6.5.** A badge stores a key
      into `badgeMarks.tsx`, never an image, so real art replaces the line
      icons there without touching any data. Moves with the 4f trophies to
      the game-expansion work.

> **A badge is the part of the economy that survives a season reset.** Points
> go to zero every quarter, deliberately, and something has to be left over or
> the reset takes everything anybody built. A tier is not that thing — it is
> read from the current balance, so it resets too. So badges are *stored*,
> which is the opposite of nearly everything else here, and it is the right way
> round: "ten big deals in March" is not a claim about the present, and
> recomputing it would be rewriting history rather than correcting it.

> **Counted from `metric_fact`, and both alternatives are tempting and wrong.**
> Notifications are pruned at ninety days, so a season badge would quietly
> undercount near the end of a quarter. Ledger rows exist only when a rule
> pays points, so a rule set to zero — "celebrate it, do not pay for it" —
> would never earn its badge at all.

> **What a rule matches is now defined once**, in `app/achievements.py`, and
> both the announcing pass and the badge pass import it. Written twice they
> would drift, and the drift shows up as a badge saying ten while the wall
> announced eight — worse than either being wrong alone, because then neither
> can be trusted. There is a test that runs both against the same facts and
> asserts they agree.

> **The extraction nearly broke the flood guard, and a test caught it.** The
> announcing pass advances its watermark past everything it *examined*, not
> just what qualified — otherwise an admin lowering a threshold from $50,000 to
> $5,000 would announce every deal from the week before at once. A single
> "matches" predicate merged those two sets, and the existing test for exactly
> that case failed. So the module has `considered` (what a rule looks at),
> `bar` (its threshold), and `matches` (the two together), and the split is
> documented as load-bearing rather than tidy.

> **Windows go through `periods`, not a second calculation.** That module
> already converts the organization's Sunday-is-0 week setting to Python's
> Monday-is-0 and calls the mix-up "the classic off-by-one". A copy of that
> conversion is how a badge counts a different week from the leaderboard
> beside it.

> **A season badge with no season running is skipped, and does not open one.**
> Starting the economy's clock is the ledger's job; a background pass doing it
> because somebody defined a badge would be a surprising thing to find.

> **Held four times reads as one badge with ×4.** A profile listing "Closer"
> four times reads as a bug, and the count is the interesting part anyway —
> it is the difference between a good month and a habit.

> **"Almost there" only lists badges somebody has started.** A list of
> everything they could theoretically earn is a catalogue, and nobody reads a
> catalogue. The bar and "2 more this week" are the half that changes
> behaviour; the badge itself rewards what already happened.

> **A badge pays nothing by default.** It is mostly not about points — it is
> the part that survives the reset, and making it pay well would turn it back
> into a balance. When it does pay, the ledger's own latch and the badge's
> both guard it, which is right for the one write that hands out money.

> **Giving one is behind `recognition.send`, not an admin capability.** A badge
> pinned on by hand *is* recognition — the durable kind — so it belongs with
> the people allowed to recognise. A counted badge can be given by hand too:
> somebody who did the work while a connector was down should not lose it to a
> gap in the data.

> **Deleting a badge takes its awards with it**, honestly, so every row in the
> admin list shows how many people hold it and the confirmation repeats the
> number. To stop a badge being earned without erasing what people have, switch
> it to "given by hand" and stop giving it.

> **What somebody holds is scoped the ordinary way**, unlike the season table.
> A badge is about one person's history rather than about where everybody
> stands. What *can* be earned is readable by everybody, because a badge nobody
> can see the terms of is a badge nobody aims at.

**Verified:** 49 backend, 13 frontend. One migration, round-tripped.

### 4j-iv. Somewhere to spend it — done

- [x] **The wallet**: earned in every season, less what was spent — a separate
      number from the one the table ranks
- [x] **Cosmetics**: rings round your face and titles under your name, bought
      once, worn one of each at a time
- [x] Rings drawn everywhere a face is — the app, in-app boards, and all four
      wall layouts that show faces; titles on the spotlight
- [x] **Prize wheel**: points, real prizes with stock, and misses, weighted,
      with the true odds shown before anybody spins
- [x] A handover list for real prizes, for the winner's manager
- [x] Announcing a wheel win on the wall, and spinning *on* the wall — built
      in 4l-ii

> **The design turns on one question: does spending cost you your place?** If
> it does, nobody spends — which is precisely how the reference economy died,
> with lifetime points equal to reward points because nothing was ever spent.
> So there are two numbers, read from the same ledger rows:
>
>     earned   everything except wallet movements — what the table ranks,
>              and it resets with the season
>     wallet   everything — what can be spent, and it carries across seasons
>
> The wallet carries over because the reason for a season does not apply to
> it: a reset keeps the *ranking* catchable, and the wallet ranks nothing.
> Wiping somebody's savings every quarter would read as theft.

> **Winnings go to the wallet, never to the table.** If a lucky spin moved
> somebody up the rankings, spinning would become a way to climb them, and the
> table would start measuring luck and appetite for risk rather than work. Both
> spends and wins are keyed under `wallet.`, and every number that ranks
> excludes that prefix.

> **The wheel cannot print points.** A wheel whose average payout reaches the
> price of a spin lets somebody spin forever and only gain. Any change that
> would do that — a bigger segment, a cheaper spin, deleting a miss — is refused
> with the sum spelled out, and the average payout sits beside the price on the
> admin panel the whole time. Break-even is refused too: returning exactly what
> it costs means free spins forever, for the prizes. Real prizes carry no
> points value; a long lunch is not a withdrawal.

> **Selling out can tip a fair wheel over**, because a gift card leaving the
> draw raises every other segment's share. So the spin checks the payout again
> over what is actually left, and closes the wheel rather than paying out an
> unfair spin.

> **The odds are shown and the slices are drawn from them.** A wheel of equal
> slices over a hidden weighting is a slot machine — a slice that looks like an
> eighth and comes up one time in a hundred is a lie told in geometry. Rare
> odds read as "1 in 40", common ones as a percentage, because that is how
> people feel them.

> **The server draws; the browser only animates**, aimed at the answer it
> already has. A draw made in the client is one anybody with the developer
> tools open can make come out their way. The draw uses the system's own
> randomness rather than Python's default, which is predictable from enough of
> its output. Somebody who asks for reduced motion gets the answer immediately.

> **A miss says so plainly.** Dressing a loss up as "almost!" on a screen
> somebody just paid to use is what makes a wheel feel like a machine for
> taking points.

> **Every spend locks the person's row first.** Without it, a double-click
> reads the same wallet twice, both see enough, and both go through. For a
> purchase the ownership check happens *after* the lock, or the second click
> passes it, spends, and loses its copy to the unique index — points taken for
> nothing. A spin locks the segments for its length, so the last gift card
> stays the last one.

> **A bought ring is an outline outside the face, not its border.** The podium
> already borders faces gold, silver and bronze by rank; a bought gold ring
> drawn the same way would make somebody in fourth look like they came first.
> On the board layout, which draws faces only when there is a photograph, a
> ring with no face to go round is drawn on its own beside the name — otherwise
> most people who bought one would never see it on the most common screen.

> **Titles are written by an admin, never typed by the wearer.** A free-text
> title on a television in reception is a moderation job nobody signed up for.
> A ring's colour is checked twice, server and browser, because it ends up in a
> `style` attribute on a public screen.

> **Retire, don't delete, once anybody owns one.** Deleting a cosmetic somebody
> paid for takes their points back without saying so, so the server refuses
> and offers retiring instead: it stops being sold and stays on everybody who
> has it. A bought ring cannot turn into a title for the same reason.

> **A real prize with no list behind it is a promise that gets forgotten on a
> Friday afternoon.** Every real win waits on a handover list, oldest first,
> for whoever can see the winner — usually their manager.

**Verified:** 64 backend, 21 frontend. One migration, round-tripped.

### 4k. Background library — done

- [x] Bundled backgrounds, categorised — **gradients, some of them moving.**
      Bundled photographs and loop footage need licensed assets; see 4k-ii.
- [x] Upload, solid, gradient, YouTube — and **uploaded video**, the ad-free
      loop. The YouTube-ads research is recorded in 4k-i.
- [x] Dim and blur, which belong to the background rather than to the panels —
      built in 4e-iii; now applied to video and, for dim, to gradients
- [x] ~~Randomise per recurrence~~ — superseded: each item shows its own
      background, and every screen on a channel is now in step. See 4k-iii.

### 4k-i. Uploaded video, the ad-free loop — done

- [x] `background-video` upload: MP4 checked by reading its structure, kept as
      uploaded
- [x] Byte-range serving on both asset routes, session and display token
- [x] `video` as a background kind, drawn muted and looping on the wall
- [x] Colours checked everywhere they reach CSS — strict on write, lenient on
      read

> **The research: nobody should be skipping YouTube ads, and there is no sign
> Spinify does.** Their help pages cover copying a link and setting a start
> time, nothing about ads, and they also accept uploaded 10–15 second clips.
> Whether an embedded video shows ads is decided by the *uploader's*
> monetisation — the embedding site cannot opt out — and YouTube's developer
> policies forbid modifying, blocking or interfering with ads, or proxying and
> re-streaming video to get round them. Building that into a product shipped
> to customers would put every one of their embeds at risk. So YouTube stays,
> with a note under the field saying ads are the uploader's call, and the
> ad-free answer is a file served from this deployment: no ads, no internet
> needed, nobody else's channel to be taken down.

> **A video that uploads and then shows nothing is worse than a refusal**, which
> is why video waited from 4e-iii until something could check the file. Every
> property that decides whether a television can play it is checked at upload,
> where the person who can fix it is looking:
>
>     container   MP4 only; a QuickTime .mov is told to export as MP4
>     codec       H.264 or AV1 — and HEVC refused by name, with where the
>                 setting lives on an iPhone, because that is what an iPhone
>                 records by default and a Chrome-based television often
>                 cannot decode it
>     picture     there has to be a video track; an MP4 can be audio only
>     length      a minute at most — a background is a loop
>     size        20 MB, under the 25 MB nginx passes
>     complete    every top-level box checked against the real end of the file
>
> **No ffmpeg.** It is a large native dependency for one feature, and nothing
> needs to *change* the file — only to read enough of it. An MP4 is a tree of
> length-prefixed boxes, and walking it is a few dozen lines.

> **The truncation check was found by its own test.** The first version stopped
> reading as soon as it found the index, so a file cut short in the footage
> *after* the index passed — and would have played partway and stalled on the
> wall. It now walks every top-level box before looking inside any.

> **Safari will not play an MP4 from a server that ignores `Range`**, and
> Chrome needs it to loop and seek cleanly. Both asset routes now answer a
> single byte range with a 206, a range past the end with a 416, and anything
> malformed with the whole file — never a guess. It also means a file whose
> index is at the end plays without being rewritten: the browser asks for the
> end first.

> **Colours were never checked, and every one of them reaches CSS on a public
> screen.** A value like `red; background: url(//elsewhere)` would make every
> television fetch a stranger's URL — with the page address, and so the
> display token, in the Referer. Now every colour is refused on write unless
> it is `#rgb` or `#rrggbb`, and a bad value already stored is dropped to
> "inherit" on read, so an old row can make a colour fall back but can never
> take a wall down.

> **A tripwire went off on purpose.** A 4e-iii test refused `video` because a
> kind that saves and draws nothing was the failure that phase undid. It was
> rewritten rather than deleted: it now says video is allowed because the file
> is checked at upload, and its other half — an unknown kind is still refused —
> is kept.

**Known, not fixed here:** an appearance can name an asset digest that does not
exist, for a photograph as much as a video — true since 4e-iii. The editor only
ever sets one from a real upload, so it bites only somebody writing the API by
hand; checking it means touching every router that accepts an appearance.

### 4k-ii. The library — done

- [x] **Kept backgrounds**: any background can be named, shelved and chosen
      again, without uploading it twice
- [x] **Bundled backgrounds** on five shelves — calm, energy, celebration,
      seasonal — and a **brand shelf** built from the organization's own colours
- [x] Gradients with a middle stop, an angle, a radial glow, and slow motion
- [x] Swatches drawn with the wall's own CSS

> **Before this, reusing a background meant uploading it again.** Each upload
> went straight onto one screen and nothing remembered it, so the second
> channel that wanted the same photograph got a second trip through the
> uploader.

> **Choosing copies; it does not link.** A library entry is a starting point,
> the same as a bundled one — so editing or removing it changes no wall already
> using it. Nothing on a television should move because somebody tidied a
> list. And it replaces the screen's background whole rather than merging,
> or a photograph's file would sit under a gradient that never uses it.

> **What ships is gradients, and that is a limit rather than a choice.** The
> roadmap asks for bundled photographs and loop videos, and those need licensed
> footage — the same question that deferred the 4f trophies and the badge art.
> A stock image shipped without a licence is a problem for every deployment
> that displays it. The shelves are built so licensed photographs and footage
> can join them later without changing anything else.

> **The brand shelf is your colours, not ours**, built from the organization's
> primary, secondary and accent at the moment the library opens. A floor that
> set its brand in Settings finds it already waiting.

> **Motion without a video file.** A drifting gradient is the cheapest way to a
> background that feels alive, and it is *moved*, never repainted: the
> gradient sits on a layer twice the screen's size and that layer drifts with
> `transform`, which a television's graphics chip does on its own. Animating
> the gradient itself would repaint the whole screen every frame, which is what
> makes a cheap stick stutter. It stands still for any device asked for less
> motion.

> **Light bundled gradients arrive dimmed**, because the text over them is
> white — and dim is now offered for any gradient, not only for photographs. A
> bright gradient behind a leaderboard is the same problem as a bright
> photograph. Blur is not: a blurred gradient is the same gradient.

> **Every bundled background is validated when the module loads**, through the
> same model a screen uses — so a typo in the list stops the API starting
> rather than blanking a television.

**Verified:** 50 backend, 17 frontend. One migration, round-tripped.

### 4k-iii. Each item's own background, and every screen in step — done

"Randomise per recurrence" was replaced by what it was reaching for. In the
product owner's words: the Appearance tab sets the default background, every
leaderboard, goal and competition can have its own, and the screen shows the
one set on the item it is showing. Variety comes from items having their own
look, not from a dice roll. And a second thing surfaced while testing it: two
tabs of one display rotated at different moments. Every screen on a channel
should show the same thing at the same time.

- [x] **An item's background beats the channel's**; a channel background is the
      default for items that have not chosen one
- [x] **Rotation by a shared clock**: every screen works out what should be on
      from the server's time, so they change slide together
- [x] **Polling on a shared boundary**, so a changed channel reaches every
      screen at once
- [x] **Celebrations on one timetable**: every screen starts a win at the same
      instant, and a screen that joins part-way joins in step
- [x] Uploaded walk-up clips actually play on the wall (broken since 4g)
- [ ] ~~Randomise per recurrence~~ — **superseded** by per-item backgrounds

> **For the background alone, the item beats the channel.** Appearance resolves
> organization → item → channel → screen, because the room's say on names,
> privacy and legibility has to beat an item's own styling — a lobby asking for
> initials wins over a contest that did not. Applied to backgrounds too, it
> meant a channel with a background painted over every item on it, which is the
> opposite of why somebody gave a leaderboard one. A background is the item's
> identity rather than the room's, so for that one field the order is
> organization → channel → item → screen. Everything else keeps the room first,
> and a screen can still override both explicitly.

> **Screens used to count; now they read the time.** Each screen started its own
> timer when it loaded and paused it through every celebration, so two tabs were
> out of step from the first second and drifted further with every win. Now the
> position in the rotation is the time modulo the cycle — every slide's dwell
> added up — so any screen asking "what should be on right now?" gets the same
> answer, however long it has been running. A screen opened part-way through a
> slide shows it for the time that is left, not for a full dwell.

> **By the server's clock, because a television's own is routinely wrong.**
> Every feed carries the server's time, and a screen works out how far its own
> clock is from it — assuming the server read its clock halfway through the
> request, and believing the quickest recent request rather than the average,
> because a slow one can be wrong by half of however slow it was.

> **A celebration no longer holds the rotation.** That was the other half of the
> drift: each screen paused for however long its own celebration ran. The
> rotation now carries on underneath, the same everywhere, and the celebration
> starts at the same instant everywhere — so when it lets go, every screen is on
> the same slide.

> **The server keeps the celebration timetable; a screen only reads it.** Each
> win is given the moment it takes over every screen on the channel — five
> seconds after it happened, on a whole second, never before the one ahead of it
> has finished and the gap has passed — and screens poll every three seconds, so
> every one has heard about a win before it starts. The timetable is worked out
> from twice the window a win is offered for, so one win ageing out cannot shift
> the start of those queued behind it and leave two screens disagreeing. A
> replay takes its place from when somebody pressed the button.

> **That ends the old reload quirk too.** A screen used to remember what it had
> played and replay a window's worth after a reload. "What is on now" is now a
> question about the time rather than about history, so a reloaded screen joins
> whatever is playing — its clip at the same second as the others' — and plays
> nothing that has finished.

> **Somebody at the keyboard still wins.** Pausing or stepping takes that one
> screen out of step on purpose; letting go puts it back where the rest of the
> room is, not where it was left.

**Found on the way: uploaded walk-up clips never played on the wall.** A clip
uploaded in 4g reaches the screen as `asset:<digest>` of kind `audio`, and the
takeover had no branch for that kind — it fell through to the image branch,
drew a broken picture, and played no sound. The 4g tests were all server-side.
It now plays through the display's own token, and a screen that joins late
starts the clip where the others are.

**Verified:** 11 backend, 16 frontend.

### 4k-iv. The walk-up announcement — done

- [x] **A walk-up can be an uploaded music video**, checked like a background
      video and played full-screen with the announcement over it
- [x] **What the announcement is for**, first and largest: "Recognition",
      "Goal hit", "Competition won", or an achievement's own name
- [x] YouTube announcements laid out within YouTube's rules — the video as large
      as the screen allows, the words in their own band beneath it
- [x] Profile editor: full YouTube link, and a separate start-at-seconds box
      that now appears for the link being typed
- [x] **Preview** beside Save in the walk-up editor: the announcement plays
      full-screen in the editor's own browser — the office walls are not
      interrupted — and closes when the clip would end, on Escape, or on its
      button
- [ ] ~~Skip YouTube ads automatically~~ — **not built, deliberately.** See below.

> **Skipping YouTube ads is not possible from this product, and the ways round
> it are ones it should not ship.** YouTube's player runs in a frame the browser
> will not let the page reach into, so nothing here can press "Skip". What is
> left is re-serving the video from this server, or hiding or muting the player
> while an ad plays — and YouTube's developer policies forbid both, while
> re-serving a music video is also copyright infringement for the customer
> doing it. Signing the television into YouTube Premium can remove ads, but
> browsers increasingly withhold the cookie that tells YouTube so inside
> another site's page, so it is not something to promise.

> **The answer that gives people exactly what they asked for is an upload.** A
> clip served from this deployment has no adverts, and — because it is ours —
> nothing forbids the words over it. So the Spinify-style announcement (the
> music video filling the screen, the occasion and the name on top) is the
> uploaded-video layout, and the editor says so beside the choice: an uploaded
> video has no adverts, a YouTube link may.

> **YouTube's embed rules forbid anything in front of its player** — "you must
> not display overlays, frames, or other visual elements in front of any part
> of a YouTube embedded player" — so a YouTube announcement cannot be the
> full-screen-with-text look. It gets the next best thing: the video as large as
> the screen allows, and the words in a band of their own beneath it, with
> nothing positioned over the player.

> **`video:` beside `asset:`**, so what an uploaded clip is can still be read
> off the one string that says what to play. `asset:` predates it and keeps
> meaning audio, so nothing already stored changes meaning.

> **With sound, muted only if the browser insists.** Autoplay with sound works
> once somebody has clicked the wall, which setting one up does. A screen nobody
> has touched is refused sound; rather than a frozen first frame in front of the
> room, the video plays on silently.

> **The preview is the wall's own screen, not a picture of it.** The takeover's
> layouts were lifted into `AnnouncementScreen`, which both the wall and the
> editor render; the only difference is where a stored clip is fetched from —
> a display token on the wall, the signed-in route in the editor. The link is
> checked by the server with the same parser Save uses, so a link that
> previews is a link that saves, and the preview holds for exactly as long as
> the wall would.

> **Not the test button removed in 4f.** That one sent a celebration to every
> wall in the building, and its screen would not go away. This one reaches no
> wall, writes no notification, and closes itself — with its close callback
> held in a ref, because a timer keyed on a callback the editor recreates each
> render would restart every time anything behind it re-rendered.

**Found on the way:** the Link box showed an uploaded clip's internal
reference, and saving it failed with "a link has to start with http"; and the
start box followed the last *saved* clip rather than the link being typed.
Both fixed.

**Verified:** 14 backend, 10 frontend.

### 4l. Game boards — done

Last, and deliberately so: one track engine with pluggable board art and
per-person tokens, rather than the twenty-eight separate designs it looks like.

- [x] Track engine driven by percent-to-target
- [x] Race track first — more families as art allows (see "Needs art" below)
- [x] Per-person token per board family
- [x] Game boards read theme tokens like every other layout — theirs drop all
      theming, which is why their fun designs hide the background and colour
      options entirely
- [x] The prize wheel on the wall: a win spins, lands, and says what it won

### 4l-i. The race track — done

- [x] `race` as a third ranked layout, beside the list and the podium
- [x] An optional **finish line** on leaderboards and competitions
- [x] Progress worked out on the server, sent with every ranked slide
- [x] A piece per person for the race family — their face, a car, a truck or a
      bike — chosen on their profile, or by their manager

> **A layout, not a separate design.** The race reads the same ranked slide the
> list and podium read and honours everything they do — the background behind
> it, the brand colour for the trails, the wall's type, the panel style for the
> lanes. The themed boards this product was measured against drop all of that,
> which is why they hide the background and colour options entirely.

> **Position is percent-to-target, and the target is the question.** With a
> finish line, a piece sits at its share of it and reaching it is finishing —
> the lane is crowned in gold and the line is a chequered flag. Without one the
> race is measured against whoever is leading, and says so above the track;
> nobody has "finished", because there was never a line to cross, and the far
> end is a plain post rather than a flag. Lower-is-better metrics run the other
> way, so faster is further along.

> **The finish line is data on the item, not appearance.** Appearance cascades
> through channels and screens, and a channel-wide finish line laid over boards
> of different metrics would be nonsense. On a competition it stays editable
> while the contest runs, like the name and the prize: it decides where the
> flag is drawn, not who wins.

> **Worked out on the server, drawn on the wall.** Every ranked slide carries
> each entrant's progress and whether they finished, computed by
> `app/game_boards.py`, so the rule has one home and one set of tests and the
> wall only draws it. The editor's preview carries the same fields in its
> sample data rather than a second copy of the rule.

> **Eight lanes at most, whatever the row count.** Past eight, lanes are too
> thin to tell apart from three metres — the 10-foot rule, not a setting.

> **A piece per family, not per board.** A car belongs on a race track, and
> choosing one for every individual leaderboard would be a setting nobody
> finds. The default is the person's own face, which needs no choosing and is
> recognisable across a room; choosing it again stores nothing, so it stays the
> default if the default ever changes. The pieces are drawn in code, as simple
> silhouettes — read at three metres, detail is noise and shape is everything.

> **A piece wears the ring its owner bought**, and otherwise their own avatar
> colour — the economy showing up on the game board, and two cars in adjacent
> lanes still reading as two people.

### 4l-ii. The prize wheel on the wall — done

Carried over from 4j-iv, where it was recorded as a game-board question.

- [x] `wheel.won`: a real prize or a points win announced on the walls
- [x] The wheel spins on the wall and lands, then says what it won

> **Only a win is announced.** A miss never is: a wall is read by whoever walks
> past, and "Peter spun and got nothing" is the same kind of thing as "Peter is
> behind on his goal" — true, and nobody else's business. The public-events
> tripwire was updated deliberately to let `wheel.won` through.

> **Luck, not work**, so not `major`: a screen on "important only" leaves it
> out. And no walk-up music — spins can come thick and fast, and fifteen seconds
> of somebody's song for every one of them would wear a floor out. The wheel
> landing is the moment.

> **A fixed-length animation rather than a timer.** Every screen already starts
> a celebration at the same instant; an animation of fixed length lands at the
> same instant too. A screen that joins after the wheel has landed shows it
> standing still rather than spinning again on its own.

**Verified:** 26 backend, 17 frontend. One migration, round-tripped.

---

### Needs art

Every Phase 4 item that was built as far as code can take it and waits on
licensed or commissioned artwork. Each is ready to receive it without further
engineering — a key, a manifest or a drawing slot rather than a redesign.

> **Moved into Phase 6**, with the art generated in code as a baseline and
> organizations' own through a new Assets tab. See Phase 6.

- [x] **Bundled trophies and entrance animations** (4f) — done in 6.6. The
      **sound pack** is 6.17
- [x] **Badge art** (4j-iii) — done in 6.5: a drawn set of 18, and the
      organization's own pictures from Assets
- [x] **Background library art** (4k-ii) — done in 6.9 as eight drawn,
      mostly moving scenes; real photographs and footage come from Assets,
      as they cannot be generated
- [x] **More game-board families** (4l) — done in 6.8: regatta, summit and
      space race

---

### Deliberately not building

- **AI everywhere** — name suggestions, generated backgrounds, the recognition
  and coaching agents. All need an external model. Templates, random variants
  and bundled media cover the same ground offline.
- **Agent self-entered scores.** Their "Local Scores" let a player type their own
  number. That contradicts the trust principle this product is built on. The
  _admin_ manual correction and the sample-data preview are fine and exist.
- **Seats, plans, and the reward store as an upsell.** No billing, per the README.
- **Hosted-only assumptions** — font CDNs, external RSS, YouTube as the only
  media path. Every customization asset is uploadable and stored locally, with
  URLs as an optional extra.

### Still open from earlier phases

- [x] Microsoft Teams delivery — **done**, see "Microsoft Teams integration" below
- [x] Slack delivery — **done**: its own Slack card, an incoming webhook per
      channel, the same choices of what and whose as Teams, messages in
      Slack's own format with typed text escaped, and a test button. The
      Microsoft Teams switch pauses Teams channels only
- [x] Recurring competitions — **done**, see
      [09-competitions.md](09-competitions.md#repeating): every day, week or
      month as separate rounds, each with its own frozen result
- [x] Stretch goals / tiered targets — **done**, see
      [07-goals-and-targets.md](07-goals-and-targets.md#stretch-levels--built)
- [x] Derived metrics (`close_rate = won / created`) — **done**, see
      [06-metrics-engine.md](06-metrics-engine.md#derived-metrics--built)
- [x] Scheduled report delivery — **done**, see
      [10-dashboards.md](10-dashboards.md#scheduled-delivery--built)
- [x] SSO group-claim → role mapping — **done**, see
      [03-auth-and-users.md](03-auth-and-users.md)
- [x] TOTP MFA for local accounts — **done**: authenticator app, recovery
      codes, a "Require two-step sign-in" switch on Settings, admin reset. See
      [03-auth-and-users.md](03-auth-and-users.md#two-step-sign-in--built)
- [x] Custom roles — **done**: a built-in role with capabilities taken away,
      enforced by route in the one check every endpoint passes. See
      [05-roles-and-permissions.md](05-roles-and-permissions.md#custom-roles--built)
- [x] Audit log export to SIEM — **done**: CSV / JSON Lines download, and a
      stream to an HTTPS collector (JSON or Splunk HEC), in order and exactly
      once. See [17-security.md](17-security.md#audit-log-export--built)
- ~~Additional CRM connectors~~ — **removed from scope.** The connector list
      already covers what deployments use; a new one is a contained addition
      later if a customer needs it
- [x] **Team membership on the Teams tab** — see who is on a team and
      add/remove people from there — **done**, see "Microsoft Teams
      integration" below
- [x] add Teams as an option for integrations where we can have our app send announcements (can be set up in the integration's settings for what to announce and where). we can also organize users into teams and create teams based on team names within Teams. this can all be done from the settings within the integration — **done**, see "Microsoft Teams integration" below

---

## Phase 5 — Hardening & polish — **done**

**Goal:** everything the product says is true, the wall looks right on every
TV, and a new admin can get from signing in to a working wall without help.

This is the UI review and QA pass that was held back until the still-open
checklist was finished. It is written up in two reports, and every item below
cites one of them, so the repro steps and the reasoning stay there rather than
being copied here:

- [`research/qa-bug-report.md`](research/qa-bug-report.md): defects, numbered
  **QA-1** to **QA-40**
- [`research/ui-ux-review.md`](research/ui-ux-review.md): design and UX,
  cited by section (**§4**) or top-10 number (**#1**)

**Two ordering rules:**

1. **Fix what is false before what is ugly.** A rule that says "the moment"
   and takes an hour, or a team board that is always empty, costs more trust
   than any amount of spacing.
2. **Build the shared pieces before sweeping the pages.** Toasts, the confirm
   dialog, the people picker and the new names all touch every page. Built
   first, each page is visited once rather than three times.

Each sub-phase ends the way the QA pass worked: a browser check at desktop
width and at 375 px, with the console open.

### Before starting — QA test data — done

The QA pass deleted what it made through the app. These rows had no delete
option in the app, and its database cleanup rolled back, so they were still in
the database:

| Table | Rows | What it is |
|---|---|---|
| `point_award` | id 1 | "QA Badge" award to user 1 |
| `season` | id 1 | Q3 2026, opened by that award (QA-19) |
| `notification` | 96591–96594 | a test recognition and three "QA Contest has started" |
| `walkup_media` | user 401 | test clip, plus its `stored_asset` row (137) |
| `metric_fact` | 4019136, 4019137 | manual −5 and +7 corrections on metric 35 |
| `metric_definition` | id 35, `qa_closed_deals` | duplicate-name test metric (QA-9) |

- [x] Deleted in one transaction, children first, each row matched on its id
      *and* its content. Checked first that nothing else pointed at any of
      them, and against the pre-QA dump that user 401 had no clip before and
      there were no seasons or awards
- Audit-log entries for the QA actions stay. They are the record of what was
  done. Display 4 ("test") shows as recently seen because the QA pass opened
  its link, and needs nothing.

### 5a. What the product says must be true — done

The high-severity bugs, plus every place where copy promises something the
code does not do.

- [x] **Team numbers (QA-1).** Team boards, team goals, "Who is contributing"
      and team standings were empty: only 3 of $1600 facts carried a team,
      because the teams were created after the data arrived
  - [x] When a person is placed on a team, their facts with a **null**
        `subject_team_id` take it, and its office. When a team is put in an
        office, its facts with a null office take that
  - [x] A one-off migration did the same for existing data: 335 of $1600 facts
        now carry a team. The other 278 belong to people still on no team
  - [x] A test that creates facts, then the team, then adds the member through
        the People bulk action, and expects the team board to show the total
  - [x] Moving someone from team A to team B still leaves last month's team A
        board unchanged (the existing snapshot test, plus one for leaving a
        team and joining another)

> **Fill the blanks, keep the snapshot.** `aggregate.py` groups on the
> snapshot on purpose, so that last quarter's team board still gives the same
> answer after people move. The report's option (a), joining to people's
> current team, would undo that. Filling only null snapshots rewrites no
> history, because "no team" was never a team and no board ever showed those
> facts under one. Moves between teams keep their snapshot, exactly as today.
> Whether an admin should also get "count this period under current teams",
> for a mid-month reorganisation, is an open question and not part of the fix.

> **A hook on the session, not a call at each door** (`app/attribution.py`).
> A person changes team from their profile, the People bulk action, the Teams
> tab and the directory mirror, and a team changes office from its editor
> through a generic `setattr` loop. A call at each would be missed at the next
> door somebody adds, and the symptom — an empty team board — looks like
> missing data rather than a bug. It is the product's first SQLAlchemy event
> listener, registered from `app/db.py` so every session has it.

- [x] **Rules fire on ingest (QA-2).** Rule detection only ran in the hourly
      job, so a win reached the wall up to an hour late
  - [x] The four announcing passes — goals hit, rules, badges, and the Teams
        and Slack posts — are one step, `jobs.announce`, run by the hourly job
        and, as a background task, straight after a correction, a webhook, and
        a "Sync now" that wrote something
  - [x] The hourly job is still the safety net, and a failed background pass
        is logged and left to it
  - [x] Copy: "as soon as the number arrives: straight away for a webhook or a
        correction, and at the next read for a scheduled source"

> **Not "within a minute".** The review suggested that copy, but a scheduled
> source reads hourly at best — the connect page deliberately offers nothing
> shorter — so for most data the wait is the source's schedule, not the
> detection. The copy says which.

> **One pass at a time, and one waiting.** `announcements.deliver` has no
> unique index to fall back on, so two passes at once could post one card to
> Teams twice; an advisory lock serialises them. A pass announces everything
> new, so a request arriving while one is already queued has nothing to add
> and returns — a burst of webhooks cannot park a thread each on the lock.

> **Found on the way: the job's own lock could leak.** It was taken on the
> job's session, which hands its connection back to the pool at every commit;
> released on a different connection, it stayed held on the first, and later
> runs skipped with "another run holds the lock" while nothing ran. Both locks
> are now held on a connection of their own (`jobs._held`). One run on 30 Sept
> did skip that way, though a job run by hand during QA may explain it.

- [x] **Read-once sources (QA-12).** A source set to read once showed "Late —
      check the scheduler", counted as overdue on Home, and raised the
      stale-feed banner agents see too
  - [x] Its next run is cleared once it has read (it was "now plus zero
        minutes", in the past the moment it was written), and a migration
        cleared the two existing ones
  - [x] Shown as "Read once — reads again only when somebody presses Sync
        now", and "Once" rather than "Every 0 minutes"
  - [x] Left out of the overdue count and the stale banner
  - ~~Make read-once an explicit mode rather than the magic `0`~~ — not done.
    It is already a named constant on both sides, and the visible symptoms
    are fixed; a schema change would buy nothing a person can see

- [x] **Dates in the organization's timezone (QA-14).**
  - [x] Competition announcements say the organization's day, and a contest
        ending at local midnight names the day before (`periods.last_day`)
  - [x] Every other server-formatted date checked: the Reporting history's
        "ended on" and the repeat "until" check had the same fault and are
        fixed; period labels and report digests were already local
  - [x] The competition form's Starts and Ends are the organization's clock,
        not the browser's, and say so ("Times are Eastern Time, the
        organization's timezone"), and the defaults are 9am and 5pm there
  - [x] **Found later, by the calendar.** The suite run at 00:15 UTC on
        1 October failed 16 tests, and two of the causes were product bugs:
        a goal created with no period, and the goal-history preview, used the
        server's UTC date — so every evening in the Americas around a month's
        end, "this month" meant next month. Both use `periods.today(org)` now.
        The rest were tests choosing "now" by UTC; they read the test
        organization's clock through `org_today()` / `org_now()` in
        `conftest.py`, and the whole suite passes inside that window

> **The timezone comes from the organization cache that already existed**,
> which now holds the whole organization rather than its appearance. Sign-in
> reads the same cache, so the organization is fetched once per page load
> instead of twice — **QA-28, fixed on the way**.

- [x] **Revoke means now (QA-15).** A 404 from either feed disconnects the
      screen. The celebrations feed asks every three seconds, so a revoked TV
      now stops within seconds rather than at the next minute's channel poll
- [x] **The wrong network is said, not hidden.** A 403 (the channel's IP
      allowlist) used to leave the last board on screen marked stale. It now
      takes the board off, shows the server's reason, and keeps asking, so
      the screen recovers when the network is allowed
- [x] **Team moves are visible (QA-8).** Adding somebody who is on another
      team asks "Clark Kent is on SMB. Move them to Phoenix?" first. Somebody
      on no team is added straight away
- [x] **Two-step "required" (QA-32).** Working as designed: the hint already
      said Microsoft sign-ins are exempt, and the QA admin signs in with
      Microsoft. What was missing is now under the switch — who signs in with
      a password and has not set it up, from an admin-only
      `GET /api/auth/mfa/unenrolled`
- [x] **Buttons the copy mentions (QA-30).** The button existed on each saved
      schedule. The line in the new-schedule form, where there is nothing to
      press yet, now says it appears once saved
- [x] **Closed Deals values (QA-39) — decided: data, not code.** The Excel
      source feeds the *count* metric "Closed Deals" from its `amount` column,
      so each deal adds its dollar value. The code read exactly what the
      mapping asked for; setting up mappings and metrics is the
      organization's job. What the product owes is noticing, and since 5h the
      Metrics page says "these look like amounts, not a count" under such a
      metric

**Verified:** 3,233 backend and 914 frontend tests, type check clean. Two
migrations, round-tripped. Not yet looked at in a browser — that is the first
job of the next session of work on this phase.

### 5b. The wall fits every TV — done

The wall is the product's face, and it depended on the TV's resolution.

- [x] **One stage (QA-3, #3).** `WallStage` lays every screen out at
      1920×1080 and scales the whole thing to the television, letterboxed.
      The live display and the editor's preview both draw inside it, so they
      cannot drift apart. A takeover's `position: fixed` is placed against the
      stage (the transform makes it the containing block), so celebrations
      scale with everything else
  - [x] Measured by `ResizeObserver`, with the window's resize event for a
        television whose browser has none
  - [x] `vh` sizes inside the stage replaced — the viewport's height means
        nothing on a fixed stage
- [x] **Rows that do not fit are paged, not cut off.** A list board, and the
      rows under a podium, show as many as fit and turn the page partway
      through the slide, with page dots. Measured rather than calculated: the
      list starts with every row and loses one at a time, before paint, until
      the slide's body stops overflowing
  - [x] Turned by the shared clock, so every screen on a channel is on the
        same page; held while somebody at the screen has it paused; the
        preview shows page one
  - [x] Shared out evenly — ten rows where seven fit are two pages of five,
        never a page of one — and a short page keeps the full page's height,
        so rows do not jump
- [x] **Readability over a picture (#8, §8).**
  - [x] A shade behind the header strip whenever the background is a
        photograph or video, and a text shadow on the header's words. The
        subtitle and the channel's name were invisible grey on yellow
  - ~~Photo backgrounds darkened to 0.55 by default~~ — not done. The base
        dim applies to every kind, colours and gradients included, and an
        inherited 0.35 cannot be told apart from a chosen one, so raising it
        would override choices. The shade darkens only where the words are
  - [x] ~~A contrast check against the sampled background colour~~ —
        **decided: not needed.** The shade covers the case the review saw
- [x] **Headlines (QA-16).** A title wraps to two lines and steps down two
      sizes before it is ever cut; a message's body steps down until it fits
      the slide. The editor shows "84/120 — a long one is drawn smaller, over
      two lines, to fit"
- [x] **Title tails.** `truncate` at a line height of 1 cut the tails off g, p
      and y in every title; found in the 1080p screenshot
- [x] **Goal gauge (QA-18).** At 0% only the track is drawn — a zero-length
      dash with round caps painted a dot at each end
- [x] **Whose goal (§8).** An unnamed goal is headed "Clark — Sales Feed
      Amount Today" with the period underneath, rather than the metric's name
      over the person's in the smallest type. A named goal keeps its name
- [x] **Units (§8): "48,210 deals".** Built at the close of Phase 5. A metric
      has an optional "Counts of" label (`metric_definition.unit_label`, the
      plural), shown after a count the way "$" goes before money: on walls,
      boards, goals, Home, reports, the digest email and an announcement's
      `{value}`. One deal reads "1 deal" ("replies" → "reply", "glasses" →
      "glass"; an acronym like "NPS" is left alone). A pair says it once:
      "12 of 40 deals". Empty means a bare number, as before. The rule is in
      `app/units.py` and `MetricValue.tsx`, which must agree, and is carried
      by every response that already carried the metric's unit
- [x] **Channel editor.** Competition slides are listed by the contest's name
      (QA-11). The drag handle already had a name and arrow-key reordering;
      its glyph is now hidden from screen readers (QA-23)
- [x] **Revoked TVs can be removed from the list (QA-17)**; the link stays
      dead either way
- [x] **Checked at 1280×720, 1920×1080, 3840×2160 and 1080×1920.** Leaderboard
      (podium and list, both pages) and goal slides, on the dev deployment's
      "test" television. Portrait letterboxes, as expected until portrait
      layouts are designed (see "Later")

> **How the sizes get checked.** The test suite runs in jsdom, which does no
> layout, so it cannot see a row fall off the screen. The paging logic has
> render tests with a faked body height, and the four sizes were checked in a
> real browser: headless Chrome driven over the DevTools protocol, with the
> viewport emulated exactly as a television's browser has it. (Chrome's own
> `--screenshot` flag lays the page out 96 px short and then captures at full
> size, which looks exactly like a letterbox bug — it is not one.) Playwright
> only if the wall regresses again.

**Verified:** 3,237 backend and 927 frontend tests, type check clean; the
screenshots above.

### 5c. Who takes part — done

Directory sync brought in bots, printers and shared mailboxes ("MFP 3100", "No
Reply", "dummy account 2"). They sit in every picker and inflate every warning
("300 people have recorded nothing"), so every count in the app is wrong until
they are hidden (#2). It comes before the people picker because the picker
depends on it.

- [x] **Spot likely non-people** (`app/directory/non_people.py`). Two tests,
      both required. *Nothing marks it as a person*: no job title,
      department, team, recorded numbers, sign-in or photo, no goal of its
      own, and still the default role. *Its name is shaped like a thing*: a
      digit, a service word ("desk", "admin", "scans"), a no-reply or
      "former_" address, or a single word. On the dev data: 26 suggested, all
      of them devices, mailboxes or test accounts; none of the 21 real people
      who also have no title
- [x] **A review card** on People, for admins: "26 accounts look like a
      device or a shared mailbox · Review · Hide all 26". Review lists each
      with its reason, ticked, to untick any to keep. Hiding goes through the
      People page's audited bulk action and is undone from the Hidden tab.
      *Nothing has been hidden on the dev data — that is the admin's call.*
      The setup-checklist step is 5g
- [x] **Hidden means gone everywhere** — checked rather than built: the user
      list every picker reads, the "recorded nothing" and "on no team" counts
      and the health figures already leave hidden people out. They were
      inflated only because nothing had suggested hiding the bots
- [x] **Nothing yet is not a place.** Home's "Where you stand" skips a board
      where the viewer is at zero on a higher-is-better metric, as it already
      skipped boards they were not on. That is what put the admin at "39th of
      137 · $0.00": a source writes a zero row for everybody it lists
- [x] **Not ranked by role (§3) — decided: no rule by role.** An admin on a
      team whose work is in the data is ranked like anybody else; one who
      does not sell has no data, and since the fix above, no data means no
      place. What decides it is the data, not the role, so there is no
      setting
- [x] **"No team" and "No office" in muted grey**, not warning orange (§5)

> Hidden people's numbers still count toward their team's total, by design
> (see the comment in `aggregate.py`). Hiding a printer changes no totals,
> because a printer has no facts.

**Verified:** 16 backend tests for the detector and endpoint, 3 render tests
for the card, and the card checked in the running app as the dev admin.

### 5d. Shared pieces: feedback, forms and dialogs — done, two items moved to 5h

Built once here, then used by 5e to 5i.

- [x] **Toasts** (`toast.ts`, drawn by `<Toasts />` in the shell): one line
      for five seconds, with an optional link, read out politely. After every
      save on boards, goals, competitions, rules, channels, slides, TV links,
      metrics, corrections, recognition and badges. A store rather than a
      provider, so a helper can call it and a form tested alone does not
      break. Deletes get theirs in the 5h page sweep
- [x] **Form status (QA-4)**: recognise, metric and correction forms clear
      their error when a submit starts, and the page clears it on success
- [x] **Skeletons**: `<Loading />` — ragged pulsing bars, still "Loading…" to
      a screen reader — in 38 places. The full-screen sign-in wait keeps its
      word
- [x] **One styled confirm dialog** (`ask()`, drawn by `<ConfirmHost />`):
      all 34 native `confirm()` calls, each keeping its sentence. The yes
      button is named for the action ("Delete", "Revoke") and drawn as a
      danger where it is one; focus starts on Cancel; Escape answers no.
      Without a host it falls back to the browser's box, so the tests that
      stub it are unchanged
  - [x] Escape, the backdrop or × on a typed-into form ask "Discard what you
        have typed?" (QA-24) — noticed from the typing, so no form reports
        whether it is dirty. A form's own Cancel still closes at once
  - [x] Focus returns to the opening button. `Modal`'s effect depended on
        `onClose`, which parents pass as a new arrow each render, so it
        re-remembered something inside the dialog as the "opener"
- [x] **Row-action names drawn above the button, outside the table (QA-25)**.
      They sat to the left, across the neighbouring buttons, and a scrolling
      table clipped them. Checked in the running app
  - ~~A ⋯ menu for every row's actions~~ — not done: with the names no longer
    overlapping, two or three icons per row read fine. Revisit per page in 5h
- [x] **Data stays fresh after a change**: badge holders after "Give"
      (QA-10), the bell after a recognition or badge (QA-35, a no-op outside
      the shell), and the organization fetched once (QA-28, in 5a)
- [x] **Names trimmed and required (QA-5)** with one `Name(n)` type on 26
      name fields; a goal's optional name of spaces becomes no name. The
      Microsoft Teams link keeps its blank-means-default
- [x] **Unique names** for offices and metrics in use, ignoring case (QA-7,
      QA-9): a unique index each (the migration names every clash and stops
      rather than choosing), a plain 409 before it on create, rename and
      restore, and default seeding skips a name already taken
- [x] **Refusals said in words (QA-13)**: one 422 handler rewrites every
      message — "Name can't be empty.", "Row count has to be at least 1." —
      and drops "Value error," from a validator's own sentence. Same shape as
      before, so the client is unchanged
- [x] **Number fields say what they take (QA-6)**: a refused keystroke shows
      "A number, 0 or more." instead of vanishing. The board's row count is a
      3–20 slider and cannot hold a bad value
- [x] **Disabled buttons say why** — on the goal form, the review's example:
      "Choose a metric to continue." About 30 other disabled buttons follow
      the same shape and are in the 5h sweep
- [x] **One relative-time helper (QA-36)**: `time.ts`, rounding down, used by
      the four places that each had their own
- [x] **A sticky save bar** — moved to 5h, and done there on Settings (user
      detail kept its per-section saves; see 5h)

**Verified:** 3,267 backend and 939 frontend tests, type check clean; the
tooltips checked in the running app.

### 5e. People picker — done

The review's largest usability problem (#1): goal, recognition, badge and
correction pickers were native dropdowns of 461 names, and competition
entrants were 461 checkboxes.

- [x] **One component**, `PeoplePicker`: type a name, an address or a team;
      each result has its face, and its team and address underneath; one
      person, or several as chips with × and "Clear all"
  - [x] "Add everyone on Metropolis (90)" and "Add all 12 matching “peter”"
  - [x] Hidden people are never offered: every list it is given is the
        default roster (5c)
  - [x] Two people with one name are two rows — checked on the dev data's
        two Peter Parkers, told apart by address
  - [x] Ranked: a name that starts with what was typed first, every typed
        word has to match somewhere ("peter gotham"), accents ignored; eight
        offered, and "N more — keep typing"
- [x] Built like `Combobox`: a real input and a list, arrows, Enter, Escape
      (which closes the list without closing the dialog around it),
      Backspace to drop the last chip, and no new dependency
- [x] **Replaces**: goal subject, recognition, give badge, correction person
      *and* the corrections list's person filter, spotlight slide,
      competition entrants, and matching an unknown identifier on a data
      source. Adding a team member was already a type-ahead (QA-8, 5a)
- [x] **Nobody is assumed.** The goal and correction forms used to preselect
      whoever sorted first, so a hurried save could land on the wrong person
- [x] **Recognising yourself (QA-34)**: still allowed, and the dialog now
      says "You won't earn points for recognising yourself". A person or a
      team is now an explicit choice, then the right picker for each

**Verified:** 9 render tests, all 948 web tests, and the goal form checked
in the running app.

### 5f. Navigation and names — done, the Points split moved to 5h

"Achievements", "Announcements" and "Achievement rules" were three names for
two things. "Screen" meant both a slide and a TV. The nav was 21 flat items
(§4).

- [x] **Grouped nav**: everyone's pages first (Home, Leaderboards, Goals,
      Competitions, Recognition, Points, Reporting), then **Wall** (TVs &
      Channels, Celebrations, Appearance), **People** (Users, Teams,
      Offices), **Data** (Integrations, Metrics, Corrections) and
      **Organization** (Settings). Each item keeps its capability; a group
      with nothing its reader can open is not shown. One definition draws
      both the sidebar and the phone drawer
  - Pages are regrouped, not merged: People and Data are headings over the
    existing pages rather than new hub pages. "Leaderboards" keeps its name —
    it was never one of the confusing ones
- [x] **One word per thing.** Achievements is **Recognition** (`/recognition`)
      and Announcements is **Celebrations** (`/celebrations`); the old
      addresses redirect, for bookmarks and old notification links. On the
      channel pages a **slide** is an item in a channel and a **TV** is a
      paired display — "Connect a TV", "Reload TV", "Add slide", "2 slides ·
      1 TV" — and the pairing screen says "TVs & Channels → Connect a TV". The
      Microsoft Teams "Announcements" tab keeps its name: it is a different
      thing, posting to Teams
- [x] **Page titles** per route, "Goals · GoalGetter" (QA-27), from
      `PageHeader`, which every page in the shell has
- [x] **A "Page not found" page** inside the shell (QA-26). Signed out, an
      unknown address still goes to sign-in first
- [x] **Breadcrumbs** on goal, user, channel, leaderboard and competition
      pages — "Goals › Clark — Closed Deals" — replacing "← Goals" and the
      like
- [x] **Internals hidden (#10)**: "Following the default — full" names the
      option ("— Peter Parker"); "not built yet" reads "coming soon"; a
      source still named by its connector's key shows the provider's name.
      Metric keys and the client GUID remain on their pages — in 5h
- [x] **Screen-reader names**: the header avatar link is "Your account"
      (QA-23), and the balance reads "10 points, 1st place" (QA-22)
- [x] **The §11 wording table**: "Always live — updates as the numbers
      arrive", "Needs 25,000 a day for 1 working day (0 a day so far)", "96%
      behind pace" (Home and the digest email), plus the rows already done in
      5a–5d
- [x] **Points split** into the player's page and Points setup — moved to 5h,
      and done there

**Verified:** 950 web tests, type check clean; the nav, the old-address
redirect and the 404 page checked in the running app.

### 5g. Setup checklist and Home — done, templates moved to "Later"

A new admin landed on "300 people have recorded nothing" with no path forward
(§3).

- [x] **Setup checklist** for admins (#4): connect data → hide accounts that
      are not people → put people on teams → make a leaderboard → build a
      channel → connect a TV. Each step is a question about the data
      (`app/setup_steps.py`), so it cannot claim done early and ticks itself
      when the work is done anywhere in the app; each links to its page, the
      next one is marked, and the card is gone once all six are done. On the
      dev data: five done, "26 accounts look like a device or a mailbox" next
  - A TV counts once it has actually connected, not when its link is made
- [x] **Until setup is complete, the checklist replaces the orange banners**
      — "350 on no team" on a deployment still making its teams is a step,
      not an alarm. Once it is complete the banners return, each already a
      link to its page
  - [x] Each banner opening its list *already filtered* ("350 on no team" →
        People, no team) — done in 5h, with the People filters
- [x] **Standings debug card off Home (QA-40)**, and deleted: by its own
      description it existed to check the numbers against the database
- [x] **Home copy**: "96% behind pace" (5f); nothing yet is not a place (5c),
      which is what drew a flat line at zero; each Needs attention goal links
      to its page
- [x] **Empty states with their action, and starter templates** for rules,
      competitions and channels — moved to "Later": templates are new
      features rather than fixes, and want designing with their editors in 5j.
      Done in 6.4

**Verified:** 3,272 backend tests — run at 00:19 UTC on 1 October, inside the
window that broke 16 of them before — and 953 frontend tests, type check
clean; Home checked in the running app as the dev admin.

### 5h. Page by page — done

Everything else in §7, one page at a time, built from the 5d to 5f pieces.

- [x] **The theme's missing tokens.** `text-h1` and the rest of the type
      scale, `text-content-subtle` (245 uses), `bg-surface-hover` (147) and
      `bg-brand-subtle` (14) were used everywhere and defined nowhere, so no
      page had a visible heading, every hint and caption was full-strength
      text, nothing lit up on hover and the current nav item had no tint. All
      are now in `theme.css`, in dark and both light blocks. The subtle text
      is a touch lighter than 12-design-system.md's #6B7484, which is 3.8:1 on
      a card, under AA for 12 px text. A sweep of every colour and text
      utility found no other undefined names
- [x] **Points split** (from 5f): Points is the player's page (this season,
      spend), and Points setup (`/points/setup`, under Organization) has
      seasons, tiers, values, the wheel and cosmetics
- [x] **Metric keys and the client GUID** (from 5f): the Metrics key column is
      gone (the key stays on the edit form), and the tenant and application
      IDs sit behind "Details"
- [x] **Carried from 5d**: a toast after every delete, archive and restore;
      a "Needs: …" line under each disabled create button saying what is
      missing (`MissingHint`); and a sticky save bar on Settings that shows
      only when something has changed, with Discard
  - Skipped: one save bar on user detail. Its sections save independently
    (profile, role, walk-up, game pieces), and one bar over them would hide
    which change it saves
  - Not needed: ⋯ menus. No row has more than three actions
- [x] **Held over from Phase 4**: the per-item appearance editors laid
      out by the window's width, so in a 28 rem modal on a wide screen the
      fields were a sliver beside the preview ("Di", "Pe"). Now they use a
      container query: stacked in a modal, side by side only where there is
      room. The Microsoft Teams, Email and directory panels were checked in
      the browser, with nothing to fix
- [x] **Leaderboards**:
  - [x] The detail page shows the board as a wall shows it, in its own
        layout and appearance (`GET /leaderboards/{id}/slide`), with Edit and
        "Show on a TV" (QA-37)
  - [x] "Always live — updates as the numbers arrive" (5f)
  - Already there: silver and bronze for 2nd and 3rd, and ◀ ▶ period stepping
  - [x] The form's "Show on wall displays" switch was removed: nothing read
        `is_tv_enabled`. It is replaced by a pointer to TVs & Channels, which
        is where a board gets onto a wall
- [x] **Goals**:
  - [x] One status chip per card (QA-20)
  - [x] Card title is who, then what ("Steve Rogers — Closed Deals")
  - [x] Filters: search (name, person or team), metric, period, status
  - [x] "31 days left · needs 140,000 more" / "Last day" / "Period over"
  - [x] Edit and Archive on the detail page
  - Skipped: stretch levels as ticks on one bar. The levels are listed under
    the bar, and ticks past 100% would need a bar that runs past the target
- [x] **Competitions**:
  - [x] Nobody leads while nobody has scored, and the card says "No scores
        yet" (QA-21)
  - [x] After publishing, go to the tab the contest is actually on (QA-13)
  - [x] The title once on the detail page: the report card is "How it is
        going"
- [x] **Recognition**: Who and What filters on the feed. "Play on wall"
      already asked which channel or TV
- [x] **Points**: when a quarter has fewer than 14 days left, the first
      season runs to the end of the next quarter instead of opening for a few
      days (QA-19). It is decided automatically rather than asked: nobody
      giving a badge should have to think about seasons
- Skipped — **Teams and offices** detail pages. A row already opens its
  members in place, and goals, boards and channels have their own filtered
  pages. The office select on a team now looks editable
- [x] **Channels and TVs**: "Connect a TV" already had "Pair with a code" and
      "Copy a link"; the duplicate "Show on wall displays" switch is gone (see
      Leaderboards)
- [x] **Users**:
  - [x] 50 at a time with Show more / Show all; Team and Role filters (Status
        is the Active / Hidden / Deactivated tabs). Bulk Hide, Set team and
        Set role were already there
  - [x] Home's "on no team" banner opens Users already filtered to agents on
        no team (`/users?team=none&role=agent`, the 5g leftover)
  - [x] Detail in two columns on a wide screen
  - [x] Walk-up clips (QA-31): `t=` / `start=` from a YouTube link fills
        "Start at"; a stored clip has ▶ Play and Remove; the preview hides the
        player's controls, captions and keyboard
- [x] **Metrics**:
  - [x] "From Microsoft Excel" under each name, by the source's own name, and
        the "Created from …" description it repeated is no longer shown
  - [x] The key column removed (on the edit form only)
  - [x] A hint when a count metric's values look like amounts (QA-39:
        average over 500)
  - Already there: the display name is the metric's name, separate from the
    key the feed uses
- [x] **Corrections**:
  - [x] From / To dates, and 100 at a time with "Load more"
  - [x] Each row says where it came from: synced, imported or entered by
        hand
  - [x] Editing a synced row warns that the change is kept, as a correction on
        top of the source
- [x] **Integrations**:
  - Already there: sources named after their file or sheet, and provider logos
  - [x] The tenant GUID replaced by "Your organization's tenant", and the IDs
        behind "Details"
- [x] **Settings**:
  - [x] Tabs: General, Branding, What people can set, Sign-in & security,
        Roles, Activity & export
  - [x] A warning when the logo looks like a portrait photo (narrower than
        1.2 : 1)
  - [x] A note when you are in a different timezone from the organization
- [x] **Account**: an SSO-only account has no "Change password" or two-step
      setup (`has_password` on `/auth/me`), and says why (QA-33). Competition
      started, finished and won are in notification preferences (QA-38)
- [x] **Reset password**: the link is checked on load
      (`POST /auth/reset-password/check`), and a used or expired one says so
      straight away (QA-29)

**Verified:** 3,272 backend tests plus the new ones in each suite touched; 960
web tests, type check clean. Board detail, Settings, Users, Metrics, the goal
form with its appearance open, and Integrations with the Microsoft 365 panel
were each checked in the running app.

### 5i. Phone — done

- [x] **Tables become stacked cards below 640 px** (Users, Corrections,
      Metrics): the name across the top, every other column in two columns
      under its label, and the row's buttons beside the last value. One CSS
      pattern, `table.gg-stack` with `data-primary`, `data-label` and
      `data-actions` on the cells, so another table opts in with attributes
      only. They used to scroll sideways, with the column that mattered off
      screen
- [x] **Every modal is a full-screen sheet on a phone**, with the title and ×
      pinned at the top and the form's action row pinned at the bottom. The
      action row is found rather than marked: nearly every form in a modal
      ends in its buttons, and `:has(button[type=submit])` leaves alone the
      few that do not. The competition form's Publish is now always on
      screen
- [x] **Filters fold behind "Filters (n)"** on Users, Goals and Corrections
      (`FilterFold`). Search, or the person picker on Corrections, stays on
      show. From 640 px up nothing changes: the wrapper is `display:
      contents`. Recognition has one dropdown besides its search, so it has
      nothing to fold
- [x] **The stale-feed warning goes to whoever can fix it.** Everyone still
      sees "Data as of 3 days ago", so a stale board is never passed off as
      current. The warning colour, the reason ("a feed behind these numbers is
      failing") and the link are for `integrations.manage` only. Agents could
      not act on them

**Verified:** 962 web tests (two new, for the warning), type check clean;
Users, Metrics, Corrections, the open filters and the competition form
checked at 390 × 844, and Users checked again at desktop width.

### 5j. Preview before it reaches a TV — done

The Appearance page proved the pattern (#7). The other editors that change a
wall showed a thumbnail, or nothing.

- [x] **A large 16:9 preview beside the board, goal, competition and slide
      editors.** From 1024 px up these dialogs open wide, with the form on
      the left and the wall on the right, held in view while the form
      scrolls (`Modal`'s `side`, `EditorPreview`). It follows every unsaved
      change. Narrower screens keep the preview inside "Give this its own
      appearance", as before
  - Board, goal and competition: sample numbers under the item's own name
    (or its metric's), in its own layout and look, and said to be samples
  - **Slides: real numbers.** `POST /channels/{id}/screens/preview` adds the
    unsaved slide inside a savepoint, puts it through every check saving
    makes and through the wall's own renderer (`channels.slide_for`, now
    shared with `build`), then rolls it all back. So the preview is the slide
    as this channel's TVs would draw it now, and a slide that would be refused
    says why. Until the form names what it shows, the panel says what to
    choose
- [x] **Rules: "Check last week" and "▶ Play celebration".**
      `POST /achievement-rules/preview` builds the unsaved rule through the
      same validation and the same matching (`achievements.matches`) as a
      real one, as if it had been made a week ago. It returns how many pieces
      of work would have fired it, for how many people, and the announcement
      the wall would have shown for the most recent. The form says "Would have
      fired 12 times in the last 7 days, for 5 people", and calls it noisy past
      three a day — the threshold hint's own "wallpaper". Play shows that
      announcement full-screen with its sound, the way the walk-up preview
      does (now one shared `CelebrationPreview`). Nothing is saved, announced
      or paid
- [x] **"Preview on a TV"** in the slide and rule editors: choose a TV and
      what is on the form plays there once, marked "Preview", for a slide's
      30 seconds or a celebration's length, then the screen goes back to its
      rotation (`app/display_previews.py`, table `display_preview`). One
      screen, not a channel. It rides the three-second celebrations poll, so
      it arrives while you are looking, and it is stored already built, by
      the same code as the editor's preview. Audited as `display.previewed`.
      Tried on the paired dev TV with a message slide and a rule's celebration
- Not done: sending the board, goal and competition editors' previews to a
  TV. An unsaved board has no standings, and a TV showing sample names would
  be the one place a preview could be mistaken for real
- [x] Fixed on the way: the takeover drew a previewed slide outside the
      stage's frame; it now uses the stage's own padding and centring

**Verified:** 3,298 backend tests (16 new here: the rule check, the slide preview,
and sending to a TV), 968 web tests, type check clean, `alembic check` clean
and the migration run down and up. Every editor checked in the running app at
desktop width, and both kinds of preview checked on the paired TV.

### Phase 5 closed — 2026-10-01

Every QA-1 to QA-40 item and every §-cited review item is either built,
decided, or moved to "Later" with its reason. The four that needed a decision
were settled at the close: QA-39 is data, not code; unit labels were built;
the contrast check is not needed; and nobody is ranked or left off by role.

What is left is not Phase 5: **"Needs art"** above (trophies and animations,
badge art, bundled photographs and loops, more game-board families), and
**"Later"** below.

**Verified at the close:** 3,308 backend tests (10 new in `test_units.py`),
972 web tests (4 new for the formatter), type check clean, `alembic check`
clean.

### Later — ideas from the review, not in Phase 5

Worth building, but new features rather than fixes (§12). Each is a
candidate for the phase after this one.

> **All of these are now Phase 6**, in the order set out there.

- **Starter templates** (from 5g) wherever a blank form appears — rules
  ("Big deal over $X", "First sale of the day"), competitions ("Friday
  sprint", "Month-end push", "Team vs team"), channels ("Sales floor",
  "Lobby — top 3 only") — and empty states that offer them
- **Bulk goals**: one target for a team or office, with per-person overrides
  in a grid
- **Rotation scheduling**: per-slide days, hours and weight, plus a night or
  idle mode per channel
- **Team identity**: logo, colour and short name for team boards and
  head-to-head
- **Manager home**: their team's board, who needs a nudge, quick recognise
- **Command palette** (Ctrl+K) to jump to any person, board or goal
- **Admin activity inbox**: failed syncs, new directory people to place,
  revoked TVs still polling, seasons ending
- **Portrait layouts** of the list and podium
- **A disconnected TV shows a fresh pairing code**, so it can be re-paired
  without anyone touching it
- **Competitions editable while running**: prize, extended end, late
  entrants, with an audit note
- **Reactions and comments** on the recognition feed
- ~~**Uploaded badge art**~~ — done in 6.5, from Assets

## Phase 6 — Art, assets and the wall's next features — **done**

**Goal:** the product ships with its own art, an organization can bring its
own through one place, and the wall and the people pages get the features
the review asked for (§12).

**The art is generated, in code, as the baseline.** Badges, trophies, entrance
animations, game pieces and backgrounds are drawn as original SVG, CSS and
canvas work, so nothing needs a licence and everything themes with the
organization's colours. An organization's own images, video and sound come in
through **Organization → Assets**. Photographs and real footage cannot be
generated; the library's photo shelves fill from uploads. Sounds come last.

**Order**, and why:

1. **TV re-pairing.** A disconnected TV shows a fresh pairing code, so it can
   be re-paired without anyone touching it. The last reliability gap on the
   wall
2. **Admin activity inbox.** Failed syncs, new directory people to place,
   revoked TVs still polling, seasons ending, in one place
3. **Organization → Assets.** Upload, browse, preview and delete images,
   video and sound, and see where each is used. The existing uploads
   (backgrounds, logos, walk-up clips) appear there. Everything after this
   draws from it
4. **Starter templates and their empty states** for rules, competitions and
   channels, each previewed before it is used (5j)
5. **Badge art.** A generated SVG set replaces the placeholder marks; an admin
   can pick an upload from Assets instead
6. **Celebration visuals.** Generated trophies and entrance animations,
   previewable on a TV
7. **Team identity.** Logo, colour and short name per team, for team boards
   and head-to-head
8. **More game-board families.** Generated pieces and boards, in team colours
9. **Background library.** Generated illustrated and abstract backgrounds and
   animated loops; photos and footage from Assets
10. **Rotation scheduling.** Per-slide days, hours and weight, and a night or
    idle mode per channel
11. **Portrait layouts** of the list and podium
12. **Bulk goals.** One target for a team or office, with per-person
    overrides in a grid
13. **Manager home.** Their team's board, who needs a nudge, quick recognise
14. **Competitions editable while running.** Prize, extended end, late
    entrants, each with an audit note
15. **Reactions and comments** on the recognition feed
16. **Command palette** (Ctrl+K) to any person, board or goal
17. **Sounds.** A generated starter pack, and sound pickers on rules and
    celebrations using the pack or Assets

Each step ends as Phase 5's did: tests, a check at desktop and phone width,
and on the paired TV wherever it touches the wall.

### 6.1 TV re-pairing — done

- [x] **A disconnected TV shows a fresh pairing code.** A screen whose link is
      refused — revoked, or removed from the list — used to say "Display
      disconnected. Ask an administrator for a new display link", which meant
      a ladder and a keyboard. It now shows a code ("This screen was
      disconnected. To connect it again"); an admin enters it under Connect a
      TV, and the screen loads its new link by itself, as a full reload so it
      starts clean on the newest build. Codes renew themselves as on `/pair`
- [x] One pairing component (`PairingCode`) for a new screen and a
      disconnected one, so the two cannot drift
- [x] The revoke confirmation says what now happens ("the television shows a
      pairing code instead"), rather than that it "cannot be restored"
- A wrong-network refusal (403) is unchanged: the link is valid, the place is
  not, and it keeps asking

**Verified:** 974 web tests (pairing, and the TV's refusal tests updated),
type check clean. End to end on a throwaway TV in the running app: playing →
revoked → code on screen within seconds → claimed → the same screen playing
its channel on the new link. Both throwaway displays were deleted afterwards.

### 6.2 Admin activity inbox — done

- [x] **Organization → Inbox**, with a count beside it in the nav. What needs
      an admin right now, problems first:
  - **A failing source**, in its own words ("The password has expired"), and
    **one that has stopped reading** (a failing one is not listed twice)
  - **A disconnected TV showing a pairing code**, with **Reconnect**
  - **A TV that has stopped checking in**, or whose link was never opened
  - **People from the directory waiting to be placed**
  - **A season ending within a week**, and what follows it
- [x] **Worked out, not stored** (`app/inbox.py`), like the setup checklist:
      every item is a question about the data asked when the inbox opens, so
      fixing the thing is how it leaves and there is nothing to mark as read.
      The source and TV checks are the ones Home's health card uses, so the
      two cannot disagree
- [x] **"Revoked TVs still polling", answered by 6.1.** A disconnected screen
      now asks for a pairing code and says which link it had
      (`display_pairing.previous_display_id`, only ever a revoked display), so
      the inbox names it, and **Reconnect** claims that code for a new display
      with the old one's name and channel and removes the revoked row
      (`POST /displays/{id}/reconnect`, audited). Nobody reads four
      characters off the screen
- Admin only: every item is a fix only an admin can make

**Verified:** 3,320 backend tests (12 new in `test_inbox.py`), 977 web tests,
type check clean, `alembic check` clean. End to end on a throwaway TV: revoked
→ pairing code on screen → in the inbox by name → Reconnect → the screen
playing its channel on the new link.

### 6.3 Organization → Assets — done

- [x] **Organization → Assets** (`/library`): every picture, video and sound
      the organization holds, on All / Images / Video / Sound shelves, each
      previewed (pictures on a checkerboard so transparency shows, video and
      sound playable in place), named, sized, and saying **where it is used**
      with a link there
- [x] **Add files**: several at once, each sent as itself with its name.
      What a file is comes from its bytes, not its name or the browser's
      claim; the claimed kind only decides which check runs first
  - A picture **with transparency is kept as art** (PNG inside 1024 px);
    anything else is **fitted to a TV** (JPEG inside 1920 × 1080), as a
    background is. Nothing is cropped
  - Video: MP4 up to 20 MB and a minute, checked as a background video is.
    Sound: up to 15 seconds, stripped of tags as a walk-up is
- [x] **Rename in place**; `stored_asset.name` and `uploaded_by_user_id` are
      new, and files from before keep working with a dated name
- [x] **Remove only what nothing uses.** "Where it is used" is worked out from
      the things that use files — the organization's, a board's, goal's,
      competition's, channel's and slide's appearance, the background library,
      walk-ups and celebration rules (`app/asset_library.py`) — so it cannot
      drift, and a removal while in use is refused naming the first three
      places. A wall drawing an empty rectangle is the failure it prevents
- People's photographs are not shown in the library. **Staff photos** —
  moved from Settings → Branding to the top of this page, above the library,
  saying plainly it is a separate upload from Add files — now works the way
  the earlier staff-directory upload does, and a little further:
  - **One drop zone**: drag in, or click (or Enter/Space) to choose, a
    `.zip`, a whole folder (read all the way down, which the earlier
    upload advertises but cannot do), or any number of single photos
  - **Matched by username** from the file's name — `pparker.jpg`, or the
    whole email address — with separators and capitals ignored, and never
    guessed between two people who both fit. One matcher for zips and single
    files (`photo_bulk.place`)
  - **Single photos go one at a time** (`POST /users/photos/one`, the name in
    `X-File-Name`), so the page counts them off ("12 of 40") and no request
    has to carry four hundred; a zip goes as itself
  - **Every file gets a line**, problems first. One nobody matched can be
    given to the right person there and then with **Choose person**; two
    photos for one person say which came later and won
- **One logo** (asked for alongside): Settings → Branding no longer offers a
  separate "logo for dark backgrounds". The one logo is drawn in the app's
  header and on walls alike. A migration moved any dark-only logo into the
  logo slot and removed the old field from every stored appearance, so no
  screen keeps drawing a mark nothing can change
- **Not `/assets`**: that is the folder the build's own scripts are served
  from, and nginx answers it as a directory. Found by the screenshot

**Verified:** 8 backend tests (`test_asset_library.py`), the image, brand and
background suites, 981 web tests, type check clean, `alembic check` clean; the
page checked in the running app against the dev organization's real files.

### 6.4 Starter templates — done

Offered wherever these forms begin blank: in the empty state while there are
none, and as a "Start from" row at the top of a new rule or competition.
Everything lands in the ordinary form, with its preview (5j); nothing is saved
until somebody has looked at it (`pages/starterTemplates.ts`).

- [x] **Rules: Big deal, Deal of the week, Big day.** Name, message and points
      from the template; **the bar from the organization's own numbers** —
      `GET /achievement-rules/suggest` takes a unit and how often it should
      fire, picks the **busiest** metric of that unit over the last four
      weeks, and returns the value that would have cleared about that many,
      rounded down to two figures ("Set from your own Sales Feed Amount
      Today: it would have fired 28 times in the last 4 weeks"). Check then
      shows exactly what it would do. On the dev data: a bar of 350
  - Found by the screenshot: the first money metric alphabetically had no
    recent data, which is why it picks by activity, not by name
- [x] **Competitions: Friday sprint, Month-end push, Team vs team.** Dates
      worked out in the organization's own timezone — next Friday nine to
      five, weekly; tomorrow to the month's last day (next month's when fewer
      than three days are left); teams Monday to Friday — with a prize and
      repeat filled in. The metric is still chosen, and Check previews it
- [x] **Channels: Sales floor, Lobby.** "From a template" on TVs & Channels
      (and the empty state) makes the channel, adds slides from **what that
      channel may show** — the server's own eligible list, which now carries a
      competition's state so only running ones are taken — and opens its
      editor, where every slide is previewed. Sales floor: every board, the
      running competitions, recent wins. Lobby: the first board as a top-three
      podium, and recent wins
- One flaky test fixed on the way: the repeating-competition form test types
  a long form key by key and once passed five seconds under a full run

**Verified:** 3,331 backend tests (3 new for the suggestion), 990 web tests
(starter dates, slides and the rule form), type check clean. In the running
app: a Big deal rule filled from the dev data, and a Sales floor channel made
and opened (then deleted).

### 6.5 Badge art — done

- [x] **A drawn set of 18 badges** (`badgeMarks.tsx`), replacing the line
      icons that stood in since 4j: Medal, Trophy, Bullseye, Finish line,
      Spark, Team player, Rocket, On fire, Crown, Lightning, Diamond, Dialer,
      Big ticket, Team spirit, Summit, Early bird, Consistent, Climber. Each
      is an emblem — a medallion on a ribbon, a shield, a hexagon, a rosette
      or a coin — in a metal or a jewel finish, with a symbol on its face.
      Original SVG, so no licence and sharp at any size; gradient ids are
      unique per drawing so two on a page never share a finish
- [x] The six keys from before keep their meaning, so every badge already
      given keeps its look's intent. An unknown key still draws the medal
- [x] **Or the organization's own**: any picture from Assets, stored as
      `asset:<digest>` (`badge.icon` widened to 80). The server accepts only
      a drawn key or a picture the organization holds, and Assets lists the
      badge as where that picture is used, so it cannot be removed under it
- [x] Bigger where badges are the point: the picker shows each emblem with its
      name, the shelf draws them at 32–40 px, and one still being worked
      towards is greyed until it is earned

**Verified:** 3,335 backend tests (4 new for badge art), 993 web tests, type
check clean, `alembic check` clean; the set checked in the running app at 1×
and 2×.

### 6.6 Celebration visuals — done

- [x] **A trophy for each kind of win**, drawn in SVG, where an emoji was
      (`wall/CelebrationArt.tsx`): a cup with a star for a goal hit, a
      laurelled cup for a competition won, a medal on a ribbon for
      recognition, a rocket for a rule's big deal, a cake with lit candles for
      a birthday, a rosette for a work anniversary. Gold, blue, pink and
      violet finishes with highlights, on the wall's own 1920 × 1080 stage
- [x] **An entrance**: the piece rises in with a bounce, settles into a slow
      float, a glow in the organization's accent breathes behind it, light
      sweeps across it once, and confetti in the brand colours is thrown out
      and falls. The words follow a beat behind
- [x] **In step across screens**: every animation is timed from when the
      celebration began, so a screen that joins part-way shows the same
      moment as the others instead of replaying the entrance; and the
      confetti is seeded by the win, so every screen throws the same pieces
- [x] **Reduced motion honoured**: everything appears, nothing flies, no
      confetti
- [x] Previews carry their kind (`event_key`), so "Play celebration" and
      "Preview on a TV" show a rule's rocket and a walk-up's medal
- A clip, a music video or a picture on a rule still takes the stage, as
  before; the trophy is for the celebrations that had only the emoji

**Verified:** 3,335 backend tests, 996 web tests (the piece for each win,
identical confetti, the late-joiner's moment), type check clean. All six
pieces shown on the paired dev TV through previews, including one caught
mid-entrance with its confetti.

### 6.7 Team identity — done

- [x] **A team has a short name and a logo**, beside the colour it already had
      and that was drawn nowhere (`team.short_name`, up to twelve characters,
      and `team.logo`, a picture from Assets). Checked: a colour is `#rrggbb`,
      a logo must be a picture the organization holds, empty means none
- [x] **Edit on the Teams page** (the pencil, which was Rename): name, short
      name, a colour from eight swatches that stay distinct on a dark wall or
      any other, no colour, and a logo from Assets — shown as the wall will
      draw it, a podium place and a board row, while it is chosen. Each team's
      mark sits beside its name in the list
- [x] **On the wall**, every team row carries its look (`channels.
      _team_identity`, beside the rings and race pieces people buy): the logo
      where a person's face would be, drawn whole on the team's colour rather
      than cropped like a photograph; with no logo, a badge in its colour with
      its short name, or initials. Podium places, race pieces, the champion
      screen, the list and head-to-head comparison panels all use it; a
      person's row is unchanged (`wall/entryLook.tsx`)
- [x] A team's logo is listed in Assets as in use, so it cannot be removed
      from under the team
- Found by the screenshot: the list layout's badge letters were scaled twice
  and drew as a dash; they now have a size of their own

**Verified:** 3,346 backend tests (4 new in `test_team_identity.py`), 1,006
web tests, type check clean, `alembic check` clean. In the running app: the
Teams list and editor, and a temporary team board with three teams given a
colour and short name, as a podium and as a list — then the teams put back as
they were and the board deleted.

### 6.8 More game-board families — done

Three families beside the race track, each a name, a set of pieces and a
drawing on the shared engine (`app/game_boards.py`, `wall/GameBoard.tsx`).
Each is a ranked layout like the podium: the same slide, the same progress
to the finish line (or the leader), the wall's background, type and panels;
every piece in the entrant's colour — a ring they bought, their team's
colour, or their own — and anybody can move their own face instead.

- [x] **Regatta**: lanes of water with their waves, a wake behind each piece
      and a buoy at the finish. Sailboat, speedboat, duck
- [x] **Summit**: columns up a mountain range, a rope up each, the flag on
      the peak. Climber, mountain goat, hot-air balloon
- [x] **Space race**: from the Earth's horizon to the Moon through a field of
      stars (scattered by a hash, so every screen draws the same sky).
      Rocket, UFO, comet
- [x] A board sends the pieces chosen for **its own** family — a car on the
      race, a sailboat on the regatta — and a board draws only its family's
      pieces; anything else is the entrant's face
- [x] Chosen per family on a person's page, as before, now with each piece
      drawn beside its name; offered in every layout picker (Appearance, and
      a board's, competition's or slide's own)
- Found by the screenshots: the first sky drew its stars in a diagonal line
  and cropped the Moon and the Earth away; found by a test: a rocket from the
  space race could appear on the regatta

**Verified:** 3,351 backend tests, including 25 game board tests (5 new), 1,011 web tests
(each family drawn, family-only pieces, every piece drawable), type check
clean. All three on the paired TV at 1920 × 1080 through "Preview on a TV",
with the Deals board and six people given pieces for the run — their choices
put back afterwards.

### 6.9 Background library — done

- [x] **Eight drawn scenes**, a new kind of background (`kind: "scene"`)
      rendered in code on the wall itself (`wall/Scenes.tsx`): Ocean waves,
      Aurora mesh, Bokeh lights, Synthwave grid, Low-poly, Skyline at dusk,
      Confetti and Contour lines. Each is drawn from the background's three
      colours (base, middle, highlight), so the same scene can be the
      product's or the brand's, and nothing needs a licence
- [x] **Moving, cheaply**: waves roll, the grid runs to the horizon, lights
      rise, confetti falls, windows twinkle, the mesh drifts — every one a
      layer moving by `transform`, never a repaint, so a television stick
      keeps up. Still for anybody who asked for less motion. Movement is
      measured in the scene's own size (`%`, `cqh`), so a library swatch and
      a 4K wall move alike
- [x] **Two new shelves**: **Scenes** (all eight), with three more — waves,
      mesh and skyline — on **Your brand** in the organization's own colours;
      and **Your photos & video**: the organization's photographs and footage
      from Assets, dimmed a little for the words over them. Art with a
      transparent background and people's photographs are left off it
- [x] The background editor has "A drawn scene": which one, its three
      colours, moving or still, and the dim slider; a scene can be kept on
      the Scenes shelf (a migration adds it to the library's checked list)
- Photographs and real footage cannot be generated; their shelf fills from
  Assets
- Found by the screenshots: the mesh blurred itself to nothing in a swatch,
  low-poly split into two flat halves, confetti was a speck, and the grid's
  fixed perspective flattened it away on a full-size screen

**Verified:** 3,357 backend tests (6 new for scenes and the photo shelf),
1,014 web tests (every scene drawn, moving only when set), type check clean,
`alembic check` clean and the migration run down and up. The Scenes and Your
photos & video shelves checked in the running app at 2×, and skyline, grid and
waves on the paired TV at 1920 × 1080 through "Preview on a TV".

### 6.10 Rotation scheduling — done

- [x] **When a slide plays**: the days of the week, and optional hours (either
      end may be open; 22:00–02:00 crosses midnight, and the small hours
      belong to the night before). Worked out on the server in the
      organization's time (`app/schedule.py`), so the television's rotation is
      unchanged — it is simply handed the slides that play now
- [x] **How often**: once to four times a cycle, spread evenly (smooth
      weighted round-robin) so a 3× slide comes round A B A C A, never back to
      back. The editor's "one full rotation takes" counts it
- [x] **Night mode** per channel: off, **Clock** (a large clock and the date)
      or **Dark** (near-black, a small dim clock), with hours and "all weekend
      too". Both drift slowly on two unrelated periods so nothing burns in,
      in the organization's time zone, saying when the wall is back
- [x] Night mode **holds real celebrations back**; a preview sent from an
      editor still shows on top, so setting up after hours works
- [x] A channel whose slides are all **scheduled for another time shows the
      clock** rather than going black; a channel with no slides at all still
      says it is empty
- [x] "When it plays" in the slide form (day chips, Every day / Weekdays,
      from–until, how often); night mode in channel settings; the slide list
      says "Weekdays · 9 am–12 pm · 2× a cycle", and the channel's header
      says when night mode is on. Duplicating a channel copies all of it
- Found by the screenshots: two choices made in one moment undid each other
  (the controls now update from the latest state), the clock wrapped onto
  two lines near the screen's edge, and the large clock clipped at the top

**Verified:** 3,383 backend tests (26 new: the rules, the rotation at a fixed
time, the API, and the feed and celebrations on a TV), 1,025 web tests (the
quiet screen in office time and back to the rotation, the drift staying on
screen, the wording), type check clean, `alembic check` clean and the
migration run down and up. The slide form, channel settings and slide list
checked in the running app; clock, dark, and a preview during dark mode on the
paired TV at 1920 × 1080 (night mode set around the current time, then put
back).

### 6.11 Portrait layouts — done

- [x] **The wall turns with the screen.** A television taller than it is
      wide gets a 1080 × 1920 stage instead of a letterboxed 16:9 one, worked
      out from the screen itself — nothing to set. Layouts read the shape
      (`useWallShape`) and draw their portrait version
- [x] **List**: the top three get a larger row (bigger face, name and
      figure); the rest keep the ordinary row. The paging measures, so a
      tall screen fits all ten on one page
- [x] **Podium**: larger faces, taller steps and bigger type, with the rest
      of the list underneath set large enough to fill the screen
- [x] Also turned: the header puts the channel's line above the title;
      a spotlight stacks the face above the name; a comparison stacks its
      panels (four make a square); climb and space boards grow to twice the
      height, names over two lines. Goals, messages, race and regatta read
      as they are
- [x] **Landscape · Portrait** under the preview in the slide, board, goal
      and competition editors and on the Appearance page, remembered in the
      browser, so a side-mounted screen can be set up from a desk
- [x] **Fixed on the way: every person's photograph was being drawn as a
      team logo** (since 6.7). Every row carries `colour` and `short_name`,
      null on a person's, and the wall decided "team" from the keys being
      there — so photographs were shrunk onto a coloured circle on every
      layout. Rows now say `is_team` outright. A team's logo is drawn inside
      its badge rather than padded, because padding in percent is a share of
      the row's width: in a 1000-pixel row it made a 56-pixel face a dinner
      plate. The 6.7 tests had used a person row without the null fields,
      which is why it passed; they now use the shapes the server sends

**Verified:** 3,384 backend tests (1 new: a person's row is not a team's),
1,039 web tests (12 new: the stage's shape, the hero rows, the podium,
comparison and spotlight in each shape, the preview switch remembered, a
photograph against a logo), type check clean. Every kind of slide on the
paired TV in portrait at 1080 × 1920 through "Preview on a TV" — list,
podium, race, regatta, climb, gauge, big number, spotlight and message — and
landscape checked unchanged at 1920 × 1080; the editor's portrait preview in
the running app.

### 6.12 Bulk goals — done

- [x] **"Set for a group"** on the Goals page: a metric, a team (or, for an
      admin, an office), a period, and one target for everybody — suggested
      from the group's last period, a little past the typical figure
- [x] **A grid of the people in it**, with last period's figure beside each
      name. Type over anybody's target to give them their own; untick
      anybody to leave them out. Working people only (active or invited),
      by name; an office lists each person's team
- [x] **Somebody who already has this goal is shown it.** Saving changes
      their target rather than giving them a second goal, and the row says
      so first ("Changes from 25,000"); one already at that number is left
      alone. The line by the button says what saving will do: "Saving makes
      8 goals and changes 2. 1 left out."
- [x] **Ordinary goals, one per person** — the same period, name and repeat
      as the goal form would make, edited and archived like any other.
      All-or-nothing: a name in the grid that is no longer in the group
      refuses the save rather than saving part of it. One audit entry for the
      grid (`goal.bulk_set`)
- [x] A manager sets their own team's; an office is an admin's

**Verified:** 3,392 backend tests (8 new: the roster and its last-period
figures, an office's teams, saving, updating rather than doubling, a stranger
in the grid refusing the lot, who may), 1,043 web tests (4 new: the grid's
defaults, overrides and left-out rows reaching the save, no save without
targets, the wording), type check clean. Checked in the running app at
1400 px and at phone width, with a target, an override and somebody left out
typed in — nothing saved to the dev data.

### 6.13 Manager home — done

- [x] **"Your team"** at the top of Home for a manager — and an admin who
      sits on a team: everybody on it ranked on one metric for the period,
      the team's busiest metric unless another is chosen (remembered in the
      browser), today / week / month / quarter. The top ten, with "Show all"
- [x] **Each person's goal beside their number**: a bar, "of $25,000.00
      goal", and whether they are ahead, on track, behind, missed or hit
- [x] **Who needs a nudge, and why**: behind pace ("is behind on Deals: 1
      deal of 40 deals, 20 deals expected by now"), missed, or nothing
      recorded for a week. Figures are written by the page, as every other
      number is. The manager is never on their own list
- [x] **Most of the team quiet at once is one note**, not ninety names: a
      floor does not go silent together, a sync does — "Nothing recorded for
      87 of the team in 8 days — the data may have stopped arriving", with a
      link to Integrations for whoever can fix it. Found in the dev data,
      whose feed stopped eight days ago
- [x] **Worth a word**: hit their goal, or leading the team outright, each
      with Recognise. **Recognise on every row** opens the recognition form
      with that person already chosen
- [x] Nobody is ranked until somebody has scored, rather than everybody
      "1st" on a board of zeros

**Verified:** 3,402 backend tests (10 new: who has a team home, the busiest
metric and choosing another, ranking within the team, goals and pace beside
the numbers at a fixed moment, quiet people and how long, a whole quiet team
as one note, the leader and a tie, no ranks at zero), 1,049 web tests (6 new),
type check clean. Checked on Home in the running app at 1400 px and phone
width — empty, and with five facts and three goals added for an hour and then
deleted.

### 6.14 Competitions editable while running — done

- [x] **"Change while running"** on a running contest: a new prize, a later
      end, and late entrants — the things that really happen to a contest,
      none of which takes anything from whoever was already winning
- [x] **Each needs a reason.** It goes in the audit log
      (`competition.changed_while_running`, `competition.joined_late`) and on
      the contest's page under **Changed while running**, for everybody who
      can see it: "The end moved from Wed 7 Oct, 9:13 AM to Wed 14 Oct, 9:13
      AM. The prize changed from “Steak dinner” to “Weekend away”." with the
      reason, who and when
- [x] **Later only.** An earlier end decides the contest for whoever is ahead
      today, so it is refused; so are a new start, other rules, and removing
      somebody. A late entrant's numbers count from the start, like
      everyone's. Nothing changes once the contest has ended
- [x] Only what actually changed needs a reason: a form sending the whole
      contest back does not have to explain the prize it left alone

**Verified:** 3,411 backend tests (9 new, and two older ones rewritten for
the new rule: a late entrant is now refused only without a reason, and a prize
change needs one), 1,052 web tests (3 new), type check clean. Checked in the
running app on a throwaway running contest changed through the API —
afterwards deleted with its audit rows.

### 6.15 Reactions and comments — done

- [x] **Reactions** on every entry of the Recognition feed: 👏 🔥 🎉 💪 ❤️ —
      a fixed handful, counted at a glance, one of each per person, the same
      button taking it back. Hovering says who ("Ann, Bob and 3 others")
- [x] **Comments** under each entry, folded away until opened so a long
      feed stays a feed. Up to 300 characters; the author can remove their
      own and an admin any (audited when it is somebody else's)
- [x] **The person it is about, and whoever wrote the shout-out, hear about a
      comment** — a new "Comments" notification, private (never on a wall)
      and mutable in notification settings like the rest. Not the commenter
- [x] **One thread per entry, however the feed collapses it.** A team
      hitting its goal is a notification per member shown as one entry, so
      reactions and comments are stored against the entry's key (event,
      subject, period) rather than a notification row — the same through
      any member's row. Removing a shout-out takes its thread with it
- [x] Two tables (`feed_reaction`, `feed_comment`), one migration

**Verified:** 3,419 backend tests (8 new: toggling, the fixed set, who hears
about a comment, removing, a team win as one thread, a private event refused,
deleting a shout-out; one preferences test updated for the new setting),
1,057 web tests (5 new), type check clean, `alembic check` clean and the
migration run down and up. Checked on the Recognition page at 1400 px and
phone width with a reaction and a comment on a temporary entry — all removed
afterwards, with the notification the comment sent.

### 6.16 Command palette — done

- [x] **Ctrl+K (⌘K on a Mac) from anywhere**, or **Search** in the top bar
      (the shortcut shown on it): type a name and jump to a person, a
      leaderboard, a goal, a competition, a channel or a page. Arrow keys
      move, Enter opens, Escape closes; before anything is typed it lists the
      pages this person can open
- [x] **Nothing appears that its own list would hide.** Boards and goals
      come from the lists' own queries — pulled out into `visible_boards`
      and `visible_goals`, which the lists now use too — contests through the
      same `_may_see` (drafts hidden from agents), people only for whoever
      can open the people pages and within their scope, channels for admins
- [x] Best first: a name starting with what was typed before one that only
      contains it. A goal is found by its name, its person or team, or its
      metric, and says which period — "October 2026" — because a repeating
      goal is the same person and metric every month. Typed `%` and `_` are
      taken literally
- [x] People open on their page (`/users/:id`), contests show their state in
      words ("Running"), faces beside names

**Verified:** 3,426 backend tests (7 new: people within scope and none for an
agent, boards and goals following their lists, contests by who may see them,
channels an admin's, wildcards), 1,062 web tests (5 new: pages before typing,
a search a moment after typing, keys, Escape), type check clean. The boards
and goals list tests pass unchanged on the shared queries. Checked in the
running app at 1400 px and phone width.

### 6.17 Sounds — done

- [x] **A starter pack of eight sounds, made here** (`app/sound_pack.py`):
      Fanfare, Chime, Gong, Level up, Ka-ching, Drum roll, Air horn,
      Applause. Synthesised — tones with harmonics, a bell's uneven
      partials, seeded noise for claps and cymbals — so nothing needs a
      licence or a file in the repository, and each comes out the same every
      time. All under four seconds, well inside a wall's fifteen. Checked by
      drawing every waveform (the drum roll was drowned by its crash and the
      gong's strike louder than its tone; both rebalanced)
- [x] **A sound picker**: none, the pack, or the organization's own sounds
      from Assets (not people's walk-ups, which are theirs), each with ▶ to
      hear it first. A pack sound is copied into the organization's store
      the moment it is chosen — which is what lets a wall fetch it through
      its own token, and Assets say where it is used — and is not in Assets
      before that. Two columns only when the picker itself has room
- [x] **On celebration rules**: "Sound", beside "Or play a link" — one
      choice, since one column says what plays. A rule may now name a sound
      in the organization's own store, checked to be theirs and a sound
- [x] **Default sounds** on the Celebrations page, for an admin: what plays
      for goals hit, competitions won, recognition, and birthdays and
      anniversaries when the person has no walk-up music. Their own always
      comes first; chosen by the wall when it builds the celebration, so a
      sound picked this morning plays for a win from a minute ago. Assets
      lists a default as a use
- [x] `organization.celebration_sounds`, one migration

**Verified:** 3,437 backend tests (11 new: every pack sound a short real WAV
and identical each time, the picker and who may open it, one copy kept,
walk-ups left out, a rule playing a stored sound and refusing another
organization's, a default playing when the person has none and their own
still winning, defaults an admin's and only sounds), 1,066 web tests (4 new;
the Celebrations page tests taught about the new request, and the defaults
card made to draw nothing rather than crash on a bad answer), type check
clean, `alembic check` clean and the migration run down and up. Checked on
the Celebrations page and in the rule form; nothing chosen, so nothing added
to the dev data.

---

## Phase 7 — The second QA pass — **done**

**Goal:** every number, preview and status the product shows is true, the
stale-data story is told once, and what an agent and a manager see holds up
as well as what an admin sees.

The second QA and UI pass is written up in
[qa-bug-report-2.md](research/qa-bug-report-2.md) (Q2-1 to Q2-30) and
[ui-ux-review-2.md](research/ui-ux-review-2.md). Every first-pass fix it
re-checked held up on a test TV. What is left is below, most important
first.

**Decided:**

- **Deleting a rule or badge keeps the points it already paid**, and the
  delete confirmation says so ("Points already paid stay"). Reversing them
  would rewrite season standings people have already seen.
- **A goal created already met does not celebrate** (Q2-11). It is not news,
  and a wall announcing "goal hit" seconds after somebody typed a target reads
  as a glitch.
- **Profiles** (review §7) are their own phase, not this one. Everything else
  in the review's top ten is in.

**Order:**

1. **Agent and manager pass.** Both reviews were done as an admin. Sign in as
   a real agent and a real manager from the dev data and see what each sees,
   first, so anything found lands in the right step below
2. **Numbers that are wrong.** Hour-based pace for competitions and short
   goals (Q2-1); the currency symbol in announcements and the rules table
   (Q2-2); zero with time gone is not "On track" (Q2-10); ended periods say
   how they finished (Q2-13)
3. **One stale-data story.** The newest row per source on its card and in the
   Inbox; one Home line naming the source; the rule check on the template's
   window, saying "no data" rather than "lower the bar" (Q2-4, Q2-5)
4. **Honest previews.** The sample follows the form — unit, people or teams,
   period, prize, end, entrants, the person — labelled as a sample, with no
   invented channel; "Preview on a TV" gets a Send button (Q2-3, Q2-9)
5. **Clean up after deletes.** A deleted contest, rule, badge, fact or comment
   takes its notifications with it; comment Remove is labelled and undoable
   (Q2-6, Q2-17)
6. **Reporting track record** grouped per person and metric, counting only
   periods that had a goal (Q2-7)
7. **Phone and accessibility.** The bell panel, the Teams list, Home's
   Recognise button, file-input labels, one `h1` (Q2-8, Q2-18, Q2-19, Q2-27)
8. **Words, dates, titles, toasts and the small fixes.** One date helper;
   "TV" for a TV; plain words for metric settings and the activity log; the
   rest of Q2-11 to Q2-30
9. **The review's bigger items.** The celebration about the person and the
   number (§6); "Show on a TV" finishing the job (§5); the palette covering
   everything with a name (§8); a confirm step for channel templates; recent
   wins with the figure and the time

Each step ends as before: tests, a check at desktop and phone width, and on
the paired TV wherever it touches the wall.

### 7.1 Agent and manager pass — done

Signed in as **Hal Jordan**, an active agent on Metropolis Sales Team, and as
**Natasha Romanoff** on the same team — made a manager for the run and put back
to agent afterwards, because **the dev data has no managers at all**: every
team lead is an admin. Seventeen routes each, at 1400 px and on a phone, with
every console error recorded.

**Held up:** no console error on any page for either role; each sees the
navigation their role allows and no more; the agent's Deals board, goals,
points, recognition and account pages; the manager's team card, goals (their
team and the agents on no team, as designed), users, reporting and teams.
Home leaving the agent off a board where he sits at $0 is the rule working
(review §3), not a gap.

**Fixed here:**

- [x] **A page somebody's role does not include said nothing** — an agent
      following a link to Reporting, or a manager to Celebrations, landed on
      Home without a word. It now stays on the address and says "Not part of
      your role", as an unknown address already did (QA-26)
- [x] **The manager's own row on "Your team" sat out of line** — it has no
      Recognise button, so its figure moved right. The button's room is kept
- [x] **"Every goal you can see is on track"** said to somebody who can see
      no goals. Now "Nothing is behind right now"

**For later steps:** the Home banner counts everybody a manager can see —
413, the agents on no team included — not their team of 93 (7.3); lowercase
"agent" on Account and "wall screens" for TVs (7.8).

### 7.2 Numbers that are wrong — done

- [x] **Short windows are measured in working hours** (Q2-1). Start, end and
      today were all reduced to dates, so a 9-to-5 sprint — the Friday sprint
      template — was "100% of the window gone" the moment it began, and a goal
      for today was "not started" until it was over. Under two days, elapsed
      time is now the working hours (09:00–18:00, weekdays) gone out of those
      in the window, or plain clock time for a window wholly out of hours. A
      9–5 sprint at noon is 37.5%; today's goal at noon is a third gone, and
      can be behind before the day is out
- [x] **A contest ending partway through its last day counts that day**
      (Q2-1). Monday 9am to Friday 5pm used to read as over all of Friday;
      now Friday morning is four days of five, and it is over at 5pm. Every
      window is over when its real end passes, not its end date
- [x] **Money says it is money** (Q2-2): "Test just closed $500!", not
      "500.00!" — on the wall, the feed and the rule check, in the
      organization's currency, without cents on a whole amount. The rules
      table shows the bar as "$350". Three tests had locked the old output in
      and now assert the right one
- [x] **Nothing is not "On track"** (Q2-10): $0 of $250,000 a working day in
      is "Not started", and Reporting counts such goals apart ("Nothing yet")
      and leaves them out of its headline — which says **"Too early to tell"**
      rather than "On pace 100%" while nothing has started
- [x] **A finished period says how it finished** (Q2-13): "Finished at $0.00
      · missed by $250,000.00", not "Period over · on pace for $0.00"; Home's
      Needs attention says "missed by" rather than "100% behind pace". No
      projection once a period is over, or from nothing at all
- [x] **A goal set already met is recorded quietly** (Q2-11, as decided):
      when no number for its metric has arrived since the goal was made, the
      hit goes to the bell, the feed and the points as before but never takes
      over a wall, and the in-app overlay passes it by. A hit made by a
      number arriving afterwards is news, and announced. A `quiet` flag on
      the notification, one migration

**Verified:** 3,448 backend tests (new: the 9–5 sprint, today's goal through
the day, an evening sprint, a last day ending at 5pm, nothing not on track,
no projection when finished or from nothing, money in an announcement in four
currencies, too early to tell, a goal set already met kept off the wall and
one met afterwards announced), 1,069 web tests (3 new: a finished goal's
line, a hit one, a running one), type check clean, `alembic check` clean and
the migration run down and up. Checked on Goals and Reporting in the running
app.

### 7.3 One stale-data story — done

- [x] **A source that syncs cleanly can still be stuck**, and is now said to
      be (Q2-5). One judgement, `app/staleness.py`: a watched source — running,
      set up, scheduled, not already failing — with no new row for three
      working days is quiet. Working days, so Friday's numbers read on Monday
      are not a quiet spell. Every page below reads that one judgement
- [x] **Source card:** "No new numbers" in amber — "It syncs cleanly, but the
      newest row is from Thu 3 Sep — nothing new in 20 working days. Has
      whatever feeds it stopped being updated?" — and a working source says
      when its newest row was
- [x] **Inbox:** "No new numbers from Excel since Thu 3 Sep", as a problem,
      linking to the source
- [x] **Home names the data, not the people:** "No new numbers since Thu 3
      Sep · Excel · Check it" in place of "400 people have recorded nothing".
      A manager sees the same line with nowhere to be sent — the fix is an
      admin's — and their "quiet people" count is now their own team, not
      every agent on no team as well (7.1: 413 for a team of 93). The health
      card no longer repeats the banner's "on no team" line
- [x] **The rule check uses the template's four weeks** (Q2-4), says how
      often a week, and when no numbers of the metric arrived at all says so
      — "No Sales Feed Amount Today arrived in the last 4 weeks, so the
      check has nothing to try it on" — instead of advising a lower bar. The
      button is "Check the last 4 weeks"
- [x] A source still named by its connector's key ("microsoft_excel") is
      called what the Integrations page calls it ("Excel") in these sentences

In the dev data the Excel source's newest row is 3 Sep; the 23 Sep numbers
came from the Snowflake source, which reads once and so is not watched.

**Verified:** 3,457 backend tests (10 new: quiet after a week, not after a
day, not over a weekend, paused, failing and read-once sources unwatched, the
card, the Inbox, Home naming the data and a manager's view of it, a manager's
own team, the source's name; two rule-check tests moved to the four-week
window), 1,070 web tests (one new: no numbers is not a high bar; the noisy
check scaled to four weeks), type check clean. Checked on Home, Integrations
and the Inbox in the running app.

### 7.4 Honest previews — done

- [x] **The editors' sample follows the form** (Q2-3). `sampleSlide` takes
      what the form says — the metric's unit, decimals, label and direction,
      people or teams, the period, the rows shown and the finish line for a
      board; who it is for, the target and the period for a goal; the prize,
      the end and the actual entrants for a contest — and keeps sample values
      only for what the form cannot know. A team board shows teams (Northern
      Lights, Harbour…), a count is "48", not "$48,200", "Last 30 days" is not
      "March", a lower-is-better board puts the smallest first, a two-entrant
      contest reads "Ann vs Bob", and a prize left empty is no prize
- [x] **Said to be a sample, inside the picture** — a small SAMPLE in the
      corner, as a TV preview says PREVIEW — and **no invented channel**: the
      "Main floor" line is gone from editors' previews of things not on a
      channel yet
- [x] **"Preview on a TV" has a Send button** (Q2-9). Choosing a TV used to
      send at once, so arrowing down the list sent to every TV passed, a
      wrong pick could not be taken back, and sending again needed a detour.
      The only TV is chosen already; the toast says "…and plays for 10
      seconds"

**Verified:** 1,080 web tests (10 new: teams, units, period and rows, lower is
better, a goal's person and target, a contest's prize, end and entrants, no
prize; choosing sends nothing, Send does and again, waits for a choice, the
only TV chosen), type check clean. Checked in the board and goal editors in
the running app.

### 7.5 Clean up after deletes — done

- [x] **A deleted thing takes its notifications with it** (Q2-6), with their
      feed entries' reactions and comments — one helper, `app/cleanup.py`,
      called from each delete: a contest ("Sprint has started"), a rule (its
      wins), a correction (a rule's win for that number), a goal ("New goal",
      "achieved"), a comment (the "commented:" notification)
- [x] **A team shout-out goes from every bell.** It is a row per member, and
      removing it deleted only the row it was opened from
- [x] **Deleting a rule takes what it announced**, as the confirmation now
      says — pausing is how to stop one and keep its history. This reverses
      the old "announcements are kept either way", which left wins in the
      feed for a rule nobody could find
- [x] **Points already paid stay** (as decided), and both the rule and the
      badge confirmations say so
- [x] **A comment's Remove is "Remove comment"**, beside the entry's "Remove
      shout-out" (Q2-17). It disappears at once, the toast offers **Undo**
      for as long as it shows, and only then is it deleted — so Undo asks
      nothing of the server. Toasts can carry an action now

**Verified:** 3,463 backend tests (6 new: a contest, a comment, a team
shout-out from every bell, a correction's win, a goal, and somebody else's
left alone; the rule-delete test rewritten for the new rule, with points
kept), 1,081 web tests (removing waits for Undo's chance, Undo puts it back),
type check clean.

### 7.6 Reporting track record — done

- [x] **One row per series** (Q2-7): a repeating goal is a copy per period,
      and each copy was its own row — the same person and metric twice. A
      series is the subject, the metric and the period type; its newest goal
      speaks for it
- [x] **Only periods that count**: one a goal in the series covered, or one
      the person recorded something in. A goal set today for somebody with no
      history read "0% · 0 of 6" — six misses for months before the goal or
      any number existed — and now reads **"No history yet"**. Periods before
      the goal with nothing in them are still drawn, dashed, "before this
      goal", and left blank in the export rather than written as zeros, so
      the columns stay aligned

**Verified:** 3,466 backend tests (3 new: a repeating goal is one row, a new
goal counts nothing, months with numbers count even before the goal; the
hit-rate test now counts the four months with numbers, not six), 1,081 web
tests, type check clean.

### 7.7 Phone and accessibility — done

- [x] **The bell's panel is a sheet across a phone** (Q2-8), under the top
      bar; anchored to the bell it hung 17 px off a 375 px screen
- [x] **Teams list on a phone** (Q2-18): the "from Microsoft Teams" chip wraps
      under the name instead of squeezing it to "$…"
- [x] **Home's "Your team" Recognise is an icon on a phone** (Q2-19), named
      by its label, so it no longer pokes out of the card
- [x] **Accessibility leftovers** (Q2-27): the photo and video inputs in the
      background editor and the walk-up clip input on Account are labelled;
      a wall preview's title is an `h2`, so a page with a preview keeps its
      one `h1`; the reaction toggle says whether it is open
- [x] The photograph help said "nothing is cropped away" (Q2-21) — a cover
      crops. Now "It fills the screen, so its edges may be cropped"

**Verified:** 1,081 web tests, type check clean. Checked at 375 px: the bell
open, the Teams list, Home's team card.

### 7.8 Words, dates, titles, toasts and the small fixes — done

- [x] **One date style** (Q2-29): "2 Oct", "Fri 2 Oct", "Fri 2 Oct, 11 pm",
      "1 – 2 Oct", a year only when it is not this one — one helper in
      `time.ts`, used by the contest check, the asset library, Activity, a
      contest's changes and rounds, Points, the wheel, sync history and every
      "Last sent". The server's "The end moved from…" says it the same way
- [x] **"Data as of" counts corrections** (Q2-12): a second date on the
      freshness feed, used only for the label. Whether a feed is late is
      still judged on what it imported, so one correction cannot make a
      stalled feed look current
- [x] **The non-people detector** (Q2-15): a team alone no longer marks a
      person; a stand-in word (test, bot, dummy, demo, sample, fake)
      outweighs a copied job title or department; run-together names split
      ("FastSourcing"); the organization's own name, from its name or its
      address, counts as a thing-word ("Northwind Vegas"). Signing in,
      numbers, goals, a photo or a chosen role still always mark a person
- [x] **Prize wheel labels** (Q2-26) run along the radius, flipped on the left
      so none is upside down, cut with "…" and named in full on hover
- [x] **Words** (review §9):
      - Metrics: "Total · Money · 2 decimals · Higher is better"
      - Activity: sentences — "changed the running contest “QA2 sprint” ·
        The end moved…", "deleted the goal for ann@…", with ids dropped and
        values as values
      - Timezone: "Pacific Time — Los Angeles (UTC−7)", the usual zones first
      - The slide picker: "QA2 sprint · running · everyone"
      - "TV" for a screen (Q2-23); "Recognition feed"; "celebration rule";
        "Pair with a code"; "Always live"
- [x] **Toasts** (Q2-22): "X connected — playing Y", "X is back on Y",
      "Added 1 · 1 refused" (Q2-20), and new ones after making a team or a badge
- [x] **Titles** (Q2-24): Home's tab says Home; a goal's page is "Ann —
      Deals"
- [x] **Small fixes**:
      - "Cancel contest", in red (Q2-28)
      - "Test User 69 is $500 behind"
      - Give a badge with none set up links to Points setup (Q2-25)
      - a celebration with no sound says "Walk-up only — others hear nothing"
      - the role on Account is a word
      - an empty board name gets the app's own error (Q2-30)
      - bulk goals starts on "Choose a team…" (Q2-14)
      - a team row says "your team" once (Q2-16)

**Verified:** 3,474 backend tests, 1,097 web tests, type check clean. Checked
in the running app: Activity, Metrics (desktop and 375 px), the timezone list,
the wheel, the asset library. The detector now suggests Jarvis Bot, Northwind
Vegas, FastSourcing NTax and the nine Test Users, and no real people.

### 7.9 The review's bigger items — done

- [x] **The celebration is about the person and the number** (review §6):
      their photo inside the glow with the trophy as its badge, the rule as
      the eyebrow, the figure ("$500") as the largest thing on screen, the
      name second, the sentence under it. The figure is formatted when the
      win happens and kept on the notification (`figure`, migration
      `d8f3b1c6e247`), as the sentence is, so a later correction or a
      currency change does not rewrite an old win. Rule previews on a TV and
      the walk-up preview show the same. A win with no number, a shout-out,
      keeps the name as its largest line
- [x] **"Show on a TV" finishes the job** (review §5): on a board, a goal and a
      contest it opens a dialog listing every channel, says "Already on"
      where it plays, adds it to another in one click (with the server's
      reason if a channel refuses it) and offers "see it on one TV first"
- [x] **A channel template is confirmed before it is made** (review §5): its
      name (made unique — "Sales floor 2" — when taken) and the slides it
      will add, numbered, then Create. New `GET /api/channels/eligible`
      answers what a channel for everyone may show before it exists.
      Clicking twice no longer leaves two "Sales floor"s
- [x] **The command palette covers everything with a name** (review §8):
      teams (for everybody), offices, celebration rules, badges and metrics
      (for whoever can open their list), each opening its list with the row
      picked out; settings tabs ("Branding"); and actions — "new" lists New
      goal, leaderboard, competition, celebration rule, channel, team and
      metric, Connect a TV and Invite people, each opening its form. A person
      shows their team and address, so "Test User" and "Test user" can be told
      apart. Two small hooks (`urlIntent.ts`) read `?new=` and `?focus=`
- [x] **Recent wins say the figure and when** (review §5): "Diana Prince — Big
      deal · $12,400 · 25 minutes ago". When the newest is over a day old the
      slide is "Latest wins", not "Recent wins". A title somebody typed is
      left alone
- [x] Also: `/points/setup?tab=badges` now opens the Badges tab — the 7.8 link
      from "Give a badge" pointed at it but the page did not read it

Not done, and why: the review's "use the channel's background, dimmed, behind
a takeover" — a see-through takeover shows the slide underneath, and the
blur that would hide it is too heavy for the cheap TV sticks walls run on.
Slide thumbnails in the template step: the numbered list says the same
thing, and the editor it opens previews each slide with real numbers.

**Verified:** 3,480 backend tests, 1,109 web tests, type check and `alembic
check` clean, migration up, down and up. On the paired TV: a rule preview
with Bruce Wayne's photo, "BIG DEAL", "$195" and his name, in that
order; the wins slide with "5 hours ago". In the app: "metropolis" finds the team
and the office, "new" lists the actions, Show on a TV on DEALS BOARD says
"Already on test" (desktop and 375 px), the Sales floor template's confirm
step lists DEALS BOARD and Recent wins, and the Badges link lands on its tab.

---

## Phase 8 — The second review's page notes — **done**

**Goal:** finish [ui-ux-review-2.md](research/ui-ux-review-2.md). Phase 7 took
its bug report and its top ten; an audit after it found about thirty smaller
notes in §5, §7, §8, §10 and §11 that no step had taken. These are those.
Profiles (§7's proposal) are still their own phase.

**Order:**

1. **People, teams and offices.** "Their face" when editing someone else; "No
   team" for no team; the Teams editor's placeholder and its colour preview;
   initials as a team's default logo; empty teams and unused offices pointed
   out; walk-up chosen from Assets as well as uploaded
2. **Home, Leaderboards and Goals.** The empty personal cards as one line;
   "No numbers for this period yet" for a team at $0; the board editor's cut
   selects, "teams" in subtitles, a View link on the created toast; the goal
   tags explained, "No earlier months", the pace line labelled, bulk goals
   offering only people who recorded something
3. **Competitions to Metrics.** The entrant picker closing after a pick;
   Recognise saying where it is seen; Default sounds below the rules; badge
   names on two lines; the email tab saying it is set up; the duplicate-name
   error on its field and the header button that turns into Cancel
4. **Integrations, Assets, Settings and the sidebar.** Logos for Close,
   Pipedrive, Freshdesk and Gong; an Unused filter with bulk remove and a
   warning for a portrait background on landscape TVs; Activity filters;
   "Set it up now" for two-step sign-in; sidebar groups that collapse
5. **TVs & Channels.** Thumbnails in the channel editor and a "Play rotation"
   preview; Connect a TV beside "No televisions are playing this yet"; the
   gear labelled; a two-entrant contest drawn as head-to-head on the wall,
   with faces
6. **Wall-aware deletes.** Deleting a board, goal or contest names the
   channels it leaves ("Removes 1 slide from Sales floor") before the confirm
7. **Real numbers in editors.** The board and goal forms' previews offer the
   real standings, as the slide editor already does

Each step ends with tests, a check at desktop and phone width, and the paired
TV where it touches the wall.

### 8.1 People, teams and offices — done

- [x] **"Their face"** in the game pieces when an admin chooses for somebody
      else; "Your face" on your own
- [x] **"No team"** for no team, where it said "— unassigned —"
- [x] **Roles and statuses as words**: "Agent", "Invited", "Hidden", on the
      People list and a person's page
- [x] **The Teams editor says what its defaults are.** No "ENT" placeholder
      that read as a value already set — the hint names the team's own
      initials instead. "None" for colour is "From its name", with a line
      saying so; the preview always drew that colour, which is what made it
      look wrong. "No logo" is "Initials", drawn as the mark it is
- [x] **An empty team says so** for an admin: "Empty — archive?" where it
      said "0 members"
- [x] **An unused office says so**: "Unused — archive it to tidy the
      pickers?" on an office with no teams and nobody in it (five on the dev
      data)
- [x] **A walk-up from Assets.** Beside the upload, an admin can choose a
      sound or a video already in the library. New `PUT /me/walkup/asset`
      takes this organization's own playable files only, stored under the
      same schemes as an upload

**Verified:** walk-up, game-piece, team and people tests; 2 new backend tests
for the library walk-up. Checked in the running app: Teams with the empty
team flagged, the team editor, Offices with five unused, a person's page.

### 8.2 Home, Leaderboards and Goals — done

- [x] **Three empty cards are one line** on Home: "Nothing personal to show
      yet — you are not on a board, a goal or a contest". The cards stay
      mounted, hidden, so they still notice when that changes
- [x] **A team with nothing yet this period says so once** — "No numbers for
      October 2026 yet" — instead of a row of "$0.00" per person, and offers
      "Show last month" when last month had numbers. The team endpoint takes
      `previous=true` for it
- [x] **The board editor's selects are not cut**: "Who can see it" and "Ties"
      have a row each, and Metric and Among stack while the preview sits
      beside the form
- [x] **"Teams ranked"**, not "· teams ·", on a board's subtitle and in the
      list; "Whole organization" capitalised
- [x] **"Board created" has a View link**
- [x] **The goal tags say what they mean**: "Repeats monthly" (by the
      goal's own period) and "Made automatically", with a line on hover, the
      same on the list and the goal's page
- [x] **"No earlier months"** where the history chart was an empty axis —
      for a goal with no periods before it, or none with numbers in them
- [x] **The pace line is named**: "| expected by today" under the bar, while
      it still matters
- [x] **Bulk goals can leave out everyone with nothing last period** in one
      click ("Leave out the N who recorded nothing in September 2026")

**Verified:** team card, bulk goals, goal and Home tests, 1 new backend test
for the previous period. Checked in the running app as the dev admin: Home
with the one line and "No numbers for October 2026 yet · Show last month", the
board editor, a goal with "Made automatically", "No earlier months" and the
labelled pace line.

### 8.3 Competitions to Metrics — done

- [x] **The entrant picker closes after a pick**, stays focused for the next
      name, and opens again on typing — it stayed open listing everybody
- [x] **"Recognise someone" says where it will be seen**: the Recognition feed,
      and the TVs of any channel that shows recognition
- [x] **Default sounds sit below the rules** on Celebrations; the rules are
      what the page is for
- [x] **Badge art names wrap to two lines** ("Team player", not "Team pla…")
- [x] **The Email tab says whether email is set up** — "Email is set up —
      sending from goalgetter@…" — where it always said "It needs email set
      up". New `GET /reporting/mail` answers in the order sending tries:
      Microsoft 365, then SMTP
- [x] **A metric name or key already taken is said on its field**, not in a
      banner at the top of the page
- [x] **The header's "New metric" stays "New metric"**, resting while a form
      is open; it used to turn into a purple Cancel

**Verified:** picker, report schedule and Metrics tests, 1 new backend test.
Checked in the running app: Celebrations, the Email tab ("sending from
goalgetter@contoso.com"), the badge art picker, a new metric form.

### 8.4 Integrations, Assets, Settings and the sidebar — done

- [x] **An "Unused" shelf in Assets**, with "Remove all N" behind a confirm.
      One that comes into use mid-way is kept, and the toast says how many
      were. Four of seven on the dev data
- [x] **A portrait picture as a background says what it will lose**: taller
      than wide, on a landscape TV, it fills by cropping most of its height.
      Measured from the picture itself, so it holds for one from Assets
- [x] **Activity filters**: a person (either side of an entry, by address), a
      kind of thing — offered from what the log actually holds, in words —
      and a date range, with Clear. `GET /audit` takes `person`, `kind`,
      `since` and `until`; new `GET /audit/kinds`
- [x] **"Set it up now"** under two-step sign-in when the only person left
      without it is you — or "Set up yours now" when you are one of several —
      linking to it on Account
- [x] **Sidebar groups fold**, remembered per person in this browser. The
      group holding the page you are on stays open whatever
- **Kept as they are: letter tiles for Close, Pipedrive, Freshdesk and Gong.**
  Those companies asked to be removed from Simple Icons, where the other
  marks come from, and a mark drawn from memory would misrepresent somebody
  else's trademark. Swapping in an official SVG from their press kits is one
  line in `connectorMark.tsx` when there is one to hand

**Verified:** 1,118 web tests, type check clean; 1 new backend test for the
filters. Checked in the running app: the Unused shelf with "Remove all 4", the
Activity filters, the Organization group folding (stored as
`["Organization"]`). Not seen on screen: the portrait warning, as no dev
background is a portrait picture.

### 8.5 TVs & Channels — done

- [x] **Thumbnails in the channel editor**: each slide drawn small, with
      real numbers, from the same renderer as the TVs. New `GET
      /channels/{id}/slides` renders every saved slide; it is asked again
      whenever a slide is added, moved or edited. Hidden on a phone
- [x] **"Play rotation"**: the slides in turn, each for its own time, with
      Previous, Pause and Next — the rotation without standing at a TV
- [x] **"Connect a TV"** beside "No televisions are playing this yet", with
      the channel already chosen in the form
- [x] **The cog says "Settings"**
- [x] **A two-entrant contest is a head-to-head on the wall**: two panels,
      two faces, two big numbers, "$4,501.20 behind" under whoever is behind,
      "Level" when tied. A race or a game board chosen on purpose still wins
- [x] **Contest slides carry faces.** They never had — every contest layout
      on the wall drew initials. One query, as a board does it
- [x] **The contest page's head-to-head has faces too**, sent only for two
      people facing each other

**Verified:** 3 new backend tests (rendered slides, contest faces on the
wall and on the page), wall and Play rotation tests. On the paired TV: a
temporary two-person contest drawn as the head-to-head with Oliver Queen's
photo (deleted afterwards, with nothing left in the bell). In the app: the
channel editor with thumbnails at desktop and 375 px, Play rotation, the
contest page.

### 8.6 Wall-aware deletes — done

- [x] **Deleting a board, a goal or a contest names the TVs it leaves**, in the
      confirm: "It also comes off the TVs: removes 1 slide from Sales floor
      and 2 from Lobby." The database cascades, so the slides went silently
      before. A board that is one panel of a comparison counts too. New `GET
      /channels/using?kind=…&id=…`; the confirm reads as before when it is on
      no channel, or the question cannot be asked

**Verified:** 1 new backend test, 1 web test. In the running app: deleting
Clark's September goal, which plays on the "test" channel, says "removes 1
slide from test" (cancelled; the goal is still there).

### 8.7 Real numbers in editors — done

- [x] **"Sample · Real numbers"** above the preview in the board and goal
      forms. Real draws the form as it would be saved, with today's
      standings or progress, by the same renderer as the TVs; it follows the
      form a moment after it stops changing. When the period has nothing in it
      the sample stays, and says why. Offered once the form names enough to
      ask — a metric, and for a goal somebody and a target
- [x] New `POST /leaderboards/draft-slide` and `POST /goals/draft-slide`: the
      board or goal is added inside a savepoint that is always rolled back,
      with a throwaway channel and slide (`channels.draw_unsaved`). Saving and
      previewing share one set of checks (`_new_board`, `_new_goal`). A
      private board is drawn as a public one would be — who may see it does
      not change what it shows
- The paths are `draft-slide`, not `preview`: `/goals/preview` is already the
  guided goal form's history

**Verified:** 3,491 backend tests, 1,125 web tests, type check and `alembic
check` clean; 2 new backend tests that also count rows to show nothing is
saved. In the running app: DEALS BOARD's edit form on Real numbers, Clark's
goal on Real numbers; boards, goals and channels counted the same before and
after.

### Phase 8 closed — 2026-10-05

Everything in ui-ux-review-2.md is built, decided or set aside with its
reason. What is left is the profiles phase (§7's proposal), deferred at the
start of Phase 7.

---

## Phase 9 — Profiles — **done**

**Goal:** one page per person that shows what they have earned, to everyone,
and how they are doing, to the people entitled to know. Sleek and simple: one
column, an empty section is not drawn, and nothing on it leads to a page the
viewer cannot open.

From ui-ux-review-2.md §7: points, tiers, badges and the wheel have no shop
window — "a badge stays on their profile", and there was no profile.

**Decided:**

- **A profile is its own page, `/people/:id`, not a board and not a settings
  page.** Editing stays where it is — Account for yourself, the person page
  under Users for admins and managers — and the profile links to it for
  whoever may edit.
- **The page is the same for everyone, and narrows by who is looking.** The
  server sends the private part only to those entitled to it; the client
  never hides what it was sent.

  | Section | Everyone | The person | Their managers, admins |
  |---|---|---|---|
  | Photo, title, team, tier | ✓ | ✓ | ✓ |
  | Season points and rank | ✓ | ✓ | ✓ |
  | Badges | ✓ | ✓ | ✓ |
  | Wins and shout-outs, with the figure | ✓ | ✓ | ✓ |
  | Goals and progress | | ✓ | ✓ |
  | Their numbers, trends and board ranks | | ✓ | ✓ |

  "Their managers, admins" is the rule the app already has: `users.view`,
  narrowed by `visible_user_ids` — an admin sees everyone, a manager their
  team. A custom role only takes abilities away, so one based on Manager or
  Admin that keeps "View people" sees private sections within its scope.
- **A win's figure is public**: "Big deal · $12,400" was announced on the TVs
  and the Recognition feed already. A goal's figures and a person's totals are
  not.
- **Every button is one the viewer can use.** Recognise, Give a badge, Edit and
  any link into an admin page appear only for someone with that ability, so
  nobody is led to "Not part of your role".
- **Agents can find colleagues** by name in the command palette, to open
  their profiles.
- Hidden accounts have no profile.

**Order:**

1. **The data.** `GET /people/{id}`: the public part for anyone in the
   organization, the private part only to those entitled, and what the
   viewer may do. Tests that an agent cannot get another agent's private part
2. **The page.** `/people/:id` as described, at desktop and phone width, with
   its empty states; "View your profile" from Account
3. **Names become links.** Boards, the Recognition feed, contest entrants and
   standings, the team card, the points table, and the command palette —
   which now finds people for agents too, opening the profile
4. **The joins.** "View profile" on a person's admin page; "Edit" on the
   profile for whoever may
5. **The switch.** "Colleagues can see each other's profiles" under Settings →
   What people can set, on by default. Off, a profile is seen only by the
   person and those entitled to the private part, and names stop being links
   for everyone else

### 9.1 The data — done

- [x] **`GET /people/{id}`** — the person (photo, title, team, office, the
      ring and title they wear), the season (points, place, tier and the
      next), their badges, their public wins (occasion, figure, who gave a
      shout-out), and `can`: whether this viewer may Recognise, Give a badge,
      and where Edit goes. Hidden accounts and other organizations: 404
- [x] **The private part only to those entitled** (`app/people.py`): the
      person, or `users.view` within `visible_user_ids`. Goals still running,
      and their place on each board of people the viewer can open, with the
      movement and their streak. Not sent otherwise — the client never hides
      what it was given
- [x] **`organization.profiles_public`** (migration `e9a4c2b7d358`), on by
      default, for 9.5; and `people.view` in the session's abilities where
      names should be links: everyone with profiles open, only admins with
      them closed

### 9.2 The page — done

- [x] **`/people/:id`** (and `/people/me`), open to every role: a header with
      their face, name, title · team · office and tier, then This season,
      Badges, Recent wins — each drawn only when it has something in it — and,
      under "🔒 Only Ann, their managers and admins see this", Goals and
      Numbers
- [x] **Buttons only for what the viewer can do**: Recognise and Give a badge
      for a manager or admin who can see them, opening with them already
      chosen; Edit to Account for yourself, to the person's page under Users
      for whoever manages them
- [x] **"View your profile"** on Account
- [x] An office named for its one team is not said twice

**Verified:** 11 backend tests — what a colleague, the person, their manager,
another team's manager and an admin each receive; hidden and foreign
accounts; wins with figures and givers; the season; the switch. 3 page tests.
In the running app as the admin (Tony Stark in full, with Edit and Give a
badge) and as Hal Jordan, an agent (Tony's public half only, no buttons;
his own profile with "Only you, your managers and admins see this"), at
desktop and 375 px.

### 9.3 Names become links — done

- [x] **`PersonLink`**: a name opens the profile where the viewer can open
      profiles (`people.view`), and is plain text where they cannot — so no
      page offers a link that ends at "not available"
- [x] **Where names appear**: board rows (boards of people only, the pinned
      "you" row too), the Recognition feed and its comments, a contest's
      entrants, table and head-to-head (people only), Home's team card and its
      notes, the season points table
- [x] **The command palette finds people for everyone while profiles are
      open**, opening the profile. A colleague is found by name only and
      shown with their team; an address is matched and shown only to
      somebody who manages people. With profiles closed it is as before:
      managers find their own people, agents nobody

### 9.4 The joins — done

- [x] **"View profile"** on a person's page under Users; **"Edit"** on the
      profile for whoever may (9.2); **"View your profile"** on Account (9.2)

### 9.5 The switch — done

- [x] **"Colleagues can see each other's profiles"** under Settings → What
      people can set, on by default, with a line saying goals and numbers
      stay private whichever way it is set. Off: a profile opens only for the
      person and those who manage them, names stop being links (an admin's
      still are — they see everyone), and agents find nobody in the palette.
      Saving it re-reads the session, so the change shows without a reload

**Verified:** 3,503 backend tests, 1,130 web tests, type check and `alembic
check` clean, the migration up, down and up. New: 21 profile and search tests
between them (who receives what; the switch through the settings endpoint and
the session's abilities; agents finding colleagues by name and not by
address), and page, link and palette tests. In the running app as Hal
Jordan, an agent: 11 links to profiles on DEALS BOARD with profiles open and 0
with them closed, the closed profile saying "This profile isn't available",
Tony Stark found in the palette with his team and no address. As the admin:
"View profile" on a person's page, the switch under What people can set. The
switch was put back on afterwards.

### Phase 9 closed — 2026-10-05

Profiles are built: a page per person, public where it is earned, private
where it is performance, and every way in scoped to who is looking.

---

## Phase 10 — The third QA pass — **done**

From [qa-ui-pass-3.md](research/qa-ui-pass-3.md): 55 of about 60 Phase 7–9
items confirmed, no regressions, and P3-1 to P3-19 found.

**Decided (5 Oct):** order 10 → 11 → 12, each committed before the next.
Money: no ".00" on a whole amount anywhere a person reads it, the TVs
included; real cents kept.

1. **The wall on the first of the month.** An empty list board says "Nobody
   has scored yet this month" — and, for a calendar board's first day, shows
   last period's winners — instead of a blank screen; "Real numbers" with
   nothing in it falls back to the sample and says so (P3-1, §4 #1).
   Template "Recent wins" untitled so it can become "Latest wins" (P3-9);
   no "Main floor" on board detail (P3-13); thumbnails hidden from screen
   readers and drawn without the photo behind them (P3-8)
2. **Archiving is wall-aware**, as deleting is: a confirm naming the TVs it
   leaves, a toast with Undo, and an archived slide marked "Archived — not
   playing · Restore" in the channel editor — boards and goals (P3-2, P3-17)
3. **Numbers that read wrong.** One money rule: no ".00" on a whole amount
   anywhere a person reads it, cents kept when they are not zero, exports
   exact (P3-7). Nothing yet is not a place — a profile leaves out a board
   where they are at zero, and an all-zero history is "No earlier months"
   (P3-6). A cancelled contest stops forecasting (P3-10); no projection
   before a quarter of the window or a few entries, "Too early to call"
   (P3-11); "Show last month" sets the period select and speaks in the past
   tense (P3-12); a missing profile's tab title (P3-5)
4. **One stale-data story on Home**: the team card and System health reuse
   the banner's source and date (P3-3)
5. **Confirms and words.** The confirm dialog's dismiss button is never
   "Cancel" beside a "Cancel …" action — "Keep it running", "Keep it" (P3-4,
   and every other `ask()` checked); the wording list (P3-14); palette
   results labelled by kind (P3-15); Connect a TV from a channel returns to
   the channel (P3-16); "Choose from Assets" shown disabled with a hint
   while the library has no sound or video (P3-18); Activity's last
   internal words and names for addresses (P3-19)
6. **A freshness chip on wall slides**: "as of 23 Sep" in a corner, only when
   the numbers are more than a day old (§4 #3)
7. **An agent and manager pass after profiles**, with temporary sessions for
   real accounts as in 7.1 (§4 #2)

### 10.1 The wall on the first of the month — done

- [x] **No blank TV for an empty board** (P3-1). Every layout — the list,
      which said nothing, as well as podium, race and game boards — says
      "Nobody has scored yet" in the same words (`wall/NobodyYet.tsx`).
      Every row at zero counts as nothing yet where higher is better; a zero
      can be a real best where lower is
- [x] **Last period's top three** on a calendar board with nothing in it yet
      (§4 #1): "September 2026's top 3", names written under the wall's
      name setting. Never for a rolling or custom period, or when last
      period was empty too (`channels._last_period`)
- [x] **"Real numbers" on an empty board shows what a TV shows** — the empty
      state and last month — and says "Nothing in this period yet — this is
      what a TV shows right now"
- [x] **Template "Recent wins" is untitled** so the wall can call it "Latest
      wins" once the newest is over a day old (P3-9)
- [x] **No invented "Main floor"** on any preview: WallPreview's default
      channel name is now none (P3-13)
- [x] **Channel thumbnails are pictures**: hidden from screen readers and
      inert, and drawn without the background photo, so slides that share
      one look different at that size (P3-8)

**Verified:** 2 new wall tests, 1 new backend test (last month's top three,
and none once this month has a number). In the running app: DEALS BOARD's
editor set to This month, on Real numbers, showing "Nobody has scored yet"
over Arthur Curry, Oliver Queen and Wally West from September; the channel
editor's thumbnails without the photo.

### 10.2 Archiving is wall-aware — done

- [x] **Archiving a board or a goal that plays on a TV asks first** (P3-2):
      "Archive “Deals board”? It stops playing on Sales floor (1 slide).
      Restore it to bring it back." Archive is one click to undo, so it asks
      only when a wall would change (`wallUse.archiveQuestion`) — from the
      boards list, the goals list and a goal's page
- [x] **A toast with Undo** after archiving a board or a goal (P3-17)
- [x] **The channel editor says "Archived — not playing · Restore"** on a
      slide whose board or goal is archived, and its thumbnail says
      "Archived" — not "Nothing to show yet", which read as missing data.
      `archived` on each slide the channels API returns

**Verified:** 1 new backend test, 2 web tests. In the running app: the
confirm on Clark's September goal ("stops playing on test (1 slide)"),
cancelled; then archived through the API, the channel editor showing
"Archived — not playing · Restore", and restored.

### 10.3 Numbers that read wrong — done

- [x] **One money rule** (P3-7): no ".00" on a whole amount anywhere a person
      reads money — the app, the TVs, the coaching email — and cents kept when
      they are real ("$4,215.37"). Rounded first, so $9.999 is "$10". In
      `formatMetric` and the digest's `_money`; announcements already did it;
      exports stay exact
- [x] **The goal page's history chart drew no bars at all** (P3-6). QA read it
      as all-zero months; Tony Stark's July and August had $21,500 and
      $11,200. Each bar's height was a percentage of a box with no height, so
      every bar was nothing. Columns now fill the chart, a zero is a hairline,
      and the bars are the brand colour rather than a grey close to the card's
- [x] **The trend line's end dot ran past the card**: a circle stretched with
      the chart into a smear. Now a round point that keeps its shape
- [x] **Nothing yet is not a place on a profile** (P3-6): a board where they
      have nothing, where higher is better, is left out — not "$0.00 · 39th
      of 137"
- [x] **No forecast from the first minutes** (P3-11): a contest is forecast
      once a quarter of its window has gone; before that, "Too early to call"
      (`too_early` on the report)
- [x] **A cancelled contest stops forecasting** (P3-10): no report card, no
      projection, and nobody "$500 behind"
- [x] **"Show last month" on Home says so** (P3-12): the period select reads
      "September 2026", and the notes speak of it as past — "led the team",
      "finished behind", "recorded nothing"
- [x] **A missing profile's tab says "Profile not available"** (P3-5), not
      the last person's name

**Verified:** 1,135 web tests, money rule tests added; 3 new backend tests
(early and cancelled forecasts, a zero board on a profile). In the running
app: Tony Stark's goal with its July and August bars and the dot inside the
card; my own profile without the $0 board.

### 10.4 One stale-data story on Home — done

- [x] **System health says it by source** (P3-3), in the banner's words:
      "Excel — no new rows since Thu 3 Sep", "Sales Feed — read once,
      newest row Wed 23 Sep" — where it said "Data last recorded 11 days ago",
      a third date with no source beside it. `sources` on the health payload
- [x] **The team card points at the banner** when it is showing: "Nothing
      recorded for 88 of the team in 11 days — see “No new numbers” above",
      not a second date and a second link
- [x] "TVs offline", not "Screens offline"

**Verified:** 1 new backend test. In the running app: Home with the banner,
the team card pointing at it, and System health listing both sources.

### 10.5 Confirms and words — done

- [x] **Never "Cancel" beside "Cancel"** (P3-4). The confirm dialog's no
      button has its own label: a question that starts "Cancel …" offers
      "Yes, cancel it" and "Keep it", drawn as a danger, where "Cancel this
      competition?" offered [Cancel] [Cancel]. In the dialog itself, so every
      `ask()` is covered; callers may name both buttons
- [x] **The wording list** (P3-14): a contest's start says "Runs until Fri 14
      Aug, 8 pm" (or "until the end of Sat 15 Aug" for one ending at
      midnight), in the app's date style; deleting an archived board no
      longer suggests archiving it; a rule's delete says "disable it instead",
      as its button does; "should the unit be Money"; the Inbox says "syncs
      cleanly", as the source card does; revoking a TV "shows a pairing code
      instead"
- [x] **Palette results say what they are** (P3-15): Team, Office, Board,
      Rule, Contest, Person… on each row
- [x] **Connect a TV from a channel returns to the channel** (P3-16)
- [x] **"Choose from Assets" for walk-up is shown to admins even while the
      library has no sound or video**, disabled, saying "Add sounds or video
      in Assets to choose one here" (P3-18)
- [x] **Activity's last internal words** (P3-19): kinds in plain words
      (Imported names, Game pieces, Data mappings, Walk-up media, Microsoft
      Teams posts…); a metric by its name, not its key; stored values as words
      ("entity type: people"); and people by name — `actor_name` and
      `target_name` on each row, the address only when the account is gone

**Verified:** 1,137 web tests; dialog, Activity and contest-start tests
updated or added, 1 new backend test. In the running app: Activity naming
people, "metropolis" in the palette as a Team and an Office, the walk-up picker's
hint.

### 10.6 Old numbers say so on the wall — done

- [x] **"Numbers as of Wed 23 Sep"** under a slide's subtitle when the newest
      number behind it is more than a day old (§4 #3) — boards, goals still
      running, contests not yet settled. Any source, corrections included,
      ratios through their parts. A working wall never shows it
      (`channels._as_of`, `as_of` on the slide)

**Verified:** 1 new backend test (old, then fresh), 1 wall test. On the
paired TV: DEALS BOARD with "Numbers as of Wed 23 Sep", and whole amounts
without ".00" beside real cents.

### 10.7 The agent and manager pass after profiles — done

Fourteen pages each, and profiles, as Hal Jordan (an agent) and Natasha
Romanoff (made a manager of Metropolis Sales Team for the run, then put back), with
temporary sessions removed afterwards (§4 #2).

- [x] **No console errors** on any page, for either role
- [x] **Profiles hold their scoping**: the agent gets the public half of a
      teammate's profile and of someone on another team, with no buttons; his
      own with "Only you, your managers and admins see this". The manager gets
      Arthur Curry (her team) in full with Recognise, Give a badge and Edit,
      and Tony Stark (another team) public only
- [x] **Every page an agent cannot use says so** — Users, Reporting and the
      rest show "Not part of your role" with a way Home; no "Show on a TV",
      Edit or Archive on a board for him; the manager's banner is not a link
      she cannot follow
- [x] **Found and fixed**: Home said "you are not on a board" to somebody on
      DEALS BOARD with nothing yet — now "Nothing personal to show yet — no
      numbers, goals or contests of yours this period"

**Verified:** 3,510 backend tests, 1,138 web tests, type check and `alembic
check` clean.

### Phase 10 closed — 2026-10-05

P3-1 to P3-19 are fixed, and the report's three suggestions — last period's
winners on an empty board, an agent and manager pass, and old numbers saying
so on the wall — are built. Along the way the goal page's history chart,
which drew no bars at all, was found and fixed.

## Phase 11 — Signing in, for people outside the tenant — **done**

People not in the Microsoft tenant have no SSO, and today "Require SSO"
blocks every password sign-in but an admin's.

**Decided (5 Oct):** a tenant user is one **synced from the directory**;
admins always keep password sign-in; temporary passwords are admin-only.

1. **Password sign-in is always offered.** "Require SSO" applies only to
   people synced from the directory, and never to an admin (the break-glass
   rule stays). Everyone else signs in with a password, under the
   organization's two-step rule
2. **No new way to learn who is in the tenant.** A refused sign-in still says
   only "Incorrect email or password", with the Microsoft button above it
   and "Signed in with Microsoft before? Use the button above" beneath
3. **Two ways to set somebody up**: the emailed invitation link (as today),
   or an admin setting their email and a temporary password — marked
   "change at first sign-in", so their first screen after signing in is
   choosing their own. Audited; admin only; not offered for somebody who
   must use SSO
4. **A reset link is not offered to somebody who must use SSO** — it would
   give them a password they cannot use
5. One shared password rule (12–72 characters) instead of six copies

### Done

- **11.1 Who must use SSO** — `app/sign_in.py` (`must_use_sso`,
  `must_use_sso_among` for lists). Bound: somebody with a live directory row
  (`DirectoryPerson.user_account_id`, not archived) **or** who has already
  signed in with SSO (`external_subject_id`) — the second added because it
  proves a work account, and without it an organization with SSO but no
  directory sync would bind nobody. Never an admin. `login` refuses with the
  same "Incorrect email or password"; `/auth/providers` now always says
  `local: true` and adds `sso_required`. The login page always shows the
  form: when SSO is required the Microsoft button leads (the one brand
  button), "or with a password", then the form and "Have a company account?
  Use the button above — passwords are for admins and people without one."
  The old "reveal the form" link is gone. The SSO setting's hint says who it
  binds. People list rows carry `must_use_sso`
- **11.2 Temporary passwords** — `user_account.must_change_password`
  (migration f1b5d3c8a469). `POST /users/{id}/temporary-password` (admin;
  `users.reset_password` capability, so a custom role that removes reset
  links removes this too; not for yourself; 409 for somebody who must use
  SSO): sets the password, signs them out everywhere, removes outstanding
  invite and reset links, activates an invited account, audits
  `password.temporary_set` with no password in it. Inviting takes an optional
  `temporary_password` (admin only) and returns no link. While the flag is
  set, `current_user` refuses everything but `/auth/me` and the new
  `/auth/choose-password` ("Choose your own password first."), and the app
  shows only a "Choose your own password" screen; choosing must differ from
  the one given, clears the flag, ends other sessions and audits
  `password.chosen`. Person page: a Password section (`PersonPassword`) with
  "Issue a reset link" and "Set a temporary password" (with "Suggest one":
  four different words and a number, from `crypto.getRandomValues`), handed
  over through the same copy box as links. Invite form: "How they get in" —
  a link, or a temporary password (admins)
- **11.3 No reset link that cannot work** — the reset endpoint 409s for
  somebody who must use SSO; their page says they sign in with their company
  account and offers no buttons
- **11.4 One rule** — `security.NewPassword` (12 characters, 72 *bytes* — 40
  accented letters used to reach bcrypt and 500) for setup, invitations,
  change, reset, choose and temporary; `web/src/passwordRule.ts`
  (`passwordProblem`, `PASSWORD_HINT`) for every form
- **11.5 Invited becomes active the moment there is a way in** (added 5
  Oct, after Phase 12) — `sign_in.activate` and `sign_in.ready_status`.
  Signing in with Microsoft as an invited person used to be *refused* (only
  `active` passed the SSO check); it now accepts the invitation. The
  directory sync linking an invited account by email now makes it active.
  Both withdraw the outstanding invite link. Reactivating a directory person
  — by the sync or by hand — comes back `active`, not `invited`: they sign
  in with their work account. Somebody given a temporary password shows
  yellow "Invited" on the People list (`awaiting_first_sign_in`) until their
  first sign-in, then green "Active"; their page says "Invited — has not
  signed in with the password you set". Tests: `test_invited_to_active.py`
  (5)
- **11.6 Links that say where they went, and point where you are** (6 Oct)
  — invite and reset links are built from the admin's own address (the
  browser's `Origin`; nginx drops the port from `Host`), via
  `tokens.base_url`, so a link made on the server's network address carries
  it with nothing to configure. `APP_URL` is still used when there is no
  usable Origin, when the admin is on localhost and `APP_URL` names a real
  address, and for everything with no admin's browser behind it — Microsoft
  redirect addresses (must match registration), TV links, webhook URLs,
  scheduled emails. The page now says what happened (`handoffWords.ts`):
  "Invitation emailed to sam@… The link is here too…", "Could not email it:
  <reason>. Send Sam this link yourself…", or "ready — send them this link"
  when nothing is set up to send; and warns when the link uses localhost.
  Same for resent invitations and reset links. Tests: `test_link_address.py`,
  `handoffWords.test.ts`
- **11.7 The web address, set in Settings** (6 Oct) — self-hosted means an
  admin should not edit `.env` and restart to say where the app is.
  `organization.public_url` (migration b3d7f5e1c682), edited under Settings
  → General → Web address; `app/public_url.py` (`get`, `chosen`, `default`,
  `normalise`). Every link that leaves the app reads it — Microsoft, Google
  and SSO redirect addresses, the Integrations page's list of them, TV links,
  webhook URLs, Teams/Slack "Open in GoalGetter", scheduled emails, cookie
  Secure flags, invite and reset links — with `APP_URL` as the default while
  it is empty. The field offers "Use the address you are on" (the browser's
  own origin) in one press but never fills itself in; warns when the address
  is localhost; and says the sign-in redirect addresses move with it. Stored
  as scheme and host only — a path, query or credentials is refused with a
  sentence. Warns before saving an `http://` address that is not localhost:
  Microsoft accepts http redirects only for localhost (found as AADSTS50011
  after setting a LAN address), so single sign-on elsewhere needs https.
  Found on the way: starting the Excel or Sheets sign-in had no test. Tests: `test_public_url.py`, `WebAddressField.render.test.tsx`
- Tests: `test_sign_in_rules.py` (18), the require-SSO tests in
  `test_auth.py` rewritten, `loginOptions`, `passwordRule` and
  `PersonPassword` tests

**Phase 11 closed — 2026-10-05.**

## Phase 12 — Dismissing notifications — **done**

**Decided (5 Oct):** all three — the bell, the Inbox and Home's banners.

1. **The bell**: dismiss one, or clear all. Dismissed is gone from the list,
   not deleted — the event's own latch still decides when it is news again,
   so a goal running out of time comes back next period, not next minute
2. **The Inbox and Home's banners** are worked out on every request, so a
   dismissal is remembered per person with what it was about — the source
   and its newest row, the day — and the item comes back on the next sync
   that changes it, or the next day

### Done

- **12.1 The bell** — `notification.dismissed_at` (migration a2c6e4d9b571).
  A ✕ on each row (a sibling of the row, so clearing never opens it; shown
  on hover from tablet width up, always on a phone) and "Clear all" beside
  "Mark all read". No question first: each gives an Undo toast, and "Clear
  all" returns the ids it cleared so Undo brings back exactly those, not
  everything cleared today. Clearing also marks read, so the badge never
  counts something not in the list; Undo puts them back as read. Only the
  bell: the same row is still the win on Recognition, the feed and the
  walls. `POST /notifications/{id}/dismiss`, `/dismiss-all`, `/restore`
- **12.2 The Inbox and Home's banners** — a `dismissal` table, one row per
  person per item, and `app/dismissals.py`. Each item now has a stable `key`
  ("source_quiet:12", "data_stale") and a fingerprint of what it is about,
  worked out by the server when dismissed, never sent by the page:
  - failing source: its error (failing the same way every run is not news);
    overdue source: its last run; quiet source: its newest row; TV offline:
    when last seen; TV showing a code: when it was disconnected; data stale
    on Home: which feeds and their newest rows
  - a count — people waiting to be placed, agents on no team, people quiet,
    goals behind — comes back only when it **grows**; three to two is not
    news
  - every dismissal lapses the next day where the organization is: "not
    today", never "never"
  - per person: one admin putting an item away leaves it for another
  The Inbox has "Not now" on each item and a quiet "N put away until it
  changes, or tomorrow · Show" underneath with "Bring back" on each; the
  sidebar badge counts only what is still asking. Home's banners get a ✕
  and one line, "A notice is put away … · Show it". When the stale-data
  banner is put away, the team card says its own sentence again instead of
  "see above". `POST /inbox/dismiss`, `/inbox/restore`,
  `/dashboard/attention/dismiss`, `/dashboard/attention/restore`
- Tests: `test_dismissals.py` (15), the Inbox render test (Not now, Bring
  back), a new `NotificationBell` render test

**Phase 12 closed — 2026-10-05.**

## Phase 13 — HTTPS out of the box, and a first install that just works — **done**

**Why.** Microsoft sign-in refuses any `http://` redirect address but
localhost (found as AADSTS50011 after setting a LAN address in 11.7), so
without HTTPS, single sign-on worked only on the server itself. The deployment
doc said to bring your own reverse proxy, which the person installing a free,
self-hosted tool usually does not have.

**Decided (6 Oct):** HTTPS ships, optional and off by default, with
GoalGetter's own certificate authority as the base option. A name in a domain
the company already owns (`goalgetter.company.com`) is documented alongside.
Caddy in front of nginx, not nginx alone: nginx terminates TLS but does not
get or renew certificates. The base option needs a private authority, and an
internal server needs Let's Encrypt's DNS challenge. nginx's native ACME
module does only the HTTP challenge, so nginx alone would need our own scripts
plus a certbot container and a reload hook. Caddy costs one container, only
when on (about 14 MB of memory, measured).

1. **The `https` service** — `docker-compose.yml`, profile `https`, switched on
   by `COMPOSE_PROFILES=https` in `.env`. `docker/caddy.Dockerfile` (Caddy with
   the Cloudflare and DuckDNS DNS plugins), `caddy/Caddyfile`, and one small
   file per certificate mode in `caddy/tls/`, chosen by `HTTPS_CERTIFICATE`:
   - `internal` — Caddy's own authority ("GoalGetter Local Authority"),
     issuing and renewing by itself; the root certificate is served at
     `http://<host>/goalgetter-root.crt`, over plain HTTP so a device can fetch
     it before it trusts anything
   - `letsencrypt` — DNS challenge through Cloudflare or DuckDNS, so the
     server never has to be reachable from the internet
   - `files` — `volumes/certs/cert.pem` and `key.pem`
   Plain `http://<host>` redirects to https. nginx keeps serving plain HTTP on
   `APP_PORT` for TVs that cannot trust a private certificate. Certificates
   and the authority live in `volumes/caddy`, so a rebuild keeps the same root.
2. **The app follows it** — `HTTPS_HOST`, `HTTPS_PORT`, `HTTP_PORT`,
   `HTTPS_CERTIFICATE` and `COMPOSE_PROFILES` read from the same `.env`;
   HTTPS counts as on only with the profile on too, so the app agrees with
   whether Caddy is running. With it on, `https://<host>` is the default web
   address (Settings still wins). Session cookies are Secure whenever
   somebody signs in over HTTPS (`sessions.secure_cookie`, from
   `X-Forwarded-Proto`, which nginx now passes through instead of replacing),
   and not on the plain address TVs use.
3. **Settings → General → HTTPS** (`HostingPanel`, `GET /api/hosting`, admin):
   on or off, which certificate, "Download the root certificate" with steps
   for Group Policy/Intune, Windows, Mac, iPhone and Android, the plain TV
   address, and the exact Microsoft redirect address to add in Azure.
4. **A first install that just works** — `setup.ps1` (Windows) and `setup.sh`
   (Mac/Linux) write `.env` from `.env.example` with fresh 64-character
   secrets, `-Https <name>` / `--https <name>` switching HTTPS on in the same
   step; they never replace an existing `.env` (a new database password would
   lock out the database it made). `.env.example` now defaults to the
   production overlay and explains every setting. `.gitattributes` keeps the
   Caddy files and `.env.example` LF.
5. **Docs** — `documentation/20-hosting.md` (new): which option is yours, the
   network basics, options A–F step by step (just this computer; HTTPS with
   GoalGetter's own certificate; your own domain; DuckDNS; your own files;
   your own proxy), the web address, TVs, troubleshooting, and what to back
   up. `16-deployment.md`'s TLS section rewritten for why it now ships. The
   README rewritten, with a step-by-step Getting started.
6. **Verified on a fresh copy** of the repository, run as a new user would:
   `setup.sh --https localhost`, `docker compose up -d` with the production
   build — all five containers healthy; the app on plain HTTP and on HTTPS;
   the redirect; the root certificate download; the certificate verified
   against it; first-run setup; sign-in over HTTPS setting a Secure cookie
   and over the plain address not; `/api/hosting` and the default web address
   both `https://…`. `setup.ps1` checked separately (no byte-order mark,
   secrets filled, refuses a second run). The test copy and its images were
   removed afterwards.
- Tests: `test_hosting.py` (10), `HostingPanel.render.test.tsx` (3)

**Phase 13 closed — 2026-10-06.**

## Phase 14 — The fourth QA pass — **done**

From [qa-ui-pass-4.md](research/qa-ui-pass-4.md) (P4-1 to P4-16). Phases
10–12 and both ways of setting people up checked out; one real bug, three
smaller ones, the rest wording and polish. Kept as required: choosing your
own password at first sign-in (the report agrees).

1. **Stale notifications on late activation (P4-1)** — the hourly job looks
   at last month's goals too (late numbers still count), and announced them
   as if new: "New goal" for a finished month, and "running out of time" at
   100%. Never announce a goal whose period is over, never "running out of
   time" once it has ended; achievements still count late. A test that
   activates somebody after a month ends; then delete the three evidence rows
2. **Correctness** — a suspended person reads "Suspended — can't sign in", not
   "Invited" (P4-2); a tie reads "Level", and "No scores yet" at 0–0 (P4-3)
3. **The bell (P4-4, P4-15)** — the ✕ shown faintly at all times, full on
   hover or focus, and a bigger tap target; focus moves to the next row after
   clearing; toasts that carry Undo last 10 seconds; an emptied bell says
   "All caught up"
4. **Sign-in wording (P4-5 to P4-8)** — the person page's Password copy for
   yourself and for somebody with no password; the Require-SSO hint says that
   signing in with Microsoft once binds you too, and the person page says
   why they are bound; the login page's "Forgotten it? Ask an admin", tab
   title, and a cleared password after a failure; Choose password re-checks
   on submit, has a show toggle and a title
5. **Polish (P4-9 to P4-16)** — one notice put away in both the Inbox and on
   Home; role names capitalised and a toast after "Let them back in";
   palette finds "password" and keeps "Invite people" and "Connect a TV" in
   reach; public profiles show board places the viewer can already see;
   Activity's repeated name and number formats; "Discard changes?" after a
   dropdown change; `GET /api/users/{id}` so a person page loads one person
6. **"Forgot password?" on the sign-in page** (added 6 Oct, asked for with the
   go-ahead) — self-service reset by email

### Done

- **14.1 Stale notifications (P4-1)** — `notifications.detect`: no "New goal"
  once a goal's period has ended, and no "running out of time" once it has
  run out; a late number still counts as a hit. Tests reproduce it: Alice
  activated in October hears only October's goal. Two tests that had leaned
  on today's real date now pin their own. The three evidence notifications
  (1001, 1002, 1003) deleted.
- **14.2 Correctness** — suspended outranks invited, on the person page
  ("Suspended — cannot sign in"), the People list badge, and
  `awaiting_first_sign_in` (P4-2). A head-to-head tie reads "Level", and "No
  scores yet" at 0–0, with nobody highlighted and nobody "behind" (P4-3).
- **14.3 The bell** — the ✕ shown at 40% opacity at all times, full on hover or
  focus, with a 44 px tap target on phones; focus moves to the next row, or
  the panel's heading, after clearing; toasts carrying Undo last 10 seconds
  (`UNDO_TOAST_MS`, which the comment-removal undo uses too); an emptied bell
  says "All caught up" (P4-4, P4-15).
- **14.4 Sign-in wording** — your own person page points at Account and offers
  nothing else; somebody with no password is told so and offered a temporary
  one, not a reset (`has_password`) (P4-5). The Require-SSO hint says signing
  in with Microsoft once binds you too, and a bound person's page says which
  reason applies (`sso_reason`) (P4-6). The sign-in page's tab title, its
  password cleared after a failure, and the "Password updated" notice from a
  reset, which was sent and never shown (P4-7). Choose your password re-checks
  on submit, has "Show passwords" and a title (P4-8).
- **14.5 Polish** — `app/shared_notices.py`: putting Home's stale-data banner
  away puts its sources away in the Inbox; putting sources away in the Inbox
  puts the banner away once none is left; bringing back either brings back the
  other (P4-9). Role names capitalised in the invite form, and a toast for
  each access action (P4-10). The palette's entries carry other words: "new"
  finds Connect a TV and Invite people, "password" finds the new "Change your
  password" and Sign-in & security (P4-11). Public profiles show "On the
  boards": the place on each board the viewer can open, run as the viewer, and
  never the number (P4-12). Activity says the name once when somebody acted on
  themselves, and groups amounts (P4-13). Dialogs ask "Discard your changes?"
  after a dropdown, switch or option change, not only typing (P4-14).
  `GET /api/users/{id}`, and the person page uses it (P4-16).
- **14.6 Forgot password** — `POST /api/auth/forgot-password` and a
  `/forgot-password` page, linked under the password field. Emailed only;
  the same answer for everybody; sent in the background; the link built from
  the Settings address, never the request; 3 per address and 20 per network
  address an hour, never counting towards a sign-in lockout; nothing for
  somebody who must use Microsoft or is suspended or hidden; the invitation
  again for somebody still invited. With no mail server the page says to ask
  an admin (`/auth/providers` → `self_reset`). Dead reset links point at it.
  The old test that no such endpoint exists became a test that the response
  never carries the link.
- Tests: `test_forgot_password.py` (15), detection (4 new), profile places
  (3), shared dismissals (3), `GET /api/users/{id}` (3); web: Forgot
  password, Modal, palette words, Activity amounts, PersonPassword cases

**Phase 14 closed — 2026-10-06.**

## Phase 15 — Real visitor addresses, and a plain port for TVs only — **done**

From [qa-ui-pass-5.md](research/qa-ui-pass-5.md) (P5-1 to P5-13). Phase 14
checked out; the hosting review found one real security problem.

1. **One sign-in limit for the whole organization (P5-1, High, proven)** —
   sign-in, two-step sign-in and Forgot password count attempts by
   `net.client_ip`, the socket peer, which behind nginx is always nginx. So
   "20 failures per network address" is 20 for everybody: anybody who can
   reach the page can keep every password sign-in locked out, admins
   included, and Forgot password stops sending company-wide after 20 an hour.
   Count by the visitor's real address (`net.real_client_ip`, already used by
   the TV allowlist), and skip the per-address limit when the real address
   cannot be known; the per-email limit still guards each account. Sessions
   and the activity log record the real address too.
2. **Both ways in are one proxy hop (P5-2)** — with HTTPS on a request passes
   Caddy → nginx, two hops, while the plain port is one; no single
   `TRUSTED_PROXY_HOPS` fits both. Caddy gets its own unpublished nginx
   listener that takes Caddy's `X-Forwarded-For` as it is; the published
   listener replaces the header instead of appending, so a client can no
   longer prepend anything. The setting stays 1, and is documented in
   `.env.example` and hosting option F, the one case that changes it.
3. **The plain port is for TVs only once HTTPS is on (P5-3)** — `:8080`
   serves `/pair`, `/display/*`, what a wall loads, and the root certificate;
   everything else, the sign-in page included, is a 301 to the HTTPS address.
   Settings says so.
4. **Hosting notes (P5-4 to P5-8)** — the setup scripts check the name given to
   `--https`/`-Https`; Settings shows the root certificate address with a
   moved `HTTP_PORT`; troubleshooting rows for "Too many sign-in attempts" and
   a certificate error when typing the IP; the HTTPS-off panel shows the three
   `.env` lines instead of a file path.
5. **Small notes (P5-9 to P5-13)** — "Suspend" on the suspend confirm; "Keep
   editing / Discard" on the discard prompt, and a form's own Cancel asks too
   when something changed; the palette ranks a title match above a match on
   other words; the expired-link page's title and link spacing; Forgot
   password's own words for a malformed address.

### Done

- **15.1 Limits by the real visitor (P5-1)** — `net.visitor_ip`: the last
  `X-Forwarded-For` hop when the connection came from a trusted proxy, the
  peer when it came straight from the visitor, and **None** when it cannot be
  known — never the proxy's own address. Sign-in, two-step sign-in, Forgot
  password, sessions and the activity log all use it (`client_ip`, the socket
  peer, is now used by nothing but the TV allowlist's own fallback). A limit
  keyed on None is skipped; the per-email limit still guards the account.
  The activity log recorded the socket peer on purpose before ("an address
  nobody can influence"); read by position, the visitor's address is just as
  unforgeable, and it is the one that answers a question.
- **15.2 One hop, either way in (P5-2)** — nginx's config split into
  `default.conf` (two listeners) and `app.inc` (the app, shared). `:80`, the
  published port, appends the peer; `:81`, never published, is Caddy's alone
  and passes Caddy's `X-Forwarded-For` as it is (Caddy ends it with the
  address that actually connected). Caddy now proxies to `web:81`. So
  `TRUSTED_PROXY_HOPS=1` is right with HTTPS on or off. It and
  `TRUSTED_PROXY_IPS` are explained in `.env.example`, and option F says to
  set 2 behind your own proxy, and why only that proxy should reach the port.
- **15.3 TVs only on the plain port (P5-3)** — `docker/web-https.sh` runs
  before nginx starts (official image's `/docker-entrypoint.d/`; mounted in
  dev, copied in the image) and writes the HTTPS address for nginx, using the
  same rule as the app (`https` profile and `HTTPS_HOST`, the name checked
  before it goes into nginx's config). With it set, `:80` serves `/pair`,
  `/display/*`, `/assets/*`, the display, pairing and image API, the two
  calls the app frame makes on load, and `/healthz`; everything else is a
  301 to the HTTPS address. The health check moved to `/healthz`, answered
  by nginx itself. Settings → HTTPS: "The plain address is for TVs only".
- **15.4 Hosting notes** — the setup scripts refuse `--https`/`-Https` with no
  name, with `https://`, or with anything but a host name, each with a
  sentence (P5-4). The HTTPS panel already gave the root certificate's
  address with a moved `HTTP_PORT`; troubleshooting now says so (P5-5), and
  has rows for "Too many sign-in attempts" (P5-6), a certificate error when
  typing the IP (P5-8) and the plain port redirecting. With HTTPS off, the
  panel shows the three `.env` lines instead of a file path (P5-7).
- **15.5 Small notes** — "Suspend" and "Hide" on their confirms (P5-9); the
  discard prompt reads "Keep editing / Discard", and a form's own Cancel asks
  too once something changed, caught by the Modal before the form's handler
  (P5-10); the palette ranks a title match above a match on other words
  (P5-11); the expired-link page is titled "Reset password" and its two links
  sit apart (P5-12); a malformed address on Forgot password gets the same
  answer as any other, and nothing is sent (P5-13).
- **Verified on a fresh copy** with HTTPS on and the production build: all
  five containers healthy; on the plain port, `/`, `/login`, `/goals`,
  `/forgot-password` and a sign-in POST all 301 to `https://localhost:8443`
  while `/pair`, `/display/…`, assets, `/healthz` and the display API answer;
  through HTTPS the session records the visitor (the host, `172.22.0.1`),
  not Caddy (`.4`) or nginx (`.2`), and a forged `X-Forwarded-For` is
  ignored; **the QA attack replayed**: 20 failures, each with a different
  forged address, all counted against the one real visitor, who is then
  refused — and a second visitor (`172.22.0.7`) signs in. The test copy and
  its images were removed.
- Tests: `visitor_ip` (6), limits behind nginx (3), malformed Forgot address
  (4); web: Modal Cancel, palette ranking, HTTPS panel

**Phase 15 closed — 2026-10-06.**

## Phase 16 — When Docker hides the visitor — **done**

From [qa-ui-pass-6.md](research/qa-ui-pass-6.md) (P6-1 to P6-5). Phase 15's
nginx and Caddy changes checked out, including forged headers and path
tricks. One real gap, which Phase 15's own proof missed: its "second visitor"
was another container, with an address of its own, not a device on the
network.

1. **Docker Desktop shows every visitor as its gateway (P6-1)** — confirmed in
   dev: a sign-in through `localhost` and one through the PC's network address
   (`192.168.1.149:8080`) were both recorded as `172.21.0.1`, Docker's bridge
   gateway, not nginx. Docker Desktop's published ports do not keep the
   visitor's address, so the per-address sign-in limit would again be one
   limit for the whole office. Docker Engine on Linux keeps addresses for
   devices on the network (only the server's own traffic arrives as the
   gateway). Fix: the API learns the gateway at start (`/proc/net/route`) and
   treats it as unknown, like the proxy, so that limit is skipped and the
   per-email limit guards each account. Test it; say it in the docs (Linux
   is the better host for a busy office).
2. **The TV IP allowlist has the same blind spot** (found checking P6-1) — on
   Docker Desktop every screen appears as the gateway, so an office range
   refuses every TV, and allowing the gateway allows every device. The
   channel's allowlist field and Settings → HTTPS say when GoalGetter cannot
   see addresses on this host.
3. **302, not 301 (P6-2)** — browsers keep a 301 for good, so turning HTTPS
   off later would leave them going to an address that no longer answers.
4. **`/api/images/` off the plain port's list (P6-3)** — it needs a session a
   TV never has; walls load pictures through `/api/display/{token}/assets/`.
5. **Small** — `--https goals.internal:8443` says to leave the port out and set
   `HTTPS_PORT` (P6-4); the "Too many sign-in attempts" row names Docker
   Desktop as the other reason everybody sees it at once (P6-5).

**Decided (6 Oct):** GoalGetter supports however people host it; nobody is
told to move to Linux. Limits follow what the host lets GoalGetter see, by
themselves, and Settings says which are in force. Per-device addresses on
Windows hosts (a front door outside Docker) are the next conversation.

### Done

- **16.1 Docker is never a visitor** — `net.docker_gateways` (the default
  route's gateway) and `net.docker_networks` (Docker's own subnet), both read
  once from `/proc/net/route`, and `net.hidden_by_docker`, which also takes
  `UNKNOWN_VISITOR_IPS` for a NAT or VPN of the host's own. `visitor_ip`
  returns None for any of them, so the per-device limit is skipped and the
  per-account limit (5 in 5 minutes) guards each account. Verified in dev: a
  failed sign-in is recorded as "unknown", not `172.21.0.1`. The subnet as
  well as the gateway, because sessions from before Phase 15 hold nginx's
  address (`172.21.0.6`), which made the first version of 16.2 say
  addresses were visible here.
- **16.2 Settings says which limits are in force** — `/api/hosting` →
  `addresses_visible`: this request's own address, or any session in the last
  30 days with a real device's address (on Linux the server's own browser
  arrives as Docker while the office's devices do not). The HTTPS panel says
  "limited for each device as well as each account", or, on Docker Desktop,
  that only per-account limits apply and how to get addresses back.
- **16.3 The TV allowlist** — the channel's "Only watchable from" field warns,
  where addresses are hidden, that a list would turn every TV away; a screen
  refused for that reason is told the server cannot see screens' addresses,
  instead of being given Docker's address. Still refused: a list that cannot
  be checked must not let everybody in.
- **16.4 nginx** — 302 instead of 301 for the plain port's redirect (P6-2);
  `/api/images/` off its list (P6-3).
- **16.5 Small** — the setup scripts' port message (P6-4); troubleshooting
  rows for Docker Desktop and for screens refused by a list (P6-5); a
  "Seeing each device" section in the hosting guide.
- Tests: gateway and subnet detection, Docker never a visitor, a device whose
  address survives, `UNKNOWN_VISITOR_IPS`, `addresses_visible` both ways, the
  screen told why; web: the panel both ways

**Phase 16 closed — 2026-10-06.**

## Phase 17 — Hosting options, managed in the app — **done**

**Asked for (6 Oct):** "x notices were dismissed · Show them" instead of
"put away until they change, or tomorrow"; then the four hosting checks and
options discussed after Phase 16, and the README's setup saying what they
are. Per-device sign-in limits should work wherever the host allows it,
without telling anybody how to host.

- **17.0 "N notices were dismissed"** — on Home ("1 notice was dismissed ·
  Show it") and in the Inbox, in place of "put away until it changes, or
  tomorrow". They still come back on a change or the next day.
- **17.1 The connection check** — `/api/hosting` → `you_appear_as`,
  `connection` (visible / docker / unknown), `proxies_seen`, `proxy_hops`
  and where it comes from, `front_door`, `sign_in_limits`. Settings →
  Hosting shows "GoalGetter sees you as 192.168.1.55" with **Check again**; on
  a host where only this visit is hidden but other devices have been seen
  lately (the server's own browser on Linux) it says so instead of warning.
  The HTTPS box's own address warning was folded into it.
- **17.2 "A proxy in front?"** — `organization.proxy_mode` (`direct`,
  `proxy`, or null for `.env`), read by `net.proxy_hops(db)`, which every
  sign-in, session, log entry and the TV allowlist now pass a session to.
  **Refused** unless the request setting it came through a proxy that passed
  an address (two X-Forwarded-For entries), and only checked when it
  changes. Option F now points here before `.env`.
- **17.3 The Windows front door** — Caddy on Windows itself, as the
  **GoalGetterHTTPS** service, in front of Docker Desktop, so devices'
  addresses survive. `windows/install-front-door.ps1` (administrator; `-Remove`
  undoes it): downloads Caddy with the Cloudflare and DuckDNS plugins,
  validates `windows/Caddyfile` against `.env` (`caddy run --envfile`, one
  place for settings), adds `docker-compose.frontdoor.yml` (Docker's ports on
  127.0.0.1 only: plain → nginx :80, HTTPS path → nginx :81, via Compose's
  `!override`), registers the service with restart-on-failure, and opens the
  firewall. `HTTPS_FRONT_DOOR=windows` turns HTTPS on for the app and for
  nginx's TV-only plain port without the `https` profile. Same three
  certificate modes (`windows/tls/`). It never adds its authority to
  Windows' trust store (`skip_install_trust`): the server is trusted like any
  other device. Hosting guide option G.
- **17.4 Wrong-password limits** — `organization.sign_in_limit_account` (3–20,
  default 5) and `sign_in_limit_device` (10–200, default 20), read by
  `rate_limit.limits`; Settings → Sign-in & security.
- **Settings → Hosting**, a new tab: Web address and HTTPS (moved from
  General), the connection check, and the proxy choice. In the palette.
- **README** — "Your hosting options, and what they mean for sign-in": a
  table of Docker Desktop / Docker Desktop + the front door / Linux / your own
  proxy against per-account and per-device limits, and what Settings →
  Hosting shows. Every "Settings → General → HTTPS" in the docs now points at
  Settings → Hosting.
- **Verified** — a fresh copy with the front-door overlay, and the real
  Windows Caddy (2.11.6, both DNS plugins) run in the foreground on loopback
  rather than as a service: the configuration validated from another folder
  (as a service starting in System32 would); `:9088` sent `/login` to the
  HTTPS address and served `/pair`; the root certificate downloaded; through
  HTTPS the session recorded **`127.0.0.1`** — the device as Windows saw it
  — not Docker's gateway `172.22.0.1`, and the connection check said
  "visible" with `front_door: windows`. **Not run here:** the installer's
  service creation and firewall steps, which need an administrator and would
  change this PC; the script parses cleanly. Everything the test created was
  removed, including the `%AppData%\Caddy` it wrote.
- Tests: `test_hosting_settings.py` (12); web: ConnectionCheck (4)

**Phase 17 closed — 2026-10-06.**

## Phase 18 — Cloudflare in front, and one guide per hosting option — **done**

**Asked (6 Oct):** if GoalGetter lives on the server but Cloudflare provides
the certificate for `goalgetter.company.com`, does the setup allow it, and
does it skip Caddy? And the README should keep the standard setup and link
to a guide for every hosting option.

**Answer:** yes, through a Cloudflare tunnel, and Caddy is not used: visitor
→ Cloudflare (certificate) → the `cloudflared` connector on the server →
nginx. Cloudflare by DNS alone (the orange cloud, ports forwarded to the
server) is documented as not set up by default: it needs open ports and an
origin certificate, and visitors would look like Cloudflare.

- **18.1 The tunnel** — a `tunnel` service (`cloudflare/cloudflared`, profile
  `cloudflare`, `TUNNEL_TOKEN` from `CLOUDFLARE_TUNNEL_TOKEN`). Its public
  hostname points at **`web:81`**, nginx's front-door listener, which keeps
  the `X-Forwarded-For` Cloudflare wrote (Cloudflare appends the real visitor
  last) and marks the visit HTTPS. Verified from a container on the Docker
  network, where the connector sits: a sign-in sent to `web:81` with
  `X-Forwarded-For: 6.6.6.6, 203.0.113.50` was recorded as `203.0.113.50`.
  Not verified: a real tunnel, which needs a Cloudflare account and domain.
- **18.2 The app knows** — `HTTPS_FRONT_DOOR=cloudflare` with `HTTPS_HOST`
  turns HTTPS on for links, cookies and the TV-only plain port, as the
  Windows front door does; `/api/hosting` says the certificate is
  Cloudflare's, with no root certificate and no TV address to guess (the
  name leads to Cloudflare, not the server), and Settings → Hosting says
  what TVs can open instead.
- **18.3 One guide per option** — `documentation/hosting/`: own-certificate,
  company-domain, duckdns, certificate-files, own-proxy, windows-front-door
  (moved out of `20-hosting.md`, every link rewritten) and cloudflare-tunnel
  (new: why and why not — reachable from the internet, traffic through
  Cloudflare, one office sharing one public address for the per-device
  limit — the dashboard steps, `web:81`, Cloudflare Access with a bypass for
  TVs, turning it off). `20-hosting.md` is the hub: which option, how it fits,
  before you start, setup guides, the web address, seeing each device, TVs,
  troubleshooting (two rows for the tunnel), backups.
- **18.4 The README** — "Setting up HTTPS on your server" keeps the standard
  setup in full (GoalGetter's own certificate), then "Other hosting options":
  a table linking every guide, and "What each option means for sign-in
  protection" (Linux, Docker Desktop, the Windows front door, a Cloudflare
  tunnel, your own proxy). Every relative link and anchor in the README, the
  hub and the guides checked by script: none broken.
- Tests: `/api/hosting` through a tunnel; the HTTPS panel through Cloudflare

**Phase 18 closed — 2026-10-06.**

## Phase 19 — Hosting, set up in the app — **done**

**Asked (6 Oct):** as much of hosting as possible done from Settings with a
clean, sleek GUI — one click where it can be — instead of editing `.env`.

**The constraint.** Today `.env` is read by containers when they start, so
the app cannot change it. The fix is to make the HTTPS pieces read their
settings from the app, not to give the app control of Docker (the Docker
socket would hand the whole server to the web app — ruled out).

1. **A clean Hosting tab** — one status card ("Reached at https://goals.internal
   · Certificate valid until 12 Jan · Per-device limits on"), status dots, a
   **Change** button, and an Advanced section folded away (web address
   override, a proxy in front). One line per item; detail behind links.
2. **HTTPS set up in the app** — Caddy always in the stack, configured by the
   API through Caddy's admin interface (a private socket only the two share),
   from settings stored in the database: GoalGetter's own certificate, your
   domain via Cloudflare DNS, DuckDNS, or certificate files **uploaded in the
   browser**. The root certificate served by the app itself. nginx's TV-only
   port follows by itself. Tokens stored encrypted.
3. **The Cloudflare tunnel in the app** — paste the token, Apply.
4. **A guided change** — choose how people reach GoalGetter (cards), fill in
   what that needs, then live checks (name resolves, HTTPS answers,
   certificate issued) before anything is switched over; Undo to the
   previous setup.
5. **What stays outside the app**, shown as short checklists with copy
   buttons and checked where possible: the first `docker compose up`, DNS
   records, the firewall, and the Windows front door (a Windows install).

**Decided (6 Oct):** Caddy always in the stack (ports 443 and 80 reserved;
change them once in `.env` if the server uses them); never the Docker socket.
**`.env` and the app kept in step, both ways:** the app writes its hosting
lines into `.env` when they are saved there, and an edit made in `.env` shows
up in the app — whichever changed last wins. Only the hosting lines, never
the secrets. Built step by step, one phase each, committed between:

- **Phase 19** — the redesigned Hosting tab, on today's setup (item 1)
- **Phase 20** — HTTPS configured from the app, and `.env` kept in step (2)
- **Phase 21** — the Cloudflare tunnel from the app (3)
- **Phase 22** — the guided change with live checks and Undo, the
  checklists, and a simpler README (4, 5)

### Phase 19 — the redesigned Hosting tab — done

- **One status card** (`HostingOverview`) in place of the stacked
  explanation boxes: Address (and where it comes from — Advanced, HTTPS, or
  the server's `.env`), HTTPS (on, and whose certificate), Certificate
  ("Valid until 12 Jan 2027", amber inside two weeks, red once expired),
  Sign-in limits (per device and per account, or per account only), and You
  appear as (with ↻). A coloured dot per line; one short note under each.
- **The certificate actually served** — `app/certificate_probe.py` connects to
  the HTTPS address as a browser would (Caddy by its service name, the Windows
  front door through `host.docker.internal`, Cloudflare on the internet),
  reads the certificate's expiry and issuer, two-second timeout, five minutes'
  memory. What visitors get, not what a setting says. Tested against a local
  TLS server with a generated certificate; elsewhere in the suite it is
  stubbed so no test knocks on a real address.
- **For devices and TVs** — only while HTTPS is on: the root certificate
  (Download, with "How to trust it" folded), the TV address with Copy.
  **Microsoft redirect** with Copy, always.
- **Advanced**, folded away: the web address override and "A proxy in front?"
  (now "As set up on the server / No / Yes", one line each). The web
  address field's four boxed warnings became one short line each.
- **Change** lists the ways to set it up, one line each, until Phase 22 makes
  it the guided change.
- `/api/hosting` adds `web_address`, `web_address_from`,
  `certificate_valid_until`, `certificate_issuer`. `HostingPanel` and
  `ConnectionCheck` were folded into the card and removed.
- Tests: the status fields, the probe (2), the card (7); field tests updated

### Phase 20 — HTTPS set up from the app, `.env` kept in step — done

- **Settings → Hosting → Change** is the HTTPS editor (`HttpsEditor`): one
  switch, the name, and the certificate — GoalGetter's own, Let's Encrypt
  (Cloudflare or DuckDNS, token, optional email) or files from IT, uploaded
  in the browser. Only the fields that choice needs. **Apply takes effect at
  once**; afterwards an "Open https://…" link, since the plain address then
  serves TVs only. "Kept in step with .env" when it is. With the Windows front
  door or a tunnel set, it says who handles HTTPS instead. The old list of
  ways is under "Other setups".
- **Caddy always runs, configured live.** `caddy/Caddyfile` is only a start
  (the admin socket, no sites); the API builds the whole configuration
  (`app/hosting_config.py`) and loads it through Caddy's admin API on a unix
  socket in a volume only the two share. `--resume`, so a restarted Caddy
  carries on with the last one; a loop re-checks every 30 seconds. The admin
  socket is in every configuration it sends — without it, admin would move
  to TCP 2019 and the app would be cut off. `caddy/tls/` is gone.
  `COMPOSE_PROFILES=https` is no longer used (harmless if left).
- **nginx follows without a restart.** The API writes nginx's HTTPS address
  into a volume shared with `web`, by a new file renamed over the old one;
  `docker/web-https.sh` watches it and reloads. **Caddy first:** nginx starts
  sending people to HTTPS only once Caddy has taken the change, so a refused
  change never strands the TVs' port.
- **Stored in the database** (`hosting_config`: on, name, certificate, DNS
  provider, token encrypted, email, the last agreed `.env`). `/api/hosting/https`
  GET/PUT (admin; the token never sent back — "Saved" — and null keeps it),
  `/api/hosting/certificate` (PEM as JSON; checked: a certificate, its own
  key, not expired; the key written 600). Audited:
  `hosting.https_changed`, `hosting.certificate_uploaded`.
- **`.env` kept in step, both ways** (`app/env_file.py`). The server's `.env`
  is mounted into the API; the app writes only `HTTPS_HOST`,
  `HTTPS_CERTIFICATE`, `DNS_PROVIDER`, `DNS_API_TOKEN`, `ACME_EMAIL`, `APP_URL`
  and `TRUSTED_PROXY_HOPS` (the last two mirror Advanced), in place, keeping
  Windows line endings, refusing line breaks. **Whichever side moved since
  they last agreed wins**, line by line; the first time, a line set in the
  file wins. `HTTPS_HOST` empty = off, the name kept. Nonsense in the file
  is ignored. **Before the first sign-in** there is no organisation, so
  `APP_URL` and the proxy stay the file's until there is — found in the fresh
  install, where the app wrote its default over `APP_URL`. No `.env`
  mounted, or not writable: the app works alone, and an untouched install
  keeps reading the environment as before.
- **Never root, two folders handed over.** Docker creates a missing folder as
  root, so the API's entrypoint now starts as root only to give
  `volumes/certs` and the nginx volume to uid 1000, then switches to it
  (`setpriv`) before anything runs. The server process checked: uid 1000.
- Setup scripts set only `HTTPS_HOST`; the front door installer no longer
  asks to remove `https` from `COMPOSE_PROFILES`. README, `20-hosting.md`,
  `16-deployment.md` and every hosting guide now say Settings first, `.env` as
  the alternative, and "Locked out? Empty `HTTPS_HOST=`".
- **Verified on a fresh copy, production images, CRLF `.env`:** HTTPS turned
  on by the app → Caddy served `goals.internal` (200), the redirect on 80,
  the TV port 302 to HTTPS while `/display` stayed 200, `.env` written with
  CRLF kept and the secrets untouched; `HTTPS_HOST` edited in the file →
  Caddy and nginx followed within 30 seconds; Caddy restarted → still
  serving; `HTTPS_HOST` emptied → off, TV port a full app again, name kept.
  Every generated configuration (off, own, files, Let's Encrypt with
  Cloudflare and DuckDNS, other ports) adapted and validated by the real
  Caddy image — a fake Cloudflare token is refused by Caddy, which the editor
  shows as "Saved, but HTTPS didn't take it: …".
- Tests: 35 backend (`test_hosting_config.py`: the file, both ways, before
  the first sign-in, each configuration, the API, uploads), 9 for the editor,
  the card's Change test. **Verified:** 3689 backend, 1190 frontend; one
  migration, round-tripped.

**Phase 20 closed — 2026-10-06.**

### Phase 21 — the Cloudflare tunnel from the app — done

- **A fourth choice in the HTTPS editor: Cloudflare tunnel** ("Cloudflare
  holds it; no port opened"). Three steps on the page — create the tunnel in
  Zero Trust, paste what it shows, add the public hostname with
  `http://web:81` (Copy) — then Apply. **Paste the whole install command**:
  the app finds the `eyJ…` token inside and checks it is one (base64 of
  account, tunnel, secret) before saving. Saved tokens show as "Saved" and
  "Tunnel 6ff42ae2…", never the token. A live line after Apply asks every two
  seconds: Connecting… → "Connected · 4 connections to Cloudflare", or why
  not. The status card has a **Tunnel** line too. "Other setups" is down to
  your own proxy and the Windows front door.
- **The `tunnel` service is always running, idle until told** — like Caddy,
  never the Docker socket. Cloudflare's image has no shell, so
  `docker/tunnel.Dockerfile` puts its `cloudflared` (pinned 2026.10.0) on
  Alpine with `docker/tunnel.sh`, as uid 1000. The API writes the token
  (0600, by rename) into a volume only the two share; the script starts
  cloudflared with `--token-file` when there is one, restarts it when it
  changes, stops it when it is emptied, and retries once a minute if
  Cloudflare refused it. It touches `alive` every three seconds and keeps
  cloudflared's output in a capped log, also in `docker compose logs`.
  `COMPOSE_PROFILES=cloudflare` is no longer used; no profiles are left, so
  `COMPOSE_PROFILES` left `.env.example`.
- **Connected, read from cloudflared itself** — its `/ready` on :2000
  (`{"status":503,"readyConnections":0,…}` until it is). Not connected: the
  service not running (heartbeat older than 20 seconds), or cloudflared's
  last error with its `error="…"` detail — and a token Cloudflare refuses
  becomes "Cloudflare doesn't accept this token. Copy it again from the
  tunnel's page."
- **No lockout through Cloudflare either.** nginx's plain port moves to TVs
  only once the tunnel is connected; until then the address the admin is on
  stays a full app. Through Cloudflare the HTTPS address never carries
  `HTTPS_PORT` — people reach Cloudflare on 443.
- **Stored and kept in step.** `hosting_config.front_door` ("", `cloudflare`,
  `windows`) and `tunnel_token_encrypted`; `HTTPS_FRONT_DOOR` and
  `CLOUDFLARE_TUNNEL_TOKEN` joined the `.env` lines kept in step, so an
  install that set up its tunnel in `.env` (Phase 18) carries on, and an edit
  there starts the tunnel within half a minute. The Windows front door is
  still its installer's: with it set, the editor says so and the API refuses
  changes. `Hosting.https_on` no longer counts a front door as "on" by
  itself — HTTPS off now stops a tunnel too.
- `/api/hosting/https` takes `front_door` and `tunnel_token`;
  `GET /api/hosting/tunnel`; `/api/hosting` adds `tunnel`. The API
  entrypoint hands the tunnel volume to uid 1000 with the other two; the
  token file is given to its folder's owner, so the root API of the
  development stack writes one the tunnel can read.
- **Verified on a fresh copy, production images:** a made-up token turned on
  from the app → handed over as uid 1000 / 0600, cloudflared started, and
  Cloudflare itself refused it (`Register tunnel error from server side
  error="Failed to get tunnel"`), shown as the refusal above; the TV port
  stayed a full app (200); HTTPS off → "tunnel: stopped", cloudflared gone;
  a token written into `.env` by hand → started within 30 seconds; the
  service stopped (in 1 second) → "The tunnel service isn't running".
  Connected itself needs a real Cloudflare account: `/ready`'s reply was
  checked against the real cloudflared, and the connected path is tested on
  that shape.
- Docs: `cloudflare-tunnel.md` rewritten Settings first, with the `.env`
  route; README, `20-hosting.md`, `16-deployment.md` updated.
- Tests: 21 backend (`test_hosting_tunnel.py`: the token found in an install
  command, the API, turning off and back to Caddy, the Windows front door
  refused, a token edited in `.env`, every status, the TV port waiting), 3
  for the editor, 1 for the card. **Verified:** 3710 backend, 1194
  frontend; one migration, round-tripped.

**Phase 21 closed — 2026-10-06.**

### Phase 22 — the guided change, tried before it is kept — done

- **Change is three steps** (`HostingChange`, replacing the Phase 20–21
  editor): **How** — six cards (your network, your company's domain, a free
  DuckDNS name, Cloudflare tunnel, a certificate from IT, plain HTTP), the
  one in use marked "now"; **Set up** — only that way's fields, and an
  **Outside GoalGetter** checklist; **Try it**. "Other setups" keeps your own
  proxy and the Windows front door, its install command to copy.
- **The checklist, checked where it can be** (`app/hosting_checks.py`,
  `POST /api/hosting/check`, nothing saved): the name in DNS, and pointing at
  the address this browser reached the server by — the one address the
  server can be sure is its own, since Docker hides the rest; Cloudflare's
  token verify endpoint; DuckDNS proven by clearing its TXT record, which
  never moves the name; the uploaded certificate covering the name (wildcards
  too); the tunnel token. Lookups get a 3-second timeout of their own. What
  can't be checked is still listed: the firewall (Windows and Linux commands
  to copy) and the Azure redirect (to copy), or a warning when Advanced → Web
  address will keep links on another address. **No check blocks**: a failed
  one makes the button "Switch over anyway" — the trial is the safety.
- **Switch over is a trial.** The new setup runs beside the old one until
  kept: Caddy serves the old name and the new (one name keeps one
  certificate — the new), a tunnel that was running keeps running, and
  nginx's plain port is a full app throughout — a way back in whatever
  happens, accepted for at most fifteen minutes the admin chose. **Keep**
  drops the old; **Undo** swaps back; **fifteen minutes without Keep** and the
  hosting loop undoes it by itself (logged). A trial changed again stays a
  trial of where it started; changed back to it, it ends. `hosting_config`
  gained `previous` (the settings before the last change, tokens still
  encrypted) and `trial_until`.
- **Try it, live**, every three seconds (`GET /api/hosting/trial`): HTTPS
  answering through Caddy and whose certificate (a fresh knock, not the
  five-minute memory), or the tunnel connected; and **"Opens from this
  device"** — the page fetches the new address itself (`no-cors`: it can't
  read the answer, but getting one at all is the test), so the device's DNS,
  the firewall and its trust in GoalGetter's own certificate are checked
  together, with the root certificate offered when that fails. A countdown
  until it is undone by itself. The card opens straight onto a trial waiting
  to be decided.
- **Undo, afterwards too.** One step back is always kept: "Undo last change:
  back to Your network · goals.internal", tried like any change
  (`POST /api/hosting/undo` with `trial`); undoing again redoes. **An edit in
  `.env` counts as decided**: it ends a trial, or becomes the change Undo
  takes back. Audited: `hosting.change_kept`, `hosting.change_undone`.
- **Certificates that renew themselves say so.** Caddy's own certificates
  last twelve hours — found on the fresh copy, where the card showed amber
  "Valid until" today, forever. It now says "Renewed automatically", and the
  issuer drops Caddy's " - ECC Intermediate". The issuer is read from the
  organisation first, so Let's Encrypt reads as "Let's Encrypt", not "R11".
- **Verified on a fresh copy, production images, real Caddy:** baseline
  goals.internal → trial new.internal: both names 200, the plain port 200
  instead of 302, `.env` following, the trial check reading the real
  certificate → Keep: goals.internal gone, new.internal 200, the plain port
  302 to it → Undo: back, `.env` too → a trial of new2.internal left to run
  out: undone by the loop within 30 seconds, logged. Screens: How, Set up
  with checks, Try it during the live trial.
- Docs: the README is a short checklist to a running app with the hosting
  options linked; detail moved to `20-hosting.md` (new "Changing it safely")
  and the deployment and dev docs; every guide uses the guided change.
- Tests: 32 backend (`test_hosting_change.py`: Undo and redo, an edit in the
  file undone, the trial serving both, keep, undo, one name one
  certificate, off on trial, tunnels both ways, changed again, back to the
  start, running out, a file edit deciding it, every check, the trial
  checks, the issuer), 14 for the guided change, 3 for the card.
  **Verified:** 3742 backend, 1198 frontend; one migration, round-tripped.

**Phase 22 closed — 2026-10-06. Hosting, set up in the app, is done.**

## Phase 23 — QA pass 7 fixes — **done**

From [qa-ui-pass-7.md](research/qa-ui-pass-7.md) (P7-n), tested on a fresh
install built from the README. Every finding is fixed except P7-18, a note
for IT.

**The three serious ones**

- **P7-1 — `APP_URL` is the fallback again, never an override.** Phases
  20–22 mirrored it onto Advanced → Web address, which beats HTTPS, so an
  install that moved `APP_URL` with `APP_PORT` kept invite links and the
  Microsoft redirect on `http://localhost:8090` after switching to HTTPS.
  Now `APP_URL` is only read — live from `.env` — as the address while HTTPS
  is off, and the Advanced address has its own line, `WEB_ADDRESS`, kept in
  step both ways. **Once, for existing installs**: an Advanced address that
  only repeats `APP_URL` came from the file, and is cleared; one an admin
  chose is kept and written to `WEB_ADDRESS`. The guided change's warning
  about an Advanced address has **Use the HTTPS address instead**
  (`DELETE /api/hosting/web-address`).
- **P7-2 — a `.env` the app can't write is still read.** On Linux it often
  belongs to root (`sudo sh setup.sh`) while the API is uid 1000, and the app
  used to ignore it entirely — so the documented way out, emptying
  `HTTPS_HOST=`, did nothing. Now edits there are always followed; only
  writing stops, and the agreement becomes the file as last seen, so the
  app's own changes aren't mistaken for edits. The first step of Change says
  which state it's in — kept in step, read only (with `sudo chown 1000 .env`
  to copy), or no file — and the log says it once. The container doesn't
  change the file's owner on the host by itself.
- **P7-3 — the Windows front door is switched on last.** The installer used
  to write `HTTPS_FRONT_DOOR=windows` before validating and starting Caddy,
  sending everyone to an address nothing served, for good if validation
  failed. Now it validates, moves Docker's ports, starts the service, waits
  up to 30 seconds for it to answer on the HTTPS port, and only then writes
  the setting; any failure first puts `COMPOSE_FILE` and `FRONT_DOOR_DATA`
  back, removes the service, and restarts Docker as it was. **And the app
  waits too**: with the front door set, or a tunnel, port 8080 stays a full
  app while it isn't answering (the certificate probe knocks on the front
  door; the tunnel's `/ready`), and serves TVs only once it is.

**Medium**

- **P7-4 — an edit in `.env` during a trial is a new trial** from the same
  start, so the old name and the way back in stay up; edited back to the
  start, it ends.
- **P7-5 — said where the admin will look.** A trial nobody kept, undone by
  itself, is in Activity ("GoalGetter undid a hosting change nobody kept",
  with what was tried) and the Inbox ("The change to other.internal wasn't
  kept, so it was undone", until the next change) — `hosting_config.
  trial_expired_at`. An edit in `.env` is in Activity too ("GoalGetter
  followed a hosting change made in .env"). System entries
  (`audit.record_system`) name GoalGetter, not "A deleted account"; every
  hosting action has a sentence in Activity and a "Hosting" filter.

**The tester's answer on port 8080, taken.** During a trial it is a full app
only when coming from plain HTTP, where it is the only way back; coming from
HTTPS, the old HTTPS name (still served) is the way back, and 8080 stays TVs
only.

**Small**

- P7-6: Undo is refused while the Windows front door is set, or would bring
  it back — it's its installer's, like every other change.
- P7-7: **Keep** asks first ("The tunnel isn't connected. Keep it anyway?")
  when the server's own live check says it isn't working.
- P7-8: after an undo, going back is called **Redo**.
- P7-9: a certificate probe that found nothing is remembered 15 seconds, not
  five minutes, so the card catches up with a change just switched over.
- P7-10: the TVs line through Cloudflare uses the real `APP_PORT`.
- P7-11: the Windows firewall command adds `-Profile Domain,Private`.
- P7-12: Caddy's http→https redirect is a 302, as nginx's has been since P6-2.
- P7-13: a tunnel token that only passes the shape check says "Looks like a
  tunnel token · … Cloudflare checks it when you switch over".
- P7-14: first-run setup lands on sign-in with "Your organization is ready"
  and the email filled in; the setup page's tab is "Set up · GoalGetter".
- P7-15: no file paths in the UI.
- P7-16: README step 3 lists all six services; `photo-bulk-test.zip` deleted.
- P7-17: during a trial, the TVs line keeps the setup that is certain.
- P7-18: a note in `20-hosting.md` for IT about managed browser extensions.

**Verified on a fresh copy, production images, `APP_URL` moved to 8090 as
the tester had it:** the card said "from .env", not Advanced; after a trial
and Keep, an invite link and the Microsoft redirect were
`https://goals.internal:8443/…` and `.env` kept `APP_URL` and an empty
`WEB_ADDRESS`; Caddy's redirect 302; a trial from HTTPS kept 8090 302 to the
old name while both names served; `.env` edited mid-trial → `other.internal`
on trial, `goals.internal` still up, Undo pointing at it; run out → back,
with the Activity entries and the Inbox item; `HTTPS_FRONT_DOOR=windows` with
no front door → `/login` on 8090 200 (full app), Undo refused, setting
removed → back to TVs only; `.env` mounted read-only → "read only" shown,
logged once, and emptying `HTTPS_HOST=` turned HTTPS off within 30 seconds.
The installer's new order was parse-checked, not run — it installs a service
on this PC.

Tests: backend for every rule (`APP_URL` never an override, the one-off
clearing and keeping, `APP_URL` live, a read-only file followed and the app's
changes standing, a mid-trial file edit and its way back, Activity and the
Inbox, Redo, Undo refused for the front door, the front door not answering,
the 302); web for Redo, the `.env` states, Keep anyway, clearing the web
address, the firewall profile. **Verified:** 3756 backend, 1204 frontend;
one migration, round-tripped.

**Phase 23 closed — 2026-10-07.**

## Phase 24 — YouTube plays signed in, and by itself — **done**

**Asked (7 Oct):** with a signed-in Chrome profile, some videos still asked to
sign in, and videos waited for a click instead of playing at their set time.

- **Why some asked to sign in:** celebrations (walk-ups, achievements) played
  in YouTube's privacy mode, `youtube-nocookie.com`, which never sees the
  browser's YouTube sign-in. Screens and backgrounds already used the normal
  player — hence "some videos".
- **Why nothing started:** Chrome won't start a page's sound until somebody
  has clicked it. Uploaded clips already fell back to playing muted; the
  YouTube player had no fallback and sat on its play button.
- **One player for every YouTube video** (`YouTubePlayer`): YouTube's normal
  player, from the set moment (`start`/`end`), talked to by `postMessage`
  (`enablejsapi`) rather than with YouTube's script, so none of YouTube's code
  runs in GoalGetter's page. Ready but not started within 1.5 s (or YouTube
  saying autoplay was blocked): **it plays muted**, and the first click or key
  anywhere turns the sound on, for every video after it. Not started even
  muted within 4 s: that is YouTube's "Sign in to confirm you're not a bot",
  and the screen says so. Videos only playable on YouTube (errors 101/150)
  and missing ones are said too. All under the player, never over it
  (YouTube's embed rules).
- Used by celebrations (and their previews), YouTube screens and YouTube
  backgrounds. YouTube screens now start at a link's `t=` and read
  `youtu.be/…?t=` and `shorts/` links, which the old split-on-slash didn't.
- **Checked against the real player** in headless Chrome from a GoalGetter
  page: it answers `listening` with `onReady` and its state; unsigned, it
  shows "Sign in to confirm you're not a bot" and never starts even muted —
  exactly what the new message names.
- `20-hosting.md` → "YouTube on TVs": sign in once in each TV's browser,
  third-party cookies for `[*.]youtube.com` if a signed-in browser still asks,
  and `--autoplay-policy=no-user-gesture-required` or the `AutoplayAllowlist`
  policy for TVs nobody will click.
- Tests: 16 for the player (normal player and start/end, asking until it
  answers, play, muted fallback, YouTube's blocked event, a click unmuting,
  the sign-in case, silent players, embedding refused, other origins
  ignored, loops, link shapes). **Verified:** 1220 frontend.

### The flashing, and sound with nobody clicking

**Asked (7 Oct):** past the sign-in now, but videos flashed the play button,
played a second, flashed again, until the announcement ended. TVs are
view-only: videos must play with sound, from their start, with no clicks.

- **The flashing was a reload every three seconds.** The wall asks for new
  wins every 3 s and redraws; a celebration's start includes how far into it
  this screen joined, which grows, and it was part of the player's address —
  so each redraw reloaded the player. The address is now worked out once per
  video. The old embed did the same; blocked sound had hidden it. **Uploaded
  songs had the same bug**, quieter: their player re-seeked on every redraw,
  a skip every few seconds. They now start once too.
- **A slow start isn't mistaken for blocked sound**: buffering restarts the
  wait (2.5 s), and YouTube's own `onAutoplayBlocked` is subscribed to
  explicitly.
- **Sound with nobody clicking can't be switched on from a page** — Chrome
  allows it after a click in the tab, for an installed app, by the
  `AutoplayAllowlist` policy, or with `--autoplay-policy=no-user-gesture-required`;
  Edge and Firefox also have a per-site setting. An installable app and a
  "click to turn on sound" prompt were both built and taken out again, as
  asked: no install, no prompt on a TV. So: **a one-time setting in each TV's
  browser**, and the app makes the rest obvious.
  - **Each TV reports when its browser held sound back**
    (`POST /api/display/{token}/sound`, written only on change,
    `display.sound_blocked_at`). As the channel opens it asks the browser
    straight away — an `AudioContext` starts "suspended" when sound is held
    back — and every player reports too. TVs & Channels marks it "Sound off"
    with the TV's address to copy and the setting for Edge, Firefox and
    Chrome (PowerShell that adds to IT's allowlist rather than over it).
  - **Nothing asks on the TV.** A small speaker in the corner while something
    with sound is on, crossed out while it's held back. A press that happens
    anyway turns sound on, silently.

### Every sound plays, one at a time — the tab icon and the header link

**Asked (7 Oct):** sound every time a YouTube video plays — in channels too,
backgrounds included — and obvious when it's playing; no install, no pop-up.
The tab's icon to be the logo from Settings, or the Goals target; "GoalGetter"
in the header to go home.

- **Everything with sound plays it** (`wall/sound.ts`): celebrations, YouTube
  screens (muted until now) and YouTube or uploaded-video backgrounds (muted
  until now). **One at a time**: a celebration over a YouTube screen over the
  background. The rotation stays mounted under a celebration, so the others
  are hushed — muted, not paused, so they stay in time — and come back when
  it lets go (the TV now tracks when a celebration has the screen). In an
  editor's preview backgrounds stay quiet.
- **The tab's icon** (`siteIcon.ts`): the organization's logo when one is
  set, in the app and on a TV (through the TV's own link); otherwise
  `favicon.svg`, the nav's Goals target in the brand colour. Back to the
  target on signing out. Checked live: the logo served, 200.
- **"GoalGetter" and the logo beside it link home.** Checked live.
- Tests: the player never reloaded across redraws, buffering not muted;
  across real polls, the YouTube player kept and the uploaded song started
  once; the report sent once; hushed and back; backgrounds with sound on a
  wall, quiet in a preview, quiet for a YouTube screen, muted while sound is
  held back; the corner speaker (never a prompt); the tab's icon; the sound
  help (no install, no click) and its policy command; the report endpoint.
  **Verified:** 3758 backend, 1235 frontend; one migration, round-tripped.

**Phase 24 closed — 2026-10-07.**

## Phase 25 — Recognition becomes Announcements — **done**

**Asked (8 Oct):** the Recognition page renamed Announcements, keeping
everything it does, plus neutral announcements for the TVs — words, a
background (a YouTube video filling the screen with the words on top
included), a YouTube video, MP4 or picture, and a sound effect from the
library — and a tab for those who can send them, to make, edit, save and
resend them. Decided: a takeover sent now; the effect first, then the video's
sound; admins and managers.

- **The page** is Announcements at `/announcements` (old `/recognition` and
  `/achievements` links redirect; the nav has a megaphone). Two tabs: **Wins &
  shout-outs** — the feed, recognising someone, playing a win on a wall, all
  as before — and **Announcements**, shown only with `announcements.send`.
- **The dashboard**: every saved announcement with how often and when it last
  went out and how long it holds; Send, Edit, Delete; New announcement.
  **Send** goes to every TV or to chosen channels.
- **The editor**: headline, more text, seconds on screen (5–120); **Behind the
  words** — the same background chooser as channels (colour, gradient,
  photograph, video loop, YouTube, drawn scene, from the library or
  uploaded); **In the middle** — a video or picture, uploaded or from the
  library, or a YouTube or picture link, with a start time for video; **Sound
  effect** — uploaded or from the library. Beside it, the announcement drawn
  exactly as a TV draws it, at TV proportions, silent, kept up to date as it
  is typed (asked of the server, so what the server checks is checked here);
  **Play it, with sound** full-screen; **Preview on a TV**; Save, or Save and
  send.
- **On the TVs** (`TvAnnouncementScreen`): its background fills the screen,
  darkened behind the words when it's a picture or video so they read at ten
  feet; media in the middle; headline and text sized to the screen they're
  drawn on (container units — which is what makes the editor's small preview
  the TV, smaller). **Sound in order**: the effect first, then the middle
  video's own sound, or else the background's — one at a time. A video
  waiting its turn starts muted in its address, so not a blip escapes; if the
  browser won't let it speak, it plays muted rather than stopping.
- **How it reaches the walls**: `tv_announcement` (designed once) and
  `tv_announcement_send` (each send; NULL channel = every wall), taken into the
  celebration timetable like a replay — not filtered by milestones, quiet in
  night mode like everything else. The feed carries `background` and
  `sound_digest`. Previews on one TV go through `display_previews`.
- **Stored files where links go**: `image:<sha256>` joins `asset:` (sound) and
  `video:`; `media.stored_ref` checks a file is the organization's and the
  kind the scheme says. A shared **`MediaField`** — Upload, From library, or a
  link — is the start of Phase 26.
- **Managers** can now list and upload library files, upload backgrounds and
  browse the background library (for announcements); renaming and removing
  files, the logo, and editing the background library stay admin's.
- `/api/tv-announcements` (because `/api/announcements` is the Teams posts):
  list, create, edit, delete, send, preview, preview on a TV, channels.
  Audited (`announcement.created/updated/deleted/sent`), in Activity.
- Also: a Phase 23 test that answered its fake API in call order, and so
  failed under load, now answers by address.
- **Verified**: an announcement saved, sent to every wall and read back from
  the dev TV's own feed with its background, time and no occasion label,
  then deleted along with its Activity rows. Tests: 12 backend
  (`test_tv_announcements.py`) plus the asset and background permission
  changes; 8 for the screen, 5 for the picker, 4 for the dashboard. **Verified:**
  3772 backend, 1252 frontend; one migration, round-tripped.

**Phase 25 closed — 2026-10-08.**

## Phase 26 — Screens the way you picture them — **done**

**Asked (8 Oct):** picture, GIF and video screens fill the TV and replace the
background; a message is massive text in the middle; YouTube screens are the
player at full size with "start at" and "play for"; backgrounds customisable
on every other screen, prefilled with what the item itself has.

- **On the TV**: picture screens fill the screen (crop) or show all of
  themselves over a blurred copy; uploaded videos and YouTube fill it from
  their start, with sound by the wall's rules; a message's headline is drawn
  as large as it fits (the fitter used to step down to the smallest size at
  every length, because tight lines let descenders spill past the box).
- **In the editor**: kind cards with what each puts on the TV; pictures and
  videos from upload, the library or a link (`image:`/`video:` accepted for
  screens, and the right sort checked for each kind); **Start at** and **Play
  for** typed as 1:30 or 90; **Background** up front, saying where it comes
  from ("From the leaderboard “Sales floor”: a photograph", worked out by the
  server in the preview) with **Use a different background** starting from
  that one, and **Back to …**; other styling defaults to the item's own
  settings rather than the organization's. Time on screen and schedule come
  after the look.
- `channel_screen.media_start_seconds`, `fit`; up to an hour on screen.
- Tests: 7 backend (library picture and video, YouTube start and length, the
  hour limit, the right sort per kind, where the background comes from).
  **Verified:** 3779 backend, 1252 frontend; one migration, round-tripped.

**Phase 26 closed — 2026-10-08.**

## Phase 27 — Upload or library everywhere, and the whole library — **done**

- **One picker everywhere.** Shout-out media (sound, video or picture) and
  celebration rule media use `MediaField`; the server turns any of them into a
  clip (`media.clip_of`), and a stored picture shows on the wall. Sound
  effects gained **Upload**; team logos and badge art an **+ Upload** tile
  (`UploadToLibrary`); the logo and people's photos **From library**
  (`LibraryPictures`, `POST /api/users/{id}/photo/from-library`). Screens,
  walk-ups and backgrounds already had both.
- **Profile pics** shelf in Assets: every person's photo, uploaded or synced,
  named and labelled with where it came from; changed on their page, never
  removed here. `GET /api/assets?photos=true` — the pickers leave photos out.
- **In use** now counts past wins (and so replays, which replay them) and TV
  announcements, so removing a file can't break one.
- **Built-in** shelf: the starter sounds (playable), the bundled backgrounds
  and the badge art — what's offered wherever those are chosen.
- Tests: 3781 backend, 1253 frontend.

## Phase 28 — Who signs in, and offices from Microsoft 365 — **done**

- **Only admins and managers can sign in** (Settings → Sign-in): password,
  SSO and invitations all refuse anyone else, and agents' open sessions end
  (`organization.sign_in_leaders_only`; `sign_in.leaders_only_refuses`).
- **Offices and departments** (Integrations → Microsoft 365, under tenant
  sync): each office and department synced people have, with how many, sent to
  an office or team here — existing, or new and named after it. People not yet
  on a team are sorted now and after every sync (`directory/places.py`;
  `office.m365_office`, `team.m365_department`).
- **In an office, on no team** (`user_account.office_id`, from Microsoft 365
  or a Team linked as an office): counted among the office's agents, with
  "⚠ x agents aren't on a team" on Offices, opening the list to put each on a
  team or make a new team for all of them.
- **Announcement video, two places**: a YouTube or MP4 *background* plays full
  screen behind the words, with its sound (drawn by the announcement's own
  players, so it waits for the effect); the *middle* plays in a smaller window
  below the words (it was a zero-width box); YouTube backgrounds loop by going
  back to their start rather than as a one-video playlist (which YouTube often
  wouldn't play), and take a **Start at** (`background.start`); Shorts, live, music and `m.` links are
  accepted; a refused draft clears the preview rather than leaving the last one; video screens and YouTube
  backgrounds cover any TV shape with no letterbox; a pasted YouTube link is
  kept as its id (a link cut to 40 characters played nothing).
- Tests: 3784 backend, 1253 frontend.

---

## Sequencing principles

1. **Vertical slices, not horizontal layers.** Finish goals end to end — table, service, API, UI — before starting leaderboards. A half-built feature across every layer can't be tested or demoed.
2. **Auth and permissions first.** Retrofitting authorization is how data leaks happen. Every feature built after 1c inherits enforcement for free.
3. **CSV import and seed data before any connector.** Seed data is how goals and leaderboards get built and tested before Phase 3 exists. CSV import is the fallback that makes every deployment viable in the meantime. Agent self-reporting is never built.
4. **Ship a deployable artifact from Phase 0.** If it's always deployable, it never needs an integration phase.
5. **Resist Phase 4 pulling forward.** Badges and points are the most fun part to build and the least necessary. The loop has to work first.

## Open questions

None open. The three asked at the start, and how they were settled:

1. ~~**Should Phase 2 competitions come before Phase 2 notifications?**~~
   **Notifications first** — 2a, with competitions as 2e, separate from goals.
2. ~~**Is dark mode worth Phase 2 scope?**~~ **Dark from Phase 0**, as the
   default; light mode was written then and made reachable in 4c.
3. ~~**Should there be a demo/seed data mode?**~~ **Yes** —
   `python -m app.seed_demo`, built in 1d-ii.

## Related docs

- [00-overview.md](00-overview.md)
- [01-architecture.md](01-architecture.md)
- [19-dev-workflow.md](19-dev-workflow.md)

### Microsoft Teams integration — done

Set up from its own **Microsoft Teams** card on the Integrations page, in three
tabs — Announcements, Teams & offices, People. It began as a section inside the
Microsoft 365 connection; three jobs in a dialog that already held sign-in,
directory sync, mail and Excel put all of them a long scroll away, so it moved
to a card of its own, the way Excel and Snowflake have theirs. The Microsoft
365 dialog points at it.

- [x] **Announcements**: any number of channels, each with what to announce
      (goals hit, recognition, competition wins, achievements, prize-wheel wins,
      birthdays, anniversaries) and whose (everyone, one office, one team)
- [x] **Pick a channel from a list**: sign in the account posts come from
      once, then choose Team → channel from the Teams it is in. A Workflows
      link is still offered, for a channel the account is not in or an
      organization that never connected Microsoft 365
- [x] Posted as an Adaptive Card — what it is for, whose, the detail, and a
      link back — once per win however often the job runs
- [x] A test button, retries with backoff, and the channel's last error shown
- [x] **Switched in the Microsoft 365 box, set up in its own card** — the
      Microsoft 365 dialog has a "Use Microsoft Teams" switch and an Email
      switch, beside Excel, and its card ticks them off when on. Off, nothing
      is posted and Teams is not read on a schedule; the settings are kept, and
      can be set up before switching on. Each channel keeps its own switch.
      Pausing drops what happens while paused rather than saving it up
- [x] **One Email card** for both ways mail goes: the Microsoft 365 mailbox
      and its test, and your own mail server (SMTP) as the other path and the
      fallback
- [x] **Microsoft Teams and channels as teams or offices**: every Team, and
      every private or shared channel, has one "Use as" choice — not used, a
      team (new or existing), or an office (new or existing)
- [x] **Here compared with Microsoft 365**: each person's team and office in
      GoalGetter, where Microsoft Teams puts them, and the office their
      Microsoft 365 profile names — filtered to what differs by default
- [x] **Hand moves kept**: "Follow Teams" or "Keep here" for anybody moved by
      hand, and nobody moved back by a sync
- [x] **Team membership on the Teams tab**: open a team to see its people,
      add by name or remove in place; a team that follows Microsoft Teams says
      so, and lists who Microsoft Teams puts there that is not there

> **Posted through a Workflows link, not Microsoft Graph.** Graph can post to a
> channel only as a signed-in person — `ChannelMessage.Send` is delegated only,
> and application-only posting is reserved for migrations — so the feed would
> depend on one real account and stop the day it was disabled. Microsoft
> retired channel webhooks on 22 May 2026 and made Workflows the replacement: a
> link created inside the channel that accepts a card. It needs no app
> registration and no permission, so the panel works for an organization that
> never connected Microsoft 365.

> **Picking a channel means posting as an account**, and that is Microsoft's
> rule, not ours: Graph lets an application post to a channel only while
> importing old messages, so everyday posting is always *as somebody*. So both
> ways are offered, and the page says which is which. The account gets its
> own sign-in — like Excel's, through the same callback, so the registration
> needs no new address — with three delegated permissions that need no admin
> consent: `Team.ReadBasic.All`, `Channel.ReadBasic.All`, `ChannelMessage.Send`.
> The picker lists only Teams the account is in, a channel is saved only once
> Microsoft confirms the account can see it, and a refused post says to add
> the account to that Team (and channel, if private). The card is the same
> object either way — Graph just wants it as a string in an attachment.

> **One label, two permissions.** `Channel.ReadBasic.All` is now wanted as an
> app role (reading every Team's channels for the mirror) *and* delegated (the
> posting account). The permission list used to de-duplicate by name, which
> would have silently dropped one; it now de-duplicates by name and kind.

> **The link is a credential**, because it carries its own signature. It is
> stored encrypted, never sent back to a browser in full — the settings show
> its host and last few characters — and changing it means pasting a new one.

> **Only Microsoft's own webhook hosts are accepted**, checked at save and again
> before every post. The server posts to whatever link is stored, so an
> unchecked one would let it be pointed at any address inside the network it
> runs on. A look-alike host (`logic.azure.com.example.net`) does not pass, and
> redirects are not followed.

> **Queued, then posted, in separate steps.** A win is written down as owed to
> a channel before any network call, so a pass that dies half-way loses
> nothing; a unique index on (channel, win) makes a second post impossible
> rather than unlikely, and the key is the wall's one-per-win key, so a team
> goal reaching eight people is one card. A new channel — or one switched back
> on — starts from now rather than being flooded with the backlog. A failure is
> retried at 1, 5 and 15 minutes and an hour, then given up on, with the
> channel's own error on the settings page ("the Workflow may have been deleted
> — make a new link").

> **Only public, celebrated events can be chosen**, so the rule that keeps
> "behind on your goal" off the wall keeps it out of the channel. Typed text is
> escaped before it goes in a card, so "5* service" does not turn bold.

> **A test posted to Microsoft from the suite, once.** The fake poster was
> swapped in after the function had bound the real one as a default argument.
> The functions now look it up when called, and every test is guarded: an
> announcement post without a fake fails the test instead of leaving the
> machine.

> **Kept by Microsoft's ids, not names.** The first version matched Team
> names against the groups directory sync stores. A rename broke it, and it
> could not see channels at all. Directory sync now keeps a snapshot of the
> Teams structure — Teams, channels, who is in them — by id, so a rename
> renames, and something deleted in Microsoft is marked gone rather than
> silently emptying a team.

> **Read as little as the job needs.** A scheduled sync reads the list of
> Teams, the members of what is linked, and the channels of Teams with a linked
> channel — nothing at all when nothing is linked. Every channel of every Team
> is read only when an admin presses "Read from Microsoft Teams". Standard
> channels' members are never read: they are exactly their Team's, which is
> also why a standard channel cannot be linked. Channels need
> `Channel.ReadBasic.All` and `ChannelMember.Read.All`, added as optional
> permissions; without them Teams still work and the panel says what to grant.

> **The Teams & offices list is searchable three ways**: All (each Team with
> its channels folded under it — a search opens any Team whose channel
> matched), Teams only, or Channels only with the Team each lives in; sorted by
> in use first, name, or most people; filtered to what is in use. **Standard
> channels are listed but not usable** — "Same people as the Team" — because
> hiding them made it look as if channels were not being read at all.

> **A refused channel permission is asked about once**, not once per Team:
> the first 403 stops the pass, and the note names the permission *kind* the
> connection's mode needs, and who can grant it.

> **A channel beats the Team it is in.** "Phoenix" can be an office and its
> private "Closers" channel a team inside it — and that team is put in that
> office. Somebody in two linked places that disagree is a conflict, left
> where they are and listed. **Only a team ever changes, never a role.**

> **Offices come through teams.** A person here has a team and a team has an
> office, so an office link never moves anybody on its own. It sets the office
> of teams linked inside it, and otherwise shows up in the comparison.

> **Two sources of truth, so the mirror only undoes its own work.** It records
> where it put each person. If their team no longer matches, somebody moved
> them by hand — on the Teams tab, a profile, or the People page — and the
> mirror leaves them there and lists them: "Follow Teams" hands them back,
> "Keep here" pins them. Somebody already on a linked team who is not in its
> Microsoft Team, and was never placed by the mirror, is listed too rather than
> removed. None of this touched how a person's own details are edited: the
> evidence of a hand move is only that their team is not the one the mirror
> chose.

> **The Teams tab uses the People page's bulk "assign team"**, so a move made
> there is audited and guarded identically — a second door to one action. A
> manager sees their own team's people only, so only their own team opens.

> **Unattended mirroring is off by default.** It moves people between teams,
> and a deployment should watch that happen once before trusting it to happen
> at three in the morning.

**Verified:** 3054 backend (41 for the mirror and structure), 853 frontend.
Four migrations, round-tripped.

