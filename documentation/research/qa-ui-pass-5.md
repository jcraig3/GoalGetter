# GoalGetter — QA / UI pass 5: hosting (Phase 13) and Phase 14

**Date:** 6 Oct 2026
**Build:** `e822b32` (Phase 14 committed)
**Signed in as:**

- **Admin:** your Microsoft account, in the app's browser pane.
- **Agent:** a throwaway agent, "QA5 Agent" (`qa5.agent@example.com`), invited with a temporary password and driven in its own headless Chrome profile.

**Previous report:** [qa-ui-pass-4.md](qa-ui-pass-4.md) (P4-n). New findings here are **P5-1 onwards**.

**Not done, on purpose:**

- I didn't switch HTTPS on in your environment. It would take ports 80 and 443 and change your `.env`. Instead I reviewed the hosting files and docs, and validated the Caddyfile in a throwaway container.
- I didn't submit Forgot password for a real account. That sends an email from your Microsoft 365 mailbox. I only submitted an address with no account.

---

## 1. Verdict

**Phase 14 is done as described.** All 16 P4 findings and Forgot password check out in the running app, at desktop and phone width, as admin and as agent.

**Phase 13 is well built and well documented.** The Caddyfile is valid, the setup scripts are careful, and `20-hosting.md` is the clearest doc in the repository.

**But the review turned up one real security issue, and two related gaps that matter once HTTPS puts GoalGetter in front of more people:**

- **P5-1 (High), proven:** every request looks to the API as if it comes from nginx. So the "per network address" limits on sign-in and Forgot password are really **one limit for the whole organisation**. A stranger who can reach the sign-in page can keep every password sign-in locked out, admins' "way back in" included.
- **P5-2 (Medium):** behind Caddy, the number of proxies changes, but the API's proxy setting doesn't. It isn't in `.env.example` or the hosting doc either.
- **P5-3 (Medium):** with HTTPS on, the plain-HTTP TV port still serves the whole app, including password sign-in sent unencrypted.

---

## 2. Hosting review (Phase 13)

### Verified

- **The Caddyfile validates and adapts** (`caddy validate` and `caddy adapt` in a throwaway `caddy:2.10-alpine`, with `HTTPS_HOST=goals.internal`, `HTTPS_CERTIFICATE=internal`). Routing is as intended:
  - Plain HTTP serves `/goalgetter-root.crt`, so a device can fetch it before trusting anything, and redirects everything else to https.
  - HTTPS imports the chosen certificate mode, serves the root certificate, and proxies to `web:80`.
  - **Caddy sets `X-Forwarded-Proto: https` itself.** It doesn't take the client's value.
- **The admin API is off** (`admin off`), and the local authority has a recognisable name ("GoalGetter Local Authority").
- **The certificate modes are one small file each** (`internal`, `letsencrypt` with Cloudflare or DuckDNS over DNS-01, `files`), chosen by `.env`.
- **Certificates live in `volumes/caddy`**, so rebuilds keep the same root, and the backup table says so.
- **`setup.sh` / `setup.ps1`:**
  - never overwrite an existing `.env`
  - generate 64-character hex secrets (with an `openssl` / `/dev/urandom` fallback)
  - warn when an old database folder exists
- **`.env.example`** explains every setting in plain words. Production is the default overlay.
- **`20-hosting.md`:** "Which option is yours?", options A–F step by step, firewall commands, per-device trust steps (Group Policy, Intune, Windows, Mac, iPhone, Android, Firefox), Azure redirect steps, troubleshooting and backups. It reads as if written for the person who'll actually install it.
- **Settings → General → HTTPS** (with HTTPS off) shows the state, a pointer to the doc, and the exact Microsoft redirect address. `/api/hosting` agrees.
- **Session cookies:** Secure when the request came through Caddy over https, and not on the plain port. As the nginx comment says, a client setting `X-Forwarded-Proto` itself can only make its own cookie stricter.

### P5-1 (High) — One sign-in limit for the whole organisation

**What happens:**

- `rate_limit.is_locked_out` locks out an **address** after 20 failed sign-ins in 5 minutes.
- Forgot password allows 20 requests an hour per address (`FORGOT_PER_IP`).
- Both use `net.client_ip`, the socket peer. **Behind nginx that is always nginx** (`172.21.0.6`): every row in `login_attempt` carries that address.

**Proven:**

