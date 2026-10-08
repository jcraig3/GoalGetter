# Security & Privacy

GoalGetter holds individual performance data about named employees and credentials to a company's data warehouse. Both are sensitive.

## Threat model

What we're actually defending against, in priority order:

1. **A curious employee** seeing performance data for people outside their scope. The most likely incident by far, and an authorization problem.
2. **A compromised account** — phished or reused password.
3. **Stored connector credentials leaking**, giving an attacker access to the company's warehouse or CRM. The highest-impact failure.
4. **An internet-exposed instance** being attacked directly. Many deployments will be internal-only; some won't be, and we can't assume.
5. **A malicious insider with admin access.** Not preventable, but must be *detectable* — hence the audit log.

Explicitly out of scope: nation-state adversaries, physical access to the host, and compromise of the underlying Docker/OS layer.

## Authentication

Covered in [03-auth-and-users.md](03-auth-and-users.md). Security-relevant decisions:

- **bcrypt cost 12.** Deliberately slow, so a stolen hash dump stays expensive to crack.
- **Server-side sessions, not JWT.** Revocation is immediate — suspending an employee ends their access on the next request, not whenever a token happens to expire.
- **HTTP-only cookies.** JavaScript cannot read the session token, which eliminates XSS token theft.
- **Timing-safe login failures.** Same error and same response time whether the email exists or not, so the endpoint can't enumerate employees.
- **No public registration.** Invite-only.
- **Rate limiting** on login and password reset — the primary defense against credential stuffing on an exposed instance.

### CSRF

`SameSite=Lax` cookies plus a double-submit CSRF token on all state-changing requests.

`SameSite=Lax` alone stops cross-site POSTs from another origin, which covers most of the risk. The token is defense in depth, because `SameSite` behavior varies across browser versions and a same-site subdomain compromise would bypass it.

## Authorization

The most likely place a real incident happens. Full detail in [05-roles-and-permissions.md](05-roles-and-permissions.md).

The rule that matters most:

> **Scope filters the query. It never filters the response.**

```python
# WRONG — one forgotten branch leaks data, and counts/aggregates are wrong anyway
rows = db.query(MetricFact).filter(metric_id=m).all()
return [r for r in rows if r.subject_user_id in visible]

# RIGHT — the database never returns what they can't see
rows = db.query(MetricFact).filter(
    MetricFact.metric_definition_id == m,
    MetricFact.subject_user_id.in_(visible_user_ids),
).all()
```

Supporting rules:

- Enforcement is **server-side, in the service layer**. Frontend permission checks are UX only.
- **Out-of-scope resources return `404`, not `403`.** A `403` confirms the resource exists — that's information leakage. `403` is reserved for in-scope resources where the *action* isn't permitted.
- The last active admin cannot be demoted, suspended, or archived. Prevents permanent lockout of a self-hosted install with no support line.

## Connector credentials

The highest-impact secret in the system. A leaked Snowflake credential is a breach of the customer's warehouse, not just of GoalGetter.

### Storage

```
data_source.config          → non-secret settings (host, database, sheet ID)
data_source.credentials_ref → pointer to an encrypted record
credential_store            → AES-256-GCM ciphertext, key from ENCRYPTION_KEY
```

Rules:

1. **Credentials never appear in `config`.** Enforced by validation, not convention — the Pydantic config schema rejects credential-shaped fields.
2. **Encrypted at rest** with `ENCRYPTION_KEY` from the environment, kept separate from any session key so that rotating one does not force re-encrypting every stored credential. (Sessions need no signing key — the cookie is an opaque random token and the database row is the source of truth.)
3. **Never returned by the API.** Not masked — *absent*. The UI shows "configured" / "not configured." A masked value is still a value that traveled over the wire and sat in a browser's memory.
4. **Never logged.** Logging filters redact known credential field names, and connector exceptions are sanitized before being written — driver errors love to include the connection string.
5. **Decrypted only in memory**, at the moment of use, never written to disk or a temp file.

### Least privilege

The UI states this at configuration time, prominently:

- SQL and Snowflake connectors: **read-only credentials required**
- OAuth connectors: request the narrowest scopes that work (`spreadsheets.readonly`, not `drive`)
- Statement timeouts on every query, so a bad configuration can't pin the customer's production database

We can't enforce that a supplied credential is read-only, but we can make it unmistakably clear that it should be — and refusing to say so is how customers hand over write access to their warehouse.

## Injection

- **SQL:** SQLAlchemy parameterized queries throughout. The generic SQL connector accepts an admin-supplied query, which is executed **as-is with parameters, never string-concatenated with user input**, on a read-only connection with a timeout. That query comes from an admin who already has database credentials, so the risk is misconfiguration rather than privilege escalation.
- **XSS:** React escapes by default. `dangerouslySetInnerHTML` is banned. User-supplied text (team names, goal descriptions, prize text) is rendered as text, never HTML.
- **CSV injection:** exported CSVs prefix cells beginning with `=`, `+`, `-`, or `@` with a single quote. Without it, a team name of `=cmd|...` becomes a formula that executes when a manager opens the export in Excel — a real and frequently overlooked attack path in any tool with CSV export.
- **File upload:** imports are size-limited, extension- and content-checked, parsed in a sandboxed code path, and never executed or stored in a web-served directory.

