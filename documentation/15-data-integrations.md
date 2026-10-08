# Data Integrations

**Phase 3.** Deliberately built last, with full attention — this is the hardest part of the product.

## Why it's last

Every connector needs somewhere to put data and a reason to care about it. Building the ingestion engine before goals, leaderboards, and dashboards exist means building against an imagined consumer. By Phase 3, `metric_fact` has a real schema, a real query pattern, and real users complaining about real gaps — the connector interface can be designed against facts rather than guesses.

Phase 1 ships manual entry and CSV/Excel import, which means the product is fully usable with zero integrations. Every connector is an accelerator, never a requirement.

## SSO is the first integration

Microsoft 365 / Entra is configured by an admin **in the app**, not in the
source or the environment, and it belongs on the **Integrations** page rather
than in a separate settings screen. Nothing about connecting a provider is
hardcoded — a client sets up their own tenant themselves.

That is not just a UI placement decision. The same Entra connection does two
jobs:

| Job | Phase |
|---|---|
| Authenticate people (OIDC sign-in) | 1a-v |
| Import people as agents (directory sync) | later |

Both need the same things: an admin-entered issuer and client credentials, an
encrypted secret, a "test connection" button, and a status indicator. So SSO's
config storage (`sso_config`, `crypto.py`) is the first instance of the pattern
the connector framework generalises — not a special case sitting beside it.

**Design consequence:** when the `Connector` protocol below is built, SSO
should be reviewed against it. If it can be expressed as a connector with an
extra capability, it should be. If not, the protocol is probably too narrow.

## The core mental model

> **Connectors do not query the source when a leaderboard loads.**

A sync job pulls from the source on a schedule, normalizes it, and writes rows into `metric_fact`. Postgres is the single source of truth the app reads from.

```
┌──────────┐   pull    ┌───────────┐  normalize  ┌─────────────┐   read   ┌─────────┐
│ Snowflake│──────────▶│  Sync job │────────────▶│ metric_fact │─────────▶│   App   │
│ Sheets   │ scheduled │ (extract, │   + map     │ (Postgres)  │  always  │         │
│ M365     │           │  dedupe)  │             │             │          │         │
└──────────┘           └───────────┘             └─────────────┘          └─────────┘
```

Querying live would be slow, would hammer the customer's warehouse with credit-consuming queries, and would make the entire product unavailable whenever the source was unreachable. Syncing means a warehouse outage degrades data freshness rather than breaking the app.

## The connector interface

Every connector implements the same contract. Adding one is writing a driver, not touching the engine.

```python
class Connector(Protocol):
    key: str                    # 'google_sheets', 'snowflake', ...
    display_name: str
    config_schema: type[BaseModel]      # non-secret settings
    credential_schema: type[BaseModel]  # secrets, stored encrypted

    def test_connection(self, config, credentials) -> ConnectionResult: ...
    def discover(self, config, credentials) -> list[SourceField]: ...
    def fetch(self, config, credentials, since: datetime | None) -> Iterator[SourceRow]: ...
```

Four methods, each earning its place:

- **`test_connection`** — the "Test" button. Connection failures must surface at configuration time with a specific error, not silently at 3am.
- **`discover`** — returns available columns/fields so the mapping UI can be built from real data instead of asking the admin to type column names.
- **`fetch`** — yields rows. Takes `since` for incremental sync. **Returns an iterator, not a list** — a warehouse query can return a million rows and must not be materialized in memory.
- Schemas are Pydantic models, so config forms and validation are generated rather than hand-built per connector.

> If you've built WordPress plugins, this is the same shape: the core defines the hook, each connector registers itself and implements the interface. The engine never knows which connector it's talking to.

## Field mapping

The genuinely hard part. Source data looks nothing like `metric_fact`.

