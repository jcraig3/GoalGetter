# GoalGetter Documentation

Design and specification docs. Written before implementation so decisions are recorded with their reasoning, and revisitable while building.

**Every doc ends with an "Open questions" section.** Those are genuine decisions still to be made — resolve them and replace the question with the decision and why.

## Read in this order

| # | Doc | Phase | What it covers |
|---|---|---|---|
| 00 | [Overview](00-overview.md) | — | What the product is, who uses it, what's in and out of scope |
| 01 | [Architecture](01-architecture.md) | — | Stack, containers, repo layout, why Postgres |
| 02 | [Data Model](02-data-model.md) | — | Full schema with reasoning |
| 18 | [Roadmap](18-roadmap.md) | — | Phase-by-phase build order |

## Phase 1 — Foundation

| # | Doc | What it covers |
|---|---|---|
| 03 | [Auth & Users](03-auth-and-users.md) | Local accounts, OIDC/SSO, sessions, invites, first-run setup |
| 04 | [Organizations & Teams](04-organizations-and-teams.md) | The org tree, membership, managers, org settings |
| 05 | [Roles & Permissions](05-roles-and-permissions.md) | Role matrix, scope resolution, enforcement |
| 06 | [Metrics Engine](06-metrics-engine.md) | Metric definitions, facts, aggregation, ranking, import |
| 07 | [Goals & Targets](07-goals-and-targets.md) | Targets, periods, recurrence, progress, pace |
| 08 | [Leaderboards](08-leaderboards.md) | Ranking, scoping, movement, TV display |
| 10 | [Dashboards](10-dashboards.md) | Personal, manager, and admin dashboards; reporting |
| 12 | [Design System](12-design-system.md) | Color, type, spacing, components, motion, accessibility |
| 13 | [Frontend Architecture](13-frontend-architecture.md) | React structure, data flow, routing, state |
| 14 | [API Conventions](14-api-conventions.md) | URLs, pagination, errors, modeling rules |

## Phase 2 — Engagement

| # | Doc | What it covers |
|---|---|---|
| 09 | [Competitions](09-competitions.md) | Formats, lifecycle, scoring, result freezing |
| 11 | [Notifications & Celebrations](11-notifications-and-celebrations.md) | Events, rate limiting, celebrations, channels |

## Phase 3 — Integrations

| # | Doc | What it covers |
|---|---|---|
| 15 | [Data Integrations](15-data-integrations.md) | Connector framework, field mapping, sync, per-connector plans |

## Operations

| # | Doc | What it covers |
|---|---|---|
| 16 | [Deployment](16-deployment.md) | Docker, configuration, upgrades, backup |
| 17 | [Security](17-security.md) | Threat model, credentials, authorization, privacy |
| 19 | [Dev Workflow](19-dev-workflow.md) | Local setup, codegen, migrations, testing, CI |
| 20 | [Hosting](20-hosting.md) | Running it for your office: which option, network basics, TVs, troubleshooting |
| — | [hosting/](hosting/) | One setup guide per option: [own certificate](hosting/own-certificate.md), [company domain](hosting/company-domain.md), [Cloudflare tunnel](hosting/cloudflare-tunnel.md), [DuckDNS](hosting/duckdns.md), [certificate files](hosting/certificate-files.md), [own proxy](hosting/own-proxy.md), [Windows front door](hosting/windows-front-door.md) |

## The core loop

Every feature should trace back to this. If it doesn't, question whether it belongs in v1.

```
DATA IN  ──▶  MEASURE  ──▶  MOTIVATE
manual        metrics       leaderboards
CSV/Excel     goals         competitions
connectors    periods       recognition
```

## Locked-in decisions

Settled, and reflected throughout these docs:

| Decision | Choice |
|---|---|
| Stack | React + Vite + TypeScript · FastAPI + SQLAlchemy · PostgreSQL 18 |
| Containers | `web`, `api`, `postgres`, `db-backup`, `https` (Caddy, configured live by the app), `tunnel` (cloudflared, idle until the app turns a tunnel on). APScheduler in-process, no broker |
| Auth | Local accounts **and** OIDC/SSO from day one |
| Term for tracked people | **Agents** (`agent` is the org role) |
| Visual direction | **Dark-first**, light theme in Phase 2 |
| Agent self-reporting | **Not built.** Agents never write metric data |
| Data entry | Connectors (Phase 3) → CSV/Excel import (Phase 1) → audited admin correction |
| Out of scope | Pricing, billing, subscriptions, telemetry — permanently |

## Terminology

Used consistently in code and UI:

| Term | Meaning |
|---|---|
| **Agent** | A person whose performance is tracked. Also the org role `agent`. |
| **Manager** | Runs a team. Org role `manager`; also a `team_membership` with `team_role = 'lead'`. |
| **Admin** | Runs the tool. Org role `admin`. |
| **Viewer** | Read-only account for TV displays. Org role `viewer`. |
| **Team** | A node in the org tree — division, department, team, or pod. |
| **Member / membership** | Structural only: a `team_membership` row. Not a role name. |
| **Metric** | What gets measured (`metric_definition`). |
| **Fact** | One measured event (`metric_fact`). |
| **Goal** | A target value for a metric, over a period, assigned to someone. |

## Conventions in these docs

- **Phase** is marked at the top of each doc.
- **Reasoning is included, not just decisions.** The "why" is what's valuable in six months.
- **Open questions are real.** They're flagged rather than silently decided.
- Cross-references use relative links so they work in any Markdown viewer.
