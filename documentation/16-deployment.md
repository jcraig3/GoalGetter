# Deployment & Configuration

**Phase 1.** The person deploying this is not a developer. `docker compose up` and it works.

## Target experience

```bash
git clone <repo> && cd GoalGetter
sh setup.sh            # or, on Windows: powershell -ExecutionPolicy Bypass -File setup.ps1
docker compose up -d
# open http://localhost:8080 → first-run setup
```

The setup script writes `.env` from `.env.example` with fresh random secrets,
and `.env.example` already points at the production overlay. Step by step in
[the README](../README.md#getting-started); HTTPS and serving other computers
in [20 Hosting](20-hosting.md).

One command, and it is the same command used in development. `.env` decides
which overlay loads:

```bash
COMPOSE_PATH_SEPARATOR=:
COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml   # production
```

Session cookies are HTTPS-only whenever somebody signs in over HTTPS (Phase
13), so turning HTTPS on protects them with nothing else to set.
`SECURE_COOKIES=true` makes them HTTPS-only everywhere, which also stops
sign-in over the plain address.

## Services

```yaml
services:
  web:        # nginx: serves the built SPA, proxies /api → api
  api:        # FastAPI + uvicorn
  postgres:   # PostgreSQL 18
  db-backup:  # cron, nightly pg_dump into volumes/backups
  https:      # Caddy: HTTPS in front of web; serves nothing until HTTPS is on
  tunnel:     # cloudflared: idle until Settings turns a Cloudflare tunnel on
```

Six containers. No Redis, no message broker, no worker.
The `webbuild` watcher exists only in the development overlay.

```
browser ─https─▶ https (Caddy) ───────────┐
browser / TV ─http :8080──────────────────┴─▶ web (nginx) ─┬─ /api/* ─▶ api (FastAPI) ─▶ postgres
                                                           └─ everything else ─▶ the built app
```

The app and its API share one address, so there is no CORS and the session
cookie stays simple. The API runs migrations on start; `db-backup` dumps
Postgres nightly at 3am. The API configures Caddy, and the Cloudflare tunnel,
while it runs, so changing HTTPS needs no restart.

Only `web` (8080) and `https` (443 and 80) publish ports. Postgres is reachable only on the internal Docker network — a database exposed to the host is how self-hosted tools end up on Shodan.

**nginx does not depend on the API being up.** It resolves the upstream at
request time through Docker's DNS, so it starts regardless and returns 502
until the API answers, rather than refusing to boot. Verified by starting nginx
with the API stopped.

## Configuration

All configuration is environment variables, loaded via `pydantic-settings` so the app fails fast at startup with a clear message if something required is missing or malformed. A container that starts and then misbehaves is far worse than one that refuses to start and says why.

### Required today

```bash
COMPOSE_PATH_SEPARATOR=:
COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml
POSTGRES_PASSWORD=              # generate: openssl rand -hex 32 (setup.sh does it)
ENCRYPTION_KEY=                 # generate: openssl rand -hex 32 (setup.sh does it)
```

`COMPOSE_PATH_SEPARATOR` is pinned because Compose splits `COMPOSE_FILE` on
`;` on Windows and `:` elsewhere — a Windows path contains a colon. Pinning it
keeps one `.env` format working on both.

### Core

```bash
APP_PORT=8080
SESSION_LIFETIME_DAYS=7
BACKUP_KEEP=14
```

### Addresses and HTTPS

```bash
APP_URL=http://localhost:8080   # default web address; Settings → Hosting → Advanced → Web address overrides it
SECURE_COOKIES=false            # true: HTTPS-only cookies even on the plain address
HTTPS_HOST=                     # the name it serves: goals.internal, goalgetter.acme.com; empty = off
HTTPS_CERTIFICATE=internal      # internal | letsencrypt | files
HTTPS_PORT=443                  # these two need `docker compose up -d` after a change
HTTP_PORT=80
DNS_PROVIDER=                   # letsencrypt only: cloudflare | duckdns
DNS_API_TOKEN=
ACME_EMAIL=
HTTPS_FRONT_DOOR=               # cloudflare (a tunnel) | windows; empty = Caddy
CLOUDFLARE_TUNNEL_TOKEN=        # the tunnel's token, from Cloudflare's dashboard
LOG_LEVEL=info
```

**Settings → Hosting → Change** sets the HTTPS lines and keeps `.env` in step
both ways (Phase 20): the app writes them there, and an edit made there is
picked up within half a minute, applied live. Whichever changed last wins.
A change is tried before it is kept (Phase 22), from the app or from `.env`.
`WEB_ADDRESS` and `TRUSTED_PROXY_HOPS` follow the Web address and proxy choice
the same way; `APP_URL` is only read, as the address while HTTPS is off.
A `.env` the app can read but not write is still followed (Phase 23). Every one is explained, with each hosting option, in
[20 Hosting](20-hosting.md).

**`ENCRYPTION_KEY` is deliberately separate from anything session-related.**
Rotating a session key is routine and merely logs everyone out; rotating an
encryption key means re-encrypting every stored credential. Coupling them would
make the routine operation dangerous.

Sessions need no signing key: the cookie is an opaque random token and the
database row is the source of truth.

**Secrets are validated at startup** via `pydantic-settings`, so a missing or
malformed value stops the container with a clear message rather than letting it
start and misbehave later.

### Database

```bash
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=goalgetter
POSTGRES_USER=goalgetter
POSTGRES_PASSWORD=              # required
```

Pointing at an external managed Postgres is supported — set the host and remove the `postgres` service.

### SSO

**Not configured here.** SSO settings live in the database and are managed by
an admin in the app, alongside the data connectors — see
[03-auth-and-users.md](03-auth-and-users.md). Nothing to set at deploy time.

The only related environment variable is `ENCRYPTION_KEY`, which encrypts the
stored client secret.

### Email (optional)

```bash
SMTP_ENABLED=false
SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM_EMAIL=goalgetter@company.com
SMTP_USE_TLS=true
```

**Everything must work without SMTP.** Invites fall back to a copyable link the admin pastes into Slack. Email is an enhancement, never a dependency.

### Scheduling

```bash
SCHEDULER_ENABLED=true          # disable on a second replica
LEADERBOARD_CACHE_SECONDS=30
DASHBOARD_CACHE_SECONDS=60
```

`SCHEDULER_ENABLED` matters: if the API is ever run with two replicas, both would run every scheduled job. One replica owns the scheduler.

## Migrations

Alembic runs automatically on container start, before uvicorn binds its port.

**Why automatic:** requiring an admin to run a migration command after every upgrade guarantees someone forgets and reports a broken app. Postgres has transactional DDL, so a failed migration rolls back completely and the container exits with a clear error rather than starting in a half-migrated state.

The startup sequence:

```
1. Wait for Postgres to accept connections
2. alembic upgrade head
3. Seed default metrics if the table is empty
4. Start uvicorn + scheduler
```

**Downgrades are not supported.** Rolling back means restoring a backup. Reversible migrations are written where practical, but "restore from backup" is the honest, tested path — and it's what a business ops admin will actually do.

## Upgrades

```bash
git pull
docker compose pull        # or build
docker compose up -d
```

Migrations apply on start. Brief downtime is acceptable; this is an internal tool, not a public service. Zero-downtime deployment adds a lot of complexity for a tool nobody is using at 3am.

**Backup before upgrading.** The README says so prominently and provides the command.

## Backup & restore

```bash
# Backup
docker compose exec -T postgres pg_dump -U goalgetter goalgetter | gzip > backup.sql.gz

# Restore
gunzip -c backup.sql.gz | docker compose exec -T postgres psql -U goalgetter goalgetter
```

A `scripts/backup.sh` wrapper ships with the repo, along with a documented cron example. Backing up is entirely the operator's responsibility and the documentation must be unambiguous about that.

All state lives in Postgres. Uploaded avatars and import files live in a mounted volume, backed up separately — documented as a second, equally required step.

## Reverse proxy & TLS

**HTTPS ships, optional and off by default (Phase 13).** An `https` container
(Caddy) sits in front of `web`, with a certificate from its own authority,
from Let's Encrypt, or from files. How to choose and set each one up:
[20 Hosting](20-hosting.md).

**Configured live, from the app (Phase 20).** Caddy always runs.
`caddy/Caddyfile` is only its starting point: the admin socket, no sites. The
API builds the real configuration (`api/app/hosting_config.py`) and loads it
through that socket, shared with the API only; Caddy runs with `--resume`, so
a restart keeps it. nginx's plain port follows within seconds. No Docker
socket, and nothing is ever restarted. **A change runs beside the old setup
until kept (Phase 22):** Caddy serves both names, and coming from plain HTTP
the plain port stays the full app, for at most 15 minutes —
[Changing it safely](20-hosting.md#changing-it-safely).

**The Cloudflare tunnel, the same way (Phase 21).** The `tunnel` container
always runs. The API writes the token to a volume only the two share, and
`docker/tunnel.sh` starts, restarts or stops `cloudflared` when it changes
(`docker/tunnel.Dockerfile`: cloudflared 2026.10.0 on Alpine, uid 1000).
Caddy serves nothing while a tunnel is on, and nginx's plain port turns
TV-only only once the tunnel is connected.

**Why it ships now, when it did not.** The first version left TLS to "whatever
the organization already runs". But GoalGetter is meant to be installed by
somebody who is not running a reverse proxy, and Microsoft sign-in refuses
any `http://` address but localhost. Without HTTPS out of the box, SSO only
worked on the server itself.

**Why Caddy beside nginx, rather than nginx alone.** nginx terminates TLS
perfectly well, but it does not get or renew certificates. The base option
needs a private certificate authority that issues and renews certificates by
itself. Let's Encrypt on a server the internet cannot reach needs a DNS
challenge. In nginx, both mean scripts of our own plus a certbot container
and a reload hook. nginx's newer native ACME module only does the HTTP
challenge, which needs the server reachable from the internet. Caddy does
both built in, and costs one container (about 14 MB of memory). nginx keeps serving the app exactly as before, plain HTTP
included, on `APP_PORT`, for TVs.

**Visitor addresses (Phase 15).** nginx has two listeners: the published
one, and port 81 used only by Caddy. Each hands the API exactly one hop of
`X-Forwarded-For`, so `TRUSTED_PROXY_HOPS=1` is right with HTTPS on or off.
Sign-in limits, sessions and the activity log use that visitor address
(`net.visitor_ip`). They used to use the socket peer, which behind nginx is
always nginx, so one person could lock everybody out. With HTTPS on, the
published port serves TVs only and redirects everything else. The app writes
the HTTPS address to a file nginx shares; `docker/web-https.sh` watches it and
reloads nginx.

**Already running your own proxy?** Leave HTTPS off in Settings → Hosting and
point it at `APP_PORT`. It must:
- append the visitor to `X-Forwarded-For`, with `TRUSTED_PROXY_HOPS=2` in `.env`
- forward `X-Forwarded-Proto` (the app marks session cookies Secure from it)
- allow 25 MB uploads and 120-second requests
- and an admin sets **Settings → Hosting → Advanced → Web address** to the proxied address

## Resource requirements

| Deployment | CPU | RAM | Disk |
|---|---|---|---|
| Small (< 50 users) | 2 cores | 2 GB | 10 GB |
| Medium (< 250) | 4 cores | 4 GB | 50 GB |
| Large (< 1000) | 8 cores | 8 GB | 200 GB |

Disk is dominated by `metric_fact`. Rough estimate: ~200 bytes/fact including indexes; 500 users × 50 facts/day ≈ 1.8 GB/year. Modest, but it grows forever without a retention policy.

## Health & observability

```
GET /api/health        liveness — process is up
GET /api/health/ready  readiness — database reachable, migrations current
GET /api/health/detail admin-only: sync status, scheduler state, queue depth
```

Structured JSON logs to stdout, for whatever the organization already collects. No bundled log stack.

**No telemetry, no phone-home, no analytics.** This is self-hosted internal software; it must be deployable in an air-gapped network and must not report anything outward. This is a hard rule.

## Development mode

```bash
docker compose up
```

Differences: Vite dev server with HMR instead of built static files, uvicorn `--reload`, Postgres port published for a local client, `SECURE_COOKIES=false`, debug logging. Documented in [19-dev-workflow.md](19-dev-workflow.md).

## Open questions

1. **Should a single-image variant exist** (nginx + FastAPI + supervisord) for admins who find Compose intimidating? Simpler to run, worse to operate. *Leaning: no — Compose is standard enough.*
2. **Kubernetes manifests / Helm chart?** *Leaning: not for v1; revisit if a deployment asks.*
3. **Retention policy** — should old `metric_fact` partitions be dropped automatically? *Leaning: never automatic. Provide a documented command and an admin UI warning. Silently deleting a customer's history is unacceptable.*
4. **`docker compose up` with no `.env`** — should it generate secrets automatically and print them? Friendlier, but risks a "temporary" install becoming production with keys in the logs. *Leaning: refuse to start, print exactly what to run.*

## Related docs

- [01-architecture.md](01-architecture.md)
- [17-security.md](17-security.md)
- [19-dev-workflow.md](19-dev-workflow.md)
