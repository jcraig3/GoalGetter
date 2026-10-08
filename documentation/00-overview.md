# GoalGetter — Product Overview

## What it is

GoalGetter is a **self-hosted sales performance and gamification platform**. A business runs it inside their own network, connects it to wherever their sales data lives, and uses it to set goals, track agent and team performance, run competitions, and surface live leaderboards.

It is modeled on [Spinify](https://spinify.com), but built as standalone software a company owns and operates rather than a SaaS subscription.

## Who uses it

| Persona | What they do in GoalGetter |
|---|---|
| **Admin / Ops** | Installs and configures the app, connects data sources, defines metrics, creates teams, invites users |
| **Manager / Team Lead** | Sets goals for their team and agents, creates competitions, reviews performance, coaches |
| **Agent** | Sees their own goals and progress, their rank, active competitions, and recent wins. Read-only — agents never enter their own numbers. |
| **TV display** | A wall screen showing live leaderboards. Authenticates with a signed URL, not an account. |

## The core loop

This is the product in one sentence, and every feature should trace back to it:

> **Data comes in → it becomes a metric → a goal is set on that metric → progress is ranked and displayed → hitting it is recognized.**

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  DATA IN     │    │   MEASURE    │    │  MOTIVATE    │
├──────────────┤    ├──────────────┤    ├──────────────┤
│ CSV / Excel  │    │ Metrics      │    │ Leaderboards │
│ Sheets / M365│───▶│ Goals        │───▶│ Competitions │
│ Snowflake/SQL│    │ Targets      │    │ Recognition  │
│ Webhook / API│    │ Periods      │    │ TV display   │
└──────────────┘    └──────────────┘    └──────────────┘
  CSV: Phase 1         Phase 1             Phase 2
  rest: Phase 3
```

## Scope

### In scope for v1

- Local user accounts **and** OIDC/SSO sign-in
- Flat teams, with one team per agent
- Three roles — admin, manager, agent — with managers scoped to their own team
- Metric definitions and a time-series metric store
- Goals and targets at individual, team, and organization level
- Live leaderboards with flexible scoping and ranking
- Time-boxed competitions
- Personal and manager dashboards
- In-app notifications and goal-hit celebrations
- TV / full-screen display mode
- Data ingestion via CSV and Excel import, plus an audited admin correction path
- Data ingestion via live connectors (Sheets, M365, Snowflake, SQL, webhook) — **Phase 3**
- Dark-first UI, with a light theme in Phase 2
- Single-command Docker deployment

### Explicitly out of scope

- **Pricing, billing, plans, or subscription management.** This is internal software. There is no paywall, no tiers, no license enforcement.
- **A public marketing site.** If one is ever needed it is a separate project.
- **Multi-tenancy across companies.** One deployment serves one company. (The schema keeps an `organization` root record so this stays *possible* later, but nothing is built for it.)
- **Being a CRM.** GoalGetter reads performance data; it does not manage deals, contacts, or pipelines.
- **Payroll or commission calculation.** It may display a commission-shaped number, but it is not a system of record for pay.
- **Native mobile apps.** The web UI is responsive; that is the mobile story for v1.
- **Agent self-reporting.** Agents never write their own numbers. Self-reported data is gameable, and a leaderboard nobody believes is worthless. Data comes from integrations; admins can correct bad rows, and every correction is audited and visibly marked.

## Non-goals worth stating

- **Not a BI tool.** It answers "who is ahead and are we going to hit the number," not arbitrary analytical questions. Resist requests to add a general query builder.
- **Not real-time to the millisecond.** Leaderboards refresh on a cadence measured in seconds to minutes. Sales data does not change fast enough to justify streaming architecture.

## Guiding principles

1. **It must work with zero external dependencies.** A business with no CRM and no warehouse should be able to install it, upload a spreadsheet, and get value. Every live connector is an accelerator, never a requirement.
2. **The person deploying it is not a developer.** `docker compose up`, fill in a few environment variables, done. Every configuration decision that can have a sane default, has one.
3. **Ship the loop before the breadth.** One metric flowing end to end from entry through celebration is worth more than ten half-built connectors.
4. **Trust is the product.** If a leaderboard is wrong, or shows someone data they shouldn't see, the tool is finished. Correctness and permission scoping come before features.

## Phasing

| Phase | Focus | Ships |
|---|---|---|
| **1** | Foundation | Auth (local + SSO), org structure, roles, users, metrics, goals, leaderboards, dashboards, CSV/Excel import, seed data |
| **2** | Engagement | Competitions, notifications, celebrations, TV display mode, richer reporting |
| **3** | Integrations | Connector framework, Google Sheets, Microsoft 365, Snowflake, generic SQL, scheduled sync + field mapping |
| **4** | Depth | Points/badges/levels, AI coaching insights, advanced analytics |

Detailed breakdown in [18-roadmap.md](18-roadmap.md).

## Related docs

- [01-architecture.md](01-architecture.md) — stack and system design
- [02-data-model.md](02-data-model.md) — database schema
- [18-roadmap.md](18-roadmap.md) — phase-by-phase build order