```
SOURCE ROW (Snowflake)                    METRIC FACT
┌────────────────────────┐               ┌──────────────────────┐
│ REP_EMAIL              │──────────────▶│ subject_user_id      │
│ CLOSE_DATE             │──────────────▶│ occurred_at          │
│ AMOUNT                 │──────────────▶│ value                │
│ OPPORTUNITY_ID         │──────────────▶│ external_id          │
│ STAGE = 'Closed Won'   │──filter──────▶│ (row included?)      │
│ (all columns)          │──────────────▶│ raw (JSONB)          │
└────────────────────────┘               └──────────────────────┘
                            metric: revenue_closed  (chosen by admin)
```

A mapping specifies:

| Mapping | Purpose |
|---|---|
| **User identity** | Which column identifies the person, and how it resolves (email, external ID, full name) |
| **Date** | Which column is `occurred_at`, plus its timezone |
| **Value** | Which column is the number — or a constant `1` for count-style metrics |
| **Metric** | Which metric this maps to; one source can feed several |
| **Filters** | Row-level conditions (`STAGE = 'Closed Won'`) |
| **Dedupe key** | Which column is `external_id` |

### User identity resolution

The most common failure mode in the entire product. A `user_identity` table maps external identifiers to GoalGetter users:

```sql
CREATE TABLE user_identity (
    id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id        BIGINT NOT NULL REFERENCES user_account(id) ON DELETE CASCADE,
    data_source_id BIGINT REFERENCES data_source(id),
    identity_type  TEXT NOT NULL,   -- email|external_id|full_name
    identity_value TEXT NOT NULL,
    UNIQUE (data_source_id, identity_type, identity_value)
);
```

**Why a table instead of matching on email every sync:** the same person is `j.craig@acme.com` in Salesforce, `jcraig` in the dialer, and `Jayden Craig` in a spreadsheet. Resolving by email alone silently drops every row from systems that use a different identifier.

**Unmatched rows are quarantined, never dropped.** They go to a review queue with a "map this identity" action that writes a `user_identity` row and reprocesses. Silently discarding rows produces an import that reports success while the numbers are quietly incomplete — the worst possible failure, because nobody knows to look.

## Sync

### Scheduling

APScheduler, per data source, cron expression (default hourly).

### Incremental where possible

`fetch(since=last_successful_sync_at)` lets a connector pull only changed rows. Enormous difference for a warehouse — a full daily reload of two years of history costs real money in Snowflake credits.

Not every source supports it. Google Sheets has no change timestamp, so sheets are read in full. The connector declares its capability; the engine adapts.

### Idempotency

Re-running a sync must not duplicate data. Guaranteed by a partial unique index:

```sql
CREATE UNIQUE INDEX idx_fact_dedupe
    ON metric_fact (data_source_id, external_id, occurred_at)
    WHERE external_id IS NOT NULL;
```

Writes use `INSERT ... ON CONFLICT DO UPDATE`. Re-syncing a corrected deal amount updates the existing fact instead of adding a second one.

This is why `external_id` mapping is required, not optional, for any connector that can supply one.

### `sync_run`

Every run is recorded — start, end, status, rows read/written/skipped/quarantined, and error detail. Without this, "why did the numbers change" and "why is the data stale" are unanswerable, and both questions will be asked constantly.

```sql
CREATE TABLE sync_run (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    data_source_id  BIGINT NOT NULL REFERENCES data_source(id),
    started_at      TIMESTAMPTZ NOT NULL,
    finished_at     TIMESTAMPTZ,
    status          TEXT NOT NULL,   -- running|success|partial|failed
    rows_read       INTEGER DEFAULT 0,
    rows_written    INTEGER DEFAULT 0,
    rows_skipped    INTEGER DEFAULT 0,
    rows_quarantined INTEGER DEFAULT 0,
    error_message   TEXT,
    error_detail    JSONB
);
```

### Failure handling

- Retry with exponential backoff, 3 attempts.
- Sustained failure → data source marked `error`, admins notified.
- **A failed sync never wipes existing data.** Stale data with a visible staleness indicator beats an empty leaderboard.
- Partial success is a real state: rows that mapped cleanly are written; problems are quarantined and reported.

## Connectors

