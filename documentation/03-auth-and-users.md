# Authentication & User Management

**Phase 1.** Both local accounts and SSO ship from day one.

## Why both from day one

An internal tool has to work for a 12-person company with no identity provider *and* for a 400-person company that mandates SSO. Retrofitting SSO later means reworking session handling, user provisioning, and the invite flow simultaneously — so the abstraction goes in now even though most early deployments will use local accounts.

## The provider abstraction

Everything above authentication asks one question: *who is this request from?* It never asks how they signed in.

```
┌────────────────┐   ┌────────────────┐
│ LocalProvider  │   │  OIDCProvider  │
│ email+password │   │  Entra/Okta/   │
│ bcrypt         │   │  Google/etc.   │
└───────┬────────┘   └───────┬────────┘
        │                    │
        └────────┬───────────┘
                 ▼
       authenticate() → user_account
                 ▼
         create session → cookie
                 ▼
      get_current_user() dependency
                 ▼
          every protected route
```

Both providers do one job: prove an identity and return a `user_account`. Session creation, cookie handling, and permission checks are shared and provider-agnostic.

> If you've built WordPress plugins: this is the same shape as a pluggable auth hook. The core never cares which plugin answered.

## Session strategy: server-side sessions, not JWT

**Decision: opaque session tokens stored in Postgres, delivered as an HTTP-only cookie.**

Why not JWT:

- **Revocation.** Suspending an employee has to take effect immediately. A JWT stays valid until it expires; a database session is deleted and the next request fails. For a tool that gates access to performance data, "logged out within 15 minutes" is not acceptable.
- **Role changes take effect instantly.** Permissions are read fresh per request rather than baked into a token at login.
- **No token storage problem in the browser.** An HTTP-only cookie can't be read by JavaScript, which removes XSS token theft entirely.
- **The usual JWT argument doesn't apply.** JWTs win when you're avoiding a database lookup across distributed services. There's one API and one database here — the lookup is a primary-key hit on an indexed table.

Cookie settings:

```
Name:     gg_session
HttpOnly: true
Secure:   true      (configurable off for local HTTP development)
SameSite: Lax
Path:     /
Max-Age:  session lifetime (default 7 days, sliding)
```

`SameSite=Lax` is safe because nginx serves the SPA and the API on the same origin. No cross-site requests, so no CORS and no CSRF exposure through cross-origin form posts. State-changing requests still carry a CSRF token — see [17-security.md](17-security.md).

## Local authentication

### Password storage

`bcrypt` via `passlib`, cost factor 12. Never SHA/MD5, never unsalted.