1. 20 failed sign-ins to made-up addresses (`qa5-lock-0…19@example.com`).
2. A **different** made-up address was then refused: `429 "Too many sign-in attempts. Try again in 5 minutes."`
3. I deleted the 20 rows straight away, which lifted the lock. Your session wasn't affected, since Microsoft sign-in doesn't go through this.

**Impact:**

- Anyone who can reach the sign-in page can lock out **every password sign-in**, every 5 minutes, indefinitely. That includes admins, whose password is the documented way back in if Microsoft sign-in is misconfigured.
- Forgot password stops sending after 20 requests an hour across the whole company, while still showing everyone "a link is on its way".
- This predates Phase 13. It matters more now that Phase 11 made passwords the main way in for people outside the tenant, and Phase 13 makes it easy to put GoalGetter on a public name.

**Fix (the order matters):**

1. **Key the per-address limits on the real client.** Use `net.real_client_ip(request, trusted_proxy_ips, trusted_proxy_hops)`, as the TV allowlist does, not `client_ip`. Keep `client_ip` for the audit log, as the docstring intends.
2. **When the real client can't be known, skip the per-address limit and keep the per-email one.** For example, when the address comes back as a proxy or Docker-gateway address. Docker Desktop on Windows and Mac can hide the client behind its own gateway, which is exactly how this server runs. The per-email limit (5 per 5 minutes) still protects each account, and a single shared counter is worse than none: it turns brute-force protection into a lockout button.
3. **Add a test** that two clients behind the same proxy don't share a lockout, and one that a forged `X-Forwarded-For` on the plain port doesn't move the limit.

### P5-2 (Medium) — Two proxies behind Caddy, one in the setting

With HTTPS on, a browser's request goes **Caddy → nginx → API**. Caddy writes the client into `X-Forwarded-For`, and nginx appends Caddy's address. `trusted_proxy_hops` defaults to **1**, so `real_client_ip` returns **Caddy's container address** for every HTTPS visitor. A TV's IP allowlist, and P5-1's fix, would both see one address for everybody coming in over HTTPS.

The plain TV port is still one hop. So no single `TRUSTED_PROXY_HOPS` value is right for both paths.

**Fix:** make both paths one hop, so the setting can stay 1:

- Give Caddy its **own unpublished nginx listener** (say `listen 81`, used only by Caddy). On it, trust `X-Forwarded-For` from Caddy (`set_real_ip_from` Caddy's address, `real_ip_header X-Forwarded-For`).
- On the published listener, **replace** the header instead of appending (`proxy_set_header X-Forwarded-For $remote_addr`). A client on port 8080 can then no longer prepend anything.
- Document `TRUSTED_PROXY_IPS` / `TRUSTED_PROXY_HOPS` in `.env.example`, and in **option F** of `20-hosting.md`. Someone's own proxy in front of nginx is the case where they must change it.

### P5-3 (Medium) — The plain port is still a full app

`20-hosting.md` says HTTPS matters because over plain HTTP "anybody else on the network can read" passwords and sessions. But with HTTPS on, `http://<server>:8080` still serves everything, including the password form. Nothing pushes people off it, and invite links can still be opened on it.

**Fix:** when the `https` profile is on, have nginx's published port serve only what TVs need and send everything else to the HTTPS address with a 301:

- `/pair`, `/display/*`
- the display and pairing API (`/api/display/*`, `/api/pair*`)
- the root certificate

A Settings note ("The plain address is for TVs only") would make it explicit.

### Smaller hosting notes

- **P5-4 — `setup.sh --https` with nothing after it** exits silently (`shift` fails under `set -e`). Say "--https needs a name, e.g. goals.internal". Neither script checks the name for spaces or a scheme (`https://goals.internal` would be written into `HTTPS_HOST`).
- **P5-5 — Moving off port 80** (`HTTP_PORT=8081`) also moves the root-certificate download to `http://goals.internal:8081/goalgetter-root.crt`. The troubleshooting row only mentions the https address changing. Settings → General → HTTPS should show the right one.
- **P5-6 — Troubleshooting has no row for "Too many sign-in attempts"**, which is worth adding after P5-1.
- **P5-7 — The HTTPS panel (with HTTPS off)** says "follow documentation/20-hosting.md in the GoalGetter folder". That's a file path in the UI for an admin who may not have the folder open. Link to the README section on the repository, or show the three `.env` lines in place.
- **P5-8 — Typing the IP when `HTTPS_HOST` is a name** gets no certificate (Caddy serves only that name), and `http://<ip>/goalgetter-root.crt` doesn't match Caddy's host either. The doc says to use the name; one line in troubleshooting ("certificate error when using the IP address") would save a support call.

---

## 3. Phase 14, verified

| Item | Seen |
|---|---|
| **Forgot password** | "Forgot password?" under the password field; page titled "Forgot password · GoalGetter"; an unknown address gets "If that address has an account, a link to choose a new password is on its way. It works once, for two hours. Check your inbox, and your junk folder."; `self_reset: true` in providers; a dead reset link offers "Get a new link"; fine at 375 px |
| Sign-in (P4-7) | Tab title "Sign in · GoalGetter"; after a failure the password is cleared and the email kept |
| Choose password (P4-8) | Titled "Choose your password · GoalGetter"; **"Show passwords"** turns both fields to text; a forced submit with a different confirmation now stays put and says they don't match |
| Stale notifications (P4-1) | The three evidence rows are deleted. Behaviour is covered by tests; I didn't re-create a late activation |
| Suspended (P4-2) | Suspend → "Suspended — cannot sign in"; Let them back in → "Invited — has not signed in with the password you set" again (correct for an account that hasn't signed in yet) |
| Tie (P4-3) | A 0–0 head-to-head reads **"No scores yet"** between the panels, with nobody "behind" |
| Bell (P4-4, P4-15) | ✕ at **40%** opacity at all times; **44×44** on a phone; focus moves to the next row after ✕; Undo stays about **10 s**; an emptied bell says **"All caught up."** |
| Person page Password (P4-5) | Yourself: "Change your own password on your Account page." Jean (no password): "They have no password — they sign in with Microsoft. A temporary password gives them one as well." Arthur (directory): which rule applies |
| Require SSO hint (P4-6) | Now names "anybody who has signed in with Microsoft before" |
| One notice, two places (P4-9) | Bringing back the Excel item in the Inbox brought Home's banner back; putting it away on Home put it away in the Inbox. **Your notices are as you left them** (2 put away) |
| Invite form and access (P4-10) | Roles "Agent / Manager / Admin"; toasts "QA5 Agent is suspended and signed out" and "QA5 Agent can sign in again" |
| Palette (P4-11) | "new" lists Connect a TV and Invite people; "password" finds Change your password and Sign-in & security |
| Profiles (P4-12) | As the agent, Arthur Curry shows **"On the boards · DEALS BOARD · Last 30 days · 1st of 130"**, with no figure |
| Activity (P4-13) | Plain sentences; no repeated name |
| Discard (P4-14) | Changing a dropdown and pressing Escape asks "Discard your changes?" |
| One person (P4-16) | `GET /api/users/491` → 200 |

### Small notes from this pass

- **P5-9 —** The **Suspend** confirm's action button says "Continue". Name it "Suspend".
- **P5-10 —** "Discard your changes?" offers **Cancel / Discard**. "Keep editing" would say which way Cancel goes. Also, a form's own **Cancel** button still throws changes away without asking (by design since 5d). Worth one more look now that dropdown changes count as changes.
- **P5-11 —** The palette's "password" lists **Invite people first**, above Change your password. Rank an exact word match on the item's own title higher.
- **P5-12 —** The expired reset-link page still has the bare tab title "GoalGetter" (use "Reset password · GoalGetter"). Its two links read run together in the text ("Get a new linkBack to sign in"); check their spacing visually.
- **P5-13 —** A malformed email on Forgot password gets a 422 with pydantic's message. It reveals nothing, but the page's own `type=email` should catch it first. Make sure the API's answer is in the app's words if it ever shows.

---

## Test data and cleanup

**Created:**

- QA5 Agent (user 491): invited with a temporary password, suspended and let back in, signed in, chose a password, and posted three comments to fill your bell
- one throwaway contest (published, cancelled, deleted)
- 20 lockout-probe sign-in attempts, plus a few sign-in and reset-request attempts with made-up addresses

**Removed:**

- the comments, through the app
- the contest, through the app
- the account and all of its attempt rows, in one transaction matched on id and address
- the probe rows straight after the test, which also lifted the lockout they caused
- the headless browser profile

**Verified:**

- Every table matches the pre-test counts, except `audit_log`, which is expected.
- Your notification dismissals and Inbox state are as you left them.
- **Backup:** `scratchpad/goalgetter-before-qa5.dump`.