> **Status, August 2026 — fourteen connectors ship.** Spreadsheets: Google Sheets,
> Excel. CRM: HubSpot, Salesforce, Pipedrive, Close. Helpdesk: Freshdesk, Zendesk.
> Calls: Gong, Aircall. Databases: generic SQL (PostgreSQL, MySQL, MariaDB,
> Snowflake, and Redshift/SQL Server as build extras) and a Snowflake preset.
> Anything else: webhook and a generic JSON API connector.
>
> **The order below is the plan as written before any of it existed, and two of its
> judgements turned out to be wrong.** Kept rather than rewritten, because what
> changed and why is the useful part:
>
> * **"Do not batch the CRMs. Each is genuinely a project."** True of hand-written
>   clients; false once the REST engine existed. HubSpot, Salesforce and Pipedrive
>   landed together in one file of about three hundred lines, because a provider is
>   a `RestSpec` rather than a codebase. What is still true is the part underneath
>   it — each needs somebody to read its documentation and understand its paging and
>   its date filter — and that no unit test can verify any of it against a live
>   account.
> * **CSV / Excel upload as the Phase 1 fallback** was dropped entirely. Data comes
>   from integrations; a spreadsheet somebody uploads by hand is a leaderboard that
>   is wrong by lunchtime.
>
> The section that replaced this one is "3b's real shape: four engines, not
> thirty-five connectors" in [18-roadmap.md](18-roadmap.md).

Build order, easiest to hardest:

### 1. CSV / Excel upload — *Phase 1*
No auth, no scheduling, no network. Ships early as the fallback that makes every deployment viable. `pandas` + `openpyxl` handle real-world files — merged cells, junk header rows, mixed types.

### 2. Google Sheets
OAuth 2.0 + `google-api-python-client`. Proves the connector abstraction end-to-end (OAuth, discovery, mapping, scheduling) at the lowest complexity. **Build this first among live connectors.**

Deployment friction is real: each self-hosted install needs its own Google Cloud OAuth client. Document it thoroughly, and support a service-account path as the lower-friction alternative for internal use.

### 3. Generic SQL
SQLAlchemy against a customer-supplied connection string plus a `SELECT`. Postgres, MySQL, MSSQL, Oracle through one code path.

**Read-only credentials are mandatory and must be stated loudly in the UI.** Also enforce a statement timeout so a bad query can't pin the customer's production database.

### 4. Microsoft 365 / Excel Online
`msal` + Microsoft Graph. Requires an Entra app registration per deployment. Pairs naturally with the OIDC work from Phase 1, since it's the same identity platform.

### 5. Snowflake
`snowflake-connector-python`. Technically straightforward — the same shape as generic SQL. The care is operational: warehouse selection, statement timeouts, and being explicit about credit consumption. A connector that silently costs a customer money in warehouse compute is a serious problem, so surface estimated query cost and default to conservative schedules.

### 6. CRMs — Salesforce, HubSpot, Dynamics
Each is genuinely a project: OAuth, object models, custom fields, API rate limits, pagination quirks. **Do not batch these.** One at a time, each fully finished. Prioritize by what the deploying business actually uses.

### 7. Webhook / generic API — *worth considering earlier*
An inbound endpoint that accepts pushed metric facts with an API key. Effectively free to build compared to any OAuth connector, and it lets a technical customer integrate anything themselves. Strong candidate to move earlier in the order.

## The Integrations page — built (shell)

Modelled on Spinify: a grid of **tiles**, one per integration, each showing a
logo, a name, a category, and one sentence about what it does. The page is the
single place any external system gets connected — SSO, email, and later every
data connector.

```
Connected            ← only rendered when something is
  ┌──────────────┐
  │ ▣ Microsoft  │  Connected
  │ Identity     │
  │ Single sign… │
  │ [⚙ Settings] │  ← reopens the same panel
  └──────────────┘

Available
  ┌──────────────┐   ┌──────────────┐
  │ ✉ Email      │   │ ▣ Snowflake  │
  │ [Coming soon]│   │ [Connect]    │
  └──────────────┘   └──────────────┘
```

**Connecting moves the tile between two lists.** Nothing is hidden and nothing
is duplicated — "what is on?" is answered by which list a tile is in, and the
button changes job with it: `Connect` before, a settings cog after.