## Transport & headers

TLS is terminated by the operator's reverse proxy ([16-deployment.md](16-deployment.md)). The app sets:

```
Strict-Transport-Security: max-age=31536000; includeSubDomains
Content-Security-Policy: default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
```

CSP is strict because the app has **no external dependencies at runtime** — no CDN, no web fonts, no analytics. Everything is served from the container, so a tight policy costs nothing and blocks injected script outright. `X-Frame-Options: DENY` prevents clickjacking.

TV display mode is the one exception worth noting: it may be embedded in a digital signage system, so a per-organization frame-ancestors allowance may be needed. Off by default.

## Display tokens

TV mode uses a signed URL so an office screen doesn't need a login after every reboot. Constraints:

- Grants access to **only** the leaderboards explicitly flagged `is_tv_enabled` — nothing else, ever
- Read-only; no endpoint reachable with it mutates anything
- Revocable and regenerable from the admin UI
- Rate limited per token
- Rotated automatically if a display is removed

This token will end up written on a sticky note next to a TV. It must be worth nothing to anyone who finds it.

## Audit log

Every security-relevant action is recorded: authentication events, role and permission changes, team membership changes, manual metric entry and edits, goal changes, data source configuration, user lifecycle changes, and display token generation.

Each entry captures actor, action, entity, before/after state, IP, and timestamp.

**Why this is a security control and not just a feature:** an insider with admin access can't be prevented from editing data, but they can be made detectable. When a leaderboard changes unexpectedly, an admin must be able to answer "did someone edit this?" If that question can't be answered, people stop believing the numbers — and a performance tool nobody believes is worthless.

The audit log is append-only from the application's perspective. There is no API to delete or modify entries.

## Privacy

Individual performance data about named employees carries obligations that vary by jurisdiction — GDPR in the EU, various state laws in the US.

Design positions:

- **Data minimization.** Only what's needed for the metric. `raw` JSONB stores the source row, which may contain more than needed; the mapping UI should let admins exclude columns from `raw`, and this should be documented.
- **Export.** A user's complete data is exportable via `GET /api/users/{id}/export` for subject access requests.
- **Deletion.** Archiving preserves history. True deletion (anonymizing a user while retaining aggregate facts) is an admin action with explicit confirmation, and is itself audited.
- **No cross-organization data flow.** One deployment, one company. Nothing leaves.
- **No telemetry.** No phone-home, no analytics, no crash reporting to a third party. The tool must be deployable air-gapped. **Hard rule.**

## Dependencies

- `pip-audit` and `npm audit` run in CI; the build fails on high-severity advisories.
- Dependencies are pinned with lockfiles.
- Base images pinned to specific digests, not `:latest` — a floating tag means the image can change under a customer between deploys.
- Containers run as a non-root user.

## Known gaps in v1

Stated honestly rather than left implicit:

1. **MFA for local accounts — built.** Authenticator-app two-step sign-in for password sign-in, and a Settings switch to require it. See [03-auth-and-users.md](03-auth-and-users.md#two-step-sign-in--built).
2. **No IP allowlisting.** Expected to be handled at the network or reverse-proxy layer.
3. **No field-level encryption** beyond credentials. Metric data is protected by database and filesystem access controls.
4. **No automated backup verification.** Backups are documented and the operator's responsibility.
5. **No security headers on the display route by default** if embedded — needs the per-org exception described above.

## Open questions

1. **Should TOTP MFA ship in Phase 1** rather than Phase 2? It's meaningful work but local-password-only is the weakest link on an internet-exposed instance.
2. **Credential storage** — is `ENCRYPTION_KEY` in the environment sufficient, or should optional external secret storage (Vault, cloud KMS) be supported? *Leaning: env var for v1, with a pluggable interface.*
3. **Session limits** — cap concurrent sessions per user, or show a "your active sessions" screen with remote sign-out? *Leaning: the sessions screen — more useful and less surprising.*
4. **Should the audit log be exportable/streamable** to an organization's SIEM? **Built** — see "Audit log export" below.

## Related docs

- [03-auth-and-users.md](03-auth-and-users.md)
- [05-roles-and-permissions.md](05-roles-and-permissions.md)
- [15-data-integrations.md](15-data-integrations.md)
- [16-deployment.md](16-deployment.md)

## Audit log export — built

Settings, under the activity log.

- **Download** every entry in a date range, oldest first, as CSV (with a UTF-8
  byte-order mark so Excel opens it) or JSON Lines. Streamed in pages, so a
  large log never loads at once.
- **Stream to a SIEM**: each new entry is POSTed to an HTTPS collector as it
  happens — a JSON batch, or Splunk's HTTP Event Collector format — with an
  auth header (`Authorization: Splunk <token>` or `Bearer <token>`). Both the
  address and the credential are stored encrypted and never shown back.
- **In order, exactly once.** The stream remembers the newest entry its
  collector accepted and moves on only on a 2xx, so a collector that is down
  receives the backlog when it returns and nothing is sent twice. A new — or
  re-enabled — stream starts from now; the download covers anything earlier.
- What leaves is only what the log already holds: who, what, to whom, when and
  from where. The log is written never to contain a secret.

