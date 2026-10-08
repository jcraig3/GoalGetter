# GoalGetter — QA / UI pass 6: Phase 15 (the P5 fixes)

**Date:** 6 Oct 2026
**Build:** `c2ae069` (Phase 15 committed)
**Previous report:** [qa-ui-pass-5.md](qa-ui-pass-5.md) (P5-n). New findings are **P6-1 onwards**.

**How this pass was done:**

- **Code review** of the nginx, Caddy and client-address changes.
- **The dev stack**, in your admin session.
- **A throwaway nginx container** started with HTTPS on (`COMPOSE_PROFILES=https`, `HTTPS_HOST=goals.internal`) on spare ports, to exercise the TV-only rules. Removed afterwards.
- **A scratch copy of `setup.sh`**, run with good and bad arguments.
- **The headless browser**, for the signed-out pages.

Your dev stack's configuration wasn't changed. The only data written was four sign-in attempts and probes with made-up addresses, all deleted.

---

## 1. Verdict

**Phase 15 does what it says, with one caveat that matters for how this product will usually be installed.**

**What works:**

- The nginx redesign is clean and correct. There's a private listener for Caddy, both paths hand the API exactly one hop, and the plain port is TV-only with HTTPS on.
- **Forged `X-Forwarded-For` values are ignored.**
- The redirect rules hold up against path tricks.
- The setup scripts validate their input.
- All the small UI fixes are in.

**The caveat (P6-1):** on **Docker Desktop**, the address nginx sees for a visitor is Docker's network gateway. In this dev stack every request was recorded as `172.21.0.1`. Docker Desktop is what the README recommends for Windows and Mac. If every device on the office network arrives as that one gateway address, which is how Docker Desktop's port publishing is documented to behave, then the per-address limit is again **one limit for everybody**: the P5-1 lockout, just with a different shared address. This needs one check from a second device to confirm (§3).

---

## 2. Verified

### The client address (P5-1, P5-2)

- **Forged headers are ignored.** A sign-in posted with `X-Forwarded-For: 203.0.113.77` was recorded as the real peer, not the forged address. The API reads the last hop, and nginx's published listener appends the peer it saw.
- **Through Caddy:** the private `:81` listener passes Caddy's `X-Forwarded-For` as it is, and Caddy (no `trusted_proxies`) writes only the address that connected. So the API sees one hop on both paths, and `TRUSTED_PROXY_HOPS=1` is right for both.
- **The fallback:** `visitor_ip` returns None when the only address it has is the proxy's own, and the per-address limits are then skipped.
- **Sessions and the activity log** now use the same visitor address.
- **`.env.example`** documents `TRUSTED_PROXY_HOPS` / `TRUSTED_PROXY_IPS`, including when 2 is right and what goes wrong either way. Option F explains it.

### The TV-only plain port (P5-3)

Throwaway nginx, HTTPS on, `goals.internal`:

| Request on the plain port | Result |
|---|---|
| `/`, `/login`, `/goals`, `/forgot-password`, `/reset-password`, `/login?next=/x` | **301 → `https://goals.internal…`**, keeping the path and query |
| `POST /api/auth/login`, `/api/auth/forgot-password`, `/api/goals`, `/api/hosting` | **301 → https**, so no password crosses plain HTTP |
| `/pair`, `/display/abc`, `/assets/…`, `/favicon.ico`, `/healthz` | **200**, served |
| `/api/display/…`, `/api/displays/pair/…`, `/api/auth/me`, `/api/setup/status`, `/api/images/…` | Passed to the API |
| `/display/../login`, `/display/%2e%2e/goals`, `//api/auth/login`, `%2F`-encoded traversal | **301**: nginx normalises before matching |
| `/api/display/x/..;/..;/auth/login` | Passed to the API, which answers **404** (Starlette doesn't treat `..;` as a parent folder), so it's harmless |
| `:81` (Caddy's listener) `/login` | 200 (correct: that listener is the HTTPS path, and it's never published) |

- **The redirect target comes from `.env`, never from the request's `Host`**, so it can't be used as an open redirect.
- **Every URL a TV loads is on the list.** I checked the display, pairing and celebration code: `/api/display/{token}`, `/celebrations`, `/assets/{digest}`, `/api/displays/pair/…`.
- **`web-https.sh`** refuses a host or port that doesn't look like one (no quotes or spaces reach nginx's config), and logs which mode it chose. `/healthz` keeps the container healthy whichever way the port behaves.

### Setup scripts (P5-4)

| Command | Result |
|---|---|
| `sh setup.sh --https` | "--https needs a name after it, e.g. sh setup.sh --https goals.internal" |
| `--https https://goals.internal` | "Give just the name, without https://" |
| `--https 'goals internal'` | "…is not a name or address. Use letters, digits, dots and dashes" |
| `--https goals.internal` | `.env` written with `COMPOSE_PROFILES=https`, `HTTPS_HOST=goals.internal` |
| a second run | "…already exists, so nothing was changed" |