**Connections belong to the organization, not the person who made them.**
Whoever signs in while connecting is the account GoalGetter uses from then on,
for everyone. If an admin connects Excel with their own Microsoft account, that
account is the one every sync runs as. Stated on the page itself, because it is
the detail most likely to surprise someone — and it is why leaving employees
need their connections reassigned rather than simply deleted.

**The long-term shape of "Connect" is signing in, not a credentials form** — and
for Microsoft it now is. An admin presses one button, enters a code on Microsoft's
own sign-in page, and the app registration is created for them: redirect URIs,
permissions, admin consent and secret, none of it typed. What made this possible
was not admin consent through Graph, which was always the plan, but realising there
was no chicken-and-egg to solve — Microsoft's command-line client is a public client
already present in every tenant, so the first sign-in needs nothing registered. See
open question 2 below, which this reverses.

The credential form is still there, directly underneath, and is not going anywhere:
it is what a blocked tenant, a restricted client and an under-privileged admin all
fall back to, and it is the only path for every provider that publishes no such
client — Google and Salesforce included.

`CATALOGUE` in `pages/Integrations.tsx` is data, so adding an integration is one
entry plus a panel rather than another block of near-identical tile markup.
Anything without a backend yet carries `available: false` and renders a disabled
**Coming soon** — visible rather than absent, so an admin looking for "how do I
make invitations email themselves?" finds the answer even when the answer is
"not yet".

### Email lives here too

Not a data source, but the same shape: an external system, connected once, for
the whole organization. Putting it on a separate settings screen would mean two
places to look for "connect something external".

**One Email card, two ways out.** Through Microsoft 365 — switched on in the
Microsoft 365 box, with the mailbox and its test in the Email card — or through
your own mail server (SMTP). Microsoft is tried first when it is on; SMTP is the
path for everybody else and the fallback if a Microsoft send fails. Microsoft
Teams follows the same rule: **switched in the Microsoft 365 box, set up in its
own card** under "Messaging and notifications".