**Why bcrypt and not SHA-256:** SHA is designed to be *fast*, which is exactly wrong for passwords — it makes brute-forcing a stolen hash dump fast too. bcrypt is deliberately slow and tunable, so cracking stays expensive as hardware improves. (Argon2id is arguably better; bcrypt is chosen for ubiquity and zero-drama deployment. Revisit if there's a reason to.)

### Password policy

- Minimum 12 characters. Length beats character-class rules.
- Checked against a list of common passwords on set/change.
- No forced rotation. Forced rotation produces `Summer2026!` → `Summer2026!!` and makes things worse. This follows current NIST guidance.
- Rate limited: 5 failed attempts per account per 15 minutes, then temporary lockout with exponential backoff.

### Flows

**Invite (the only way a local account is created)**

There is no public sign-up. An admin invites; the invitee sets their own password.

```
Admin enters email + name + role
   → user_account created, status='invited'
   → single-use invite token generated, 7-day expiry
   → invite link shown to admin (and emailed if SMTP is configured)
   → user opens link, sets password
   → status='active', session created, logged in
```

**Why the link is shown to the admin, not only emailed:** many internal deployments won't have SMTP configured on day one. The tool must be fully usable without email — the admin can paste the link into Slack or Teams. Email is an enhancement, never a dependency.

**Password reset**

Same token mechanism. Requires SMTP. If SMTP isn't configured, the UI says so plainly and an admin can generate a reset link manually — the fallback must be visible, not a dead end.

**Login**

```
POST /api/auth/login  { email, password }
   → look up user by (org, email)
   → verify hash
   → check status is 'active'
   → create session row, set cookie
   → return current user + permissions
```

Failed login returns the same generic error and takes the same time whether the email exists or not. Otherwise the endpoint becomes a way to enumerate who works at the company.

## OIDC / SSO

Standard Authorization Code flow with PKCE, via `Authlib`. Works with Microsoft Entra ID, Okta, Google Workspace, Auth0, Keycloak — anything OIDC-compliant.

### Configuration — in the app, not the environment

**Decision: SSO settings are stored in the database and configured through the
admin UI**, alongside the data connectors. Not environment variables.

An admin of a self-hosted deployment should not have to SSH into a server, edit
a file, and restart containers to connect their identity provider. It also puts
SSO in the same place as every other external connection, which keeps one
mental model instead of two.

```sql
CREATE TABLE sso_config (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    organization_id   BIGINT NOT NULL REFERENCES organization(id),
    enabled           BOOLEAN NOT NULL DEFAULT false,
    provider          TEXT,          -- which connection signs people in
    scopes            TEXT NOT NULL DEFAULT 'openid profile email',
    button_label      TEXT NOT NULL DEFAULT 'Sign in with SSO',
    auto_provision    BOOLEAN NOT NULL DEFAULT false,
    require_sso       BOOLEAN NOT NULL DEFAULT false,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

> **The credential is not in this table, and used to be.** `issuer`, `client_id` and
> the client secret moved to `oauth_client` in Phase 3 — see
> [18-roadmap.md](18-roadmap.md) §3e. One Entra app registration can hold several
> redirect URIs and asks for scopes per request, so the same registration signs
> people in *and* reads their Excel workbooks. Keeping a copy here meant an admin
> pasted the same client id and secret into two forms on the same page, and
> rotating a leaked secret was two jobs.
>
> `provider` names the connection to use — `microsoft`, `oidc`, or anything else in
> `app/providers.py`. **This does not narrow SSO to the providers we ship connectors
> for**: a generic `oidc` connection takes a typed issuer, which is what keeps Okta,
> Auth0 and Keycloak working exactly as described below. Microsoft's issuer is
> derived from its tenant id rather than typed, because a URL with a GUID in the
> middle is a thing people mistype.

Discovery via `/.well-known/openid-configuration` means only the issuer is
entered — token, auth, and JWKS endpoints are fetched from the provider.

Four consequences of storing this in the database:

**The client secret is encrypted at rest**, exactly like connector credentials
([17-security.md](17-security.md)). It is never returned by the API — not
masked, absent. The UI shows "configured" or "not configured."

**A break-glass path is mandatory.** If `require_sso` is on and the config is
wrong, every admin is locked out of a self-hosted install with no support line.
At least one local admin account always retains password login, and the UI
states this when SSO is set to required.

**Config is read per request, not cached at boot.** Saving new settings takes
effect immediately, with no container restart — otherwise storing it in the
database solves nothing.

**"Test connection" before enabling.** Fetch the discovery document and verify
the credentials while the admin is still on the screen, rather than finding out
at someone's next login attempt.

### Flow

```
User clicks "Sign in with Microsoft"
   → redirect to IdP with PKCE challenge + state
   → user authenticates at IdP
   → IdP redirects to /api/auth/oidc/callback?code=...
   → exchange code for tokens, validate ID token signature + claims
   → match user by external_subject_id, else by email
   → create session, set cookie, redirect to app
```

### Just-in-time provisioning

`auto_provision` (default `false`) controls what happens when someone authenticates successfully but has no account.

- **`false`** — access denied with a clear message. Admins control exactly who gets in.
- **`true`** — an `agent` account is created automatically. Convenient for large orgs where everyone should have access.

Default is off because the safer failure mode is "a legitimate user has to ask for access," not "everyone in the tenant silently gains access to sales performance data."

**Roles from groups — built, off by default.** An admin lists groups and the
role each gives ("Sales Managers → manager"); with it switched on, every SSO
sign-in sets the person's role to the highest role any of their groups gives.

- **Groups from the token or the directory.** The token's `groups` and `roles`
  claims when the identity provider sends them; otherwise the group names
  directory sync already stores for that person (matched on Entra's `oid`, or
  email). So an Entra tenant with directory sync on needs no token setup.
- **Nothing matching leaves the role alone**, so a forgotten group never
  quietly demotes everybody in it.
- **Never the last admin** — skipped and logged instead of locking everybody out.
- Every change is audited as `user.role_changed` from "sso groups", and a new
  account made on first sign-in gets its role from its groups straight away.

Roles are still editable in GoalGetter; with this on, the next sign-in puts the
groups' answer back, which is the point of switching it on.

### Account linking

Matching on `external_subject_id` first, falling back to verified email, lets an existing local user transparently start using SSO. On first successful SSO login the `sub` is stored, and subsequent logins match on it directly — which matters because email addresses change and `sub` doesn't.

If `require_sso` is enabled, password login is disabled for everyone **except admins**.

That is the break-glass path: a typo in the issuer URL would otherwise lock every user out of a self-hosted deployment with no support line, recoverable only by editing the database by hand. Role-based rather than a per-account flag, so *any* admin can recover it — not just whoever ran setup.

**The trade-off, stated plainly:** every admin account keeps a password-guessable path, and admins are the highest-value target. Login rate limiting therefore matters most for exactly these accounts. An organisation wanting true SSO-only, including admins, is not supported today.

## User lifecycle

| State | Meaning | Can sign in |
|---|---|---|
| `invited` | Account created, password not yet set | No |
| `active` | Normal | Yes |
| `suspended` | Access revoked, data retained | No |
| archived (`archived_at` set) | Soft-deleted | No |

**Users are never hard-deleted.** Their metric facts, goal history, and past leaderboard positions are part of the company's record. Archiving hides them from pickers and current leaderboards while preserving history. All active sessions are destroyed on suspend or archive.

## API surface

```
POST   /api/auth/login              email + password
POST   /api/auth/logout             destroys session
GET    /api/auth/me                 current user + resolved permissions
GET    /api/auth/providers          which sign-in methods are enabled (drives the UI)
GET    /api/auth/oidc/start         begin SSO redirect
GET    /api/auth/oidc/callback      SSO return
POST   /api/auth/accept-invite      token + new password
POST   /api/auth/forgot-password    email in, the same 202 answer always out (Phase 14)
POST   /api/auth/reset-password

GET    /api/users                   list (filtered by permission)
POST   /api/users/invite
GET    /api/users/{id}
PATCH  /api/users/{id}
POST   /api/users/{id}/suspend
POST   /api/users/{id}/archive
POST   /api/users/{id}/resend-invite
```

`GET /api/auth/providers` is what lets the login screen render correctly without a rebuild — it returns whether local login and/or SSO are enabled, and the SSO button label.

## First-run setup

A fresh deployment has no users, so there must be a way in.

```
Container starts, user table empty
   → app enters setup mode
   → all routes redirect to /setup
   → form: organization name, timezone, first admin's name/email/password
   → creates organization + first admin, logs them in
   → setup mode permanently disabled
```

Setup mode is available **only** while zero users exist, so it can't be reused as a backdoor later.

## Frontend notes

- Auth state lives in one `AuthProvider` context, hydrated from `GET /api/auth/me` on load.
- A `<RequireAuth>` route wrapper redirects unauthenticated users to `/login`, preserving the intended destination.
- A `<RequirePermission>` wrapper handles role-gated routes.
- Any `401` from the API clears auth state and redirects to login — handled once in the API client, not per-call.

## Open questions

1. **Session lifetime** — 7-day sliding is proposed. Should there be an absolute maximum (e.g. re-auth after 30 days regardless of activity)?
2. **MFA for local accounts** — **built**: see "Two-step sign-in" below.
3. **Email/SMTP** — should Phase 1 include SMTP configuration at all, or is admin-copies-the-link sufficient until Phase 2 notifications need email anyway?

## Passwords — built

| Path | Who | What |
|---|---|---|
| `POST /api/auth/change-password` | anyone signed in | Requires the current password. Keeps this session, ends all others. |
| `POST /api/users/{id}/reset-password` | admin | Issues a single-use link, valid 2 hours. |
| `POST /api/auth/forgot-password` | anyone | Emails a reset link (or, to somebody still invited, the invitation again). Only where mail can be sent. |
| `POST /api/auth/reset-password` | the link holder | Sets the password, ends every session, clears the lockout. Does **not** sign in. |

**Self-service "Forgot password?" (Phase 14), by email only.** It was left out
at first because, with no mail server, the link could only come back in the
response, and anyone could request one for the admin and be handed it. It
exists now with four rules:
- **Emailed, never returned.** With nowhere to send from, `/auth/providers`
  says `self_reset: false` and the page says to ask an admin.
- **One answer for everybody.** No account, a suspended one, someone who must
  use Microsoft, too many requests: all get "If that address has an account…".
  The email goes in the background, so timing does not tell them apart either.
- **The link is built from the address in Settings, never from the request.**
  Otherwise a forged `Origin` could make a real reset email point at a
  stranger's site (password reset poisoning).
- **Three per address, 20 per network address, per hour.** Counted in the
  sign-in attempts table under `reset:<email>` and marked succeeded, so asking
  never counts towards a sign-in lockout.

**Reset is admin-only while invite is admin-or-manager.** Inviting creates an
account nobody was using; resetting takes over one somebody is.

**Minimum 12 characters, maximum 72.** Length over character-class rules —
current guidance is to require length and screen against common passwords, not
to demand a symbol and a digit, which mostly produces "Password1!". The ceiling
is bcrypt's: it silently truncates beyond 72 bytes, so allowing more would give
a false sense of strength.

## Related docs

- [05-roles-and-permissions.md](05-roles-and-permissions.md)
- [17-security.md](17-security.md)
- [04-organizations-and-teams.md](04-organizations-and-teams.md)

## Two-step sign-in — built

An authenticator app (Microsoft Authenticator, Google Authenticator, 1Password
and the rest) for **password** sign-in. SSO sign-in is untouched: its second
step is the identity provider's.

- **TOTP, RFC 6238**, written out in `app/totp.py` and checked against the RFC's
  own test vectors: six digits, 30-second steps, one step of drift either way.
  A code is accepted once — the step it matched is remembered.
- **A correct password is not a session.** With two-step sign-in on, the login
  endpoint answers 202 with a five-minute encrypted challenge; only a code or a
  one-use recovery code turns it into a session. Wrong codes are rate-limited
  per account, like passwords.
- **Setup** (Account → Two-step sign-in): a QR code drawn in the browser (the
  secret is in the picture, so it is never sent to a QR service), the key to
  type by hand, a code to confirm, then ten recovery codes shown once and stored
  hashed. A new secret stays pending until confirmed, so starting again never
  breaks a working authenticator.
- **Settings → Require two-step sign-in.** Anybody signing in with a password
  and no authenticator is walked through setup straight after their password,
  before they are in. While it is required it cannot be turned off by the
  person — only moved to a new phone.
- **Lost phone**: an admin resets it from the person's page (audited); their
  password alone signs them in until they set it up again.