### UI

| Item | Seen |
|---|---|
| Confirm buttons (P5-9) | "Cancel / **Suspend**", "Cancel / **Hide**" (both cancelled; nothing changed) |
| Discard (P5-10) | A form's own **Cancel** after a dropdown change now asks "Discard your changes?" with **Keep editing / Discard** |
| Palette (P5-11) | "password" → **Change your password** first |
| Expired link (P5-12) | Title "Reset password · GoalGetter"; the links are 24 px apart |
| Malformed email (P5-13) | `{"email":"not-an-email"}` → 202 with the standard answer |
| HTTPS panel (P5-7) | Shows the three `.env` lines, the README section name, and "passwords cross the network unencrypted" |
| Troubleshooting (P5-5, P5-6, P5-8) | Rows for "Too many sign-in attempts", a certificate error with the IP address, the moved root-certificate link, and 8080 redirecting |

---

## 3. Findings

| ID | Sev | Area | Finding |
|---|---|---|---|
| P6-1 | **High (to confirm)** | Sign-in limits | On Docker Desktop every visitor may arrive as Docker's gateway (`172.21.0.1`), so the per-address limit could again be shared by everyone |
| P6-2 | Low | nginx | The plain-port redirect is a **301**, which browsers cache for good. Turning HTTPS off later leaves those browsers still jumping to an https address that no longer answers |
| P6-3 | Low | nginx | `/api/images/` is on the TV allowlist but needs a signed-in session, which a TV never has. It's harmless, but it's one more door on the plain port than TVs need |
| P6-4 | Low | Setup | `--https goals.internal:8443` says "not a name or address". Suggest "Leave the port out; set HTTPS_PORT=8443 in .env" |
| P6-5 | Low | Docs | The new "Too many sign-in attempts" row says "if everybody sees it at once… you have your own proxy in front". On Docker Desktop that may be Docker itself (P6-1) |

### P6-1 — Docker Desktop and the visitor's address

**Seen:** in this dev stack (Docker Desktop 4.80, Windows), my sign-in attempts were recorded as **`172.21.0.1`**. That's `goalgetter_default`'s gateway, not nginx's `172.21.0.6`. So Phase 15 did move the recorded address off nginx, but onto the gateway.

**Why it matters:**

- `visitor_ip` returns None only when the address equals the proxy's own. The gateway isn't nginx, so it's treated as a real visitor.
- Docker Desktop's published ports are documented to arrive from its own network layer rather than preserving each client's source address.
- If that holds here, **every phone and PC in the office arrives as `172.21.0.1`**. Twenty wrong passwords from anyone would then lock out every password sign-in for five minutes, as in P5-1.
- The Phase 15 proof ran on a fresh install. If its "second visitor" came from a different container or machine with its own source address, it wouldn't have seen this.

**Confirm in a minute:**

1. From a phone on the office Wi-Fi, open `http://<server address>:8080/login`.
2. Sign in with a made-up email and any password.
3. Then run:

   ```
   docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select email, ip_address from login_attempt order by id desc limit 3;"'
   ```

If the phone's row says `172.21.0.1` rather than its own `192.168…` / `10…` address, this is confirmed. (Delete the row afterwards.)

**Fix:**

1. **Treat the Docker network's gateway as "unknown", like the proxy itself.** The API can learn it at startup, either from the container's default route (`/proc/net/route`) or by listing the bridge's gateway in a new setting.
2. **Skip the per-address limit for that address**, exactly as for None. The per-email limit still guards each account.
3. **Say it in the docs:** on Docker Desktop, GoalGetter can't tell office devices apart, so it relies on the per-email limit. Docker Engine on Linux preserves addresses. Linux is the better host for a busy office anyway.
4. **Add a test** where the peer is nginx and the last `X-Forwarded-For` entry is the gateway: `visitor_ip` should be None.

### P6-2 — A permanent redirect is hard to take back

`return 301 $1$request_uri;` — browsers cache a 301 indefinitely. If an organisation tries HTTPS and turns it off again, every browser that visited `http://server:8080/` while it was on keeps going to `https://…`, which no longer answers, until someone clears the cache. Use **302** (or 307), which costs nothing here since the plain port's pages are never bookmarked by TVs.

---

## Test data and cleanup

- **Sign-in attempts:** two made-up addresses in the dev stack (`qa6-probe-a/b@example.com`), recorded and deleted.
- **Throwaway files and containers removed:** the nginx container (`qa6ngx`) and its network, the scratch `setup.sh` copy, and the headless browser profile.
- **Not changed:** your `.env`, compose files and running containers. The Suspend and Hide confirms were cancelled, and Jean Grey is still active.