It unblocks self-service password reset, which is currently admin-issued
precisely because there is no way to deliver a link — see
[03-auth-and-users.md](03-auth-and-users.md#passwords--built). Until SMTP
exists, invitations and resets produce a link to copy, which works with no mail
server at all.

## Configuration UI

The one-click goal from the original brief. Realistic target: a five-step wizard where the only typing is choosing what to measure.

```
1. CHOOSE SOURCE      grid of connector cards
2. CONNECT            OAuth popup, or credential form + [Test Connection]
3. SELECT DATA        pick sheet / table / object — populated by discover()
4. MAP FIELDS         auto-suggested mappings + live preview of 10 rows
5. SCHEDULE           frequency + [Run First Sync]
```

Two things make this feel like one click:

**Auto-suggested mapping.** `discover()` returns column names; the mapper suggests based on name similarity and data shape — a column named `EMAIL` containing `@` is the user identifier; a date column is `occurred_at`. The admin confirms rather than composes.

**Live preview.** Show 10 real rows transformed into facts, including which users they resolved to, *before* anything is written. Mapping errors are caught in three seconds instead of after a sync writes 40,000 wrong rows.

### Data source management

Per source: status, last sync time and outcome, rows synced, next scheduled run, quarantine queue count, sync history, and manual "Sync now."

**Staleness must be visible in the app, not just this page.** If a leaderboard is showing 3-day-old data because a sync has been failing, that leaderboard says so. Silently stale data is the fastest way to lose trust in the tool.

## Security

Full detail in [17-security.md](17-security.md). The rules:

- **Credentials are never stored in `data_source.config`.** They go to a separate encrypted store, keyed by `credentials_ref`, encrypted with a key from the environment.
- **Credentials are never returned by the API.** Not masked — absent. The UI shows "configured" or "not configured."
- OAuth refresh tokens are encrypted at rest and rotated per the provider's rules.
- Every connection requires TLS. No plaintext database connections.
- SQL connectors: read-only credentials, statement timeouts, and the supplied query is parameterized and never string-concatenated.
- Every data source change is audited.

## Open questions — all answered

Kept with their answers rather than deleted, because two of the five were decided
*against* the leaning written here, and what changed somebody's mind is worth more
than the conclusion on its own.

**1. Should the webhook/API connector move to Phase 2?** *Leaning was yes.* — **It
stayed in Phase 3, and went first within it.** Not for cost reasons: it was built
first as the honest test of the abstraction, because a connector that is *posted to*
rather than polled breaks every assumption a pull-shaped framework makes. Building
it first meant the framework had to accommodate it rather than being retrofitted.
The one thing this exposed, and it is not small: **a self-hosted deployment usually
cannot receive a webhook at all** — a SaaS provider on the public internet cannot
reach an internal server. So SQL was reordered ahead of Google Sheets, because an
outbound database connection is the only integration many companies can have.

**2. OAuth app registration burden — is there an alternative?** *Answered "no" once,
and that answer was wrong.* — **There is one, and it is now the primary path for
Microsoft.** The reasoning that produced "no" is still sound as far as it goes: a
shared app would mean us holding a client secret on a customer's behalf, which is
precisely the hosted relay this product does not have. What it missed is that a
*public* client holds no secret at all — and that Microsoft publishes one, present
in every tenant, which its own command-line tooling signs in as. So an admin can
sign in through it, and GoalGetter spends that token creating **their** app
registration through Graph: the application, its redirect URIs, its permissions,
admin consent and its secret, in one press. Nothing is registered in advance by
anybody, nothing is hosted, and no secret ships in this repository — which is what
makes it viable for software somebody pulls onto their own server. See
[api/app/entra.py](../api/app/entra.py).

Two things did not change. **One registration still serves everything** — since 3e,
one Entra app signs people in, reads their Excel *and* syncs their people — and the
automatic path creates exactly that one. And **the manual path stays first-class**,
directly beneath the automatic one on the same panel, because three real situations
fall back to it: a tenant whose Conditional Access blocks device sign-in, a tenant
that restricts Microsoft's command-line client, and an admin without the role. A
setup that only works when the happy path works is a setup that strands people.

The one genuine limit is worth writing down, because it will surface as a support
question. Microsoft lets a **Cloud Application Administrator** create all of this
and consent to every *delegated* permission, but reserves consent for its own
*application* permissions — `User.Read.All`, `GroupMember.Read.All` — to a
**Privileged Role Administrator**. Directory sync therefore ends with two
permissions outstanding unless somebody senior runs it. That is reported as a named
list rather than as a failure: everything else is created and working.

Service accounts survive as the documented alternative for Google Sheets, where a
company has no Workspace. Google has no equivalent of Microsoft's public client, so
that provider is still registered by hand.

**3. Historical backfill — how far back?** *Leaning: ask, default 90 days.* —
**Exactly that.** Four choices from *nothing* to *a year*, defaulting to 90 days,
imported once on the first sync. What the leaning did not anticipate is the
protection that turned out to matter more: a first sync with a big backfill is
precisely where a source hits its row cap, and that used to report itself as a clean
success while the watermark moved past rows nobody had read. It now reports
`partial` and holds the window.

**4. Two sources feeding one metric — detect and warn, or block?** — **Detect and
warn.** Blocking would be wrong: two sources feeding one metric is legitimate and
common — two regions, two systems mid-migration. Double-counting the *same event*
twice is the actual hazard, and `external_id` is what prevents it.

**5. Transformation depth — expressions or direct mapping?** *Leaning: direct
mapping plus filters.* — **Direct mapping plus filters, and one multiplier.** The
multiplier is the one concession, and it earns its place because unit conversion is
not a transformation anybody chooses: a source reporting cents into a metric holding
currency needs `× 0.01` or every number is a hundred times too big. An expression
language would have been a second place where "which column is the person" could be
decided.

## Related docs

- [02-data-model.md](02-data-model.md)
- [06-metrics-engine.md](06-metrics-engine.md)
- [17-security.md](17-security.md)
