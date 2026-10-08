# GoalGetter — QA / UI pass 7: hosting set up in the app (Phases 19–22)

**Date:** 6 Oct 2026 (evening)
**Build:** `d3fafbe` (Phase 22 committed)
**Previous report:** [qa-ui-pass-6.md](qa-ui-pass-6.md) (P6-n). New findings are **P7-1 onwards**.

**How this pass was done:**

- **A fresh install.** A separate copy built from `git ls-files`, started from nothing the way the README says:
  - `setup.ps1`, then `docker compose up -d` with the production images
  - its own ports (8090 / 8443 / 8081) and its own Docker project
  - first-run setup with a throwaway admin
  - **Linux folder permissions:** the `volumes/certs` bind mount was swapped for a root-owned Docker volume, so the uid-1000 handover was tested as on a Linux host. The other shared folders already are Docker volumes.
- **A headless Chrome** that resolved `*.internal` to this machine. First it played a device that doesn't trust GoalGetter's certificate, then one that does.
- **Everything in the guided change, for real:**
  - every pre-switch check (with made-up tokens and a self-signed test certificate)
  - Switch over, Undo, Keep, Undo last change
  - a trial left to run out
  - a Cloudflare tunnel with a well-formed made-up token (Cloudflare itself refused it)
  - `.env` edited during a trial, and while the app was open
  - `HTTPS_FRONT_DOOR=windows` set without the front door installed
  - `.env` mounted read-only into the API
- **Removed afterwards:** the fresh copy, its containers, volumes, images and the test browser. Your dev stack wasn't touched.

---

## 1. Verdict

**The guided change is good work.**

- The three steps read clearly, and the checklist is specific.
- The checks give useful answers even with bad input.
- The trial really does keep the old setup working.
- Undo, Keep and the 15-minute run-out all behave as documented.
- `.env` writes are surgical: only the managed lines change, comments are kept, and secrets are never touched.

**Three findings are serious enough to fix before anyone outside the team installs it.** Each was proven on the fresh copy:

- **P7-1 — `APP_URL` in `.env` silently becomes an "Advanced" override that beats HTTPS.** After switching to HTTPS and pressing **Keep**, new invitation links and the Microsoft sign-in redirect still pointed at `http://localhost:8090`. That hits any install that changed `APP_URL`, including everyone who moved `APP_PORT`.
- **P7-2 — If the app can't *write* `.env`, it stops *reading* it too.** Then the documented way out of a lockout ("empty `HTTPS_HOST=`") does nothing, even after a restart. On Linux that's a likely state (`sudo sh setup.sh`, or a server user whose id isn't 1000).
- **P7-3 — The Windows front door installer turns the front door on in `.env` before checking and starting it.** Within 30 seconds the app sends everything but TV pages to an HTTPS address that nothing serves yet. If the check then fails, the script stops and leaves the setting on, and everyone stays locked out until someone edits `.env`.

---

## 2. What could not be tested here, and how to test it

| Item | Why not | How to test (about 10 minutes each) |
|---|---|---|
| **A real Cloudflare tunnel** | Needs a Cloudflare account and a domain; I can't create accounts or enter live tokens | Zero Trust → Networks → Tunnels → Create (Cloudflared) → paste the install command into Settings → Hosting → Change → **Cloudflare tunnel**; public hostname → `http://web:81`; **Switch over**. Expect "Connected · 4 connections". Then **Keep**, open the name from a phone on mobile data, and sign in. Check that port 8080 then serves TVs only |
| **Let's Encrypt through Cloudflare DNS** | A live API token | A token from the **Edit zone DNS** template for one zone → **Your company's domain** → Check (expect the token to pass) → Switch over. Watch `docker compose logs -f https` for the certificate, then confirm the card shows "Let's Encrypt" and a ~90-day expiry |
| **Let's Encrypt through DuckDNS** | A DuckDNS account | Create `something.duckdns.org` pointing at the server's LAN address → **A free DuckDNS name** → Check → Switch over. Also try it from a phone on Wi-Fi: some routers block public names that lead to private addresses |
| **A second device** | I can't use a phone | On the office Wi-Fi: open `http://<server>:8080`, then the new `https://` name during a trial. Expect the root-certificate prompt for **Your network**; install it (iPhone: also Settings → General → About → Certificate Trust Settings); "Opens from this device" should turn green on the phone. Note any firewall prompt on the server |
| **A Linux host** | No Linux machine here (only Docker Desktop's own WSL) | On Ubuntu: `sh setup.sh --https goals.internal` **as a normal user, then again in a fresh folder with `sudo`**, then `docker compose up -d`. In the sudo case, confirm P7-2 (Settings → Hosting won't say "Kept in step with .env", and emptying `HTTPS_HOST` does nothing). Also confirm that per-device limits say "on" (Linux keeps addresses) |
| **The Windows front door installer** | It installs a service and opens the firewall, which changes this PC's security settings | On a spare Windows PC, as administrator: `windows\install-front-door.ps1`, then `-Remove`. Check P7-3's window by watching port 8080 while it runs |

**What was tested in their place:**

- **Linux permissions:** uid-1000 ownership of root-owned volumes. The server process runs as uid 1000; `certs`, `nginx-gg` and `tunnel` were handed to it; the tunnel ran as uid 1000 with a 0600 token file. `caddy-admin` stays root's, which is correct.
- **The Cloudflare and DuckDNS token checks** against the real services, with made-up tokens.
- **A tunnel refused by Cloudflare** during a trial.
- **The front door's effect on the app**, via `.env`.

---

## 3. Verified

### README, from nothing

- **`setup.ps1`** wrote `.env` with two 64-character secrets and refused a second run.
- **`docker compose up -d`** brought all six services up (api, web and postgres healthy, plus https, tunnel and db-backup). It took 40 seconds with images cached, and the README's "a few minutes" for a first build is fair.
- **First-run setup → sign in → Settings → Hosting** follows the README's steps 4 and 5. See P7-14 and P7-16 for two rough edges.

### The guided change

| Step | Seen |
|---|---|
| How | Six cards with the current one marked "now". "Other setups" holds your own proxy and the Windows front door |
| Set up | Only that way's fields. "Outside GoalGetter" lists the DNS record, the ports, and the firewall commands (Windows and Linux) to copy |
| Check, with no DNS | "goals.internal isn't in DNS yet · Add a record pointing it at this server." A warning, not a block |
| Check, Cloudflare (fake token) | "Cloudflare doesn't accept this token · Make one from the Edit zone DNS template." |
| Check, DuckDNS (fake token) | "DuckDNS doesn't accept this token for qa-goalgetter-test-7781"; a non-DuckDNS name gets "A DuckDNS name ends in .duckdns.org" |
| Check, tunnel | A garbage token gets "That isn't a tunnel token… it starts with eyJ"; an install command has its token found inside it |
| Check, files | A self-signed test certificate covering `it.internal` and `*.corp.internal`: the right name and the wildcard pass; the wrong name gets "It's for it.internal, *.corp.internal." |
| Switch over | Both the old and new names answer 200; port 8090 is a full app; `.env` follows; countdown "undone by itself in 14:50 unless kept" |
| Try it | "HTTPS answers · GoalGetter Local Authority". On an untrusting device, "Doesn't open from this device yet…" plus **Download the root certificate**; on a trusting device, "Opens from this device" |
| Undo (in a trial) | Back to plain HTTP; `.env` emptied; HTTPS name gone; port 8090 a full app |
| Keep | "Kept. GoalGetter is at https://goals.internal:8443. The plain address, port 8090, now serves TVs only." 8090: `/` and `/login` → 302 to HTTPS, `/pair` and `/display` 200 |
| Run-out | Not kept → undone at 02:18:11, 10 s after the deadline (log: "the change on trial was not kept in time; undoing it") |
| Undo last change | Tried like any change, going back to the setup before the trial (not the abandoned trial) |
| Tunnel refused, in a trial | "The tunnel isn't connected · Cloudflare doesn't accept this token…", while the old name and port 8090 kept working. Undo cleared the token from `.env` and the volume and stopped `cloudflared` |
| `.env` edit with the app open | `HTTPS_HOST=other.internal` → Caddy and nginx followed within ~30 s; the app showed it as "now" |
| `.env` content | Only the managed lines changed; comments intact; secrets untouched; empty `HTTPS_HOST=` (with a writable `.env`) → off within 30 s |
| Front door set | The API refuses changes: "HTTPS is handled by the Windows front door. Remove it first…" |
| Phone width | No horizontal overflow on the trial screen |

### Your question: the plain-HTTP window during a trial

**From plain HTTP to HTTPS, I'm comfortable with it.** Port 8080 is the only way back if the new name doesn't open, it's capped at 15 minutes, and only an admin can start it.

**From one HTTPS setup to another, it isn't needed.** The old HTTPS name keeps serving through the trial, and that is already the way back. Suggestion: keep port 8080 TV-only during a trial whenever the current setup already has HTTPS, and open it only when the current setup is plain HTTP. That removes most of the window at no cost.

---

## 4. Findings

| ID | Sev | Area | Finding |
|---|---|---|---|
| P7-1 | **High** | Web address | Any custom `APP_URL` becomes an Advanced override that beats HTTPS, so links and the Microsoft redirect stay on the old address after Keep |
| P7-2 | **High** | `.env` | When the app can't write `.env` it ignores it entirely, so the "empty `HTTPS_HOST=`" escape fails, even after a restart |
| P7-3 | **Med–High** | Windows front door | The installer writes `HTTPS_FRONT_DOOR=windows` before validating or starting Caddy, which locks everyone out for that window, and for good if validation fails |
| P7-4 | Med | Trial | An `.env` edit during a trial decides it at once: the old name and the plain fallback go, and the admin's open tab is cut off |
| P7-5 | Med | Activity | The automatic undo after 15 minutes appears only in the container log; `.env`-driven changes are never in Activity either |
| P7-6 | Low–Med | Front door | "Undo last change" is accepted while the front door is set (other changes are refused), and it clears `HTTPS_FRONT_DOOR` |
| P7-7 | Low | Trial | **Keep** is plain and immediate while the live check is failing (a refused tunnel) |
| P7-8 | Low | Wording | After undoing a trial, "Undo last change: back to …" is really a redo |
| P7-9 | Low | Card | During a trial the card says Certificate "Not reachable yet" while the trial says "HTTPS answers" |
| P7-10 | Low | Tunnel | The TVs line says "…the server's own address **:8080**/pair", a hard-coded port (the install uses 8090) |
| P7-11 | Low | Checklist | The Windows firewall command has no `-Profile`, so it opens the ports on Public networks too (the installer uses Domain, Private) |
| P7-12 | Low | Caddy | The http→https redirect on port 80/8081 is a permanent **301** (nginx was moved to 302 in Phase 16 for this reason) |
| P7-13 | Low | Check | A well-formed tunnel token shows as a green "ok · Tunnel 6ff42ae2…" with nothing verified; "Looks like a tunnel token" would be honest |
| P7-14 | Low | First run | After "Create organization" you land on a blank sign-in page: no "your organisation is ready", no email filled in. The setup page's tab title is just "GoalGetter" |
| P7-15 | Low | Wording | With the front door set, the editor says "Changed with its own setup: `documentation/hosting/windows-front-door.md`", a file path in the UI |
| P7-16 | Low | README | Step 3 says `api`, `web` and `postgres` show healthy; `https` and `tunnel` now always run too (no health check). A stray `photo-bulk-test.zip` is committed at the repository root |
| P7-17 | Low | Trial | During a trial the TVs line already shows the **new** name, so a TV set up then would point at a name that may be undone |
| P7-18 | Note | Deployment | A company-managed browser extension covered GoalGetter (at `other.internal`) with a cookie overlay. IT should allow GoalGetter's name before rollout |

### P7-1 — `APP_URL` becomes an override that beats HTTPS

**Seen:**

1. The fresh install's `.env` had `APP_URL=http://localhost:8090`, written by me after moving `APP_PORT`, as `.env.example` says to.
2. After first sign-in, Settings → Hosting said "Address http://localhost:8090 · **set under Advanced**", though nobody had opened Advanced.
3. Every Set up step then warned "Advanced → Web address is http://localhost:8090; links and Microsoft sign-in keep using it."
4. After switching to `goals.internal` and pressing **Keep**:
   - `POST /api/users/invite` returned `http://localhost:8090/accept-invite?token=…`
   - the Microsoft redirect read `http://localhost:8090/api/auth/sso/callback`
   - Keep's own message said "GoalGetter is at https://goals.internal:8443"

**Cause:** `hosting_config._take_from_file` maps `APP_URL` onto `organization.public_url`, the Advanced override. Only an empty value or exactly `http://localhost:8080` maps to "no override". The override sits first in the precedence, above the HTTPS address. But `.env.example` says of `APP_URL`: "The web address until an admin sets one in the app… With HTTPS on, the HTTPS address is used instead."

**Impact:** for anyone who changed `APP_PORT`, or set `APP_URL` to the server's address as earlier docs suggested, every link GoalGetter sends after switching to HTTPS points at an address other devices can't open, and Microsoft sign-in breaks.

**Fix:**

- Treat `APP_URL` as the **fallback** the docs describe. Mirror only an explicitly chosen Advanced address into a separate `.env` line (e.g. `WEB_ADDRESS=`).
- Or, at minimum, when the first sync finds a non-default `APP_URL` on an install without HTTPS, don't import it as an override.
- Make the checklist's warning one-click fixable: "Use the HTTPS address instead".

### P7-2 — A read-only `.env` turns the escape hatch off

**Seen (`.env` mounted read-only into the API):**

1. `/api/hosting` and `/api/hosting/https` said `env_connected: false`. Nothing was logged and nothing shown.
2. `HTTPS_HOST=` emptied in the file: 40 s later Caddy still served the name, and port 8090 still sent `/login` to HTTPS.
3. `docker compose up -d` (the API recreated with `HTTPS_HOST` empty in its environment): **still on.** The database setting wins.

**Why it's likely on Linux:**

- `setup.sh` creates `.env` as whoever runs it, mode 644.
- The API runs as uid 1000.
- Run with `sudo` (common, since Docker often needs it), or by a user whose id isn't 1000, and the file is readable but not writable.

**Fix:**

- **Read `.env` even when it can't be written**, so the file wins whenever it changed, and only writing is skipped.
- Have the entrypoint try to give the file to uid 1000 (it already does this for three folders) and log when it can't.
- Settings → Hosting: when `env_connected` is false, say so ("Changes here aren't written to .env, and .env edits aren't read; see …").
- Keep an escape that never depends on the sync, for example an `HTTPS_FORCE_OFF=1` line the API honours at start.

### P7-3 — The front door installer's order

`install-front-door.ps1`, in order:

1. Downloads Caddy.
2. **Sets `HTTPS_FRONT_DOOR=windows` in `.env`.**
3. Validates the Caddy configuration, and exits on failure ("Nothing was started; fix .env and run this again").
4. `docker compose up -d`.
5. Creates and starts the service.

The app reads `.env` every 30 seconds. With `HTTPS_FRONT_DOOR=windows` set on the fresh copy and no front door installed, Docker's Caddy stopped serving the name (no answer), and port 8090 sent everything but `/pair` and `/display` to `https://other.internal:8443`, which nothing served. That holds from step 2 until the service answers, and **indefinitely if step 3 fails**.

**Fix:**

- Write `HTTPS_FRONT_DOOR=windows` **last**, after the service is running and answering on the HTTPS port.
- On any failure, put the previous value back.
- In the app, as with the tunnel (which waits until it's connected), keep port 8080 a full app until the front door actually answers (the certificate probe already knocks on `host.docker.internal`).

### P7-4 — `.env` edits during a trial

Phase 22's rule is that "an edit in `.env` counts as decided". On the fresh copy, editing `HTTPS_HOST` during a trial of `new.internal` (old: `goals.internal`) made `other.internal` live within 30 s. **Both `goals.internal` and `new.internal` stopped at once**, port 8090 went TV-only, and the admin's open tab on `goals.internal` was cut off. That's consistent with the rule, but it's the one way to skip the safety net the trial exists for.

**Suggestion:** treat a file edit during a trial as a **new trial**, from the same starting point, with the same 15 minutes. Then the plain port and the old name stay up, and the admin decides in the app. At least, show it in the card next time the admin looks ("Changed in .env at 19:01").

### P7-5 — What Activity doesn't show
- **The automatic undo** after 15 minutes is a WARNING in `docker compose logs api` only. An admin who walked away returns to find their change gone, with no entry in Activity, the bell or the Inbox. Add a `hosting.change_expired` audit entry and an Inbox item ("Your hosting change wasn't kept and was undone at 19:18").
- **Changes made in `.env`** never reach Activity. After the file edit, Activity's latest hosting entry still said `new.internal` while `other.internal` was live. Record them as "changed in .env".

### P7-6 — Undo while the front door is set
With `HTTPS_FRONT_DOOR=windows`, `PUT /api/hosting/https` is refused, but `POST /api/hosting/undo` returned 200. It also cleared `HTTPS_FRONT_DOOR` and switched Docker's Caddy back on. On a real front-door install, `.env` would then say "no front door" while the Windows service still holds the ports. Apply the same refusal to Undo, or make Undo the documented way out of a broken front door (and say so).

### P7-7 to P7-17
These are as described in the table. Two worth a minute:

- **P7-7:** with the only live check failing, ask "The tunnel isn't connected. Keep it anyway?".
- **P7-10:** use the configured `APP_PORT`, as the trial's own TVs line already does.

---

## Test data and cleanup

- **The fresh copy** (project `ggfresh`, ports 8090/8443/8081): its containers, network, volumes (including the root-owned test volume) and its three built images are removed, along with its folder.
- **The test browser profile** is removed.
- **Test files removed:** the self-signed test certificate and the scratch step files.
- **Your dev stack:** untouched (same containers and uptimes before and after), with no data written.
